"""Full-screen, click-through hologram of your hand: glowing skeleton, a cursor ring on the fingertip, and a pinch
indicator that tightens as thumb and index close, then ripples when the click lands."""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ui.overlay_utils import force_topmost
from ui.theme import C

BONES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]
TIPS = (4, 8, 12, 16, 20)
_LABEL = {"pinch": "CLICK", "right": "RIGHT CLICK", "scroll": "SCROLL", "fist": "HOLD TO STOP"}


class HandCursorOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.state = "lost"
        self.pts: list[tuple[float, float]] | None = None
        self.k = 0.0                       # 0 open … 1 pinched
        self._ripple = -1.0
        self._top_t = 0.0
        self._last = 0.0
        self._skel, self._skel_t = False, 0.0
        self._fade = QTimer(self)          # hide the hologram if updates stop (camera stalls)
        self._fade.timeout.connect(self._check_stale)
        self._fade.start(400)

    def _skeleton(self) -> bool:
        if time.time() - self._skel_t > 1.0:                   # config is re-read at most once a second
            self._skel_t = time.time()
            try:
                from core import hand_cursor
                self._skel = hand_cursor.show_skeleton()
            except Exception:
                self._skel = False
        return self._skel

    def _fit(self):
        scr = QGuiApplication.primaryScreen()
        self.setGeometry(scr.geometry())

    def _dpr(self) -> float:
        scr = QGuiApplication.primaryScreen()
        return max(1.0, scr.devicePixelRatio()) if scr else 1.0

    def update_state(self, x: int, y: int, state: str):
        if state == "pinch" and self.state != "pinch":
            self._ripple = 0.0
        self.state = state
        if state == "lost":
            self.pts = None
            self.hide()
        else:
            self._ensure_visible()

    def set_hand(self, pts, pinch: float):
        self._last = time.time()
        if not pts:
            self.pts = None
            self.hide()
            return
        d = self._dpr()                       # controller works in physical pixels, Qt paints in logical ones
        self.pts = [(x / d, y / d) for x, y in pts]
        self.k = pinch
        self._ensure_visible()
        self.update()

    def _ensure_visible(self):
        if not self.isVisible():
            self._fit()
            self.show()
        if time.time() - self._top_t > 1.0:
            self._top_t = time.time()
            force_topmost(self)

    def _check_stale(self):
        if self.isVisible() and time.time() - self._last > 1.2:
            self.pts = None
            self.hide()

    def paintEvent(self, _):
        if not self.pts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pts = [QPointF(x, y) for x, y in self.pts]
        col = QColor({"pinch": C.GREEN, "right": C.ACC, "scroll": C.AMBER, "fist": C.RED}.get(self.state, C.PRI))

        # optional outline (Settings → Gestures → "Show hand outline"): thin bones only, never joint dots
        if self._skeleton():
            path = QPainterPath()
            for a, b in BONES:
                path.moveTo(pts[a])
                path.lineTo(pts[b])
            c = QColor(col)
            c.setAlpha(70)
            p.setPen(QPen(c, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)

        # pinch indicator between thumb and index, closing in as the fingers do
        t, i8 = pts[4], pts[8]
        mid = QPointF((t.x() + i8.x()) / 2, (t.y() + i8.y()) / 2)
        pulse = 1 + 0.12 * math.sin(time.time() * 9)
        rad = (7 + (1 - self.k) * 22) * pulse
        c = QColor(col)
        c.setAlpha(70 + int(160 * self.k))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(c, 2))
        p.drawEllipse(mid, rad, rad)
        if self.state == "pinch":
            c.setAlpha(120)
            p.setBrush(c)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(mid, 6, 6)

        # cursor ring on the fingertip
        ring = QColor(col)
        ring.setAlpha(230)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ring, 2))
        rr = 13 if self.state != "pinch" else 9
        p.drawEllipse(i8, rr, rr)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.4))
        p.drawLine(QPointF(i8.x() - 4, i8.y()), QPointF(i8.x() + 4, i8.y()))
        p.drawLine(QPointF(i8.x(), i8.y() - 4), QPointF(i8.x(), i8.y() + 4))

        # click ripple
        if self._ripple >= 0:
            r = 10 + self._ripple * 46
            rc = QColor(C.GREEN)
            rc.setAlpha(int(200 * (1 - self._ripple)))
            p.setPen(QPen(rc, 2.5))
            p.drawEllipse(i8, r, r)
            self._ripple += 0.09
            if self._ripple >= 1:
                self._ripple = -1.0
            else:
                self.update()

        label = _LABEL.get(self.state)
        if label:
            f = p.font()
            f.setPointSize(8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(QPointF(i8.x() + 20, i8.y() - 16), label)
