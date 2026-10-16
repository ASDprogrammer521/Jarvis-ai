from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QConicalGradient,
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ui_fx import GlassCard, Toggle, fade_in, mix
from ui_theme import C, qcol, rgba


def font(size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont("Segoe UI", size, weight)


def draw_icon(p: QPainter, kind: str, r: QRectF, color: QColor, w: float = 1.8) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = r.center()
    s = min(r.width(), r.height())
    u = s / 24.0
    p.translate(c)
    p.scale(u, u)
    path = QPainterPath()
    if kind == "home":
        p.drawEllipse(QPointF(0, 0), 8, 8)
        p.setBrush(color)
        p.drawEllipse(QPointF(0, 0), 2.6, 2.6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 11, 4.2)
    elif kind == "chat":
        path.addRoundedRect(QRectF(-9, -8, 18, 13), 4, 4)
        path.moveTo(-3, 5)
        path.lineTo(-5, 10)
        path.lineTo(2, 5)
        p.drawPath(path)
        for dx in (-4, 0, 4):
            p.drawPoint(QPointF(dx, -1.5))
    elif kind == "gear":
        p.drawEllipse(QPointF(0, 0), 4, 4)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(7 * math.cos(a), 7 * math.sin(a)), QPointF(10 * math.cos(a), 10 * math.sin(a)))
        p.drawEllipse(QPointF(0, 0), 7, 7)
    elif kind in ("mic", "mic_off"):
        path.addRoundedRect(QRectF(-3.5, -10, 7, 12), 3.5, 3.5)
        p.drawPath(path)
        p.drawArc(QRectF(-7, -6, 14, 14), 200 * 16, 140 * 16)
        p.drawLine(QPointF(0, 8), QPointF(0, 11))
        p.drawLine(QPointF(-3, 11), QPointF(3, 11))
        if kind == "mic_off":
            p.setPen(QPen(qcol(C.RED), w + .4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-9, -9), QPointF(9, 10))
    elif kind == "send":
        path.moveTo(-10, -8)
        path.lineTo(10, 0)
        path.lineTo(-10, 8)
        path.lineTo(-6, 0)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(-6, 0), QPointF(3, 0))
    elif kind == "close":
        p.drawLine(QPointF(-7, -7), QPointF(7, 7))
        p.drawLine(QPointF(-7, 7), QPointF(7, -7))
    elif kind == "full":
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p.drawLine(QPointF(sx * 9, sy * 9), QPointF(sx * 9, sy * 4))
            p.drawLine(QPointF(sx * 9, sy * 9), QPointF(sx * 4, sy * 9))
    elif kind == "compact":
        path.addRoundedRect(QRectF(-10, -7, 20, 14), 3, 3)
        p.drawPath(path)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(2, 0, 6, 4), 1.2, 1.2)
    elif kind == "stats":
        for i, h in enumerate((8, 14, 10)):
            p.drawLine(QPointF(-7 + i * 7, 9), QPointF(-7 + i * 7, 9 - h))
    elif kind == "cube":
        pts = [QPointF(0, -10), QPointF(9, -5), QPointF(9, 5), QPointF(0, 10), QPointF(-9, 5), QPointF(-9, -5)]
        path.moveTo(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(0, 0), QPointF(0, 10))
        p.drawLine(QPointF(0, 0), QPointF(9, -5))
        p.drawLine(QPointF(0, 0), QPointF(-9, -5))
    elif kind == "clip":
        p.drawLine(QPointF(0, -8), QPointF(0, 8))
        p.drawLine(QPointF(-8, 0), QPointF(8, 0))
    elif kind == "back":
        p.drawLine(QPointF(8, 0), QPointF(-8, 0))
        p.drawLine(QPointF(-8, 0), QPointF(-2, -6))
        p.drawLine(QPointF(-8, 0), QPointF(-2, 6))
    p.restore()


