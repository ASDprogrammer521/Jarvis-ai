from __future__ import annotations

import math

import numpy as np

GL_FLOAT, GL_TRIANGLES, GL_BLEND, GL_SCISSOR_TEST, GL_DEPTH_TEST = 0x1406, 0x0004, 0x0BE2, 0x0C11, 0x0B71
GL_ONE, GL_ONE_MINUS_SRC_ALPHA = 1, 0x0303

VS = """
#version 120
attribute vec3 aA;
attribute vec3 aB;
attribute vec2 aC;
uniform vec3 uR0;
uniform vec3 uR1;
uniform vec3 uR2;
uniform float uScale;
uniform float uRad;
uniform float uDist;
uniform vec2 uCen;
uniform vec2 uRes;
uniform float uWidth;
uniform vec2 uWK;
varying vec4 vAB;
varying vec2 vPix;
varying float vZ;
vec3 rotp(vec3 p) {
    p *= uScale;
    return vec3(dot(uR0, p), dot(uR1, p), dot(uR2, p));
}
void main() {
    vec3 qa = rotp(aA);
    vec3 qb = rotp(aB);
    float fa = uDist / (uDist - qa.z);
    float fb = uDist / (uDist - qb.z);
    vec2 sa = vec2(uCen.x + qa.x * uRad * fa, uCen.y - qa.y * uRad * fa);
    vec2 sb = vec2(uCen.x + qb.x * uRad * fb, uCen.y - qb.y * uRad * fb);
    vec2 d = sb - sa;
    float L = length(d);
    vec2 t = (L > 0.0001) ? d / L : vec2(1.0, 0.0);
    vec2 n = vec2(-t.y, t.x);
    float hw = 0.5 * uWidth * (uWK.x + uWK.y) + 1.0;
    vec2 pos = mix(sa, sb, aC.x) + n * aC.y * hw + t * (aC.x * 2.0 - 1.0) * hw;
    vAB = vec4(sa, sb);
    vPix = pos;
    vZ = mix(qa.z, qb.z, aC.x);
    gl_Position = vec4(pos.x / uRes.x * 2.0 - 1.0, 1.0 - pos.y / uRes.y * 2.0, 0.0, 1.0);
}
"""

FS = """
#version 120
uniform float uAlpha;
uniform vec3 uMain;
uniform vec3 uAcc;
uniform float uMix;
uniform float uWidth;
uniform vec2 uWK;
uniform vec2 uDK;
varying vec4 vAB;
varying vec2 vPix;
varying float vZ;
void main() {
    vec2 a = vAB.xy;
    vec2 ab = vAB.zw - a;
    float l2 = max(dot(ab, ab), 0.000001);
    float h = clamp(dot(vPix - a, ab) / l2, 0.0, 1.0);
    float d = length(vPix - (a + ab * h));
    float zn = clamp((vZ + 1.6) / 3.2, 0.0, 1.0);
    float hw = max(0.5, 0.5 * uWidth * (uWK.x + uWK.y * zn));
    float cov = 1.0 - smoothstep(hw - 0.6, hw + 0.6, d);
    float al = uAlpha * (uDK.x + uDK.y * zn) * cov;
    vec3 col = mix(uMain, uAcc, uMix);
    gl_FragColor = vec4(col * al, al);
}
"""

_CORNERS = np.array([(0, -1), (1, -1), (1, 1), (0, -1), (1, 1), (0, 1)], dtype=np.float32)


def supports(model) -> bool:
    for L in model.layers:
        if L.kind not in ("lines", "points"):
            return False
        P = L.p
        if P["scan"] or P["jit"] or P["wob"] or P["ampxz"]:
            return False
    return True


def rot_rows(yaw: float, pitch: float, roll: float):
    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    m = rz @ rx @ ry
    return tuple(tuple(float(v) for v in row) for row in m)


