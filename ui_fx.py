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
    QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect, QPushButton, QWidget,
)

import ui_geo as geo
from ui_theme import C, qcol

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
    try:
        fx = QGraphicsOpacityEffect(w)
        fx.setOpacity(0.0)
        w.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", w)
        a.setDuration(ms)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda: w.setGraphicsEffect(None))
        a.start()
        w._fade_anim = a
    except Exception:
        pass


def slide_to(w: QWidget, end: QPoint, ms: int = 320) -> None:
    a = QPropertyAnimation(w, b"pos", w)
    a.setDuration(ms)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.start()
    w._slide_anim = a


class Backdrop(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.aurora = True
        self.stars = True
        self.speed = 1.0
        self._t = 0.0
        self._tick_n = 0
        self._small: QImage | None = None
        rng = np.random.default_rng(11)
        self._stars = rng.random((140, 4))
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(40)

    def small(self) -> QImage | None:
        return self._small

    def _alive(self) -> bool:
        try:
            return self.isVisible() and not self.window().isMinimized()
        except Exception:
            return True

    def _tick(self) -> None:
        if not self._alive():
            return
        self._tick_n += 1
        self._t += 0.040 * self.speed
        self._render_small()
        self.update()
        if self._tick_n % 3 == 0:
            for c in self.findChildren(GlassCard):
                if c.isVisible():
                    c.update()

    def _render_small(self) -> None:
        W, H = max(2, self.width() // 6), max(2, self.height() // 6)
        if self._small is None or self._small.width() != W or self._small.height() != H:
            self._small = QImage(W, H, QImage.Format.Format_RGB32)
        img = self._small
        p = QPainter(img)
        p.fillRect(0, 0, W, H, qcol(C.BG))
        if self.aurora:
            t = self._t
            specs = ((C.PRI, .30, .50, .20, .27), (C.ACC, .70, .60, .27, .31),
                     (C.ACC2, .50, .90, .31, .21), (C.PRI_DIM, .15, .80, .23, .35))
            m = max(W, H)
            for i, (col, ax, ay, sp, sp2) in enumerate(specs):
                cx = W * (ax + 0.30 * math.sin(t * sp + i * 1.7))
                cy = H * (ay * 0.7 + 0.30 * math.cos(t * sp2 + i * 2.3))
                g = QRadialGradient(cx, cy, m * 0.55)
                c0 = qcol(col, 95)
                g.setColorAt(0.0, c0)
                g.setColorAt(0.55, qcol(col, 28))
                g.setColorAt(1.0, qcol(col, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawRect(0, 0, W, H)
        p.end()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._small is not None:
            p.drawImage(QRectF(self.rect()), self._small)
        else:
            p.fillRect(self.rect(), qcol(C.BG))
        W, H = self.width(), self.height()
        if self.stars:
            t = self._t
            p.setPen(Qt.PenStyle.NoPen)
            for x, y, d, ph in self._stars:
                px = (x * W + t * 6 * (0.3 + d)) % W
                py = (y * H - t * 3 * d) % H
                tw = 0.5 + 0.5 * math.sin(t * 1.3 + ph * 20)
                col = qcol("#ffffff", int(30 + 150 * d * tw))
                r = 0.5 + 1.4 * d
                p.setBrush(col)
                p.drawEllipse(QPointF(px, py), r, r)
        v = QRadialGradient(W / 2, H / 2, max(W, H) * 0.75)
        v.setColorAt(0.55, QColor(0, 0, 0, 0))
        v.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(v))
        p.drawRect(self.rect())


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

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.hide()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._bg: QImage | None = None
        self._k = 0.0
        self._content: QWidget | None = None
        self._fx: QGraphicsOpacityEffect | None = None
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
            img = host.grab().toImage()
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
        self._fx = QGraphicsOpacityEffect(content)
        self._fx.setOpacity(0.0)
        content.setGraphicsEffect(self._fx)
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

    def _drop_content(self):
        if self._content is not None:
            try:
                self._content.setGraphicsEffect(None)
                self._content.hide()
                self._content.deleteLater()
            except Exception:
                pass
        self._content = None
        self._fx = None

    def _place(self):
        c = self._content
        if c is None:
            return
        dy = (1.0 - self._k) * 26
        c.move(int((self.width() - c.width()) / 2), int((self.height() - c.height()) / 2 + dy))
        if self._fx is not None:
            self._fx.setOpacity(self._k)

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
    MODELS = ("crystal", "globe", "knot", "helix", "face")
    model_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 300)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.state = "INITIALISING"
        self.muted = False
        self.speaking = False
        self.model = "crystal"
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
        self._blink = True
        self._blink_t = 0.0
        self._cm = np.array(QColor(C.PRI).getRgb()[:3], dtype=np.float64)
        self._ca = np.array(QColor(C.ACC).getRgb()[:3], dtype=np.float64)
        self._ico = geo.icosahedron()
        self._globe = geo.fib_sphere(380)
        self._rings = [geo.circle(90, .0, .0), geo.circle(90, 1.05, .6), geo.circle(90, -.9, -.5)]
        self._knot = geo.torus_knot(520)
        self._helix = geo.helix(120)
        self._halo = geo.circle(46, .35, .0)
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._step)
        self._tm.start(24)

    def set_model(self, name: str) -> None:
        if name in self.MODELS:
            if name == "face" and self._avatar is None:
                name = "crystal"
            self.model = name
            self.update()

    def cycle_model(self) -> str:
        ms = [m for m in self.MODELS if m != "face" or self._avatar is not None]
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

        self._blink_t += dt
        if self._blink_t > 0.7:
            self._blink = not self._blink
            self._blink_t = 0.0

        if self._avatar is not None and self.model == "face":
            try:
                self._avatar.step(dt, self._amp, speaking=self.speaking, muted=self.muted,
                                  state=self.state, v_open=v_open, v_wide=v_wide or 0.0,
                                  v_level=v_level, v_seq=v_seq,
                                  v_hop=(sched[2] if sched is not None else 0.02))
            except Exception:
                pass
        if self._alive():
            self.update()

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
            p.drawPoints(QPolygonF([QPointF(float(a), float(c)) for a, c in zip(sx[sel], sy[sel])]))

    def _lines(self, p, sx, sy, z, idx, width: float, alpha: float = 1.0, mixc: float = 0.0):
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
            p.drawLines([QLineF(float(sx[idx[i, 0]]), float(sy[idx[i, 0]]),
                                float(sx[idx[i, 1]]), float(sy[idx[i, 1]])) for i in sel])

    def _chain(self, n: int, closed: bool = True) -> np.ndarray:
        a = np.arange(n)
        b = (a + 1) % n if closed else a + 1
        idx = np.stack([a, b], 1)
        return idx if closed else idx[:-1]

    def _draw_crystal(self, p, cx, cy, R, yaw, pitch, amp):
        v, faces, edges = self._ico
        s = 1.0 + amp * 0.16
        r1 = geo.rotate(v * s, yaw, pitch)
        sx, sy, z, f = geo.project(r1, cx, cy, R)
        light = np.array([0.4, 0.6, 0.7])
        tri = r1[faces]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nrm /= (np.linalg.norm(nrm, axis=1)[:, None] + 1e-9)
        order = np.argsort(tri[:, :, 2].mean(axis=1))
        p.setPen(Qt.PenStyle.NoPen)
        for i in order:
            lum = abs(float(nrm[i] @ light))
            col = mix(self._col("m"), self._col("a"), lum)
            col.setAlpha(int(24 + 70 * lum))
            p.setBrush(col)
            p.drawPolygon(QPolygonF([QPointF(float(sx[j]), float(sy[j])) for j in faces[i]]))
        self._lines(p, sx, sy, z, edges, 1.5, 1.0, 0.3)
        self._dots(p, sx, sy, z, 6.0, 1.0, 0.5)
        r2 = geo.rotate(v * 0.52 * s, -yaw * 1.7, -pitch * 0.8 + 0.4)
        sx2, sy2, z2, _ = geo.project(r2, cx, cy, R)
        self._lines(p, sx2, sy2, z2, edges, 1.1, 0.8, 0.9)
        self._dots(p, sx2, sy2, z2, 3.6, 0.9, 1.0)
        for ring in self._rings[:2]:
            rr = geo.rotate(ring * 1.38, yaw * 0.6, pitch + 0.2)
            rx, ry, rz, _ = geo.project(rr, cx, cy, R)
            self._lines(p, rx, ry, rz, self._chain(len(ring)), 1.0, 0.45, 0.6)

    def _draw_globe(self, p, cx, cy, R, yaw, pitch, amp):
        n = len(self._globe)
        i = np.arange(n)
        jitter = 1.0 + amp * 0.18 * np.sin(i * 1.7 + self._t * 9)
        pts = self._globe * jitter[:, None]
        r = geo.rotate(pts, yaw, pitch)
        sx, sy, z, f = geo.project(r, cx, cy, R)
        self._dots(p, sx, sy, z, 3.4, 1.0, 0.25)
        for k, ring in enumerate(self._rings):
            rr = geo.rotate(ring * 1.12, yaw * (1.2 + k * .4), pitch + k * 0.5)
            rx, ry, rz, _ = geo.project(rr, cx, cy, R)
            self._lines(p, rx, ry, rz, self._chain(len(ring)), 1.2, 0.8, 0.7 + k * 0.1)
        lat = []
        for ly in (-0.5, 0.0, 0.5):
            c = geo.circle(70) * math.sqrt(1 - ly * ly)
            c[:, 1] = ly
            lat.append(c)
        for c in lat:
            rr = geo.rotate(c, yaw, pitch)
            rx, ry, rz, _ = geo.project(rr, cx, cy, R)
            self._lines(p, rx, ry, rz, self._chain(len(c)), 0.8, 0.35, 0.2)

    def _draw_knot(self, p, cx, cy, R, yaw, pitch, amp):
        n = len(self._knot)
        for k, (sc, mc) in enumerate(((1.0, 0.0), (1.07, 0.5), (0.93, 1.0))):
            pts = np.roll(self._knot, k * 17, axis=0) * sc * (1 + amp * 0.12)
            pts = pts * (1.0 + 0.04 * np.sin(np.arange(n) * 0.3 + self._t * 3 + k))[:, None]
            r = geo.rotate(pts, yaw, pitch, roll=self._t * 0.2)
            sx, sy, z, _ = geo.project(r, cx, cy, R * 1.25)
            self._lines(p, sx, sy, z, self._chain(n), 2.4 - k * 0.5, 1.0 - k * 0.2, mc)
        r = geo.rotate(self._knot, yaw, pitch, roll=self._t * 0.2)
        sx, sy, z, _ = geo.project(r, cx, cy, R * 1.25)
        self._dots(p, sx[::9], sy[::9], z[::9], 5.0, 1.0, 0.8)

    def _draw_helix(self, p, cx, cy, R, yaw, pitch, amp):
        s1, s2 = self._helix
        wob = 1.0 + amp * 0.35
        a = geo.rotate(s1 * np.array([wob, 1.0, wob]), yaw, pitch * 0.5)
        b = geo.rotate(s2 * np.array([wob, 1.0, wob]), yaw, pitch * 0.5)
        ax, ay, az, _ = geo.project(a, cx, cy, R * 1.15)
        bx, by, bz, _ = geo.project(b, cx, cy, R * 1.15)
        n = len(s1)
        rung = np.arange(0, n, 5)
        sx = np.concatenate([ax, bx])
        sy = np.concatenate([ay, by])
        z = np.concatenate([az, bz])
        self._lines(p, sx, sy, z, np.stack([rung, rung + n], 1), 1.2, 0.6, 0.5)
        ch = self._chain(n, closed=False)
        self._lines(p, ax, ay, az, ch, 2.6, 1.0, 0.0)
        self._lines(p, bx, by, bz, ch, 2.6, 1.0, 1.0)
        self._dots(p, sx[np.concatenate([rung, rung + n])], sy[np.concatenate([rung, rung + n])],
                   z[np.concatenate([rung, rung + n])], 6.0, 1.0, 0.5)

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        amp = self._amp
        band_h = H * 0.78
        cx = W / 2 + self._look[0] * W * 0.05
        cy = band_h * 0.52 + self._look[1] * H * 0.04
        R = min(W * 0.34, band_h * 0.40) * (1.0 + amp * 0.06)
        main, acc = self._col("m"), self._col("a")

        g = QRadialGradient(cx, cy, R * 2.3)
        g.setColorAt(0.0, QColor(main.red(), main.green(), main.blue(), int(58 + amp * 110)))
        g.setColorAt(0.5, QColor(acc.red(), acc.green(), acc.blue(), int(18 + amp * 40)))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), R * 2.3, R * 2.3)

        fy = cy + R * 1.45
        fg = QRadialGradient(cx, fy, R * 1.3)
        fg.setColorAt(0, QColor(main.red(), main.green(), main.blue(), 70))
        fg.setColorAt(1, QColor(0, 0, 0, 0))
        p.save()
        p.translate(0, fy)
        p.scale(1.0, 0.16)
        p.translate(0, -fy)
        p.setBrush(QBrush(fg))
        p.drawEllipse(QPointF(cx, fy), R * 1.3, R * 1.3)
        p.restore()
        for rt in self._ripples:
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
        if self.model == "face" and self._avatar is not None:
            try:
                r_head = min(min(W, H) * 0.355, band_h / (self._avatar.SPAN + 0.08))
                head_cy = 12 + (band_h - 12 - self._avatar.SPAN * r_head) / 2.0 + r_head
                self._avatar.paint(p, W / 2, head_cy, r_head, main, acc, qcol(C.BG))
            except Exception:
                self.model = "crystal"
        elif self.model == "globe":
            self._draw_globe(p, cx, cy, R, yaw, pitch, amp)
        elif self.model == "knot":
            self._draw_knot(p, cx, cy, R, yaw, pitch, amp)
        elif self.model == "helix":
            self._draw_helix(p, cx, cy, R, yaw, pitch, amp)
        else:
            self._draw_crystal(p, cx, cy, R, yaw, pitch, amp)

        if self.model != "face":
            cr = R * (0.24 + amp * 0.18)
            cg = QRadialGradient(cx, cy, cr)
            cg.setColorAt(0, QColor(255, 255, 255, 230))
            cg.setColorAt(0.25, QColor(main.red(), main.green(), main.blue(), 200))
            cg.setColorAt(1, QColor(main.red(), main.green(), main.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(cg))
            p.drawEllipse(QPointF(cx, cy), cr, cr)

        if self.particles:
            ang = self._t * 0.6
            for k, sc in enumerate((1.55, 1.85)):
                pts = geo.rotate(self._halo * sc, ang * (1 if k == 0 else -0.7), 0.35 + k * 0.5)
                hx, hy, hz, _ = geo.project(pts, cx, cy, R)
                self._dots(p, hx, hy, hz, 2.6, 0.9, 0.7 + 0.3 * k)

        self._paint_status(p, W, H, band_h, amp)
        p.end()

    def _paint_status(self, p, W, H, band_h, amp):
        main, acc = self._col("m"), self._col("a")
        if self.muted:
            txt = "MUTED"
        elif self.speaking:
            txt = "SPEAKING"
        elif self.state in ("THINKING", "PROCESSING"):
            txt = self.state
        else:
            txt = self.state
        f = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(QPen(main))
        y = band_h + 4
        p.drawText(QRectF(0, y, W, 24), Qt.AlignmentFlag.AlignCenter, txt)
        N, bw, gap = 28, 5.0, 4.0
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
            gr = QLinearGradient(0, by + 20 - h, 0, by + 20)
            gr.setColorAt(0, mix(main, acc, i / N))
            gr.setColorAt(1, QColor(main.red(), main.green(), main.blue(), 60))
            p.setBrush(QBrush(gr))
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), by + 20 - h, bw, h), bw / 2, bw / 2)

# by ASDcuber521
