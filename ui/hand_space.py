"""Hand Space window: a full-screen, hand-controlled file workspace (drives → folders → pictures and notes).

Logic and physics live in core/hand_space.py; this file only draws them. The mouse works too (handy without a camera).
Pictures are decoded in background threads, so browsing a big photo folder never stalls the screen.

GPU: when OpenGL is on (Settings → hw_accel, default) the whole overlay is drawn by the GPU through an OpenGL canvas;
3D models (.obj / .stl) are shaded by their own shader and videos are decoded by the GPU (mpv hwdec) and rendered
into a texture (ui/hs_gpu.py). Set "hand_space_gpu": false in the config to fall back to the CPU painter.
"""
from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QPolygonF, QRadialGradient, QSurfaceFormat, QTextOption)
from PyQt6.QtWidgets import QWidget

from core.hand_space import Card, Space, human_size
from ui import hs_gpu
from ui.fx import GL_ENABLED, samples_for
from ui.hand_overlay import BONES
from ui.mesh_formats import HEAVY_EXT
from ui.overlay_utils import force_topmost
from ui.theme import C, read_cfg

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget as _GLW
except Exception:                                     # pragma: no cover - PyQt build without OpenGL widgets
    _GLW = None

THUMB_SIDE, LARGE_SIDE = 480, 3200
_AL = Qt.AlignmentFlag
PROFILE = bool(os.environ.get("JARVIS_PROFILE"))               # set JARVIS_PROFILE=1 to print timings every 3 s

_FONTS: dict = {}
_ELIDE: dict = {}
_FM: dict = {}


def _F(size, weight=None, family: str = "Segoe UI") -> QFont:
    """Shared QFont objects: building a font (and its metrics) for every card on every frame was pure CPU waste."""
    k = (family, size, weight)
    f = _FONTS.get(k)
    if f is None:
        f = QFont(family, size) if weight is None else QFont(family, size, weight)
        _FONTS[k] = f
    return f


def _elided(text: str, size: int, width: int) -> str:
    k = (text, size, width)
    r = _ELIDE.get(k)
    if r is None:
        fm = _FM.get(size)
        if fm is None:
            fm = _FM[size] = QFontMetrics(_F(size, QFont.Weight.DemiBold))
        r = fm.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        if len(_ELIDE) > 800:
            _ELIDE.clear()
        _ELIDE[k] = r
    return r


def _decode(path: str, side: int):
    """Runs in a worker thread: returns (QImage, width, height). PIL is fast (JPEG draft mode) and honours EXIF rotation."""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            ow, oh = im.size
            try:
                im.draft("RGB", (side, side))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im)
            im.thumbnail((side, side), Image.BILINEAR)
            im = im.convert("RGBA")
            w, h = im.size
            qi = QImage(im.tobytes("raw", "RGBA"), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            real = (max(ow, oh), min(ow, oh)) if w >= h else (min(ow, oh), max(ow, oh))
            return qi, w, h, real
    except Exception:
        qi = QImage(path)
        if qi.isNull():
            return None
        if max(qi.width(), qi.height()) > side:
            qi = qi.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return qi, qi.width(), qi.height(), (qi.width(), qi.height())


if _GLW is not None:
    class _Canvas(_GLW):
        """Full-size OpenGL surface: every QPainter call of the overlay runs on the GPU, and 3D / video draw into it natively."""

        def __init__(self, owner):
            super().__init__(owner)
            self._owner = owner
            fmt = QSurfaceFormat()
            fmt.setAlphaBufferSize(8)
            fmt.setDepthBufferSize(24)
            fmt.setStencilBufferSize(8)
            fmt.setSamples(samples_for(str(read_cfg().get("quality") or "auto")))
            self.setFormat(fmt)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)     # the overlay keeps the mouse / keyboard

        def paintGL(self):
            self._owner._paint_gl(self)