class IconButton(QPushButton):

    def __init__(self, icon: str, size: int = 42, checkable: bool = False, tip: str = "",
                 parent=None, flat: bool = False):
        super().__init__(parent)
        self.icon_kind = icon
        self.flat = flat
        self.setFixedSize(size, size)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip:
            self.setToolTip(tip)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(160)
        self._an.valueChanged.connect(self._set_h)

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def _go(self, to):
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

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isCheckable() and self.isChecked()
        h = self._h
        if on:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, qcol(C.PRI, 70))
            g.setColorAt(1, qcol(C.ACC, 70))
            p.setBrush(QBrush(g))
            p.setPen(QPen(qcol(C.PRI, 190), 1.1))
            p.drawRoundedRect(r, r.height() * .34, r.height() * .34)
        elif not self.flat or h > 0.01:
            p.setBrush(QColor(255, 255, 255, int((8 if not self.flat else 0) + 28 * h)))
            p.setPen(QPen(QColor(255, 255, 255, int((22 if not self.flat else 0) + 60 * h)), 1))
            p.drawRoundedRect(r, r.height() * .34, r.height() * .34)
        col = mix(qcol(C.TEXT_MED), qcol(C.PRI if on else C.TEXT), max(h, 1.0 if on else 0.0))
        draw_icon(p, self.icon_kind, r.adjusted(r.width() * .26, r.height() * .26, -r.width() * .26, -r.height() * .26), col)

    def set_icon(self, kind: str):
        self.icon_kind = kind
        self.update()


