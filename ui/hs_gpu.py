"""GPU helpers for Hand Space: shaded 3D models and hardware-decoded video, drawn straight into the overlay's OpenGL canvas.

* GlMesh  — uploads a triangle mesh (.obj / .stl) once, then draws it every frame with a vertex+fragment shader (lit, depth-tested).
* GlVideo — mpv decodes with the GPU (hwdec) and renders into an OpenGL texture (mpv render API); the texture is then drawn
            as a quad. No frame ever goes through the CPU.

Every draw call needs the canvas' OpenGL context to be current (they are called from the canvas' paintGL).
Loading (`load_mesh`) is pure numpy and runs in a worker thread.
"""
from __future__ import annotations

import math
import os
import struct
from collections import OrderedDict

import numpy as np

from ui.glholo import rot_rows

GL_FLOAT, GL_TRIANGLES, GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST = 0x1406, 0x0004, 0x0BE2, 0x0C11, 0x0B71
GL_DEPTH_BUFFER_BIT, GL_LEQUAL, GL_LESS = 0x0100, 0x0203, 0x0201
GL_ONE, GL_ONE_MINUS_SRC_ALPHA = 1, 0x0303
GL_TEXTURE_2D, GL_TEXTURE0 = 0x0DE1, 0x84C0
GL_CULL_FACE = 0x0B44

MAX_TRIS = 1_500_000                      # more than this is thinned out (the GPU could take more; the RAM to parse it is the limit)
MAX_BYTES = 200 * 1024 * 1024
SMALL_MODEL_BYTES = 8 * 1024 * 1024       # only models up to this size are drawn live on the small cards


# ── loading (worker thread) ──────────────────────────────────────────────────────────
def _read_obj(path: str) -> np.ndarray:
    verts: list = []
    faces: list = []
    n_lines = 0
    with open(path, "rb") as f:
        for raw in f:
            n_lines += 1
            if n_lines % 50000 == 0:
                import time
                time.sleep(0)                                  # let the UI thread breathe while a big file parses
            if raw[:2] == b"v ":
                t = raw.split()
                verts.append((float(t[1]), float(t[2]), float(t[3])))
            elif raw[:2] == b"f ":
                t = raw.split()[1:]
                n = len(verts)
                idx = []
                for x in t:
                    i = int(x.split(b"/")[0])
                    idx.append(i - 1 if i > 0 else n + i)
                for k in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[k], idx[k + 1]))
    if not verts or not faces:
        raise ValueError("this OBJ has no faces to draw")
    v = np.asarray(verts, dtype=np.float32)
    fa = np.asarray(faces, dtype=np.int64)
    if fa.min() < 0 or fa.max() >= len(v):
        raise ValueError("broken face indices")
    return v[fa]                                               # (n, 3, 3)


def _read_stl(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) >= 84:
        n = struct.unpack_from("<I", raw, 80)[0]
        if 84 + 50 * n == len(raw) and n > 0:                  # binary STL
            dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return np.frombuffer(raw, dtype=dt, count=n, offset=84)["v"].astype(np.float32)
    vs = []                                                    # ASCII STL
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            t = line.split()
            vs.append((float(t[1]), float(t[2]), float(t[3])))
    if len(vs) < 3:
        raise ValueError("this STL has no triangles")
    a = np.asarray(vs, dtype=np.float32)
    return a[: len(a) // 3 * 3].reshape(-1, 3, 3)


def load_mesh(path: str):
    """→ (float32 array (n_vertices, 6): position + face normal, triangle count). Centred and scaled to a unit sphere."""
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("file is too large (200 MB max)")
    ext = os.path.splitext(path)[1].lower()
    tri = _read_stl(path) if ext == ".stl" else _read_obj(path)
    tri = np.ascontiguousarray(tri, dtype=np.float32)
    if len(tri) > MAX_TRIS:
        tri = tri[:: math.ceil(len(tri) / MAX_TRIS)]
    flat = tri.reshape(-1, 3)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(flat - c, axis=1).max()) or 1.0
    tri = (tri - c) / r
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    nn = np.repeat(n[:, None, :], 3, axis=1)
    data = np.concatenate([tri, nn], axis=2).reshape(-1, 6).astype(np.float32)
    return data, int(len(tri))


# ── shared GL setup ──────────────────────────────────────────────────────────────────
def _gl_funcs():
    from PyQt6.QtGui import QOpenGLContext
    from PyQt6.QtOpenGL import QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        raise RuntimeError("no current OpenGL context")
    prof = QOpenGLVersionProfile()
    prof.setVersion(2, 1)
    f = QOpenGLVersionFunctionsFactory.get(prof, ctx)
    if f is None:
        raise RuntimeError("OpenGL 2.1 functions are unavailable")
    f.initializeOpenGLFunctions()
    return f, ctx


