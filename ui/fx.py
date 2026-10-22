from __future__ import annotations

import math
import time

import numpy as np
from PyQt6.QtCore import (
    QEasingCurve, QLineF, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
    QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QGradient, QPolygonF, QRadialGradient, QSurfaceFormat,
)
from PyQt6.QtWidgets import (
    QPushButton, QWidget,
)

import ui.geo as geo
from ui import glholo
from ui import models as objmodels
from ui.theme import C, qcol, read_cfg

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget as _GLW
except Exception:
    _GLW = None

GL_ENABLED = bool(_GLW is not None and read_cfg().get("hw_accel", True))

try:
    from core.avatar import HoloAvatar
except Exception:
    HoloAvatar = None


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def fade_in(w: QWidget, ms: int = 320) -> None:
    return None


def slide_to(w: QWidget, end: QPoint, ms: int = 320) -> None:
    a = QPropertyAnimation(w, b"pos", w)
    a.setDuration(ms)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.start()
    w._slide_anim = a


_BackdropBase = _GLW if GL_ENABLED else QWidget


def samples_for(q: str) -> int:
    return 0 if q == "lite" else 4 if q == "high" else 2


class Backdrop(_BackdropBase):

    def __init__(self, parent=None):
        super().__init__(parent)
        if GL_ENABLED:
            fmt = QSurfaceFormat()
            fmt.setSamples(samples_for(str(read_cfg().get("quality") or "auto")))
            self.setFormat(fmt)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.aurora = True
        self.stars = True
        self.speed = 1.0
        self.paused = False
        self.stage = None
        self._t = 0.0
        self._last_t = time.time()
        self._tick_n = 0
        self._small_t = 0.0
        self._slow = 0
        self._dirty = True
        self._small: QImage | None = None
        rng = np.random.default_rng(11)
        self._stars = rng.random((120, 4))
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(250 if GL_ENABLED else 125)

    def small(self) -> QImage | None:
        return self._small

    def _alive(self) -> bool:
        try:
            return self.isVisible() and not self.window().isMinimized()
        except Exception:
            return True

    def _advance_time(self) -> None:
        now = time.time()
        dt = min(0.25, now - self._last_t)
        self._last_t = now
        self._t += dt * self.speed

    def _tick(self) -> None:
        if self.paused or not self._alive():
            return
        try:
            active = self.window().isActiveWindow()
        except Exception:
            active = True
        if not active:
            self._slow = (self._slow + 1) % 8
            if self._slow:
                return
        st = self.stage
        stage_vis = st is not None and st.isVisible() and not st.paused
        want = 250 if (stage_vis or not GL_ENABLED) else 70
        if self._tm.interval() != want and (self.aurora or self.stars):
            self._tm.setInterval(want)
        if not (self.aurora or self.stars) and not self._dirty:
            return
        forced = self._dirty
        self._dirty = False
        self._tick_n += 1
        self._advance_time()
        if GL_ENABLED and not stage_vis:
            self.update()
        now = time.time()
        if not GL_ENABLED or forced or now - self._small_t >= 0.25:
            self._small_t = now
            self._render_small()
            if not GL_ENABLED:
                self.update()
            if forced or GL_ENABLED or self._tick_n % 2 == 0:
                for c in self.findChildren(GlassCard):
                    if c.isVisible():
                        c.update()

    def _specs(self):
        return ((C.PRI, .30, .50, .20, .27), (C.ACC, .70, .60, .27, .31),
                (C.ACC2, .50, .90, .31, .21), (C.PRI_DIM, .15, .80, .23, .35))

    def _blob(self, i: int, spec, W: float, H: float):
        col, ax, ay, sp, sp2 = spec
        t = self._t
        cx = W * (ax + 0.30 * math.sin(t * sp + i * 1.7))
        cy = H * (ay * 0.7 + 0.30 * math.cos(t * sp2 + i * 2.3))
        return col, cx, cy, max(W, H) * 0.55

    def _vignette(self, p, W: float, H: float) -> None:
        v = QRadialGradient(W / 2, H / 2, max(W, H) * 0.75)
        v.setColorAt(0.55, QColor(0, 0, 0, 0))
        v.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(v))
        p.drawRect(QRectF(0, 0, W, H))

    def _render_small(self) -> None:
        W, H = max(2, self.width() // 6), max(2, self.height() // 6)
        if self._small is None or self._small.width() != W or self._small.height() != H:
            self._small = QImage(W, H, QImage.Format.Format_RGB32)
        p = QPainter(self._small)
        p.fillRect(0, 0, W, H, qcol(C.BG))
        if self.aurora:
            for i, spec in enumerate(self._specs()):
                col, cx, cy, r = self._blob(i, spec, W, H)
                g = QRadialGradient(cx, cy, r)
                g.setColorAt(0.0, qcol(col, 95))
                g.setColorAt(0.55, qcol(col, 28))
                g.setColorAt(1.0, qcol(col, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawRect(0, 0, W, H)
        self._vignette(p, W, H)
        p.end()

    def _draw_aurora_gl(self, p, W: float, H: float) -> None:
        p.fillRect(QRectF(0, 0, W, H), qcol(C.BG))
        if self.aurora:
            lite = bool(self.stage is not None and self.stage.lite)
            p.setPen(Qt.PenStyle.NoPen)
            for i, spec in enumerate(self._specs()[:2 if lite else 4]):
                col, cx, cy, r = self._blob(i, spec, W, H)
                g = QRadialGradient(cx, cy, r)
                g.setColorAt(0.0, qcol(col, 95))
                g.setColorAt(0.55, qcol(col, 28))
                g.setColorAt(1.0, qcol(col, 0))
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(cx, cy), r, r)
        self._vignette(p, W, H)

    def paint_stars(self, p, ox: float = 0.0, oy: float = 0.0, w: float | None = None, h: float | None = None):
        if not self.stars:
            return
        BW, BH = max(1, self.width()), max(1, self.height())
        t = self._t
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, d, ph in self._stars:
            px = (x * BW + t * 6 * (0.3 + d)) % BW - ox
            py = (y * BH - t * 3 * d) % BH - oy
            if w is not None and not (-4 <= px <= w + 4 and -4 <= py <= h + 4):
                continue
            tw = 0.5 + 0.5 * math.sin(t * 1.3 + ph * 20)
            r = 0.5 + 1.4 * d
            p.setBrush(qcol("#ffffff", int(30 + 150 * d * tw)))
            p.drawEllipse(QPointF(px, py), r, r)

    def _paint_software(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._small is not None:
            p.drawImage(QRectF(self.rect()), self._small)
        else:
            p.fillRect(self.rect(), qcol(C.BG))
        self.paint_stars(p)

    def _paint_gl(self) -> None:
        t0 = time.perf_counter()
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._advance_time()
        W, H = float(self.width()), float(self.height())
        self._draw_aurora_gl(p, W, H)
        self.paint_stars(p)
        st = self.stage
        if st is not None and st.external and st.isVisible():
            tl = st.mapTo(self, QPoint(0, 0))
            st._origin = (tl.x(), tl.y())
            p.save()
            p.translate(tl.x(), tl.y())
            p.setClipRect(QRectF(0, 0, st.width(), st.height()))
            st._paint_scene(p, st.width(), st.height())
            p.restore()
        p.end()
        if st is not None:
            st._frame_done((time.perf_counter() - t0) * 1000.0)

    if GL_ENABLED:
        def paintGL(self):
            self._paint_gl()
    else:
        def paintEvent(self, e):
            self._paint_software(e)



class GlassCard(QWidget):

    def __init__(self, parent=None, radius: int = 22, tint: int = 150, accent: str | None = None):
        super().__init__(parent)
        self.radius = radius
        self.tint = tint
        self.accent = accent
        self._bd: Backdrop | None = None

    def _find_bd(self):
        if self._bd is not None:
            return self._bd
        w = self.parentWidget()
        while w is not None and not isinstance(w, Backdrop):
            w = w.parentWidget()
        self._bd = w
        return w

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(path)
        bd = self._find_bd()
        img = bd.small() if bd is not None else None
        if img is not None and not img.isNull() and bd.width() > 0:
            try:
                tl = self.mapTo(bd, QPoint(0, 0))
                k = img.width() / bd.width()
                p.drawImage(r, img, QRectF(tl.x() * k, tl.y() * k, self.width() * k, self.height() * k))
            except Exception:
                pass
        p.fillRect(self.rect(), qcol(C.PANEL, self.tint))
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(255, 255, 255, 22))
        g.setColorAt(0.5, QColor(255, 255, 255, 4))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), QBrush(g))
        p.setClipping(False)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        edge = qcol(self.accent or "#ffffff", 95 if self.accent else 70)
        bg.setColorAt(0.0, edge)
        bg.setColorAt(0.5, QColor(255, 255, 255, 14))
        bg.setColorAt(1.0, qcol(self.accent or "#ffffff", 50 if self.accent else 26))
        p.setPen(QPen(QBrush(bg), 1.1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class Toggle(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 27)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = bool(checked)
        self._k = 1.0 if self._on else 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(200)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._set_k)

    def _set_k(self, v):
        self._k = float(v)
        self.update()

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, on: bool, emit: bool = False) -> None:
        on = bool(on)
        if on == self._on:
            return
        self._on = on
        self._an.stop()
        self._an.setStartValue(self._k)
        self._an.setEndValue(1.0 if on else 0.0)
        self._an.start()
        if emit:
            self.toggled.emit(on)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._on, emit=True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, mix(QColor(255, 255, 255, 36), qcol(C.PRI), self._k))
        g.setColorAt(1, mix(QColor(255, 255, 255, 36), qcol(C.ACC), self._k))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._k
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class GlowButton(QPushButton):

    def __init__(self, text: str = "", variant: str = "ghost", parent=None, pill: bool = False):
        super().__init__(text, parent)
        self.variant = variant
        self.pill = pill
        self._h = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.setMinimumHeight(36)
        self._an = QVariantAnimation(self)
        self._an.setDuration(160)
        self._an.valueChanged.connect(self._set_h)

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def _go(self, to: float):
        self._an.stop()
        self._an.setStartValue(self._h)
        self._an.setEndValue(to)
        self._an.start()

    def enterEvent(self, e):
        self._go(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._go(0.0)
        super().leaveEvent(e)

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width() + 22, max(36, s.height()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        rad = r.height() / 2 if self.pill else 12
        h = self._h
        txt = qcol(C.TEXT)
        if self.variant in ("primary", "danger"):
            a, b = (C.PRI, C.ACC) if self.variant == "primary" else (C.RED, C.ACC2)
            if h > 0.01:
                gl = QRadialGradient(r.center(), r.width() * 0.7)
                gl.setColorAt(0, qcol(a, int(70 * h)))
                gl.setColorAt(1, qcol(a, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(gl))
                p.drawRect(self.rect())
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, mix(qcol(a), QColor("#ffffff"), 0.18 * h))
            g.setColorAt(1, mix(qcol(b), QColor("#ffffff"), 0.18 * h))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r, rad, rad)
            txt = qcol("#07080f")
        else:
            on = self.isCheckable() and self.isChecked()
            fill = qcol(C.PRI, 46) if on else QColor(255, 255, 255, int(14 + 26 * h))
            edge = qcol(C.PRI, 170) if on else QColor(255, 255, 255, int(34 + 90 * h))
            p.setBrush(fill)
            p.setPen(QPen(edge, 1))
            p.drawRoundedRect(r, rad, rad)
            if on or h > 0.5:
                txt = qcol(C.PRI) if on else qcol(C.TEXT)
        if not self.isEnabled():
            txt.setAlpha(110)
        p.setPen(txt)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ModalLayer(QWidget):
    closed = pyqtSignal()
    opened = pyqtSignal()

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.hide()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._bg: QImage | None = None
        self._k = 0.0
        self._content: QWidget | None = None
        self._dismissable = True
        self._closing = False
        self._an = QVariantAnimation(self)
        self._an.setDuration(280)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._on_k)
        self._an.finished.connect(self._on_done)

    def is_open(self) -> bool:
        return self.isVisible() and not self._closing

    def present(self, content: QWidget, w: int, h: int, dismissable: bool = True) -> None:
        host = self.parentWidget()
        self._drop_content()
        self.setGeometry(host.rect())
        self.hide()
        try:
            img = self._snapshot(host)
            sw, sh = img.width(), img.height()
            small = img.scaled(max(2, sw // 16), max(2, sh // 16),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self._bg = small.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        except Exception:
            self._bg = None
        self._dismissable = dismissable
        self._closing = False
        content.setParent(self)
        content.setFixedSize(min(w, max(240, host.width() - 40)), min(h, max(200, host.height() - 40)))
        self._content = content
        content.show()
        self._k = 0.0
        self._place()
        self.show()
        self.raise_()
        self.setFocus()
        self._an.stop()
        self._an.setStartValue(0.0)
        self._an.setEndValue(1.0)
        self._an.start()
        self.opened.emit()

    @staticmethod
    def _flat(img: QImage) -> bool:
        w, h = img.width(), img.height()
        if w < 8 or h < 8:
            return True
        lo, hi = [255, 255, 255], [0, 0, 0]
        for gx in range(1, 6):
            for gy in range(1, 6):
                c = img.pixelColor(int(w * gx / 6), int(h * gy / 6))
                for i, v in enumerate((c.red(), c.green(), c.blue())):
                    lo[i] = min(lo[i], v)
                    hi[i] = max(hi[i], v)
        return max(hi[i] - lo[i] for i in range(3)) < 10

    def _snapshot(self, host: QWidget) -> QImage:
        if hasattr(host, "grabFramebuffer"):
            try:
                base = host.grabFramebuffer()
                if not base.isNull():
                    p = QPainter(base)
                    for ch in host.children():
                        if isinstance(ch, QWidget) and ch is not self and ch.isVisible():
                            ch.render(p, ch.pos())
                    p.end()
                    if not self._flat(base):
                        return base
            except Exception:
                pass
        img = host.grab().toImage()
        if self._flat(img) and hasattr(host, "small") and host.small() is not None:
            return host.small()
        return img

    def _drop_content(self):
        if self._content is not None:
            try:
                self._content.hide()
                self._content.deleteLater()
            except Exception:
                pass
        self._content = None

    def _place(self):
        c = self._content
        if c is None:
            return
        dy = (1.0 - self._k) * 26
        c.move(int((self.width() - c.width()) / 2), int((self.height() - c.height()) / 2 + dy))

    def _on_k(self, v):
        self._k = float(v)
        self._place()
        self.update()

    def _on_done(self):
        if self._closing:
            self.hide()
            self._drop_content()
            self._closing = False
            self.closed.emit()

    def dismiss(self) -> None:
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._an.stop()
        self._an.setStartValue(self._k)
        self._an.setEndValue(0.0)
        self._an.start()

    def resizeEvent(self, e):
        self._place()
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._bg is not None:
            p.setOpacity(self._k)
            p.drawImage(self.rect(), self._bg)
        p.setOpacity(1.0)
        p.fillRect(self.rect(), QColor(4, 5, 14, int(140 * self._k)))

    def mousePressEvent(self, e):
        c = self._content
        if self._dismissable and c is not None and not c.geometry().contains(e.position().toPoint()):
            self.dismiss()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._dismissable:
            self.dismiss()
        else:
            super().keyPressEvent(e)


class Stage3D(QWidget):
    model_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 300)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.external = GL_ENABLED
        if not self.external:
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.quality = "auto"
        self.paused = False
        self.lite = False
        self.fps = 0.0
        self._fc = 0
        self._fct = time.time()
        self._ms = 8.0
        self._bar_cache: dict = {}
        self._bd: Backdrop | None = None
        self.state = "INITIALISING"
        self.muted = False
        self.speaking = False
        self._models = objmodels.load_all()
        self._order = objmodels.ordered_names(self._models)
        self.model = self._order[0]
        self.show_status = True
        self.speed = 1.0
        self.particles = True
        self._avatar = None
        if HoloAvatar is not None:
            try:
                self._avatar = HoloAvatar()
            except Exception:
                self._avatar = None
        self._yaw, self._pitch = 0.5, 0.28
        self._vy = 0.0
        self._vp = 0.0
        self._drag: QPointF | None = None
        self._look = [0.0, 0.0]
        self._look_t = [0.0, 0.0]
        self._t = 0.0
        self._last = time.time()
        self._live = 0.0
        self._amp = 0.0
        self._visemes = None
        self._vis_i = None
        self._ripples: list[float] = []
        self._next_ripple = 0.0
        self._cm = np.array(QColor(C.PRI).getRgb()[:3], dtype=np.float64)
        self._ca = np.array(QColor(C.ACC).getRgb()[:3], dtype=np.float64)
        self._last_xyz = None
        self.gpu_enabled = bool(GL_ENABLED and read_cfg().get("gpu_holo", True))
        self.on_gpu_event = None
        self._glh = None
        self._gpu_cache: dict = {}
        self._origin = (0, 0)
        self._geom = (0.0, 0.0, 1.0)
        self._gl_frames = 0
        self._gl_checked = False
        self._halo = geo.circle(46, .35, .0)
        self._ticks = np.linspace(0, 2 * math.pi, 72, endpoint=False)
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._step)
        self._tm.start(24)

    def model_names(self) -> list:
        names = list(self._order)
        if self._avatar is not None:
            names.append("face")
        return names

    def set_model(self, name: str) -> None:
        name = str(name).lower()
        if name == "face" and self._avatar is None:
            name = self._order[0]
        if name == "face" or name in self._models:
            self.model = name
            self.update()

    def _meta(self, key: str, default: str = "0") -> str:
        m = self._models.get(self.model)
        return (m.meta.get(key, default) if m is not None else default)

    def cycle_model(self) -> str:
        ms = self.model_names()
        self.set_model(ms[(ms.index(self.model) + 1) % len(ms)] if self.model in ms else ms[0])
        self.model_changed.emit(self.model)
        return self.model

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            pass

    def set_audio_level(self, level: float) -> None:
        try:
            lv = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            return
        if lv > self._live:
            self._live = lv

    def push_visemes(self, frames, hop: float, at: float) -> None:
        try:
            if not frames:
                return
            hop = max(1e-3, float(hop))
            at = float(at)
            new = list(frames)
            cur = self._visemes
            if cur is not None:
                old, t0, ohop = cur
                if abs(ohop - hop) < 1e-6:
                    i = int(round((at - t0) / hop))
                    if 0 <= i <= len(old) + 1:
                        merged = old[:i] + new
                        played = int((time.time() - t0) / hop) - 2
                        if played > 60:
                            merged = merged[played:]
                            t0 += played * hop
                            if self._vis_i is not None:
                                self._vis_i = max(0, self._vis_i - played)
                        self._visemes = (merged, t0, hop)
                        return
            self._visemes = (new, at, hop)
            self._vis_i = None
        except Exception:
            pass

    def _targets(self):
        if self._meta("palette", "") == "gold":
            if self.muted:
                return QColor(C.RED), QColor("#ff8a5c")
            if self.speaking:
                return QColor("#ffd27a"), QColor("#ff7a1f")
            if self.state in ("THINKING", "PROCESSING"):
                return QColor("#ffb020"), QColor("#ff5a1f")
            if self.state == "SLEEPING":
                return QColor("#9c7a3c"), QColor("#7a4a22")
            return QColor("#ffb02e"), QColor("#ff7a1a")
        if self.muted:
            return QColor(C.RED), QColor(C.RED)
        if self.speaking:
            return QColor(C.PRI), QColor(C.ACC2)
        if self.state in ("THINKING", "PROCESSING"):
            return QColor(C.ACC), QColor(C.AMBER)
        if self.state == "LISTENING":
            return QColor(C.PRI), QColor(C.GREEN)
        if self.state == "SLEEPING":
            return QColor(C.TEXT_DIM), QColor(C.PRI_DIM)
        return QColor(C.PRI), QColor(C.ACC)

    def _alive(self) -> bool:
        if self.paused:
            return False
        try:
            return self.isVisible() and not self.window().isMinimized()
        except Exception:
            return True

    def _step(self) -> None:
        now = time.time()
        dt = min(0.08, now - self._last)
        self._last = now
        v_open = v_wide = v_level = v_seq = None
        sched = self._visemes
        if sched is not None:
            frames, t0, hop = sched
            i = int((now - t0) / hop)
            if 0 <= i < len(frames):
                j = self._vis_i if self._vis_i is not None else i
                v_seq = frames[max(0, j):i + 1]
                self._vis_i = max(j, i + 1)
                v_level, v_open, v_wide = frames[i]
                if v_seq:
                    peak = max(f[0] for f in v_seq)
                    if peak > self._live:
                        self._live = peak
            elif i >= len(frames):
                self._visemes = None
                self._vis_i = None
        self._live *= 0.86
        self._amp += (self._live - self._amp) * 0.4
        self._t += dt * self.speed
        mt, at = self._targets()
        self._cm += (np.array(mt.getRgb()[:3], dtype=np.float64) - self._cm) * min(1.0, dt * 6)
        self._ca += (np.array(at.getRgb()[:3], dtype=np.float64) - self._ca) * min(1.0, dt * 6)

        if self._drag is None:
            self._yaw += (self._vy + (0.32 + self._amp * 1.3) * self.speed) * dt
            self._pitch += self._vp * dt
            self._vy *= 0.94
            self._vp *= 0.94
            self._pitch += (0.26 - self._pitch) * min(1.0, dt * 0.8)
        for i in (0, 1):
            self._look[i] += (self._look_t[i] - self._look[i]) * min(1.0, dt * 5)

        if self.speaking and not self.muted and now >= self._next_ripple:
            self._ripples.append(self._t)
            self._next_ripple = now + 0.75
        self._ripples = [r for r in self._ripples if self._t - r < 2.2]

        if self._avatar is not None and self.model == "face":
            try:
                self._avatar.step(dt, self._amp, speaking=self.speaking, muted=self.muted,
                                  state=self.state, v_open=v_open, v_wide=v_wide or 0.0,
                                  v_level=v_level, v_seq=v_seq,
                                  v_hop=(sched[2] if sched is not None else 0.02))
            except Exception:
                pass
        active = (self.speaking or self._amp > 0.02 or self._drag is not None
                  or bool(self._ripples) or self._visemes is not None)
        try:
            focused = self.window().isActiveWindow()
        except Exception:
            focused = True
        if self.lite:
            want = 40 if active else 80
        else:
            want = 33 if active else 50
        if not focused or self.paused or not self.isVisible():
            want = 200
        if self._tm.interval() != want:
            self._tm.setInterval(want)
        if self._glh is not None and self._glh.used and not self._gl_checked:
            self._gl_frames += 1
            if self._gl_frames >= 60:
                self._gl_checked = True
                QTimer.singleShot(60, self._gl_selfcheck)
        if self._alive():
            self._request_paint()

    def _backdrop(self):
        if self._bd is None:
            w = self.parentWidget()
            while w is not None and not isinstance(w, Backdrop):
                w = w.parentWidget()
            self._bd = w
        return self._bd

    def _request_paint(self) -> None:
        if self.external:
            bd = self._backdrop()
            if bd is not None:
                bd.update()
                return
        self.update()

    def _frame_done(self, ms: float) -> None:
        self._ms += (ms - self._ms) * 0.08
        self._fc += 1
        now = time.time()
        if now - self._fct >= 1.0:
            self.fps = self._fc / (now - self._fct)
            self._fc = 0
            self._fct = now
        if self.quality == "lite":
            self.lite = True
        elif self.quality == "high":
            self.lite = False
        elif self._ms > 22:
            self.lite = True
        elif self._ms < 9:
            self.lite = False

    def _paint_bg(self, p, W, H):
        bd = self._backdrop()
        img = bd.small() if bd is not None else None
        if img is None or img.isNull() or bd.width() <= 0:
            p.fillRect(0, 0, W, H, qcol(C.BG))
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tl = self.mapTo(bd, QPoint(0, 0))
        k = img.width() / bd.width()
        p.drawImage(QRectF(0, 0, W, H), img, QRectF(tl.x() * k, tl.y() * k, W * k, H * k))
        bd.paint_stars(p, tl.x(), tl.y(), W, H)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.position()
            self._vy = self._vp = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        W, H = max(1, self.width()), max(1, self.height())
        self._look_t = [(pos.x() / W - 0.5) * 0.35, (pos.y() / H - 0.5) * 0.25]
        if self._drag is not None:
            dx, dy = pos.x() - self._drag.x(), pos.y() - self._drag.y()
            self._yaw += dx * 0.011
            self._pitch = max(-1.2, min(1.2, self._pitch + dy * 0.009))
            self._vy = dx * 0.6
            self._vp = dy * 0.3
            self._drag = pos

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.cycle_model()

    def leaveEvent(self, e):
        self._look_t = [0.0, 0.0]
        super().leaveEvent(e)

    def _col(self, which: str = "m", a: int = 255) -> QColor:
        v = self._cm if which == "m" else self._ca
        return QColor(int(v[0]), int(v[1]), int(v[2]), max(0, min(255, int(a))))

    def _dots(self, p, sx, sy, z, base: float, alpha: float = 1.0, mixc: float = 0.0):
        b = geo.depth_bucket(z)
        for k in range(4):
            sel = b == k
            if not sel.any():
                continue
            t = (k + 0.5) / 4
            col = mix(self._col("m"), self._col("a"), mixc)
            col.setAlpha(int((50 + 205 * t) * alpha))
            p.setPen(QPen(col, base * (0.55 + 0.9 * t), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            xy = np.column_stack((sx[sel], sy[sel])).tolist()
            p.drawPoints(QPolygonF([QPointF(a, c) for a, c in xy]))

    def _lines(self, p, sx, sy, z, idx, width: float, alpha: float = 1.0, mixc: float = 0.0):
        if len(idx) == 0:
            return
        zm = (z[idx[:, 0]] + z[idx[:, 1]]) / 2
        b = geo.depth_bucket(zm)
        for k in range(4):
            sel = np.where(b == k)[0]
            if sel.size == 0:
                continue
            t = (k + 0.5) / 4
            col = mix(self._col("m"), self._col("a"), mixc)
            col.setAlpha(int((35 + 190 * t) * alpha))
            p.setPen(QPen(col, width * (0.6 + 0.7 * t), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            ii = idx[sel]
            seg = np.column_stack((sx[ii[:, 0]], sy[ii[:, 0]], sx[ii[:, 1]], sy[ii[:, 1]])).tolist()
            p.drawLines([QLineF(a, c, d, e) for a, c, d, e in seg])

    def _chain(self, n: int, closed: bool = True) -> np.ndarray:
        a = np.arange(n)
        b = (a + 1) % n if closed else a + 1
        idx = np.stack([a, b], 1)
        return idx if closed else idx[:-1]

    def _hud_rings(self, p, cx: float, cy: float, rb: float) -> None:
        t = self._t
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - rb, cy - rb, 2 * rb, 2 * rb)
        p.setPen(QPen(self._col("m", 34), 1.0))
        p.drawEllipse(QPointF(cx, cy), rb, rb)
        p.setPen(QPen(self._col("m", 175), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        base = int(t * 22 * 16)
        for k in range(3):
            p.drawArc(rect, (base + k * 120 * 16) % (360 * 16), 36 * 16)
        if self.lite:
            return
        r2 = rb * 0.88
        rect2 = QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2)
        p.setPen(QPen(self._col("a", 130), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for k in range(2):
            p.drawArc(rect2, (-int(t * 36 * 16) + k * 180 * 16) % (360 * 16), 64 * 16)
        ang = self._ticks + t * 0.12
        cs, sn = np.cos(ang).tolist(), np.sin(ang).tolist()
        ri = rb * 1.06
        long_i, short_o, long_o = 6, rb * 1.11, rb * 1.16
        segs = []
        for i, (c, s) in enumerate(zip(cs, sn)):
            ro = long_o if i % long_i == 0 else short_o
            segs.append(QLineF(cx + ri * c, cy + ri * s, cx + ro * c, cy + ro * s))
        p.setPen(QPen(self._col("m", 80), 1.0))
        p.drawLines(segs)

    def _sparks(self, p, cx, cy, R, yaw, n: int = 3, trail: int = 7):
        pts = []
        for k in range(n):
            for j in range(trail):
                a = self._t * (1.3 + 0.25 * k) - j * 0.075 + k * 2.1
                pts.append((math.cos(a), 0.0, math.sin(a)))
        r = geo.rotate(np.array(pts), yaw * 0.3, 0.55)
        sx, sy, z, _ = geo.project(r, cx, cy, R)
        for j in range(trail):
            self._dots(p, sx[j::trail], sy[j::trail], z[j::trail], 5.5 * (1 - j * 0.09), (1 - j / trail), 0.9)

    def _draw_layer(self, p, L, cx, cy, R, yaw, pitch, amp):
        P = L.p
        lite = self.lite
        if lite and P["lite"] == 0:
            return
        t = self._t
        kind = L.kind
        if kind == "sparks":
            self._sparks(p, cx, cy, R * P["r"], yaw, int(P["n"]), int(P["trail"]))
            return
        if kind == "pulse":
            if self._last_xyz is None:
                return
            sx, sy, z = self._last_xyz
            n = len(sx)
            cnt = int(P["n"])
            ids = [int(t * P["speed"] + m * n / cnt) % n for m in range(cnt)]
            if not lite:
                self._dots(p, sx[ids], sy[ids], z[ids], P["size"] * 2.3, 0.25, P["mix"])
            self._dots(p, sx[ids], sy[ids], z[ids], P["size"], 1.0, P["mix"] + 0.1)
            return
        pts = L.verts * (P["scale"] * (1.0 + P["amp"] * amp))
        if P["ampxz"]:
            k = 1.0 + P["ampxz"] * amp
            pts = pts * np.array([k, 1.0, k])
        if P["jit"]:
            pts = pts * (1.0 + P["jit"] * amp * np.sin(L.ar * 1.7 + t * 9))[:, None]
        if P["wob"]:
            pts = pts * (1.0 + P["wob"] * np.sin(L.ar * 0.3 + t * 3 + P["phase"]))[:, None]
        r = geo.rotate(pts, yaw * P["spin"] + P["yaw0"], pitch * P["pitchmul"] + P["tilt"], roll=P["roll"] * t)
        sx, sy, z, _ = geo.project(r, cx, cy, R * P["rad"])
        alpha = P["a"]
        if P["blink"]:
            alpha *= max(0.05, 1.0 - P["blink"] * 0.5 * (1.0 + math.sin(t * P["rate"] + P["phase"])))
        add = P["add"] > 0
        if add:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        try:
            idx = L.idx
            if kind == "faces":
                self._draw_faces(p, r, sx, sy, idx, alpha, P["spec"] > 0)
            elif kind == "lines":
                if P["lite"] < 1 and lite:
                    idx = idx[::2]
                    ymid = L.ymid[::2] if L.ymid is not None else None
                else:
                    ymid = L.ymid
                if P["scan"] == "y" and ymid is not None and len(idx):
                    pulse = ((t * 0.5) % 2.0) - 1.0
                    hot = np.abs(ymid * P["scale"] - pulse) < 0.14
                    self._lines(p, sx, sy, z, idx[~hot], P["w"], alpha, P["mix"])
                    if hot.any():
                        self._lines(p, sx, sy, z, idx[hot], P["w"] * 2.8, 1.0, 0.5)
                else:
                    self._lines(p, sx, sy, z, idx, P["w"], alpha, P["mix"])
                self._last_xyz = (sx, sy, z)
            elif kind == "points":
                ids = idx[::2] if (P["lite"] < 1 and lite) else idx
                if P["scan"] == "lon" and L.ang is not None and len(ids):
                    sweep = (t * 1.1) % (2 * math.pi)
                    d = np.abs(((L.ang[ids] - sweep + math.pi) % (2 * math.pi)) - math.pi)
                    hot = d < 0.22
                    cold = ids[~hot]
                    self._dots(p, sx[cold], sy[cold], z[cold], P["size"], alpha, P["mix"])
                    if hot.any():
                        hi = ids[hot]
                        self._dots(p, sx[hi], sy[hi], z[hi], P["size"] * 2.0, 1.0, 1.0)
                else:
                    self._dots(p, sx[ids], sy[ids], z[ids], P["size"], alpha, P["mix"])
        finally:
            if add:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def _draw_faces(self, p, r, sx, sy, tris, alpha, specular):
        if self.lite or len(tris) == 0:
            return
        tri = r[tris]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nrm /= (np.linalg.norm(nrm, axis=1)[:, None] + 1e-9)
        order = np.argsort(tri[:, :, 2].mean(axis=1)).tolist()
        lums = np.abs(nrm @ np.array([0.4, 0.6, 0.7])).tolist()
        specs = (np.clip(nrm[:, 2], 0, 1) ** 6).tolist()
        sxl, syl, fl = sx.tolist(), sy.tolist(), tris.tolist()
        cm, ca = self._col("m"), self._col("a")
        p.setPen(Qt.PenStyle.NoPen)
        for i in order:
            lum, spec = lums[i], (specs[i] if specular else 0.0)
            col = mix(cm, ca, lum)
            col.setAlpha(int(min(255, (26 + 75 * lum + 110 * spec) * alpha)))
            if spec > 0.2:
                col = mix(col, QColor(255, 255, 255, col.alpha()), spec * 0.55)
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(sxl[j], syl[j]) for j in fl[i]]))

    def _gpu_ok(self, m) -> bool:
        v = self._gpu_cache.get(m.name)
        if v is None:
            v = glholo.supports(m)
            self._gpu_cache[m.name] = v
        return v

    def _gpu_off(self, why: str) -> None:
        self.gpu_enabled = False
        print(f"[GPU holo] disabled: {why}")
        if self.on_gpu_event:
            try:
                self.on_gpu_event(why)
            except Exception:
                pass

    def _gpu_draw(self, p, m, cx, cy, R, yaw, pitch, amp) -> bool:
        host = self._backdrop()
        if host is None:
            return False
        if self._glh is None:
            self._glh = glholo.GlHolo()
            if not self._glh.init():
                self._gpu_off("shader setup failed: " + self._glh.err)
                return False
        clip = (self._origin[0], self._origin[1], self.width(), self.height())
        cm = (float(self._cm[0]), float(self._cm[1]), float(self._cm[2]))
        ca = (float(self._ca[0]), float(self._ca[1]), float(self._ca[2]))
        ok = self._glh.draw(p, host, m, self._origin, cx, cy, R, yaw, pitch, amp, self._t, cm, ca, self.lite, clip)
        if not ok:
            self._gpu_off("draw failed: " + self._glh.err)
        return ok

    def _gl_selfcheck(self) -> None:
        host = self._backdrop()
        if host is None or not self.gpu_enabled:
            return
        try:
            img = host.grabFramebuffer()
            dpr = float(img.devicePixelRatio() or 1.0)
            ox, oy = self._origin
            cx, cy, R = self._geom
            gold = 0
            x0, x1 = int(ox * dpr), int((ox + self.width()) * dpr)
            y0, y1 = int(oy * dpr), int((oy + self.height()) * dpr)
            rmin2 = (0.45 * R * dpr) ** 2
            mx, my = (ox + cx) * dpr, (oy + cy) * dpr
            for y in range(max(0, y0), min(img.height(), y1), 4):
                for x in range(max(0, x0), min(img.width(), x1), 4):
                    if (x - mx) ** 2 + (y - my) ** 2 < rmin2:
                        continue
                    c = img.pixelColor(x, y)
                    if c.red() > 140 and c.red() > c.blue() * 1.6:
                        gold += 1
            if gold < 120:
                self._gpu_off(f"nothing was drawn on screen ({gold} lit samples)")
        except Exception as e:
            print(f"[GPU holo] self-check skipped: {e}")

    def _draw_model(self, p, name, cx, cy, R, yaw, pitch, amp):
        m = self._models.get(name)
        if m is None:
            return
        if self.external and self.gpu_enabled and self._gpu_ok(m):
            if self._gpu_draw(p, m, cx, cy, R, yaw, pitch, amp):
                return
        self._last_xyz = None
        for L in m.layers:
            self._draw_layer(p, L, cx, cy, R, yaw, pitch, amp)

    def _paint_scene(self, p, W, H):
        amp = self._amp
        band_h = H * (0.78 if self.show_status else 0.96)
        cx = W / 2 + self._look[0] * W * 0.05
        cy = band_h * 0.50 + self._look[1] * H * 0.04
        R = min(W * 0.30, band_h * 0.29) * (1.0 + amp * 0.06)
        self._geom = (cx, cy, R)
        main, acc = self._col("m"), self._col("a")

        g = QRadialGradient(cx, cy, R * 2.3)
        g.setColorAt(0.0, QColor(main.red(), main.green(), main.blue(), int(58 + amp * 110)))
        g.setColorAt(0.5, QColor(acc.red(), acc.green(), acc.blue(), int(18 + amp * 40)))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), R * 2.3, R * 2.3)

        floor_on = self._meta("floor", "1") != "0"
        fy = cy + R * 1.45
        fg = QRadialGradient(cx, fy, R * 1.3)
        fg.setColorAt(0, QColor(main.red(), main.green(), main.blue(), 70))
        fg.setColorAt(1, QColor(0, 0, 0, 0))
        p.save()
        p.translate(0, fy)
        p.scale(1.0, 0.16)
        p.translate(0, -fy)
        if floor_on:
            p.setBrush(QBrush(fg))
            p.drawEllipse(QPointF(cx, fy), R * 1.3, R * 1.3)
        p.restore()
        for rt in ([] if (self.lite or not floor_on) else self._ripples):
            age = (self._t - rt) / 2.2
            rr = R * (0.9 + age * 1.6)
            col = QColor(acc.red(), acc.green(), acc.blue(), int(90 * (1 - age)))
            p.setPen(QPen(col, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.save()
            p.translate(0, fy)
            p.scale(1.0, 0.16)
            p.translate(0, -fy)
            p.drawEllipse(QPointF(cx, fy), rr, rr)
            p.restore()

        yaw, pitch = self._yaw + self._look[0] * 2.0, self._pitch + self._look[1]
        face_ok = self.model == "face" and self._avatar is not None
        if face_ok:
            try:
                r_head = min(min(W, H) * 0.355, band_h / (self._avatar.SPAN + 0.08))
                head_cy = 12 + (band_h - 12 - self._avatar.SPAN * r_head) / 2.0 + r_head
                hg = QRadialGradient(W / 2, head_cy, r_head * 1.7)
                hg.setColorAt(0.45, QColor(main.red(), main.green(), main.blue(), 46))
                hg.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(hg))
                p.drawEllipse(QPointF(W / 2, head_cy), r_head * 1.7, r_head * 1.7)
                self._hud_rings(p, W / 2, head_cy, r_head * 1.12)
                self._avatar.paint(p, W / 2, head_cy, r_head, main, acc, qcol(C.BG))
                if not self.lite:
                    p.save()
                    clip = QPainterPath()
                    clip.addEllipse(QPointF(W / 2, head_cy), r_head * 0.95, r_head)
                    p.setClipPath(clip)
                    yy = head_cy - r_head + ((self._t * 0.35) % 1.0) * 2 * r_head
                    sg = QLinearGradient(0, yy - 16, 0, yy + 16)
                    sg.setColorAt(0.0, QColor(main.red(), main.green(), main.blue(), 0))
                    sg.setColorAt(0.5, QColor(main.red(), main.green(), main.blue(), 60))
                    sg.setColorAt(1.0, QColor(main.red(), main.green(), main.blue(), 0))
                    p.fillRect(QRectF(W / 2 - r_head, yy - 16, 2 * r_head, 32), QBrush(sg))
                    p.restore()
            except Exception:
                self.model = "crystal"
                face_ok = False
        if not face_ok:
            if self._meta("hud", "1") != "0":
                self._hud_rings(p, cx, cy, R * 1.62)
            if self._meta("rim", "0") != "0" and not self.lite:
                rim = QRadialGradient(cx, cy, R * 1.22)
                rim.setColorAt(0.78, QColor(main.red(), main.green(), main.blue(), 0))
                rim.setColorAt(0.93, QColor(main.red(), main.green(), main.blue(), 70))
                rim.setColorAt(1.0, QColor(main.red(), main.green(), main.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(rim))
                p.drawEllipse(QPointF(cx, cy), R * 1.22, R * 1.22)
            self._draw_model(p, self.model, cx, cy, R, yaw, pitch, amp)
            if self._meta("glow", "1") != "0":
                cr = R * (0.24 + amp * 0.18) * (1.25 if self._meta("palette", "") == "gold" else 1.0)
                cg = QRadialGradient(cx, cy, cr)
                cg.setColorAt(0, QColor(255, 255, 255, 230))
                cg.setColorAt(0.25, QColor(main.red(), main.green(), main.blue(), 200))
                cg.setColorAt(1, QColor(main.red(), main.green(), main.blue(), 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(cg))
                p.drawEllipse(QPointF(cx, cy), cr, cr)
            if self.particles and not self.lite and self._meta("particles", "1") != "0":
                ang = self._t * 0.6
                for k, sc in enumerate((1.55, 1.85)):
                    pts = geo.rotate(self._halo * sc, ang * (1 if k == 0 else -0.7), 0.35 + k * 0.5)
                    hx, hy, hz, _ = geo.project(pts, cx, cy, R)
                    self._dots(p, hx, hy, hz, 2.6, 0.9, 0.7 + 0.3 * k)

        if self.show_status:
            self._paint_status(p, W, H, band_h, amp)

    def _render(self) -> None:
        t0 = time.perf_counter()
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        self._paint_bg(p, W, H)
        self._paint_scene(p, W, H)
        p.end()
        self._frame_done((time.perf_counter() - t0) * 1000.0)

    def paintEvent(self, _):
        if not self.external:
            self._render()

    def _paint_status(self, p, W, H, band_h, amp):
        main, acc = self._col("m"), self._col("a")
        if self.muted:
            txt = "MUTED"
        elif self.speaking:
            txt = "SPEAKING"
        else:
            txt = self.state
        f = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(QPen(main))
        y = band_h + 4
        p.drawText(QRectF(0, y, W, 24), Qt.AlignmentFlag.AlignCenter, txt)
        N, bw, gap = (18 if self.lite else 28), 5.0, 4.0
        x0 = (W - N * (bw + gap)) / 2
        by = y + 30
        mid = (N - 1) / 2
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(N):
            env = (1 - abs(i - mid) / mid) ** 0.8
            if self.muted:
                h = 3.0
            else:
                idle = 4 + 2.5 * math.sin(self._t * 2.2 + i * 0.55)
                h = idle + amp * 30 * env * (0.55 + 0.45 * math.sin(self._t * 9 + i * 0.8))
            h = max(3.0, min(34.0, h))
            key = (i, N, main.red() >> 2, main.green() >> 2, main.blue() >> 2,
                   acc.red() >> 2, acc.green() >> 2, acc.blue() >> 2)
            br = self._bar_cache.get(key)
            if br is None:
                if len(self._bar_cache) > 600:
                    self._bar_cache.clear()
                gr = QLinearGradient(0, 0, 0, 1)
                gr.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
                gr.setColorAt(0, mix(main, acc, i / N))
                gr.setColorAt(1, QColor(main.red(), main.green(), main.blue(), 60))
                br = QBrush(gr)
                self._bar_cache[key] = br
            p.setBrush(br)
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), by + 20 - h, bw, h), bw / 2, bw / 2)


# by ASDcuber521