def build_vertices(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = len(a)
    out = np.empty((n, 6, 8), dtype=np.float32)
    out[:, :, 0:3] = a[:, None, :]
    out[:, :, 3:6] = b[:, None, :]
    out[:, :, 6:8] = _CORNERS[None, :, :]
    return out.reshape(-1, 8)


def layer_geometry(L, half: bool) -> np.ndarray:
    if L.kind == "lines":
        idx = L.idx[::2] if half else L.idx
        return build_vertices(L.verts[idx[:, 0]], L.verts[idx[:, 1]])
    ids = L.idx[::2] if half else L.idx
    pts = L.verts[ids]
    return build_vertices(pts, pts)


def layer_uniforms(L, t: float, amp: float, yaw: float, pitch: float, R: float, lite: bool):
    P = L.p
    if lite and P["lite"] == 0:
        return None
    alpha = P["a"]
    if P["blink"]:
        alpha *= max(0.05, 1.0 - P["blink"] * 0.5 * (1.0 + math.sin(t * P["rate"] + P["phase"])))
    lines = L.kind == "lines"
    return {
        "rows": rot_rows(yaw * P["spin"] + P["yaw0"], pitch * P["pitchmul"] + P["tilt"], P["roll"] * t),
        "scale": P["scale"] * (1.0 + P["amp"] * amp),
        "rad": R * P["rad"],
        "width": P["w"] if lines else P["size"],
        "alpha": alpha,
        "mix": P["mix"],
        "add": P["add"] > 0,
        "wk": (0.6, 0.7) if lines else (0.55, 0.9),
        "dk": (0.137, 0.745) if lines else (0.196, 0.804),
        "half": bool(lite and P["lite"] < 1),
    }


class GlHolo:

    def __init__(self):
        self.ok = False
        self.used = False
        self.err = ""
        self.f = None
        self.prog = None
        self._buf: dict = {}
        self._Buffer = None

    def init(self) -> bool:
        try:
            from PyQt6.QtGui import QOpenGLContext
            from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                                        QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)
            ctx = QOpenGLContext.currentContext()
            if ctx is None:
                raise RuntimeError("no current OpenGL context")
            prof = QOpenGLVersionProfile()
            prof.setVersion(2, 1)
            f = QOpenGLVersionFunctionsFactory.get(prof, ctx)
            if f is None:
                raise RuntimeError("OpenGL 2.1 functions are unavailable")
            f.initializeOpenGLFunctions()
            prog = QOpenGLShaderProgram()
            if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS):
                raise RuntimeError("vertex shader: " + prog.log())
            if not prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS):
                raise RuntimeError("fragment shader: " + prog.log())
            if not prog.link():
                raise RuntimeError("link: " + prog.log())
            self.f, self.prog, self._Buffer, self.ok = f, prog, QOpenGLBuffer, True
        except Exception as e:
            self.err = str(e)
            self.ok = False
        return self.ok

    def _vbo(self, key, L, half: bool):
        b = self._buf.get(key)
        if b is None:
            data = layer_geometry(L, half)
            vbo = self._Buffer(self._Buffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            raw = data.tobytes()
            vbo.allocate(raw, len(raw))
            b = (vbo, len(data))
            self._buf[key] = b
        return b

    def draw(self, p, host, model, org, cx, cy, R, yaw, pitch, amp, t, cm, ca, lite, clip) -> bool:
        f, prog = self.f, self.prog
        dpr = float(host.devicePixelRatioF())
        W, H = float(host.width()), float(host.height())
        stride = 8 * 4
        p.beginNativePainting()
        try:
            f.glViewport(0, 0, int(W * dpr), int(H * dpr))
            f.glEnable(GL_SCISSOR_TEST)
            f.glScissor(int(clip[0] * dpr), int((H - clip[1] - clip[3]) * dpr), int(clip[2] * dpr) + 1, int(clip[3] * dpr) + 1)
            f.glDisable(GL_DEPTH_TEST)
            f.glEnable(GL_BLEND)
            prog.bind()
            prog.setUniformValue("uRes", W, H)
            prog.setUniformValue("uCen", float(org[0] + cx), float(org[1] + cy))
            prog.setUniformValue("uDist", 3.4)
            prog.setUniformValue("uMain", cm[0] / 255.0, cm[1] / 255.0, cm[2] / 255.0)
            prog.setUniformValue("uAcc", ca[0] / 255.0, ca[1] / 255.0, ca[2] / 255.0)
            locs = [prog.attributeLocation(n) for n in ("aA", "aB", "aC")]
            for i, L in enumerate(model.layers):
                u = layer_uniforms(L, t, amp, yaw, pitch, R, lite)
                if u is None:
                    continue
                vbo, count = self._vbo((model.name, i, u["half"]), L, u["half"])
                vbo.bind()
                prog.enableAttributeArray(locs[0])
                prog.setAttributeBuffer(locs[0], GL_FLOAT, 0, 3, stride)
                prog.enableAttributeArray(locs[1])
                prog.setAttributeBuffer(locs[1], GL_FLOAT, 12, 3, stride)
                prog.enableAttributeArray(locs[2])
                prog.setAttributeBuffer(locs[2], GL_FLOAT, 24, 2, stride)
                r0, r1, r2 = u["rows"]
                prog.setUniformValue("uR0", *r0)
                prog.setUniformValue("uR1", *r1)
                prog.setUniformValue("uR2", *r2)
                prog.setUniformValue("uScale", float(u["scale"]))
                prog.setUniformValue("uRad", float(u["rad"]))
                prog.setUniformValue("uWidth", float(u["width"]))
                prog.setUniformValue("uAlpha", float(u["alpha"]))
                prog.setUniformValue("uMix", float(u["mix"]))
                prog.setUniformValue("uWK", *u["wk"])
                prog.setUniformValue("uDK", *u["dk"])
                f.glBlendFunc(GL_ONE, GL_ONE if u["add"] else GL_ONE_MINUS_SRC_ALPHA)
                f.glDrawArrays(GL_TRIANGLES, 0, count)
                vbo.release()
            for loc in locs:
                prog.disableAttributeArray(loc)
            prog.release()
            f.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            f.glDisable(GL_SCISSOR_TEST)
            self.used = True
            return True
        except Exception as e:
            self.err = str(e)
            self.ok = False
            return False
        finally:
            p.endNativePainting()

# by ASDcuber521