def _program(vs: str, fs: str):
    from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
    prog = QOpenGLShaderProgram()
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vs):
        raise RuntimeError("vertex shader: " + prog.log())
    if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fs):
        raise RuntimeError("fragment shader: " + prog.log())
    if not prog.link():
        raise RuntimeError("link: " + prog.log())
    return prog


# ── 3D models ────────────────────────────────────────────────────────────────────────
MESH_VS = """
#version 120
attribute vec3 aP;
attribute vec3 aN;
uniform vec3 uR0;
uniform vec3 uR1;
uniform vec3 uR2;
uniform float uScale;
uniform float uRad;
uniform float uDist;
uniform vec2 uCen;
uniform vec2 uRes;
varying vec3 vN;
void main() {
    vec3 p = vec3(dot(uR0, aP), dot(uR1, aP), dot(uR2, aP)) * uScale;
    vN = vec3(dot(uR0, aN), dot(uR1, aN), dot(uR2, aN));
    float f = uDist / (uDist - p.z);
    vec2 s = vec2(uCen.x + p.x * uRad * f, uCen.y - p.y * uRad * f);
    float z = clamp(-p.z / (uScale * 1.02 + 0.001), -1.0, 1.0);
    gl_Position = vec4(s.x / uRes.x * 2.0 - 1.0, 1.0 - s.y / uRes.y * 2.0, z, 1.0);
}
"""

MESH_FS = """
#version 120
uniform vec3 uMain;
uniform vec3 uAcc;
uniform float uAlpha;
varying vec3 vN;
void main() {
    vec3 n = normalize(vN);
    vec3 L = normalize(vec3(-0.45, 0.6, 0.75));
    float d = max(dot(n, L), 0.0) + 0.35 * max(dot(-n, L), 0.0);
    float rim = pow(1.0 - clamp(abs(n.z), 0.0, 1.0), 2.2);
    vec3 base = mix(vec3(0.66, 0.74, 0.84), uMain, 0.30);
    vec3 col = base * (0.20 + 0.85 * d) + uAcc * rim * 0.55;
    gl_FragColor = vec4(col * uAlpha, uAlpha);
}
"""


