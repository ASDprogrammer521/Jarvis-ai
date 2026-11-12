"""Hand Space window: a full-screen holographic workspace of glass cards and a 3D model, driven by your hands.

Logic and physics live in core/hand_space.py; this file only draws them. The mouse works too (handy without a camera).
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient, QTextOption)
from PyQt6.QtWidgets import QWidget

from core.hand_space import Card, Space
from ui.hand_overlay import BONES
from ui.overlay_utils import force_topmost
from ui.theme import C

_PHI = (1 + math.sqrt(5)) / 2
_RAW = [(-1, _PHI, 0), (1, _PHI, 0), (-1, -_PHI, 0), (1, -_PHI, 0), (0, -1, _PHI), (0, 1, _PHI),
        (0, -1, -_PHI), (0, 1, -_PHI), (_PHI, 0, -1), (_PHI, 0, 1), (-_PHI, 0, -1), (-_PHI, 0, 1)]
_NORM = math.sqrt(1 + _PHI ** 2)
VERTS = [(x / _NORM, y / _NORM, z / _NORM) for x, y, z in _RAW]
EDGES = [(i, j) for i in range(12) for j in range(i + 1, 12)
         if math.dist(VERTS[i], VERTS[j]) < 2 / _NORM * 1.02]
_RNG = random.Random(7)
VSPEED = [_RNG.uniform(0.6, 2.6) for _ in VERTS]
RING = [(math.cos(a), math.sin(a)) for a in (2 * math.pi * k / 72 for k in range(72))]
PARTS = []
for _ in range(170):
    _v = [_RNG.gauss(0, 1) for _ in range(3)]
    _n = math.sqrt(sum(c * c for c in _v)) or 1.0
    PARTS.append(((_v[0] / _n, _v[1] / _n, _v[2] / _n), _RNG.uniform(0.3, 1.0), _RNG.uniform(1.5, 3.4)))


class HandSpaceOverlay(QWidget):
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.space = Space(1920, 1080)
        self._imgs: dict[str, QPixmap | None] = {}
        self._last = time.time()
        self._t = QTimer(self)
        self._t.timeout.connect(self._frame)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def show_overlay(self, cards: list[dict] | None = None):
        scr = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(scr)
        self.space.resize(scr.width(), scr.height())
        if cards is not None:
            self.space.set_cards(cards)
            self._imgs.clear()
        self.space.close_requested = False
        self.show()
        force_topmost(self, click_through=False)
        self.activateWindow()
        self.setFocus()
        self._last = time.time()
        self._t.start(16)

    def hide(self):                           # noqa: A003
        self._t.stop()
        super().hide()

    def hideEvent(self, e):
        self._t.stop()
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
        self.update()

    # ── input fallback: mouse / keyboard ─────────────────────────────────────────────
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)
            if self.space.close_requested:
                self.hide()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), True)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.space.mouse(e.position().x(), e.position().y(), False)
            self.space.visible[0] = False

    # ── drawing ──────────────────────────────────────────────────────────────────
    def _img(self, path: str) -> QPixmap | None:
        if path not in self._imgs:
            px = QPixmap(path)
            self._imgs[path] = px.scaled(760, 540, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation) if not px.isNull() else None
        return self._imgs[path]

    def paintEvent(self, _):
        sp = self.space
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        g = QRadialGradient(QPointF(W / 2, H * 0.52), max(W, H) * 0.75)
        g.setColorAt(0, QColor(8, 20, 40, 214))
        g.setColorAt(1, QColor(2, 4, 12, 238))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(110, 231, 255, 10), 1))                       # faint scan lines
        for y in range(0, H, 5):
            p.drawLine(0, y, W, y)

        self._draw_model(p)
        order = sorted(sp.cards, key=lambda c: (c.open, c.held, c.lift))
        for c in order:
            self._draw_card(p, c)
        for i, h in enumerate(sp.hands):
            if sp.visible[i] and h.pts:
                self._draw_hand(p, h)

        # ✕ and hint
        cx, cy = W - 60, 60
        p.setBrush(QColor(255, 255, 255, 18))
        p.setPen(QPen(QColor(C.PRI), 1.6))
        p.drawEllipse(QPointF(cx, cy), 28, 28)
        p.drawLine(QPointF(cx - 8, cy - 8), QPointF(cx + 8, cy + 8))
        p.drawLine(QPointF(cx - 8, cy + 8), QPointF(cx + 8, cy - 8))
        f = QFont("Segoe UI", 10)
        p.setFont(f)
        p.setPen(QColor(C.TEXT_MED))
        p.drawText(QRectF(0, H - 46, W, 30), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, sp.hint + "      ·      Esc / ✕ to leave")

    # 3D model ------------------------------------------------------------------
    def _rot(self, v, yaw, pitch):
        x, y, z = v
        x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        return x, y, z

    def _draw_model(self, p: QPainter):
        m = self.space.model
        r, e = m.radius, m.explode
        c0 = QPointF(m.cx, m.cy)
        glow = QRadialGradient(c0, r * 1.7)
        glow.setColorAt(0, QColor(110, 231, 255, int(70 * (1 - e * 0.6) + 40 * e)))
        glow.setColorAt(1, QColor(110, 231, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c0, r * 1.7, r * 1.7)

        def proj(v, spread=0.0):
            x, y, z = self._rot(v, m.yaw, m.pitch)
            k = 1.0 / (1.0 - 0.25 * z)
            s = r * (1 + spread)
            return QPointF(m.cx + x * s * k, m.cy + y * s * k), z

        alpha = max(0.0, 1.0 - e * 1.6)
        pri = QColor(C.PRI)
        # three great circles
        for ax in range(3):
            path = QPainterPath()
            for j, (a, b) in enumerate(RING):
                v = (a, b, 0.0) if ax == 0 else (0.0, a, b) if ax == 1 else (a, 0.0, b)
                pt, _ = proj(v, e * 0.4)
                path.moveTo(pt) if j == 0 else path.lineTo(pt)
            path.closeSubpath()
            pri.setAlpha(int(90 * alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(pri, 1.2))
            p.drawPath(path)
        # icosahedron edges + vertices
        pts = [proj(v, e * VSPEED[i] * 2.2) for i, v in enumerate(VERTS)]
        for i, j in EDGES:
            z = (pts[i][1] + pts[j][1]) / 2
            pri.setAlpha(int((70 + 150 * (z + 1) / 2) * alpha))
            p.setPen(QPen(pri, 1.6 if z > 0 else 1.0))
            p.drawLine(pts[i][0], pts[j][0])
        p.setPen(Qt.PenStyle.NoPen)
        for pt, z in pts:
            pri.setAlpha(int((120 + 120 * (z + 1) / 2) * max(alpha, e * 0.35)))
            p.setBrush(pri)
            p.drawEllipse(pt, 3.6, 3.6)
        # core
        core = QColor(C.ACC)
        core.setAlpha(int(200 * (1 - e)))
        p.setBrush(core)
        p.drawEllipse(c0, r * 0.07 * (1 + 0.15 * math.sin(time.time() * 4)), r * 0.07 * (1 + 0.15 * math.sin(time.time() * 4)))
        # explosion debris
        if e > 0.02:
            hot = QColor(C.AMBER)
            for d, sp_, size in PARTS:
                pt, z = proj(d, e * sp_ * 3.4)
                hot.setAlpha(int(min(1.0, e * 2.2) * (1.0 - e * 0.35) * 230))
                p.setBrush(hot)
                p.drawEllipse(pt, size * (0.6 + 0.4 * (z + 1) / 2), size * (0.6 + 0.4 * (z + 1) / 2))

    # cards ---------------------------------------------------------------------
    def _draw_card(self, p: QPainter, c: Card):
        w, h = c.w, c.h
        sc = 1.0 + 0.07 * c.lift
        p.save()
        p.translate(c.x, c.y)
        p.rotate(math.degrees(c.angle))
        p.scale(sc, sc)
        rect = QRectF(-w / 2, -h / 2, w, h)
        # soft shadow
        for k in range(5):
            sh = QColor(0, 0, 0, 22 + int(18 * c.lift))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sh)
            p.drawRoundedRect(rect.adjusted(-k * 3, -k * 3 + 10 + 8 * c.lift, k * 3, k * 3 + 10 + 8 * c.lift), 18 + k * 2, 18 + k * 2)
        # glass body
        gr = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gr.setColorAt(0, QColor(150, 210, 255, 62 if not c.open else 120))
        gr.setColorAt(1, QColor(40, 90, 160, 40 if not c.open else 110))
        p.setBrush(gr)
        edge = QColor(C.GREEN if c.held else C.PRI)
        edge.setAlpha(230 if c.held else 150)
        p.setPen(QPen(edge, 1.8 if c.held else 1.2))
        p.drawRoundedRect(rect, 16, 16)
        # highlight
        hl = QPainterPath()
        hl.addRoundedRect(rect.adjusted(2, 2, -2, -h * 0.55), 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawPath(hl)

        d = c.data
        inner = rect.adjusted(14, 12, -14, -12)
        img = self._img(d["image"]) if d.get("image") else None
        if img is not None:
            clip = QPainterPath()
            clip.addRoundedRect(rect.adjusted(5, 5, -5, -5), 12, 12)
            p.setClipPath(clip)
            tr = rect.adjusted(5, 5, -5, -5)
            k = max(tr.width() / img.width(), tr.height() / img.height())          # "cover": fill the card, crop the overflow
            sw, sh = tr.width() / k, tr.height() / k
            p.drawPixmap(tr, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
            p.setClipping(False)
            tf = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
            p.setFont(tf)
            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(rect.adjusted(15, 0, 0, -9).translated(1, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, d["title"])
            p.setPen(QColor(255, 255, 255, 240))
            p.drawText(rect.adjusted(15, 0, 0, -9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, d["title"])
        else:
            tf = QFont("Segoe UI", 13 if c.k < 0.5 else 20, QFont.Weight.Bold)
            p.setFont(tf)
            p.setPen(QColor(C.PRI))
            th = 28 if c.k < 0.5 else 44
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), th), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, d["title"])
            p.setPen(QPen(QColor(C.PRI), 1))
            p.drawLine(QPointF(inner.left(), inner.top() + th + 2), QPointF(inner.left() + 40, inner.top() + th + 2))
            bf = QFont("Segoe UI", 9 if c.k < 0.5 else 12)
            p.setFont(bf)
            p.setPen(QColor(C.TEXT))
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WordWrap)
            text = d.get("text", "")
            if c.k < 0.5:
                text = text[:150] + ("…" if len(text) > 150 else "")
            p.drawText(QRectF(inner.left(), inner.top() + th + 8, inner.width(), inner.height() - th - 8), text, opt)
        p.restore()

    # hands ---------------------------------------------------------------------
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