class StatePill(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._text = "INITIALISING"
        self._color = QColor(C.PRI)
        self._t = 0.0
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(90)
        self.setMinimumWidth(150)

    def set(self, text: str, color: str):
        self._text = text
        self._color = QColor(color)
        self.update()

    def _tick(self):
        if self.isVisible():
            self._t += 0.09
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor(self._color.red(), self._color.green(), self._color.blue(), 28))
        p.setPen(QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 110), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        pulse = 0.5 + 0.5 * math.sin(self._t * 4)
        c = QPointF(r.left() + 16, r.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color.red(), self._color.green(), self._color.blue(), int(50 + 60 * pulse)))
        p.drawEllipse(c, 5 + 3 * pulse, 5 + 3 * pulse)
        p.setBrush(self._color)
        p.drawEllipse(c, 3.6, 3.6)
        f = font(9, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        p.setFont(f)
        p.setPen(self._color)
        p.drawText(QRectF(r.left() + 30, r.top(), r.width() - 36, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


class MetricTile(QWidget):

    def __init__(self, label: str, color_attr: str = "PRI", parent=None):
        super().__init__(parent)
        self.label = label
        self.color_attr = color_attr
        self.setFixedSize(132, 112)
        self._pct = 0.0
        self._disp = 0.0
        self._text = "--"
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(60)

    def set_value(self, pct: float, text: str):
        self._pct = max(0.0, min(100.0, pct))
        self._text = text

    def _tick(self):
        if abs(self._pct - self._disp) > 0.1 and self.isVisible():
            self._disp += (self._pct - self._disp) * 0.18
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(getattr(C, self.color_attr))
        ring = QRectF(self.width() / 2 - 34, 6, 68, 68)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, 0, 360 * 16)
        g = QConicalGradient(ring.center(), 90)
        g.setColorAt(0, col)
        g.setColorAt(1, qcol(C.ACC))
        p.setPen(QPen(QBrush(g), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, 90 * 16, int(-self._disp / 100 * 360 * 16))
        p.setPen(qcol(C.TEXT))
        p.setFont(font(10, QFont.Weight.Bold))
        p.drawText(ring, Qt.AlignmentFlag.AlignCenter, self._text)
        p.setPen(qcol(C.TEXT_DIM))
        f = font(8, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(f)
        p.drawText(QRectF(0, 82, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self.label)


class ChatView(QScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self._body = QWidget()
        self._body.setAutoFillBackground(False)
        self._lay = QVBoxLayout(self._body)
        self._lay.setContentsMargins(6, 6, 10, 6)
        self._lay.setSpacing(8)
        self._lay.addStretch()
        self.setWidget(self._body)
        self._count = 0
        self.verticalScrollBar().rangeChanged.connect(self._stick)

    def _bw(self) -> int:
        return max(240, int(self.viewport().width() * 0.88))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self._bw()
        for lb in self._body.findChildren(QLabel):
            if lb.property("bub"):
                lb.setMaximumWidth(w)

    def _stick(self, _lo, hi):
        self.verticalScrollBar().setValue(hi)

    def clear(self):
        while self._lay.count() > 1:
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._count = 0

    def add(self, kind: str, who: str, text: str):
        if self._count > 300:
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            self._count -= 1
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        bub = QLabel(text)
        bub.setWordWrap(True)
        bub.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bub.setFont(font(10))
        bub.setProperty("bub", True)
        bub.setMaximumWidth(self._bw())
        if kind == "user":
            bub.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {rgba(C.PRI, .30)}, stop:1 {rgba(C.ACC, .30)});"
                f"border: 1px solid {rgba(C.PRI, .45)}; border-radius: 14px; padding: 9px 13px; color: {C.TEXT};")
            h.addStretch()
            h.addWidget(bub)
        elif kind in ("sys", "err"):
            col = C.RED if kind == "err" else C.TEXT_DIM
            bub.setFont(font(9))
            bub.setStyleSheet(f"color: {col}; padding: 2px 6px; background: transparent;")
            h.addWidget(bub)
            h.addStretch()
        else:
            bub.setStyleSheet(
                f"background: {rgba('#ffffff', .07)}; border: 1px solid {rgba('#ffffff', .10)};"
                f"border-radius: 14px; padding: 9px 13px; color: {C.TEXT};")
            if who:
                bub.setText(f"<span style='color:{C.PRI};font-weight:600'>{who}</span><br>{text}")
            h.addWidget(bub)
            h.addStretch()
        self._lay.insertWidget(self._lay.count() - 1, row)
        self._count += 1
        fade_in(row, 260)


class HueSlider(QWidget):
    picked = pyqtSignal(str)
    committed = pyqtSignal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = QColor(color).hsvHueF() if QColor(color).hsvHueF() >= 0 else 0.5

    def color(self) -> str:
        return QColor.fromHsvF(self._h, 0.62, 1.0).name()

    def set_color(self, hx: str):
        c = QColor(hx)
        if c.isValid() and c.hsvHueF() >= 0:
            self._h = c.hsvHueF()
            self.update()

    def _from(self, x: float):
        self._h = max(0.0, min(0.999, (x - 12) / max(1, self.width() - 24)))
        self.update()
        self.picked.emit(self.color())

    def mousePressEvent(self, e):
        self._from(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._from(e.position().x())

    def mouseReleaseEvent(self, e):
        self.committed.emit(self.color())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(12, self.height() / 2 - 5, self.width() - 24, 10)
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        for i in range(0, 11):
            g.setColorAt(i / 10, QColor.fromHsvF(min(i / 10, .999), .62, 1.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(bar, 5, 5)
        x = bar.left() + bar.width() * self._h
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(x, bar.center().y()), 10, 10)
        p.setBrush(QColor.fromHsvF(self._h, .62, 1.0))
        p.drawEllipse(QPointF(x, bar.center().y()), 7, 7)


class Segmented(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], current: str = "", parent=None):
        super().__init__(parent)
        self._btns: dict[str, QPushButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for key, label in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(34)
            b.clicked.connect(lambda _=False, k=key: self.select(k, True))
            self._btns[key] = b
            lay.addWidget(b)
        self._cur = current
        self._style()

    def select(self, key: str, emit: bool = False):
        self._cur = key
        self._style()
        if emit:
            self.changed.emit(key)

    def current(self) -> str:
        return self._cur

    def _style(self):
        for k, b in self._btns.items():
            on = k == self._cur
            b.setChecked(on)
            b.setStyleSheet(
                f"QPushButton {{ padding: 0 14px; border-radius: 17px; font-weight: 600;"
                f"color: {C.PRI if on else C.TEXT_MED};"
                f"background: {rgba(C.PRI, .18) if on else rgba('#ffffff', .05)};"
                f"border: 1px solid {rgba(C.PRI, .6) if on else rgba('#ffffff', .10)}; }}"
                f"QPushButton:hover {{ border-color: {C.PRI}; color: {C.TEXT}; }}")


def setting_row(title: str, sub: str, widget: QWidget | None) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 8, 0, 8)
    h.setSpacing(14)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setFont(font(10, QFont.Weight.DemiBold))
    col.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setFont(font(8))
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {C.TEXT_DIM};")
        col.addWidget(s)
    h.addLayout(col, 1)
    if widget is not None:
        h.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
    return w


def section_label(text: str) -> QLabel:
    l = QLabel(text.upper())
    f = font(8, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.4)
    l.setFont(f)
    l.setStyleSheet(f"color: {C.PRI}; margin-top: 14px;")
    return l


def divider() -> QFrame:
    d = QFrame()
    d.setFixedHeight(1)
    d.setStyleSheet(f"background: {rgba('#ffffff', .07)}; border: none;")
    return d


def make_page() -> tuple[QScrollArea, QVBoxLayout]:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sc.viewport().setAutoFillBackground(False)
    body = QWidget()
    body.setAutoFillBackground(False)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(4, 0, 14, 20)
    lay.setSpacing(0)
    sc.setWidget(body)
    return sc, lay


def ghost_btn(text: str, slot=None, variant: str = "ghost"):
    from ui_fx import GlowButton
    b = GlowButton(text, variant)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    return b

# by ASDcuber521
