"""Lock screen: Jarvis' window goes completely black with a padlock, and only a saved face or the PIN brings it back.

It is its own top-level window laid exactly over the Jarvis window (a child widget can be hidden behind the GPU-rendered 3D
stage, a top-level one cannot). The on-screen keypad makes the PIN usable with the hand cursor or a touch screen too.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.theme import C, rgba


class LockIcon(QWidget):
    """Glowing padlock. When a face is recognised the ring turns green and the shackle lifts as the confirmation fills."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(210, 210)
        self.progress = 0.0
        self.found = False
        self._phase = 0.0

    def tick(self):
        self._phase = (self._phase + 0.045) % (2 * math.pi)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(105, 105)
        col = QColor(C.GREEN if self.found else C.PRI)
        g = QRadialGradient(c, 100)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 60))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 100, 100)

        # rotating ring(s)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, (rad, w, a) in enumerate(((86, 2.4, 220), (96, 1.1, 110))):
            rc = QColor(col)
            rc.setAlpha(a)
            p.setPen(QPen(rc, w, Qt.PenStyle.DashLine if k else Qt.PenStyle.SolidLine))
            p.save()
            p.translate(c)
            p.rotate(math.degrees(self._phase) * (1 if k == 0 else -1.5))
            p.drawEllipse(QPointF(0, 0), rad, rad)
            p.restore()
        if self.progress > 0:                                     # confirmation arc
            gc = QColor(C.GREEN)
            p.setPen(QPen(gc, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(c.x() - 80, c.y() - 80, 160, 160), 90 * 16, int(-360 * 16 * self.progress))

        # padlock: body + shackle (the shackle lifts with the progress)
        lift = 10 * self.progress
        pen = QPen(col, 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        sh = QPainterPath()
        sh.moveTo(c.x() - 17, c.y() - 4 - lift)
        sh.lineTo(c.x() - 17, c.y() - 22 - lift)
        sh.arcTo(QRectF(c.x() - 17, c.y() - 48 - lift, 34, 34), 180, -180)
        sh.lineTo(c.x() + 17, c.y() - 4 - lift)
        p.drawPath(sh)
        body = QRectF(c.x() - 30, c.y() - 4, 60, 46)
        fill = QColor(col)
        fill.setAlpha(46)
        p.setBrush(fill)
        p.drawRoundedRect(body, 9, 9)
        p.setBrush(col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(c.x(), c.y() + 15), 5.5, 5.5)               # keyhole
        p.drawRoundedRect(QRectF(c.x() - 2.4, c.y() + 18, 4.8, 12), 2, 2)


class Dots(QWidget):
    """Shows how many characters of the PIN have been entered (never the characters)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(30)
        self.n = 0
        self._shake = 0.0

    def set_count(self, n: int):
        self.n = n
        self.update()

    def shake(self):
        self._shake = 1.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shown = max(4, self.n)
        gap = 24
        x0 = self.width() / 2 - (shown - 1) * gap / 2
        if self._shake > 0:
            x0 += math.sin(self._shake * 30) * 8 * self._shake
            self._shake = max(0.0, self._shake - 0.08)
            QTimer.singleShot(16, self.update)
        for i in range(shown):
            filled = i < self.n
            col = QColor(C.PRI if filled else C.TEXT_DIM)
            p.setBrush(col if filled else Qt.BrushStyle.NoBrush)
            p.setPen(QPen(col, 1.6))
            p.drawEllipse(QPointF(x0 + i * gap, 15), 6, 6)


class LockScreen(QWidget):
    pin_submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, name: str = "JARVIS"):
        # Qt "parent" is deliberately None: this must be a real top-level window. `anchor` is the window it covers.
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.anchor = parent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._buf = ""
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setContentsMargins(30, 24, 30, 24)
        lay.setSpacing(8)

        self.icon = LockIcon()
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel(f"{name.upper()} IS LOCKED")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        self.title.setStyleSheet(f"color:{C.TEXT};letter-spacing:5px;background:transparent;")
        lay.addWidget(self.title)
        self.status = QLabel("Look at the camera — or enter your PIN")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"color:{C.PRI};background:transparent;font-size:12px;")
        lay.addWidget(self.status)
        lay.addSpacing(6)
        self.dots = Dots()
        self.dots.setFixedWidth(300)
        lay.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignHCenter)
        self.error = QLabel("")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error.setFixedHeight(18)
        self.error.setStyleSheet(f"color:{C.RED};background:transparent;font-size:11px;")
        lay.addWidget(self.error)

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✔"]
        for i, k in enumerate(keys):
            b = QPushButton(k)
            b.setFixedSize(64, 64)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            accent = k == "✔"
            b.setStyleSheet(
                f"QPushButton{{background:{rgba(C.PRI, .2 if accent else .06)};color:{C.TEXT};border:1px solid "
                f"{C.PRI if accent else rgba(C.PRI, .35)};border-radius:32px;font-size:20px;font-weight:600;}}"
                f"QPushButton:hover{{background:{rgba(C.PRI, .3)};border-color:{C.PRI};}}"
                f"QPushButton:pressed{{background:{rgba(C.GREEN, .4)};}}")
            b.clicked.connect(lambda _=False, key=k: self._key(key))
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)

        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(33)

    # ── geometry: exactly over the Jarvis window ─────────────────────────────────────
    def cover(self):
        w = self.anchor
        if w is None:
            return
        if w.isMinimized() or not w.isVisible():
            if self.isVisible():
                self.hide()
            return
        g = w.frameGeometry()
        if self.geometry() != g:
            self.setGeometry(g)
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()
            self.setFocus()

    # ── PIN entry ────────────────────────────────────────────────────────────────────
    def _key(self, k: str):
        if k == "⌫":
            self._buf = self._buf[:-1]
        elif k == "✔":
            self._submit()
            return
        else:
            self._buf += k
        self.error.setText("")
        self.dots.set_count(len(self._buf))

    def _submit(self):
        if not self._buf:
            return
        pin, self._buf = self._buf, ""
        self.dots.set_count(0)
        self.pin_submitted.emit(pin)

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
        elif key == Qt.Key.Key_Backspace:
            self._key("⌫")
        elif key == Qt.Key.Key_Escape:
            self._buf = ""
            self.dots.set_count(0)
        elif e.text() and e.text().isprintable() and not (e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self._key(e.text())
        else:
            super().keyPressEvent(e)

    # ── state from the window ────────────────────────────────────────────────────────
    def set_error(self, msg: str):
        self.error.setText(msg)
        if msg:
            self.dots.shake()

    def set_progress(self, frac: float, seeing_face: bool):
        self.icon.progress = max(0.0, min(1.0, frac))
        self.icon.found = seeing_face and frac > 0
        self.status.setText("Face recognised…" if frac > 0 else "Look at the camera — or enter your PIN")

    def set_camera_note(self, note: str):
        if note:
            self.status.setText(note)

    def focus_pin(self):
        self.cover()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _tick(self):
        if self.isVisible():
            self.icon.tick()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))                     # solid black: nothing of Jarvis shows through