class GlMesh:
    def __init__(self):
        self.ok = False
        self.err = ""
        self.f = None
        self.prog = None
        self._Buffer = None
        self._bufs: OrderedDict = OrderedDict()                # path → (QOpenGLBuffer, vertex count)

    def init(self) -> bool:
        try:
            from PyQt6.QtOpenGL import QOpenGLBuffer
            self.f, _ = _gl_funcs()
            self.prog = _program(MESH_VS, MESH_FS)
            self._Buffer = QOpenGLBuffer
            self.ok = True
        except Exception as e:
            self.err = str(e)
            self.ok = False
        return self.ok

    def has(self, key: str) -> bool:
        return key in self._bufs

    def upload(self, key: str, data: np.ndarray, keep: int = 3) -> bool:
        try:
            vbo = self._Buffer(self._Buffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            raw = data.tobytes()
            vbo.allocate(raw, len(raw))
            vbo.release()
            self._bufs[key] = (vbo, len(data))
            while len(self._bufs) > keep:
                _, (old, _n) = self._bufs.popitem(last=False)
                old.destroy()
            return True
        except Exception as e:
            self.err = str(e)
            return False

    def drop_all(self):
        for vbo, _ in self._bufs.values():
            try:
                vbo.destroy()
            except Exception:
                pass
        self._bufs.clear()

    def draw(self, p, host, key: str, rect, yaw: float, pitch: float, zoom: float, alpha: float, cm, ca) -> bool:
        """rect: QRectF in the widget's pixels (the model is centred in it and clipped to it)."""
        ent = self._bufs.get(key)
        if not self.ok or ent is None or rect.width() < 4 or rect.height() < 4:
            return False
        vbo, count = ent
        f, prog = self.f, self.prog
        dpr = float(host.devicePixelRatioF())
        W, H = float(host.width()), float(host.height())
        rows = rot_rows(yaw, pitch, 0.0)
        rad = min(rect.width(), rect.height()) / 2.0 * 0.86
        p.beginNativePainting()
        try:
            f.glViewport(0, 0, int(W * dpr), int(H * dpr))
            f.glEnable(GL_SCISSOR_TEST)
            f.glScissor(int(rect.x() * dpr), int((H - rect.y() - rect.height()) * dpr), int(rect.width() * dpr) + 1, int(rect.height() * dpr) + 1)
            f.glClear(GL_DEPTH_BUFFER_BIT)
            f.glEnable(GL_DEPTH_TEST)
            f.glDepthFunc(GL_LESS)
            f.glDisable(GL_CULL_FACE)
            f.glEnable(GL_BLEND)
            f.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            prog.bind()
            prog.setUniformValue("uRes", W, H)
            prog.setUniformValue("uCen", float(rect.center().x()), float(rect.center().y()))
            prog.setUniformValue("uDist", 3.4)
            prog.setUniformValue("uScale", float(zoom))
            prog.setUniformValue("uRad", float(rad))
            prog.setUniformValue("uAlpha", float(max(0.0, min(1.0, alpha))))
            prog.setUniformValue("uMain", cm[0] / 255.0, cm[1] / 255.0, cm[2] / 255.0)
            prog.setUniformValue("uAcc", ca[0] / 255.0, ca[1] / 255.0, ca[2] / 255.0)
            prog.setUniformValue("uR0", *rows[0])
            prog.setUniformValue("uR1", *rows[1])
            prog.setUniformValue("uR2", *rows[2])
            lp, ln = prog.attributeLocation("aP"), prog.attributeLocation("aN")
            vbo.bind()
            prog.enableAttributeArray(lp)
            prog.setAttributeBuffer(lp, GL_FLOAT, 0, 3, 24)
            prog.enableAttributeArray(ln)
            prog.setAttributeBuffer(ln, GL_FLOAT, 12, 3, 24)
            f.glDrawArrays(GL_TRIANGLES, 0, count)
            prog.disableAttributeArray(lp)
            prog.disableAttributeArray(ln)
            vbo.release()
            prog.release()
            f.glClear(GL_DEPTH_BUFFER_BIT)                     # leave the depth buffer clean for the 2D painter
            f.glDisable(GL_DEPTH_TEST)
            f.glDisable(GL_SCISSOR_TEST)
            return True
        except Exception as e:
            self.err = str(e)
            self.ok = False
            return False
        finally:
            p.endNativePainting()


# ── video (mpv → OpenGL texture → quad) ──────────────────────────────────────────────
QUAD_VS = """
#version 120
attribute vec2 aP;
uniform vec4 uRect;
uniform vec2 uRes;
varying vec2 vUV;
void main() {
    vec2 pos = uRect.xy + aP * uRect.zw;
    vUV = vec2(aP.x, 1.0 - aP.y);
    gl_Position = vec4(pos.x / uRes.x * 2.0 - 1.0, 1.0 - pos.y / uRes.y * 2.0, 0.0, 1.0);
}
"""

QUAD_FS = """
#version 120
uniform sampler2D uTex;
uniform float uAlpha;
varying vec2 vUV;
void main() {
    vec3 c = texture2D(uTex, vUV).rgb;
    gl_FragColor = vec4(c * uAlpha, uAlpha);
}
"""


class GlVideo:
    MAX_SIDE = 3840

    def __init__(self):
        self.err = ""
        self.player = None
        self.rc = None
        self.path: str | None = None
        self.f = None
        self.prog = None
        self._quad = None
        self._fbo = None
        self._fbo_size = (0, 0)
        self._ctx = None

    @property
    def active(self) -> bool:
        return self.player is not None

    # context must be current for start() / draw() / stop()
    def start(self, path: str) -> bool:
        if self.player is not None:
            if self.path != path:
                self.path = path
                try:
                    self.player.pause = False
                    self.player.play(path)
                except Exception as e:
                    self.err = str(e)
                    return False
            return True
        self.err = ""
        try:
            import ctypes
            from PyQt6.QtOpenGL import QOpenGLBuffer
            self.f, self._ctx = _gl_funcs()
            self.prog = _program(QUAD_VS, QUAD_FS)
            quad = np.array([(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)], dtype=np.float32).tobytes()
            self._quad = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self._quad.create()
            self._quad.bind()
            self._quad.allocate(quad, len(quad))
            self._quad.release()

            from actions.hud_video import _import_mpv
            mpv = _import_mpv()
            try:
                import locale
                locale.setlocale(locale.LC_NUMERIC, "C")        # libmpv requires the C numeric locale
            except Exception:
                pass
            player = mpv.MPV(vo="libmpv", hwdec="auto-safe", keep_open="yes", osc=False, ytdl=False, idle="yes",
                             input_default_bindings=False, input_vo_keyboard=False, cache="yes", volume=100)
            ctx = self._ctx

            def get_proc(_c, name):
                addr = ctx.getProcAddress(name)
                return ctypes.cast(int(addr), ctypes.c_void_p).value if addr else 0
            proc = mpv.MpvGlGetProcAddressFn(get_proc)
            self._proc = proc                                   # keep alive
            rc = mpv.MpvRenderContext(player, "opengl", opengl_init_params={"get_proc_address": proc})
            rc.update_cb = lambda: None
            self.player, self.rc, self.path = player, rc, path
            player.play(path)
            return True
        except Exception as e:
            self.err = str(e) or e.__class__.__name__
            self.stop()
            return False

    def stop(self):
        rc, pl = self.rc, self.player
        self.rc = self.player = None
        self.path = None
        for obj, fn in ((rc, "free"), (pl, "terminate")):
            if obj is not None:
                try:
                    getattr(obj, fn)()
                except Exception:
                    pass
        if self._fbo is not None:
            self._fbo = None
            self._fbo_size = (0, 0)
        if self._quad is not None:
            try:
                self._quad.destroy()
            except Exception:
                pass
            self._quad = None

    def apply(self, cmds: list):
        pl = self.player
        if pl is None:
            return
        seek = 0.0
        for kind, val in cmds:
            if kind == "seek":
                seek += float(val)
            elif kind == "pause":
                try:
                    pl.pause = bool(val)
                except Exception:
                    pass
        if abs(seek) > 0.01:
            try:
                pl.command("seek", seek, "relative+keyframes")
            except Exception:
                pass

    def info(self):
        """(position s, duration s, aspect or None, ended)"""
        pl = self.player
        if pl is None:
            return 0.0, 0.0, None, False
        try:
            pos = float(pl.time_pos or 0.0)
            dur = float(pl.duration or 0.0)
            w, h = pl.dwidth, pl.dheight
            asp = (w / h) if (w and h) else None
            return pos, dur, asp, bool(pl.eof_reached)
        except Exception:
            return 0.0, 0.0, None, False

    def _ensure_fbo(self, w: int, h: int):
        from PyQt6.QtOpenGL import QOpenGLFramebufferObject
        if self._fbo is None or self._fbo_size != (w, h):
            self._fbo = QOpenGLFramebufferObject(w, h)
            self._fbo_size = (w, h)

    def draw(self, p, host, rect, alpha: float, target) -> bool:
        """Render the current frame (hardware decoded) and draw it in `rect`. `target` = (w, h) logical size the film is rendered at."""
        if self.rc is None or self.f is None or rect.width() < 4 or rect.height() < 4:
            return False
        f, prog = self.f, self.prog
        dpr = float(host.devicePixelRatioF())
        W, H = float(host.width()), float(host.height())
        tw = int(max(64, min(self.MAX_SIDE, target[0] * dpr)))
        th = int(max(64, min(self.MAX_SIDE, target[1] * dpr)))
        p.beginNativePainting()
        try:
            self._ensure_fbo(tw, th)
            fbo = self._fbo
            fbo.bind()
            try:
                self.rc.update()
            except Exception:
                pass
            self.rc.render(opengl_fbo={"w": tw, "h": th, "fbo": int(fbo.handle())}, flip_y=True, block_for_target_time=False)
            fbo.release()                                       # back to the canvas' own framebuffer
            f.glActiveTexture(GL_TEXTURE0)
            f.glViewport(0, 0, int(W * dpr), int(H * dpr))
            f.glEnable(GL_SCISSOR_TEST)
            f.glScissor(int(rect.x() * dpr), int((H - rect.y() - rect.height()) * dpr), int(rect.width() * dpr) + 1, int(rect.height() * dpr) + 1)
            f.glDisable(GL_DEPTH_TEST)
            f.glDisable(GL_CULL_FACE)
            f.glEnable(GL_BLEND)
            f.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            prog.bind()
            f.glBindTexture(GL_TEXTURE_2D, int(fbo.texture()))
            prog.setUniformValue("uTex", 0)
            prog.setUniformValue("uRes", W, H)
            prog.setUniformValue("uRect", float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))
            prog.setUniformValue("uAlpha", float(max(0.0, min(1.0, alpha))))
            loc = prog.attributeLocation("aP")
            self._quad.bind()
            prog.enableAttributeArray(loc)
            prog.setAttributeBuffer(loc, GL_FLOAT, 0, 2, 8)
            f.glDrawArrays(GL_TRIANGLES, 0, 6)
            prog.disableAttributeArray(loc)
            self._quad.release()
            f.glBindTexture(GL_TEXTURE_2D, 0)
            prog.release()
            f.glDisable(GL_SCISSOR_TEST)
            return True
        except Exception as e:
            self.err = str(e) or e.__class__.__name__
            return False
        finally:
            p.endNativePainting()