class HandSpaceOverlay(QWidget):
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.space = Space(1920, 1080)
        self.space.on_release = self._release_files
        self._thumbs: OrderedDict[str, QPixmap] = OrderedDict()
        self._large: OrderedDict[str, QPixmap] = OrderedDict()
        self._jobs: dict[tuple, Future] = {}
        self._failed: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._bg: QPixmap | None = None
        self._idle = 0
        self._fs = False                       # True while the open item is drawn full screen (no card chrome)
        self._chromes: dict = {}               # cached card bodies: one texture per size instead of gradients every frame
        self._state = None
        self._last = time.time()
        # GPU: 3D models, video, OpenGL canvas
        self._mesh = hs_gpu.GlMesh()
        self._video = hs_gpu.GlVideo()
        self._mpool = ThreadPoolExecutor(max_workers=1)
        self._mjobs: dict[str, Future] = {}
        self._mdata: dict[str, tuple] = {}
        self._mfail: dict[str, str] = {}
        self._tris: dict[str, int] = {}
        self._vfail: dict[str, str] = {}
        self._gl_tried = False
        self._pre = False
        self._fn = 0
        self._pt = [0.0, 0]
        self._live = 0
        self._anim = False
        self._cm = QColor(C.PRI).getRgb()[:3]
        self._ca = QColor(C.ACC).getRgb()[:3]
        self._cv = None
        if _GLW is not None and GL_ENABLED and read_cfg().get("hand_space_gpu", True):
            try:
                self._cv = _Canvas(self)
                self._cv.setGeometry(self.rect())
            except Exception:
                self._cv = None
        self._t = QTimer(self)
        self._t.timeout.connect(self._frame)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def show_overlay(self, pinned: str | None = None):
        scr = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(scr)
        self.space.resize(scr.width(), scr.height())
        self.space.start(pinned)                       # always begins on "This PC": the drives, C: first
        self.space.close_requested = False
        self._bg = None
        self.show()
        force_topmost(self, click_through=False)
        self.activateWindow()
        self.setFocus()
        self._last = time.time()
        self._t.start(28)
        if self._cv is not None:
            self._cv.setGeometry(self.rect())
            QTimer.singleShot(700, self._check_gl)

    def _check_gl(self):
        """If the OpenGL canvas could not start on this machine, drop it and paint on the CPU as before."""
        cv = self._cv
        if cv is not None and self.isVisible() and not cv.isValid():
            self._cv = None
            cv.hide()
            cv.deleteLater()
            self._bg = None
            QWidget.update(self)

    def update(self, *a):                      # noqa: A003 - repaint the GL canvas when there is one
        cv = self._cv
        if cv is not None:
            cv.update()
        else:
            super().update(*a)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._cv is not None:
            self._cv.setGeometry(self.rect())

    def _gpu_release(self):
        """Free the video player and the 3D buffers (needs the canvas' context)."""
        cv = self._cv
        for f in self._mjobs.values():
            f.cancel()
        self._mjobs.clear()
        self._mdata.clear()
        self._mfail.clear()
        self._vfail.clear()
        if cv is None:
            self._video.stop()
            return
        try:
            cv.makeCurrent()
            self._video.stop()
            self._mesh.drop_all()
            cv.doneCurrent()
        except Exception:
            pass

    def hide(self):                           # noqa: A003
        self._t.stop()
        super().hide()

    def hideEvent(self, e):
        self._t.stop()
        self._gpu_release()
        for f in self._jobs.values():
            f.cancel()
        self._jobs.clear()
        self._thumbs.clear()                  # give the memory back
        self._large.clear()
        self._failed.clear()
        super().hideEvent(e)
        self.closed.emit()

    def set_hands(self, all_lm):
        if not self.isVisible():
            return
        self.space.update_hands(all_lm)
        if self.space.close_requested:
            self.hide()

    def _frame(self):
        now = time.time()
        self.space.step(now - self._last, now)
        self._last = now
        self._poll_images()
        self._poll_models()
        sp = self.space
        op = sp.opened
        if op is not None and op.cmds:                       # buttons / drags aimed at the video player
            cmds, op.cmds = op.cmds, []
            if op.data.get("kind") == "video":
                self._video.apply(cmds)
        if self._video.active and (op is None or op.data.get("kind") != "video" or not op.open):
            self._video.park()                               # film closed: keep the player ready for the next one
        self._fn += 1
        if not self._pre and self._fn % 15 == 0 and any(e.get("kind") == "video" for e in sp.entries):
            self._pre = True                                 # this folder has films: build the player in the background now
            hs_gpu.prewarm_player()
        anim, self._anim = self._anim, False
        state = (sp.toast, sp.hover_btn, id(sp.hover_card), sp.version, round(sp.ui_a, 2), round(sp.fk, 2), sp.page,
                 sp.select, len(sp.sel), sp.prompt is not None, sp.menu)
        changed, self._state = state != self._state, state
        busy = (changed or any(sp.visible) or op is not None or sp.prompt is not None or self._jobs or self._mjobs or anim
                or any(c.a < 0.99 or c.homing or c.k > 0.01 or c.hov > 0.01 or abs(c.vx) + abs(c.vy) > 2.0 for c in sp.cards))
        self._idle += 0 if busy else 1
        want = 16 if (self._video.active and op is not None and not op.paused) else 28      # film: smooth; otherwise ~36 fps is plenty (camera = 30)
        if self._t.interval() != want:
            self._t.setInterval(want)
        if busy:                                   # an idle screen (nothing moving, nobody there) is not repainted at all
            self.update()

    def _gpu_stop_video(self):
        cv = self._cv
        if cv is None:
            self._video.stop()
            return
        try:
            cv.makeCurrent()
            self._video.stop()
            cv.doneCurrent()
        except Exception:
            pass

    # ── 3D models (background parse → GPU upload) ───────────────────────────────────
    def _poll_models(self):
        for path, fut in list(self._mjobs.items()):
            if not fut.done():
                continue
            del self._mjobs[path]
            try:
                self._mdata[path] = fut.result()
            except Exception as e:
                self._mfail[path] = str(e) or "unreadable"

    def _upload_models(self):
        """Runs inside paintGL (the context is current): one upload per frame so a big model never freezes the screen."""
        for path in list(self._mdata):
            data, tris = self._mdata.pop(path)
            if self._mesh.ok and self._mesh.upload(path, data):
                self._tris[path] = tris
            else:
                self._mfail[path] = self._mesh.err or "GPU upload failed"
            break

    def _mesh_state(self, c: Card, opened: bool) -> str:
        path = c.data["path"]
        if self._mesh.has(path):
            return "ready"
        if path in self._mfail:
            return "failed"
        if path in self._mjobs or path in self._mdata:
            return "loading"
        heavy = os.path.splitext(path)[1].lower() in HEAVY_EXT           # STEP / USD are slow to read: only when opened
        if (opened or (not heavy and c.data.get("_sz", 0) <= hs_gpu.SMALL_MODEL_BYTES)) and len(self._mjobs) < 2:
            self._mjobs[path] = self._mpool.submit(hs_gpu.load_mesh, path)
            return "loading"
        return "idle"

    # ── pictures (background decode) ────────────────────────────────────────────────
    def _want(self, path: str, side: int, cache: OrderedDict, limit: int):
        if path in cache or path in self._failed:
            if path in cache:
                cache.move_to_end(path)
            return
        key = (path, side)
        if key not in self._jobs and len(self._jobs) < 12:
            self._jobs[key] = self._pool.submit(_decode, path, side)

    def _poll_images(self):
        sp = self.space
        op = sp.opened
        for c in sp.cards:
            if c.data.get("image") and c.a > 0.02:
                self._want(c.data["image"], THUMB_SIDE, self._thumbs, 150)
        if op is not None and op.data.get("image") and op.k > 0.3:
            self._want(op.data["image"], LARGE_SIDE, self._large, 3)
        for key, fut in list(self._jobs.items()):
            if not fut.done():
                continue
            del self._jobs[key]
            path, side = key
            try:
                res = fut.result()
            except Exception:
                res = None
            if res is None:
                self._failed.add(path)
                continue
            qi, w, h, real = res
            for c in sp.cards:
                if c.data.get("image") == path and w > 0 and h > 0:
                    c.data["aspect"], c.data["dims"] = w / h, real
            if side == THUMB_SIDE:
                self._thumbs[path] = QPixmap.fromImage(qi)
                while len(self._thumbs) > 150:
                    self._thumbs.popitem(last=False)
            else:
                self._large[path] = QPixmap.fromImage(qi)
                while len(self._large) > 3:
                    self._large.popitem(last=False)

    def _release_files(self, paths):
        """Space is about to rename / move / delete files: let go of a video that may hold one open."""
        try:
            if self._video.active:
                self._video.park()
        except Exception:
            pass

    # ── input fallback: mouse / keyboard ─────────────────────────────────────────────
    def keyPressEvent(self, e):
        k, sp = e.key(), self.space
        mods = e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if sp.prompt is not None:                                    # the rename box takes all typing
            names = {Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter", Qt.Key.Key_Escape: "esc", Qt.Key.Key_Backspace: "backspace",
                     Qt.Key.Key_Delete: "delete", Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end"}
            if ctrl and k == Qt.Key.Key_A:
                sp.prompt_key("", "all")
            elif k in names:
                sp.prompt_key("", names[k])
            elif not ctrl:
                sp.prompt_key(e.text())
            return
        if ctrl and k in (Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V, Qt.Key.Key_A):
            if k == Qt.Key.Key_A:
                sp.select_all()
            else:
                sp._press({Qt.Key.Key_C: "a_copy", Qt.Key.Key_X: "a_cut", Qt.Key.Key_V: "a_paste"}[k], time.time())
            return
        if k == Qt.Key.Key_F2:
            sp._press("a_rename", time.time())
            return
        if k == Qt.Key.Key_Delete:
            sp._press("a_delete", time.time())
            return
        if k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            sp._press("v_full", time.time())
        elif k == Qt.Key.Key_Escape:
            if sp.opened is not None or sp.menu or sp.full or sp.select:
                sp.back()
            else:
                self.hide()
        elif k == Qt.Key.Key_Backspace:
            sp.back()
        elif k == Qt.Key.Key_Home:
            sp.go_root()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            sp.key_arrow(-1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            sp.key_arrow(1)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            sp._press("v_plus", time.time())
        elif k == Qt.Key.Key_Minus:
            sp._press("v_minus", time.time())
        elif k == Qt.Key.Key_Space:
            sp._press("v_play", time.time())
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)
            if self.space.close_requested:
                self.hide()
        elif e.button() == Qt.MouseButton.RightButton:
            self.space.back()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)
        else:
            self.space.hover_at(e.position().x(), e.position().y())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), False)
            self.space.visible[0] = False

    def wheelEvent(self, e):
        self.space.wheel(e.angleDelta().y(), e.position().x(), e.position().y())

    def leaveEvent(self, e):
        self.space.mouse_hover = None
        super().leaveEvent(e)

    # ── drawing: backdrop ────────────────────────────────────────────────────────────
    def _background(self) -> QPixmap:
        W, H = self.width(), self.height()
        if self._bg is None or self._bg.width() != W or self._bg.height() != H:
            bg = QPixmap(W, H)
            bg.fill(Qt.GlobalColor.transparent)
            p = QPainter(bg)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            g = QRadialGradient(QPointF(W / 2, H * 0.55), max(W, H) * 0.8)
            g.setColorAt(0, QColor(10, 24, 46, 222))
            g.setColorAt(1, QColor(2, 4, 12, 242))
            p.fillRect(QRectF(0, 0, W, H), QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)                                       # faint dot grid
            p.setBrush(QColor(110, 231, 255, 22))
            for x in range(40, W, 48):
                for y in range(40, H, 48):
                    p.drawEllipse(QPointF(x, y), 1.1, 1.1)
            top = QLinearGradient(0, 0, 0, 130)                                # top and bottom bars sit on a darker band
            top.setColorAt(0, QColor(0, 6, 16, 190))
            top.setColorAt(1, QColor(0, 6, 16, 0))
            p.fillRect(QRectF(0, 0, W, 130), QBrush(top))
            bot = QLinearGradient(0, H - 150, 0, H)
            bot.setColorAt(0, QColor(0, 6, 16, 0))
            bot.setColorAt(1, QColor(0, 6, 16, 190))
            p.fillRect(QRectF(0, H - 150, W, 150), QBrush(bot))
            p.end()
            self._bg = bg
        return self._bg

    def paintEvent(self, _):
        if self._cv is not None:                      # the GL canvas covers this widget and paints everything
            return
        p = QPainter(self)
        self._draw(p)
        p.end()

    def _paint_gl(self, cv):
        t0 = time.perf_counter() if PROFILE else 0.0
        try:
            self._paint_gl_inner(cv)
        finally:
            if PROFILE:
                self._pt[0] += time.perf_counter() - t0
                self._pt[1] += 1
                if self._pt[1] >= 90:
                    print(f"[hand space] paint {self._pt[0] / self._pt[1] * 1000:.1f} ms/frame · {len(self.space.cards)} cards")
                    self._pt = [0.0, 0]

    def _paint_gl_inner(self, cv):
        p = QPainter(cv)
        if not p.isActive():
            return
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(cv.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        try:
            self._draw(p)
        finally:
            p.end()

    def _draw(self, p: QPainter):
        sp = self.space
        if self._cv is not None:
            if not self._gl_tried:
                self._gl_tried = True
                self._mesh.init()
            self._upload_models()
        self._live = 0
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        p.drawPixmap(0, 0, self._background())

        op = sp.opened
        if op is not None and sp.fk > 0.55 and op.k > 0.5:           # FULL SCREEN: only the item itself is drawn
            p.fillRect(QRectF(0, 0, W, H), QColor(0, 0, 0, 255))
            self._fs = True
            try:
                self._draw_card(p, op)
            finally:
                self._fs = False
            self._draw_full_ui(p, op, W, H)
        else:
            dim = max((c.k for c in sp.cards), default=0.0)
            for c in sorted(sp.cards, key=lambda c: (c.open, c.k, c.held, c.lift)):
                if c.open or c.k > 0.02:
                    p.fillRect(QRectF(0, 0, W, H), QColor(0, 4, 12, int(170 * dim + 85 * sp.fk)))      # dark scrim behind the open card
                    dim = 0.0
                self._draw_card(p, c, faded=op is not None and not c.open and c.k < 0.02)
            if sp.empty:
                p.setFont(_F(16))
                p.setPen(QColor(C.TEXT_DIM))
                p.drawText(QRectF(0, H / 2 - 20, W, 40), _AL.AlignCenter, "This folder is empty")
            self._draw_topbar(p, W)
            if sp.prompt is None:
                if sp.menu_box is not None:
                    self._draw_menu_panel(p, sp.menu_box)
                for b in sp.buttons:
                    self._draw_button(p, b)
            if sp.pages > 1 and op is None:
                p.setFont(_F(12, QFont.Weight.DemiBold))
                p.setPen(QColor(C.TEXT_MED))
                p.drawText(QRectF(W / 2 - 70, H - 112, 140, 52), _AL.AlignCenter, f"Page {sp.page + 1} / {sp.pages}")
            p.setFont(_F(10))
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(0, H - 50, W, 30), _AL.AlignHCenter | _AL.AlignVCenter, sp.hint + "      ·      Esc / ✕ to leave")
        t = sp.toast
        if t:
            p.setFont(_F(11))
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(t) + 44
            r = QRectF((W - tw) / 2, H - 172, tw, 38)
            p.setBrush(QColor(10, 24, 46, 230))
            p.setPen(QPen(QColor(C.PRI), 1))
            p.drawRoundedRect(r, 19, 19)
            p.setPen(QColor(C.TEXT))
            p.drawText(r, _AL.AlignCenter, t)
        if sp.prompt is not None:
            self._draw_prompt(p, W, H)
            for b in sp.buttons:
                self._draw_button(p, b)
        for i, h in enumerate(sp.hands):
            if sp.visible[i] and h.pts:
                self._draw_hand(p, h)

    # full screen: the item alone; a thin title and one control bar that fade away when the hand rests
    def _draw_full_ui(self, p: QPainter, c: Card, W: int, H: int):
        sp = self.space
        a = sp.ui_a
        if a < 0.02:
            return
        d = c.data
        p.save()
        p.setOpacity(a)
        top = QLinearGradient(0, 0, 0, 120)
        top.setColorAt(0, QColor(0, 0, 0, 170))
        top.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, W, 120), QBrush(top))
        bot = QLinearGradient(0, H - 190, 0, H)
        bot.setColorAt(0, QColor(0, 0, 0, 0))
        bot.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(0, H - 190, W, 190), QBrush(bot))
        info = d["title"]
        kind = d.get("kind")
        if kind == "image" and d.get("dims"):
            info += f"   ·   {d['dims'][0]}×{d['dims'][1]}"
        elif kind == "model" and self._tris.get(d["path"]):
            info += f"   ·   {self._tris[d['path']]:,} triangles"
        if kind in ("image", "model") and abs(c.zoom - 1.0) > 0.01:
            info += f"   ·   {int(c.zoom * 100)}%"
        self._title(p, QRectF(40, 28, W - 120, 36), info, 13, "#ffffff")
        if kind == "video" and self._video.active:
            pos, dur, _asp, _end = self._video.info()
            bw = min(W * 0.6, 900.0)
            bar = QRectF((W - bw) / 2, H - 150, bw, 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRoundedRect(bar, 2.5, 2.5)
            if dur > 0:
                p.setBrush(QColor(C.PRI))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(5.0, bar.width() * min(1.0, pos / dur)), 5), 2.5, 2.5)
            p.setFont(_F(9))
            p.setPen(QColor(255, 255, 255, 230))
            tm = lambda x: f"{int(x) // 60}:{int(x) % 60:02d}"                  # noqa: E731
            p.drawText(QRectF(bar.left(), bar.top() - 22, bar.width(), 20), _AL.AlignRight | _AL.AlignVCenter, f"{tm(pos)} / {tm(dur)}")
        for b in sp.buttons:
            self._draw_button(p, b)
        p.restore()

    def _draw_menu_panel(self, p: QPainter, box: tuple):
        r = QRectF(*box)
        p.setPen(QPen(QColor(C.PRI), 1.0))
        p.setBrush(QColor(8, 20, 40, 244))
        p.drawRoundedRect(r, 16, 16)
        for b in self.space.buttons:                                    # a thin rule above Delete
            if b["id"] == "a_delete":
                p.setPen(QPen(QColor(255, 255, 255, 40), 1))
                p.drawLine(QPointF(b["x"] + 8, b["y"] - 3), QPointF(b["x"] + b["w"] - 8, b["y"] - 3))

    def _draw_prompt(self, p: QPainter, W: int, H: int):
        pr = self.space.prompt
        p.fillRect(QRectF(0, 0, W, H), QColor(0, 4, 12, 200))
        box = QRectF(W / 2 - 330, H / 2 - 90, 660, 200)
        p.setBrush(QColor(12, 28, 52, 245))
        p.setPen(QPen(QColor(C.PRI), 1.4))
        p.drawRoundedRect(box, 20, 20)
        p.setFont(_F(14, QFont.Weight.DemiBold))
        p.setPen(QColor(C.TEXT))
        p.drawText(QRectF(box.x() + 28, box.y() + 14, box.width() - 56, 32), _AL.AlignLeft | _AL.AlignVCenter, pr["title"])
        fld = QRectF(box.x() + 28, box.y() + 54, box.width() - 56, 44)
        p.setBrush(QColor(0, 0, 0, 120))
        p.setPen(QPen(QColor(255, 120, 120) if pr["error"] else QColor(C.PRI), 1.2))
        p.drawRoundedRect(fld, 10, 10)
        p.setFont(_F(15))
        fm = QFontMetrics(p.font())
        txt, cur, s0 = pr["text"], pr["cur"], pr["sel0"]
        x0 = fld.x() + 14
        lo, hi = min(cur, s0), max(cur, s0)
        if lo != hi:
            p.fillRect(QRectF(x0 + fm.horizontalAdvance(txt[:lo]), fld.y() + 8, fm.horizontalAdvance(txt[lo:hi]), fld.height() - 16), QColor(60, 140, 255, 130))
        p.setPen(QColor(C.TEXT))
        p.drawText(QRectF(x0, fld.y(), fld.width() - 28, fld.height()), _AL.AlignLeft | _AL.AlignVCenter, txt)
        if int(time.time() * 2) % 2 == 0:
            cx = x0 + fm.horizontalAdvance(txt[:cur])
            p.setPen(QPen(QColor(C.TEXT), 1.6))
            p.drawLine(QPointF(cx, fld.y() + 9), QPointF(cx, fld.bottom() - 9))
        if pr["error"]:
            p.setFont(_F(10))
            p.setPen(QColor(255, 140, 140))
            p.drawText(QRectF(fld.x(), fld.bottom() + 4, fld.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, pr["error"])

    # ── top bar ──────────────────────────────────────────────────────────────────────
    def _draw_topbar(self, p: QPainter, W: int):
        sp = self.space
        left = 40 + 2 * (76 + 12) + 14
        right = min((b["x"] for b in sp.buttons if b["id"] in ("arrange", "sort", "select", "close")), default=W - 40) - 18
        r = QRectF(left, 30, max(100, right - left), 34)
        p.setFont(_F(15, QFont.Weight.DemiBold))
        p.setPen(QColor(C.TEXT))
        fm = QFontMetrics(p.font())
        p.drawText(r, _AL.AlignLeft | _AL.AlignVCenter, fm.elidedText(sp.crumb, Qt.TextElideMode.ElideLeft, int(r.width())))
        p.setFont(_F(10))
        p.setPen(QColor(C.GREEN if sp.select else C.TEXT_DIM))
        p.drawText(QRectF(left, 64, r.width(), 24), _AL.AlignLeft | _AL.AlignVCenter,
                   f"{len(sp.sel)} selected" if sp.select else sp.summary)

    # ── buttons ──────────────────────────────────────────────────────────────────────
    def _draw_button(self, p: QPainter, b: dict):
        sp = self.space
        r = QRectF(b["x"], b["y"], b["w"], b["h"])
        hot = sp.hover_btn == b["id"] and b["on"]
        age = time.time() - sp.flash.get(b["id"], 0.0)
        pulse = max(0.0, 1.0 - age / 0.3)
        a = 1.0 if b["on"] else 0.32
        if b.get("menu"):                                              # a row of the ⋯ menu: flat, left-aligned text
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 90, 90, 60 if b["danger"] else 0) if not hot else QColor(150, 210, 255, 50))
            p.drawRoundedRect(r, 10, 10)
            col = QColor(255, 130, 130) if b["id"] == "a_delete" else QColor(C.TEXT if b["on"] else C.TEXT_DIM)
            col.setAlpha(int(255 * a))
            p.setFont(_F(11, QFont.Weight.DemiBold))
            p.setPen(col)
            p.drawText(QRectF(r.left() + 16, r.top(), r.width() - 24, r.height()), _AL.AlignLeft | _AL.AlignVCenter, b["label"])
            return
        fill = QColor(150, 210, 255, int((26 + 44 * hot + 80 * pulse) * (1 if b["on"] else 0.6)))
        p.setBrush(fill)
        edge = QColor(C.PRI)
        edge.setAlpha(int((130 + 110 * hot) * a))
        p.setPen(QPen(edge, 1.6 if hot else 1.1))
        rr = r.adjusted(-2 * pulse, -2 * pulse, 2 * pulse, 2 * pulse)
        p.drawRoundedRect(rr, 14, 14)
        if b.get("active") or b.get("danger"):
            tint = QColor(255, 90, 90, 70) if b.get("danger") else QColor(60, 220, 150, 60)
            p.setBrush(tint)
            p.setPen(QPen(QColor(255, 110, 110) if b.get("danger") else QColor(C.GREEN), 1.6))
            p.drawRoundedRect(r, 14, 14)
        col = QColor(C.TEXT if b["on"] else C.TEXT_DIM)
        col.setAlpha(int(255 * a))
        icon_rect = QRectF(r.center().x() - 11 - (22 if b["label"] else 0), r.center().y() - 11, 22, 22)
        if not b["label"]:
            icon_rect = QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22)
        ico = {"v_prev": "left", "v_next": "right", "pg_prev": "left", "pg_next": "right", "v_plus": "plus",
               "v_play": "play" if (sp.opened is not None and sp.opened.paused) else "pause",
               "v_minus": "minus", "v_open": "ext", "v_close": "close", "close": "close", "home": "home", "up": "up",
               "explorer": "folder", "sort": "sort", "arrange": "grid", "a_more": "more",
               "v_full": "shrink" if sp.full else "expand"}.get(b["id"])
        textonly = ico is None
        if ico:
            self._icon(p, ico, icon_rect, col)
        if b["label"]:
            p.setFont(_F(11, QFont.Weight.DemiBold))
            p.setPen(col)
            if textonly:
                p.drawText(r, _AL.AlignCenter, b["label"])
            else:
                p.drawText(QRectF(r.left() + 46, r.top(), r.width() - 52, r.height()), _AL.AlignLeft | _AL.AlignVCenter, b["label"])

    @staticmethod
    def _icon(p: QPainter, kind: str, r: QRectF, col: QColor):
        pen = QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        cx, cy = r.center().x(), r.center().y()
        L = lambda a, b, c, d: p.drawLine(QPointF(a, b), QPointF(c, d))       # noqa: E731
        if kind == "close":
            L(x + 3, y + 3, x + w - 3, y + h - 3)
            L(x + 3, y + h - 3, x + w - 3, y + 3)
        elif kind in ("left", "right"):
            s = -1 if kind == "left" else 1
            L(cx - 4 * s, y + 2, cx + 4 * s, cy)
            L(cx + 4 * s, cy, cx - 4 * s, y + h - 2)
        elif kind == "plus":
            L(x + 2, cy, x + w - 2, cy)
            L(cx, y + 2, cx, y + h - 2)
        elif kind == "minus":
            L(x + 2, cy, x + w - 2, cy)
        elif kind == "play":
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(x + 4, y + 2), QPointF(x + 4, y + h - 2), QPointF(x + w - 3, cy)]))
        elif kind == "pause":
            L(x + 6, y + 2, x + 6, y + h - 2)
            L(x + w - 6, y + 2, x + w - 6, y + h - 2)
        elif kind == "up":
            L(cx, y + h - 2, cx, y + 3)
            L(cx - 6, y + 9, cx, y + 3)
            L(cx + 6, y + 9, cx, y + 3)
        elif kind == "home":
            path = QPainterPath()
            path.moveTo(x + 1, cy)
            path.lineTo(cx, y + 2)
            path.lineTo(x + w - 1, cy)
            p.drawPath(path)
            p.drawRect(QRectF(x + 4, cy, w - 8, h / 2 - 2))
        elif kind == "ext":
            p.drawRect(QRectF(x + 2, y + 6, w - 8, h - 8))
            L(cx - 1, cy + 1, x + w - 2, y + 2)
            L(x + w - 9, y + 2, x + w - 2, y + 2)
            L(x + w - 2, y + 2, x + w - 2, y + 9)
        elif kind == "folder":
            p.drawRoundedRect(QRectF(x + 1, y + 5, w - 2, h - 8), 3, 3)
            L(x + 2, y + 5, x + 6, y + 2)
            L(x + 6, y + 2, x + 11, y + 2)
        elif kind == "sort":
            for i, ln in enumerate((w - 2, w - 8, w - 14)):
                L(x + 1, y + 4 + i * 7, x + 1 + ln, y + 4 + i * 7)
        elif kind == "more":
            p.setBrush(col)
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                p.drawEllipse(QPointF(x + 3 + i * (w - 6) / 2, cy), 2.1, 2.1)
        elif kind in ("expand", "shrink"):
            s2 = 7 if kind == "expand" else -7
            for sx, sy in ((x + 2, y + 2), (x + w - 2, y + 2), (x + 2, y + h - 2), (x + w - 2, y + h - 2)):
                dx = 1 if sx < cx else -1
                dy = 1 if sy < cy else -1
                if kind == "shrink":
                    sx, sy = sx + dx * 7, sy + dy * 7
                    dx, dy = -dx, -dy
                L(sx, sy, sx + dx * 7, sy)
                L(sx, sy, sx, sy + dy * 7)
        elif kind == "grid":
            for i in range(2):
                for j in range(2):
                    p.drawRoundedRect(QRectF(x + 2 + i * 10, y + 2 + j * 10, 8, 8), 2, 2)

    # ── cards ────────────────────────────────────────────────────────────────────────
    def _chrome(self, w: float, h: float, accent: QColor) -> QPixmap:
        """The glass body of a resting card (shadow, fill, border, sheen) drawn once and reused: no gradients per card per frame."""
        dpr = float(self.devicePixelRatioF())
        key = (int(w), int(h), accent.rgb(), dpr)
        pm = self._chromes.get(key)
        if pm is None:
            if len(self._chromes) > 60:
                self._chromes.clear()
            pad = 16
            pm = QPixmap(int((w + 2 * pad) * dpr), int((h + 2 * pad) * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(pad, pad, w, h)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(0, 0, 0, 44))                                         # one soft shadow
            q.drawRoundedRect(rect.adjusted(-3, 4, 3, 10), 19, 19)
            gr = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gr.setColorAt(0, QColor(150, 210, 255, 66))
            gr.setColorAt(1, QColor(40, 90, 160, 44))
            q.setBrush(gr)
            edge = QColor(accent)
            edge.setAlpha(150)
            q.setPen(QPen(edge, 1.2))
            q.drawRoundedRect(rect, 16, 16)
            hl = QPainterPath()
            hl.addRoundedRect(rect.adjusted(2, 2, -2, -h * 0.55), 14, 14)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(255, 255, 255, 12))
            q.drawPath(hl)
            q.end()
            self._chromes[key] = pm
        return pm

    def _draw_card(self, p: QPainter, c: Card, faded: bool = False):
        if c.a < 0.01:
            return
        fs = self._fs and c.open
        w, h = c.w, c.h
        appear = 1.0 if fs else c.a
        sc = 1.0 if fs else (0.9 + 0.1 * appear) * (1.0 + 0.05 * c.lift + 0.03 * c.hov)
        kind = c.data.get("kind", "file")
        accent = QColor({"drive": C.PRI, "folder": C.AMBER, "image": C.PRI, "text": C.ACC, "model": C.ACC, "video": C.PRI}.get(kind, C.TEXT_MED))
        p.save()
        p.setOpacity(appear * (0.35 if faded else 1.0))
        p.translate(c.x, c.y)
        if not fs:
            p.rotate(math.degrees(c.angle))
        p.scale(sc, sc)
        rect = QRectF(-w / 2, -h / 2, w, h)
        cpath = c.data.get("path")
        if not fs:
            p.setPen(Qt.PenStyle.NoPen)
            if c.k < 0.02 and not c.open:                               # resting card: the cached body
                p.drawPixmap(QPointF(-w / 2 - 16, -h / 2 - 16), self._chrome(w, h, accent))
                if c.lift > 0.03:
                    p.setBrush(QColor(0, 0, 0, int(36 * c.lift)))
                    p.drawRoundedRect(rect.adjusted(0, 10, 0, 14), 18, 18)
                if c.hov > 0.02 or c.held:
                    p.setBrush(QColor(150, 210, 255, int(36 * c.hov)))
                    edge = QColor(C.GREEN if c.held else accent)
                    edge.setAlpha(240 if c.held else int(90 + 150 * c.hov))
                    p.setPen(QPen(edge, 1.8))
                    p.drawRoundedRect(rect, 16, 16)
            else:                                                       # opening / open: its size changes every frame, drawn directly
                p.setBrush(QColor(0, 0, 0, 44))
                p.drawRoundedRect(rect.adjusted(-3, 4, 3, 10), 19, 19)
                gr = QLinearGradient(rect.topLeft(), rect.bottomRight())
                gr.setColorAt(0, QColor(150, 210, 255, 128))
                gr.setColorAt(1, QColor(40, 90, 160, 120))
                p.setBrush(gr)
                edge = QColor(accent)
                edge.setAlpha(200)
                p.setPen(QPen(edge, 1.4))
                p.drawRoundedRect(rect, 16, 16)
            if cpath and cpath in self.space.sel:
                p.setBrush(QColor(60, 220, 150, 40))
                p.setPen(QPen(QColor(C.GREEN), 2.6))
                p.drawRoundedRect(rect, 16, 16)
                cr = QRectF(rect.right() - 34, rect.top() + 8, 26, 26)
                p.setBrush(QColor(C.GREEN))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(cr)
                p.setPen(QPen(QColor(4, 20, 14), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cr.x() + 7, cr.center().y()), QPointF(cr.center().x() - 1, cr.bottom() - 8))
                p.drawLine(QPointF(cr.center().x() - 1, cr.bottom() - 8), QPointF(cr.right() - 6, cr.y() + 8))
            elif self.space.select and kind != "drive":
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 70), 1.2, Qt.PenStyle.DashLine))
                p.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 13, 13)
            if cpath and cpath in self.space.clip_paths:
                p.setOpacity(appear * 0.55)                               # cut items look faded until pasted
        if kind == "image":
            self._card_image(p, c, rect)
        elif kind == "model":
            self._card_model(p, c, rect)
        elif kind == "video":
            self._card_video(p, c, rect)
        elif kind == "text":
            self._card_text(p, c, rect)
        elif kind in ("drive", "folder"):
            self._card_place(p, c, rect, accent)
        else:
            self._card_file(p, c, rect)
        p.restore()

    @staticmethod
    def _title(p: QPainter, rect: QRectF, text: str, size: int = 11, color: str | None = None, align=_AL.AlignLeft):
        p.setFont(_F(size, QFont.Weight.DemiBold))
        p.setPen(QColor(color or C.TEXT))
        p.drawText(rect, align | _AL.AlignVCenter, _elided(text, size, int(rect.width())))

    # drives and folders
    def _card_place(self, p: QPainter, c: Card, rect: QRectF, accent: QColor):
        d = c.data
        inner = rect.adjusted(16, 12, -16, -12)
        cx = inner.left() + 46
        cy = inner.top() + 42
        if d["kind"] == "folder":
            tab = QPainterPath()
            tab.addRoundedRect(QRectF(cx - 32, cy - 26, 30, 14), 4, 4)
            body = QPainterPath()
            body.addRoundedRect(QRectF(cx - 32, cy - 18, 64, 46), 7, 7)
            g = QLinearGradient(cx, cy - 18, cx, cy + 28)
            top = QColor(accent)
            top.setAlpha(235)
            bot = QColor(accent).darker(150)
            bot.setAlpha(235)
            g.setColorAt(0, top)
            g.setColorAt(1, bot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(accent).darker(135))
            p.drawPath(tab)
            p.setBrush(g)
            p.drawPath(body)
        else:
            body = QRectF(cx - 36, cy - 16, 72, 36)
            g = QLinearGradient(body.topLeft(), body.bottomLeft())
            g.setColorAt(0, QColor(190, 230, 255, 230))
            g.setColorAt(1, QColor(80, 140, 200, 230))
            p.setPen(QPen(QColor(C.PRI), 1.4))
            p.setBrush(g)
            p.drawRoundedRect(body, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.GREEN))
            p.drawEllipse(QPointF(body.right() - 10, body.bottom() - 9), 3.2, 3.2)
            p.setBrush(QColor(20, 50, 90, 150))
            p.drawRoundedRect(QRectF(body.left() + 8, body.bottom() - 11, 26, 4), 2, 2)
        tx = inner.left() + 100
        if d["kind"] == "drive":
            self._title(p, QRectF(tx - 10, inner.top() + 14, inner.right() - tx + 10, 24), d["title"], 11)
        else:
            self._title(p, QRectF(inner.left(), inner.bottom() - 52, inner.width(), 26), d["title"], 12)
        p.setFont(_F(9))
        p.setPen(QColor(C.TEXT_DIM))
        if d["kind"] == "drive":
            bar = QRectF(inner.left(), inner.bottom() - 34, inner.width(), 8)
            p.setBrush(QColor(255, 255, 255, 30))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bar, 4, 4)
            used = max(0.0, min(1.0, d.get("used", 0.0)))
            p.setBrush(QColor(C.RED if used > 0.9 else C.AMBER if used > 0.75 else C.PRI))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(8.0, bar.width() * used), bar.height()), 4, 4)
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(inner.left(), inner.bottom() - 22, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))
        else:
            p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))

    # generic files (zip, pdf, exe …)
    def _card_file(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        if c.k > 0.5:
            self._open_file(p, c, rect)
            return
        inner = rect.adjusted(16, 12, -16, -12)
        pg = QRectF(inner.left() + 6, inner.top() + 2, 40, 52)
        path = QPainterPath()
        path.moveTo(pg.left(), pg.top())
        path.lineTo(pg.right() - 12, pg.top())
        path.lineTo(pg.right(), pg.top() + 12)
        path.lineTo(pg.right(), pg.bottom())
        path.lineTo(pg.left(), pg.bottom())
        path.closeSubpath()
        p.setPen(QPen(QColor(C.TEXT_MED), 1.3))
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawPath(path)
        ext = (d.get("_ext") or "").lstrip(".").upper()[:4] or "FILE"
        p.setFont(_F(8, QFont.Weight.Bold))
        p.setPen(QColor(C.PRI))
        p.drawText(QRectF(pg.left(), pg.top() + 22, pg.width(), 20), _AL.AlignCenter, ext)
        self._title(p, QRectF(inner.left(), inner.bottom() - 52, inner.width(), 26), d["title"], 11)
        p.setFont(_F(9))
        p.setPen(QColor(C.TEXT_DIM))
        p.drawText(QRectF(inner.left(), inner.bottom() - 26, inner.width(), 20), _AL.AlignLeft | _AL.AlignVCenter, d.get("sub", ""))

    def _open_file(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        inner = rect.adjusted(34, 28, -34, -28)
        self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 44), d["title"], 18, C.PRI)
        p.setPen(QPen(QColor(C.PRI), 1))
        p.drawLine(QPointF(inner.left(), inner.top() + 50), QPointF(inner.left() + 50, inner.top() + 50))
        rows = [("Type", (d.get("_ext") or "").lstrip(".").upper() or "File"), ("Size", human_size(d.get("_sz", 0))),
                ("Modified", d.get("date", "")), ("Location", d.get("path", ""))]
        p.setFont(_F(12))
        for i, (k, v) in enumerate(rows):
            y = inner.top() + 66 + i * 34
            p.setPen(QColor(C.TEXT_DIM))
            p.drawText(QRectF(inner.left(), y, 100, 28), _AL.AlignLeft | _AL.AlignVCenter, k)
            p.setPen(QColor(C.TEXT))
            fm = QFontMetrics(p.font())
            p.drawText(QRectF(inner.left() + 100, y, inner.width() - 100, 28), _AL.AlignLeft | _AL.AlignVCenter,
                       fm.elidedText(v, Qt.TextElideMode.ElideMiddle, int(inner.width() - 100)))
        from core.hand_space import can_launch
        if not can_launch(d):
            p.setFont(_F(10))
            p.setPen(QColor(C.AMBER))
            p.drawText(QRectF(inner.left(), inner.bottom() - 30, inner.width(), 26), _AL.AlignLeft | _AL.AlignVCenter,
                       "Programs and scripts are never started from a gesture.")

    # notes
    def _card_text(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        mono = bool(d.get("mono"))
        if c.k > 0.5:
            inner = rect.adjusted(34, 26, -34, -26)
            self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 44), d["title"], 18, C.PRI)
            p.setPen(QPen(QColor(C.PRI), 1))
            p.drawLine(QPointF(inner.left(), inner.top() + 48), QPointF(inner.left() + 50, inner.top() + 48))
            view = QRectF(inner.left(), inner.top() + 60, inner.width(), inner.height() - 60)
            f = QFont("Cascadia Mono" if mono else "Segoe UI", 11 if mono else 13)
            p.setFont(f)
            p.setPen(QColor(C.TEXT))
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if mono else QTextOption.WrapMode.WordWrap)
            text = d.get("full") or d.get("text") or ""
            full_h = QFontMetrics(f).boundingRect(QRectF(0, 0, view.width() - 14, 10 ** 6).toRect(),
                                                  int(Qt.TextFlag.TextWordWrap), text).height()
            c.scroll = max(0.0, min(c.scroll, max(0.0, full_h - view.height() + 10)))
            p.save()
            p.setClipRect(view)
            p.drawText(QRectF(view.left(), view.top() - c.scroll, view.width() - 14, full_h + 40), text, opt)
            p.restore()
            if full_h > view.height():                                    # scroll bar
                tr = QRectF(view.right() - 5, view.top(), 4, view.height())
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 30))
                p.drawRoundedRect(tr, 2, 2)
                th = max(30.0, view.height() * view.height() / full_h)
                ty = tr.top() + (tr.height() - th) * (c.scroll / max(1.0, full_h - view.height()))
                p.setBrush(QColor(C.PRI))
                p.drawRoundedRect(QRectF(tr.left(), ty, 4, th), 2, 2)
            return
        inner = rect.adjusted(14, 10, -14, -10)
        self._title(p, QRectF(inner.left(), inner.top(), inner.width(), 26), d["title"], 11, C.PRI)
        p.setPen(QPen(QColor(C.PRI), 1))
        p.drawLine(QPointF(inner.left(), inner.top() + 29), QPointF(inner.left() + 34, inner.top() + 29))
        p.setFont(QFont("Cascadia Mono" if mono else "Segoe UI", 8 if mono else 9))
        p.setPen(QColor(C.TEXT))
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        p.save()
        p.setClipRect(QRectF(inner.left(), inner.top() + 34, inner.width(), inner.height() - 34))
        p.drawText(QRectF(inner.left(), inner.top() + 34, inner.width(), inner.height() - 34), d.get("text", "") or "(empty)", opt)
        p.restore()

    # pictures
    def _card_image(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        path = d["image"]
        big = self._large.get(path) if c.k > 0.3 else None
        px = big or self._thumbs.get(path)
        fs = self._fs and c.open
        pad, rad = (0, 0) if fs else (4, 12)
        tr = rect.adjusted(pad, pad, -pad, -pad)
        clip = QPainterPath()
        clip.addRoundedRect(tr, rad, rad)
        p.save()
        p.setClipPath(clip)
        if px is None:
            p.setBrush(QColor(255, 255, 255, 14 + int(10 * math.sin(time.time() * 4))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(tr)
            if path in self._failed:
                p.setPen(QColor(C.TEXT_DIM))
                p.setFont(_F(10))
                p.drawText(tr, _AL.AlignCenter, "Can't show this picture")
        else:
            iw, ih = px.width(), px.height()
            if c.k > 0.3:                                                     # opened: the whole picture, zoomable
                z = max(1.0, c.zoom)
                sw, sh = iw / z, ih / z
                sx = max(0.0, min(iw - sw, c.vcx * iw - sw / 2))
                sy = max(0.0, min(ih - sh, c.vcy * ih - sh / 2))
                p.drawPixmap(tr, px, QRectF(sx, sy, sw, sh))
            else:                                                             # small card: fill it, crop the overflow
                k = max(tr.width() / iw, tr.height() / ih)
                sw, sh = tr.width() / k, tr.height() / k
                p.drawPixmap(tr, px, QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh))
        if not fs:
            strip = QLinearGradient(0, tr.bottom() - 46, 0, tr.bottom())
            strip.setColorAt(0, QColor(0, 0, 0, 0))
            strip.setColorAt(1, QColor(0, 0, 0, 190))
            p.fillRect(QRectF(tr.left(), tr.bottom() - 46, tr.width(), 46), QBrush(strip))
        p.restore()
        if fs:
            return
        title = d["title"] if c.k < 0.5 else d["title"] + (f"   ·   {d['dims'][0]}×{d['dims'][1]}" if d.get("dims") else "")
        self._title(p, QRectF(rect.left() + 16, rect.bottom() - 34, rect.width() - 100, 26), title, 10 if c.k < 0.5 else 12, "#ffffff")
        if c.k > 0.5 and c.zoom > 1.01:
            p.setFont(_F(11, QFont.Weight.DemiBold))
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(QRectF(rect.right() - 100, rect.bottom() - 34, 84, 26), _AL.AlignRight | _AL.AlignVCenter, f"{int(c.zoom * 100)}%")

    # 3D models: shaded by the GPU
    def _card_model(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        path = d["path"]
        fs = self._fs and c.open
        pad, rad = (0, 0) if fs else (4, 12)
        tr = rect.adjusted(pad, pad, -pad, -pad)
        g = QLinearGradient(tr.topLeft(), tr.bottomLeft())
        g.setColorAt(0, QColor(12, 30, 60, 255 if fs else 215))
        g.setColorAt(1, QColor(3, 8, 20, 255 if fs else 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(tr, rad, rad)
        opened = c.k > 0.3
        drawn = False
        state = "off"
        if self._cv is not None and self._mesh.ok:
            state = self._mesh_state(c, opened)
            if state == "ready" and (opened or (abs(c.angle) < 0.12 and self._live < 12)):
                area = tr if fs else tr.adjusted(0, 4, 0, -(54 if opened else 44))
                box = p.worldTransform().mapRect(area)
                if opened:
                    yaw, pitch, zoom = c.yaw, c.pitch, c.zoom
                else:
                    yaw, pitch, zoom = time.time() * 0.7 + c.phase, 0.35, 1.0
                drawn = self._mesh.draw(p, self._cv, path, box, yaw, pitch, zoom, p.opacity(), self._cm, self._ca)
                if drawn and not opened:
                    self._live += 1
                    self._anim = True
        if not drawn:
            msg = {"loading": "Loading 3D model…", "failed": self._mfail.get(path, "Can't show this model"),
                   "off": "3D models need OpenGL (hw_accel on)", "idle": ""}.get(state, "")
            f = _F(26 if not opened else 40, QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor(C.ACC))
            p.drawText(QRectF(tr.left(), tr.top() + 6, tr.width(), tr.height() - 70), _AL.AlignCenter, "3D")
            if msg:
                p.setFont(_F(9))
                p.setPen(QColor(C.TEXT_DIM))
                p.drawText(QRectF(tr.left() + 10, tr.bottom() - 62, tr.width() - 20, 22), _AL.AlignCenter,
                           QFontMetrics(p.font()).elidedText(msg, Qt.TextElideMode.ElideRight, int(tr.width() - 24)))
        if fs:
            return
        strip = QLinearGradient(0, tr.bottom() - 46, 0, tr.bottom())
        strip.setColorAt(0, QColor(0, 0, 0, 0))
        strip.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(tr.left(), tr.bottom() - 46, tr.width(), 46), QBrush(strip))
        tris = self._tris.get(path)
        title = d["title"] + (f"   ·   {tris:,} triangles" if opened and tris else "")
        self._title(p, QRectF(rect.left() + 16, rect.bottom() - 34, rect.width() - 100, 26), title, 10 if not opened else 12, "#ffffff")
        if c.k > 0.5 and abs(c.zoom - 1.0) > 0.01:
            p.setFont(_F(11, QFont.Weight.DemiBold))
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(QRectF(rect.right() - 100, rect.bottom() - 34, 84, 26), _AL.AlignRight | _AL.AlignVCenter, f"{int(c.zoom * 100)}%")

    # videos: decoded and rendered by the GPU (mpv)
    def _card_video(self, p: QPainter, c: Card, rect: QRectF):
        d = c.data
        path = d["path"]
        fs = self._fs and c.open
        pad, rad = (0, 0) if fs else (4, 12)
        tr = rect.adjusted(pad, pad, -pad, -pad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 255 if fs else 215))
        p.drawRoundedRect(tr, rad, rad)
        playing = False
        err = self._vfail.get(path, "")
        if c.open and self._cv is not None and not err:
            v = self._video
            if not v.active or v.path != path:
                if not v.start(path):
                    self._vfail[path] = v.err or "player error"
                    err = self._vfail[path]
            if v.active and not err:
                box = p.worldTransform().mapRect(tr)
                playing = v.draw(p, self._cv, box, p.opacity(), (c.ow, c.oh) if fs else (c.ow - 8, c.oh - 8))
                pos, dur, asp, _ended = v.info()
                if asp and abs(asp - (d.get("aspect") or 0.0)) > 0.01:
                    d["aspect"] = asp
                if not playing and v.err:
                    self._vfail[path] = v.err
                    err = v.err
                if playing:
                    if not fs:                                       # full screen draws this bar itself, above the controls
                        bar = QRectF(tr.left() + 18, tr.bottom() - 58, tr.width() - 36, 5)
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(255, 255, 255, 60))
                        p.drawRoundedRect(bar, 2.5, 2.5)
                        if dur > 0:
                            p.setBrush(QColor(C.PRI))
                            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(5.0, bar.width() * min(1.0, pos / dur)), 5), 2.5, 2.5)
                        p.setFont(_F(9))
                        p.setPen(QColor(255, 255, 255, 230))
                        fm = lambda s: f"{int(s) // 60}:{int(s) % 60:02d}"         # noqa: E731
                        p.drawText(QRectF(bar.left(), bar.top() - 22, bar.width(), 20), _AL.AlignRight | _AL.AlignVCenter,
                                   f"{fm(pos)} / {fm(dur)}")
                    if c.paused:
                        p.setBrush(QColor(0, 0, 0, 120))
                        p.drawEllipse(tr.center(), 38, 38)
                        p.setBrush(QColor(255, 255, 255, 235))
                        cx, cy = tr.center().x(), tr.center().y()
                        p.drawPolygon(QPolygonF([QPointF(cx - 11, cy - 18), QPointF(cx - 11, cy + 18), QPointF(cx + 19, cy)]))
                    self._anim = True
        if not playing:
            cx, cy = tr.center().x(), tr.center().y() - 12
            p.setPen(QPen(QColor(C.PRI), 2))
            p.setBrush(QColor(110, 231, 255, 36))
            p.drawEllipse(QPointF(cx, cy), 28, 28)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.PRI))
            p.drawPolygon(QPolygonF([QPointF(cx - 9, cy - 13), QPointF(cx - 9, cy + 13), QPointF(cx + 14, cy)]))
            msg = err and f"GPU video unavailable: {err}"[:120]
            if not msg and c.open and self._cv is None:
                msg = "GPU video needs OpenGL (hw_accel on)"
            elif not msg and c.open:
                msg = "Loading video…"
            if msg:
                p.setFont(_F(9))
                p.setPen(QColor(C.AMBER))
                p.drawText(QRectF(tr.left() + 14, tr.bottom() - 96, tr.width() - 28, 40), _AL.AlignCenter | Qt.TextFlag.TextWordWrap,
                           msg + ("  ·  ⧉ opens it in your default player" if err or self._cv is None else ""))
        if fs:
            return
        strip = QLinearGradient(0, tr.bottom() - 46, 0, tr.bottom())
        strip.setColorAt(0, QColor(0, 0, 0, 0))
        strip.setColorAt(1, QColor(0, 0, 0, 190))
        p.fillRect(QRectF(tr.left(), tr.bottom() - 46, tr.width(), 46), QBrush(strip))
        self._title(p, QRectF(rect.left() + 16, rect.bottom() - 34, rect.width() - 100, 26), d["title"], 10 if c.k < 0.5 else 12, "#ffffff")

    # ── hands ────────────────────────────────────────────────────────────────────────
    def _skeleton(self) -> bool:
        if time.time() - getattr(self, "_skel_t", 0.0) > 1.0:
            self._skel_t = time.time()
            try:
                from core import hand_cursor
                self._skel = hand_cursor.show_skeleton()
            except Exception:
                self._skel = False
        return getattr(self, "_skel", False)

    def _draw_hand(self, p: QPainter, h):
        pts = [QPointF(x, y) for x, y in h.pts]
        col = QColor(C.GREEN if h.pinching else C.AMBER if h.claw else C.RED if h.fist else C.PRI)
        if self._skeleton():                                   # optional thin outline, never joint dots
            path = QPainterPath()
            for a, b in BONES:
                path.moveTo(pts[a])
                path.lineTo(pts[b])
            c = QColor(col)
            c.setAlpha(70)
            p.setPen(QPen(c, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        mid = QPointF(h.pos[0], h.pos[1])
        ring = QColor(col)
        ring.setAlpha(230)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ring, 2))
        p.drawEllipse(mid, 10 if h.pinching else 20, 10 if h.pinching else 20)
        if h.claw:
            p.drawEllipse(QPointF(*h.palm), 120, 120)
        if h.fist_prog > 0.05:                                 # fist held: a ring fills up, then "back"
            pc = QPointF(*h.palm)
            p.setPen(QPen(QColor(C.AMBER), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(pc.x() - 46, pc.y() - 46, 92, 92), 90 * 16, int(-360 * 16 * h.fist_prog))
            p.setFont(_F(10, QFont.Weight.DemiBold))
            p.setPen(QColor(C.AMBER))
            p.drawText(QRectF(pc.x() - 50, pc.y() + 52, 100, 22), _AL.AlignCenter, "Back")
