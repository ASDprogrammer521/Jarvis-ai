from __future__ import annotations

import html as _html
import math
import threading
import time
import uuid
from collections import deque

from PyQt6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ui.fx import GlassCard, GlowButton, fade_in, mix
from ui.theme import C, hotkeys, patch_cfg, qcol, read_cfg, rgba
from ui.widgets import IconButton, MetricTile, draw_icon, font


from ui.hover import HoverAnimationMixin
class LogoMark(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 46)
        self._t = 0.0
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(120)

    def _tick(self):
        if self.isVisible() and not self.window().isMinimized():
            self._t += 0.12
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(23, 23)
        g = QRadialGradient(c, 23)
        g.setColorAt(0.5, qcol(C.PRI, 60))
        g.setColorAt(1, qcol(C.PRI, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, 23, 23)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(C.PRI), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(6, 6, 34, 34), int(self._t * 40 * 16), 250 * 16)
        p.setPen(QPen(qcol(C.ACC, 190), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(12, 12, 22, 22), int(-self._t * 60 * 16), 150 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcol("#ffffff"))
        p.drawEllipse(c, 2.6, 2.6)


class NavItem(HoverAnimationMixin, QPushButton):

    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self.icon_kind = icon
        self.label = text
        self.setCheckable(True)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.valueChanged.connect(self._set_h)
        self._k = 0.0                      # 0 = side bar collapsed (icon only), 1 = expanded

    def set_k(self, k: float):
        self._k = float(k)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        on = self.isChecked()
        if on:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, qcol(C.PRI, 70))
            g.setColorAt(1, qcol(C.ACC, 24))
            p.setBrush(QBrush(g))
            p.setPen(QPen(qcol(C.PRI, 110), 1))
            p.drawRoundedRect(r, 14, 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcol(C.PRI))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 11, 3.5, r.height() - 22), 2, 2)
        elif self._h > 0.01:
            p.setBrush(QColor(255, 255, 255, int(16 * self._h)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 14, 14)
        col = qcol(C.PRI) if on else mix(qcol(C.TEXT_MED), qcol(C.TEXT), self._h)
        draw_icon(p, self.icon_kind, QRectF(r.left() + 14, r.center().y() - 11, 22, 22), col, 1.8)
        alpha = max(0.0, min(1.0, (self._k - 0.35) / 0.55))
        if alpha > 0.01:
            tc = QColor(qcol(C.TEXT) if on else col)
            tc.setAlphaF(alpha)
            p.setPen(tc)
            p.setFont(font(12, QFont.Weight.DemiBold if on else QFont.Weight.Medium))
            p.setClipRect(r)
            p.drawText(QRectF(r.left() + 50, r.top(), max(0.0, r.width() - 56), r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)


class Sidebar(GlassCard):
    """Left navigation. Rests as a slim icon rail and slides open over the content while the mouse is on it.

    It floats above the page area (the window reserves the slim width), so opening it never
    re-lays-out the pages or the 3D stage.
    """
    progress = pyqtSignal(float)           # 0.0 collapsed → 1.0 expanded
    COLLAPSED = 76
    EXPANDED = 248
    MARGIN = 14

    def __init__(self, parent):
        super().__init__(parent, radius=26, tint=150)
        self._k = 0.0
        self.setFixedWidth(self.COLLAPSED)
        self._an = QVariantAnimation(self)
        self._an.setDuration(220)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._set_k)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(260)          # small grace period so it doesn't flicker shut
        self._hold.timeout.connect(self._maybe_collapse)
        parent.installEventFilter(self)

    @property
    def k(self) -> float:
        return self._k

    def reposition(self):
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(self.MARGIN, self.MARGIN, self.width(), max(200, p.height() - 2 * self.MARGIN))

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QEvent.Type.Resize:
            self.reposition()
        return False

    def _go(self, target: float):
        self._an.stop()
        self._an.setStartValue(self._k)
        self._an.setEndValue(float(target))
        self._an.start()

    def _set_k(self, v):
        self._k = float(v)
        self.tint = int(150 + 90 * self._k)   # more opaque while it covers the page
        self.setFixedWidth(int(round(self.COLLAPSED + (self.EXPANDED - self.COLLAPSED) * self._k)))
        self.reposition()
        self.progress.emit(self._k)
        self.update()

    def expand(self):
        self._hold.stop()
        if self._k < 1.0 and not (self._an.state() == QVariantAnimation.State.Running and self._an.endValue() == 1.0):
            self._go(1.0)

    def collapse(self):
        self._hold.stop()
        self._go(0.0)

    def _maybe_collapse(self):
        if self.underMouse():
            return
        self.collapse()

    def enterEvent(self, e):
        self.expand()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hold.start()
        super().leaveEvent(e)


class PageHeader(QWidget):
    """Small title for a page — the window no longer has a top bar."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 2, 0, 4)
        lay.setSpacing(0)
        t = QLabel(title)
        t.setFont(font(20, QFont.Weight.Bold))
        lay.addWidget(t)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
            lay.addWidget(sub)


class InputBar(GlassCard):
    submitted = pyqtSignal(str)
    mic_clicked = pyqtSignal()
    attach_clicked = pyqtSignal()
    detach_clicked = pyqtSignal()

    def __init__(self, parent=None, attach: bool = True):
        super().__init__(parent, radius=30, tint=150, accent=C.PRI)
        self.setFixedHeight(62)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)
        self.mic = IconButton("mic", 44, True, f"Mute / unmute  {hotkeys()['mute']}")
        self.mic.setChecked(True)
        self.mic.clicked.connect(self.mic_clicked.emit)
        lay.addWidget(self.mic)
        self.chip = QPushButton()
        self.chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip.setToolTip("Click to detach")
        self.chip.setStyleSheet(f"QPushButton {{ color: {C.PRI}; background: {rgba(C.PRI, .12)};"
                                f"border: 1px solid {rgba(C.PRI, .4)}; border-radius: 15px; padding: 5px 12px; }}")
        self.chip.clicked.connect(self.detach_clicked.emit)
        self.chip.hide()
        lay.addWidget(self.chip)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Ask me anything…")
        self.edit.setMinimumHeight(44)
        self.edit.setStyleSheet("QLineEdit { background: transparent; border: none; font-size: 14px; }")
        self.edit.returnPressed.connect(self._go)
        lay.addWidget(self.edit, 1)
        if attach:
            att = IconButton("clip", 40, tip="Attach file", flat=True)
            att.clicked.connect(self.attach_clicked.emit)
            lay.addWidget(att)
        send = IconButton("send", 44, tip="Send")
        send.force_on = True
        send.clicked.connect(self._go)
        lay.addWidget(send)

    def _go(self):
        t = self.edit.text().strip()
        if t:
            self.edit.clear()
            self.submitted.emit(t)

    def set_text(self, t: str):
        self.edit.setText(t)
        self.edit.setFocus()
        self.edit.setCursorPosition(len(t))

    def set_live(self, live: bool):
        self.mic.setChecked(live)
        self.mic.set_icon("mic" if live else "mic_off")

    def set_file(self, name: str | None):
        if name:
            self.chip.setText(f"📎 {name[:26]}  ✕")
            self.chip.show()
        else:
            self.chip.hide()


class SparkChart(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(86)
        self.a: deque = deque([0.0] * 60, maxlen=60)
        self.b: deque = deque([0.0] * 60, maxlen=60)

    def push(self, v1: float, v2: float):
        self.a.append(max(0.0, min(100.0, v1)))
        self.b.append(max(0.0, min(100.0, v2)))
        self.update()

    def _series(self, p, data, color: str, w: float, h: float):
        n = len(data)
        pts = [QPointF(i * w / (n - 1), h - 4 - (v / 100.0) * (h - 10)) for i, v in enumerate(data)]
        path = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mx = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, qcol(color, 80))
        g.setColorAt(1, qcol(color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(fill)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(color), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for k in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(0, h * k), QPointF(w, h * k))
        self._series(p, self.b, C.ACC, w, h)
        self._series(p, self.a, C.PRI, w, h)


def _title(text: str) -> QLabel:
    t = QLabel(text)
    f = font(13, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
    t.setFont(f)
    return t


class ActionTile(HoverAnimationMixin, QPushButton):

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.icon_kind, self.label = icon, label
        self.setFixedSize(100, 98)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.valueChanged.connect(self._set_h)





    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF((self.width() - 56) / 2, 4, 56, 56)
        g = QLinearGradient(box.topLeft(), box.bottomRight())
        g.setColorAt(0, QColor(255, 255, 255, int(16 + 26 * self._h)))
        g.setColorAt(1, qcol(C.PRI, int(10 + 40 * self._h)))
        p.setBrush(QBrush(g))
        p.setPen(QPen(qcol(C.PRI, int(40 + 150 * self._h)), 1))
        p.drawRoundedRect(box, 15, 15)
        draw_icon(p, self.icon_kind, box.adjusted(15, 15, -15, -15), mix(qcol(C.TEXT_MED), qcol(C.PRI), self._h), 1.9)
        p.setPen(qcol(C.TEXT_MED) if self._h < 0.5 else qcol(C.TEXT))
        p.setFont(font(10, QFont.Weight.Medium))
        p.drawText(QRectF(0, 65, self.width(), 30), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.label)


class QuickActionsCard(GlassCard):
    triggered = pyqtSignal(str)

    ITEMS = (("folder", "Open Folder", "folder"), ("screenshot", "Screenshot", "screenshot"),
             ("music", "Play Music", "music"), ("calc", "Calculator", "calc"),
             ("note", "Notepad", "notepad"), ("search", "Search Web", "web"))

    def __init__(self, parent=None):
        super().__init__(parent, radius=24, tint=140)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(_title("Quick Actions"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        for i, (icon, label, key) in enumerate(self.ITEMS):
            b = ActionTile(icon, label)
            b.clicked.connect(lambda _=False, k=key: self.triggered.emit(k))
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addStretch()


class PerformanceCard(GlassCard):

    def __init__(self, parent=None):
        super().__init__(parent, radius=24, tint=140)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(6)
        lay.addWidget(_title("System Performance"))
        row = QHBoxLayout()
        row.setSpacing(0)
        self.cpu = MetricTile("CPU", "PRI", ring=64)
        self.ram = MetricTile("RAM", "ACC", ring=64)
        self.tmp = MetricTile("TEMP", "ACC2", ring=64)
        for t in (self.cpu, self.ram, self.tmp):
            row.addWidget(t, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(row)
        self.chart = SparkChart()
        lay.addWidget(self.chart)
        leg = QHBoxLayout()
        for col, name in ((C.PRI, "CPU"), (C.ACC, "RAM")):
            d = QLabel(f"●  {name}")
            d.setStyleSheet(f"color: {col}; font-size: 10px;")
            leg.addWidget(d)
        leg.addStretch()
        lay.addLayout(leg)

    def update_stats(self, s: dict):
        self.cpu.set_value(s["cpu"], f"{s['cpu']:.0f}%")
        self.ram.set_value(s["mem"], f"{s['mem']:.0f}%")
        if s["tmp"] >= 0:
            self.tmp.label = "TEMP"
            self.tmp.set_value(min(100, s["tmp"]), f"{s['tmp']:.0f}°C")
        elif s["gpu"] >= 0:
            self.tmp.label = "GPU"
            self.tmp.set_value(s["gpu"], f"{s['gpu']:.0f}%")
        else:
            self.tmp.label = "NET"
            self.tmp.set_value(min(100, s["net"] * 10), f"{s['net']:.1f}")
        self.chart.push(s["cpu"], s["mem"])


class _Check(QPushButton):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(3, 3, 20, 20)
        if self.isChecked():
            p.setBrush(qcol(C.GREEN, 235))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 6, 6)
            draw_icon(p, "check", r.adjusted(3, 3, -3, -3), qcol("#06120c"), 2.2)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 90), 1.5))
            p.drawRoundedRect(r, 6, 6)


class TasksCard(GlassCard):
    focus_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=24, tint=140)
        self.tasks: list = list(read_cfg().get("tasks") or [])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_title("Today's Tasks"))
        head.addStretch()
        self.count = QLabel("")
        self.count.setStyleSheet(f"color: {C.TEXT_DIM};")
        head.addWidget(self.count)
        lay.addLayout(head)
        self.box = QVBoxLayout()
        self.box.setSpacing(4)
        lay.addLayout(self.box)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Add a task…")
        self.edit.returnPressed.connect(self.add)
        row.addWidget(self.edit, 1)
        b = IconButton("clip", 40, tip="Add task")
        b.clicked.connect(self.add)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addStretch()
        self._render()

    def focus_input(self):
        self.edit.setFocus()

    def reload(self):
        self.tasks = list(read_cfg().get("tasks") or [])
        self._render()

    def _save(self):
        patch_cfg(tasks=self.tasks)

    def add(self):
        t = self.edit.text().strip()
        if t and len(self.tasks) < 14:
            self.tasks.append({"id": uuid.uuid4().hex[:8], "text": t[:80], "done": False})
            self.edit.clear()
            self._save()
            self._render()

    def _toggle(self, tid: str, done: bool):
        for t in self.tasks:
            if t["id"] == tid:
                t["done"] = done
        self._save()
        self._render()

    def _delete(self, tid: str):
        self.tasks = [t for t in self.tasks if t["id"] != tid]
        self._save()
        self._render()

    def _render(self):
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for t in self.tasks:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            cb = _Check()
            cb.setChecked(t["done"])
            cb.clicked.connect(lambda _=False, i=t["id"], c=cb: self._toggle(i, c.isChecked()))
            h.addWidget(cb)
            lb = QLabel(t["text"])
            lb.setWordWrap(True)
            lb.setStyleSheet(f"color: {C.TEXT_DIM if t['done'] else C.TEXT};" + ("text-decoration: line-through;" if t["done"] else ""))
            h.addWidget(lb, 1)
            x = IconButton("close", 26, flat=True, tip="Delete")
            x.clicked.connect(lambda _=False, i=t["id"]: self._delete(i))
            h.addWidget(x)
            self.box.addWidget(row)
        done = sum(1 for t in self.tasks if t["done"])
        self.count.setText(f"{done}/{len(self.tasks)} done" if self.tasks else "")
        if not self.tasks:
            e = QLabel("Nothing planned yet — add your first task.")
            e.setStyleSheet(f"color: {C.TEXT_DIM};")
            self.box.addWidget(e)


def ago(ts: float) -> str:
    d = max(0, int(time.time() - ts))
    if d < 45:
        return "just now"
    if d < 3600:
        return f"{max(1, d // 60)} min ago"
    if d < 86400:
        return f"{d // 3600} hr ago"
    return f"{d // 86400} d ago"


class ActivityCard(GlassCard):

    def __init__(self, parent=None):
        super().__init__(parent, radius=24, tint=140)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)
        lay.addWidget(_title("Recent Activity"))
        self.box = QVBoxLayout()
        self.box.setSpacing(8)
        lay.addLayout(self.box)
        lay.addStretch()
        self.items: deque = deque(maxlen=40)
        self.refresh()

    def add(self, text: str):
        self.items.appendleft((time.time(), str(text)[:70]))
        self.refresh()

    def refresh(self):
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self.items:
            e = QLabel("Your commands and system events appear here.")
            e.setStyleSheet(f"color: {C.TEXT_DIM};")
            e.setWordWrap(True)
            self.box.addWidget(e)
            return
        for ts, text in list(self.items)[:6]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {C.PRI}; font-size: 8px;")
            h.addWidget(dot)
            lb = QLabel(text)
            lb.setStyleSheet(f"color: {C.TEXT};")
            h.addWidget(lb, 1)
            a = QLabel(ago(ts))
            a.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
            h.addWidget(a)
            self.box.addWidget(row)


class MusicCard(GlassCard):
    _now = pyqtSignal(str)
    toast = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent, radius=24, tint=140)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(16)
        art = QLabel("♪")
        art.setFixedSize(64, 64)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setStyleSheet(f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {rgba(C.PRI, .45)}, stop:1 {rgba(C.ACC, .45)});"
                          "border-radius: 16px; font-size: 28px; color: white;")
        lay.addWidget(art)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_title("Music"))
        self.line = QLabel("Spotify")
        self.line.setStyleSheet(f"color: {C.TEXT_MED};")
        self.line.setWordWrap(True)
        col.addWidget(self.line)
        lay.addLayout(col, 1)
        for icon, act, tip in (("prev", "previous", "Previous"), ("play", "toggle", "Play / pause"), ("next", "next", "Next")):
            b = IconButton(icon, 46, tip=tip)
            b.force_on = icon == "play"
            b.clicked.connect(lambda _=False, a=act: self._cmd(a))
            lay.addWidget(b)
        self._now.connect(self._set)
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._poll)
        self._busy = False

    def showEvent(self, e):
        self._poll()
        self._tm.start(8000)
        super().showEvent(e)

    def hideEvent(self, e):
        self._tm.stop()
        super().hideEvent(e)

    def _set(self, text: str):
        self.line.setText(text)

    def _call(self, params: dict) -> str:
        from actions import spotify_controller as sc
        return str(sc.spotify_controller(params))

    def _poll(self):
        if self._busy or not self.isVisible():
            return
        self._busy = True

        def work():
            try:
                self._now.emit(self._call({"action": "now_playing"}).replace("Now playing: ", "").strip())
            except Exception:
                self._now.emit("Spotify isn't available")
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    def _cmd(self, act: str):
        def work():
            try:
                self._call({"action": act})
            except Exception as e:
                self.toast.emit(f"Spotify: {e}")
            time.sleep(1.2)
            self._busy = False
            self._poll()
        threading.Thread(target=work, daemon=True).start()


class DashboardPage(QWidget):
    quick = pyqtSignal(str)
    toast = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(PageHeader("Dashboard", "System, tasks, activity and music at a glance"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setAutoFillBackground(False)
        g = QGridLayout(body)
        g.setContentsMargins(0, 0, 8, 8)
        g.setSpacing(14)
        self.quick_card = QuickActionsCard()
        self.perf = PerformanceCard()
        self.tasks = TasksCard()
        self.activity = ActivityCard()
        self.music = MusicCard()
        self.quick_card.triggered.connect(self.quick.emit)
        self.music.toast.connect(self.toast.emit)
        g.addWidget(self.quick_card, 0, 0)
        g.addWidget(self.perf, 0, 1)
        g.addWidget(self.tasks, 1, 0)
        g.addWidget(self.activity, 1, 1)
        g.addWidget(self.music, 2, 0, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(3, 1)
        sc.setWidget(body)
        outer.addWidget(sc)

    def tick(self, snapshot: dict):
        self.perf.update_stats(snapshot)
        self._n = getattr(self, "_n", 0) + 1
        if self._n % 15 == 0:
            self.activity.refresh()


# ─────────────────────────── Phone page (Phone Link style) ───────────────────────────
_APP_COLORS = {"SMS": "#4f8cff", "WhatsApp": "#25d366", "Telegram": "#2aabee"}


def _when_text(raw) -> str:
    """'14:05' for today, '03 Nov' for older messages, 'Now' if the stamp is unusable."""
    try:
        ts = int(raw or 0)
        if ts > 10_000_000_000:
            ts //= 1000
        if ts <= 0:
            ts = int(time.time())
        lt = time.localtime(ts)
        if time.strftime("%Y%m%d", lt) == time.strftime("%Y%m%d"):
            return time.strftime("%H:%M", lt)
        return time.strftime("%d %b", lt)
    except (TypeError, ValueError, OSError, OverflowError):
        return "Now"


def _clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def _link_btn(text: str, color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFlat(True)
    b.setStyleSheet(
        f"QPushButton {{ background: transparent; border: none; color: {color or C.PRI}; "
        f"font-size: 11px; font-weight: 600; padding: 2px 0; }}"
        f"QPushButton:hover {{ color: {C.TEXT}; }}")
    return b


class Avatar(QWidget):
    def __init__(self, text: str, color: str, size: int = 38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._text = (text.strip()[:1] or "?").upper()
        self._color = color

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(qcol(self._color, 60))
        p.setPen(QPen(qcol(self._color, 150), 1.2))
        p.drawEllipse(r)
        p.setPen(qcol(self._color))
        p.setFont(font(max(9, self.width() // 3), QFont.Weight.Bold))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._text)


class PhoneGlyph(QWidget):
    """A small drawn phone — lit when the link is up."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 90)
        self._on = False

    def set_online(self, on: bool):
        self._on = bool(on)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        edge = qcol(C.PRI if self._on else C.TEXT_DIM)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, qcol(C.PRI, 80 if self._on else 22))
        g.setColorAt(1, qcol(C.ACC, 46 if self._on else 10))
        p.setBrush(QBrush(g))
        p.setPen(QPen(edge, 2))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(edge)
        p.drawRoundedRect(QRectF(r.center().x() - 7, r.top() + 7, 14, 3.6), 1.8, 1.8)
        p.setPen(QPen(qcol(C.TEXT_MED, 120 if self._on else 60), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(4):
            y = r.top() + 28 + i * 11
            p.drawLine(QPointF(r.left() + 9, y), QPointF(r.right() - 9 - (8 if i % 2 else 0), y))


class PhoneAction(HoverAnimationMixin, QPushButton):
    """Rounded tile: emoji on top, caption below (the three big actions + the Actions tab)."""

    def __init__(self, glyph: str, caption: str, parent=None, height: int = 74):
        super().__init__(parent)
        self._glyph = glyph
        self._caption = caption
        self.setFixedHeight(height)
        self.setMinimumWidth(70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.valueChanged.connect(self._set_h)

    def set_caption(self, glyph: str, caption: str):
        self._glyph = glyph
        self._caption = caption
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        en = self.isEnabled()
        h = self._h if en else 0.0
        p.setBrush(QColor(255, 255, 255, int(10 + 26 * h)))
        p.setPen(QPen(QColor(255, 255, 255, int(26 + 70 * h)), 1))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(qcol(C.TEXT if en else C.TEXT_DIM))
        p.setFont(QFont("Segoe UI Emoji", 17))
        p.drawText(QRectF(r.left(), r.top() + 8, r.width(), 32), Qt.AlignmentFlag.AlignCenter, self._glyph)
        p.setFont(font(9, QFont.Weight.DemiBold))
        p.setPen(qcol(C.TEXT_MED if en else C.TEXT_DIM))
        p.drawText(QRectF(r.left(), r.top() + 43, r.width(), r.height() - 45), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._caption)


class NotificationCard(QWidget):
    """One phone notification: avatar, sender, time, text and Call / Mark as read."""
    dismissed = pyqtSignal(int)
    call = pyqtSignal(str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.nid = item["id"]
        color = _APP_COLORS.get(item["app"], C.PRI)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(Avatar(item["sender"] or item["app"], color, 36), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(item["sender"] or item["app"])
        name.setStyleSheet(f"color: {C.TEXT}; font-size: 12px; font-weight: 700;")
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        when = QLabel(f'{item["app"]} · {_when_text(item["ts"])}')
        when.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        top.addWidget(name, 1)
        top.addWidget(when)
        col.addLayout(top)
        text = item["text"]
        body = QLabel(text if len(text) <= 180 else text[:177] + "…")
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px;")
        col.addWidget(body)
        act = QHBoxLayout()
        act.setSpacing(16)
        if item["sender"]:
            c = _link_btn("Call")
            c.clicked.connect(lambda _=False, who=item["sender"]: self.call.emit(who))
            act.addWidget(c)
        m = _link_btn("Mark as read")
        m.clicked.connect(lambda _=False: self.dismissed.emit(self.nid))
        act.addWidget(m)
        act.addStretch(1)
        col.addLayout(act)
        lay.addLayout(col, 1)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawRoundedRect(r, 14, 14)


class ConversationRow(HoverAnimationMixin, QPushButton):
    """A row in the Messages tab: avatar, name, last line, time and unread count."""

    def __init__(self, app: str, name: str, last: str, when: str, unread: int, parent=None):
        super().__init__(parent)
        self.app, self.name, self.last, self.when, self.unread = app, name, last, when, unread
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.valueChanged.connect(self._set_h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        if self._h > 0.01:
            p.setBrush(QColor(255, 255, 255, int(18 * self._h)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 14, 14)
        color = _APP_COLORS.get(self.app, C.PRI)
        av = QRectF(r.left() + 10, r.center().y() - 19, 38, 38)
        p.setBrush(qcol(color, 60))
        p.setPen(QPen(qcol(color, 150), 1.2))
        p.drawEllipse(av)
        p.setPen(qcol(color))
        p.setFont(font(13, QFont.Weight.Bold))
        p.drawText(av, Qt.AlignmentFlag.AlignCenter, (self.name.strip()[:1] or "?").upper())
        x = av.right() + 12
        right = r.right() - 12
        p.setFont(font(9))
        p.setPen(qcol(C.TEXT_DIM))
        tw = p.fontMetrics().horizontalAdvance(self.when)
        p.drawText(QRectF(right - tw, r.top() + 9, tw + 2, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.when)
        p.setFont(font(11, QFont.Weight.Bold if self.unread else QFont.Weight.DemiBold))
        p.setPen(qcol(C.TEXT))
        name_w = max(10.0, right - x - tw - 10)
        p.drawText(QRectF(x, r.top() + 9, name_w, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideRight, int(name_w)))
        p.setFont(font(10))
        p.setPen(qcol(C.TEXT_MED if self.unread else C.TEXT_DIM))
        last_w = max(10.0, right - x - (26 if self.unread else 0))
        p.drawText(QRectF(x, r.top() + 29, last_w, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.last.replace("\n", " "), Qt.TextElideMode.ElideRight, int(last_w)))
        if self.unread:
            br = QRectF(right - 18, r.top() + 29, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcol(C.PRI))
            p.drawEllipse(br)
            p.setPen(qcol("#ffffff"))
            p.setFont(font(8, QFont.Weight.Bold))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, str(min(self.unread, 99)))


class _Tab(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-bottom: 2px solid transparent; "
            f"color: {C.TEXT_MED}; font-size: 12px; font-weight: 600; padding: 0 16px; }}"
            f"QPushButton:hover {{ color: {C.TEXT}; }}"
            f"QPushButton:checked {{ color: {C.TEXT}; border-bottom: 2px solid {C.PRI}; }}")


def _dot_css(color: str) -> str:
    return f"color: {color}; font-size: 11px; font-weight: 700; letter-spacing: 1px;"


class PhonePage(QWidget):
    """Phone Link-style page: device card · three big actions · notifications on the left,
    Messages / Calls / Actions on the right."""

    command = pyqtSignal(str, str)      # (phone_control action, value) — the window forwards it
    toast = pyqtSignal(str)

    MAX_ITEMS = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self._online = False
        self._ringing = False
        self._call_started = 0.0
        self._link_provider = None
        self._items: list[dict] = []
        self._next_id = 1
        self._cards: dict[int, NotificationCard] = {}
        self._thread_key: str | None = None

        page_l = QVBoxLayout(self)
        page_l.setContentsMargins(0, 0, 0, 0)
        page_l.setSpacing(8)
        page_l.addWidget(PageHeader("Phone", "Calls, messages and notifications from your paired Android phone"))
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 8, 8)
        body.setSpacing(14)
        page_l.addLayout(body, 1)

        # ── left column: device · call banner · 3 actions · notifications ──
        left_w = QWidget()
        left_w.setFixedWidth(360)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)

        dev = GlassCard(radius=24, tint=190, accent=C.PRI)
        dh = QHBoxLayout(dev)
        dh.setContentsMargins(18, 16, 18, 16)
        dh.setSpacing(16)
        self.glyph = PhoneGlyph()
        dh.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        info = QVBoxLayout()
        info.setSpacing(5)
        self.device_name = QLabel("No phone connected")
        self.device_name.setStyleSheet(f"color: {C.TEXT}; font-size: 17px; font-weight: 800;")
        self.device_name.setWordWrap(True)
        info.addWidget(self.device_name)
        brow = QHBoxLayout()
        brow.setSpacing(8)
        self.battery_pct = QLabel("--")
        self.battery = QProgressBar()
        self.battery.setRange(0, 100)
        self.battery.setTextVisible(False)
        self.battery.setFixedHeight(8)
        brow.addWidget(self.battery_pct)
        brow.addWidget(self.battery, 1)
        info.addLayout(brow)
        self._battery_css(0, C.TEXT_DIM)
        self.connection = QLabel("● OFFLINE")
        info.addWidget(self.connection)
        self.device_details = QLabel("Pair an Android phone to see its battery and notifications.")
        self.device_details.setWordWrap(True)
        self.device_details.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px;")
        info.addWidget(self.device_details)
        self.link_info = QLabel("")
        self.link_info.setWordWrap(True)
        self.link_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.link_info.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 9px;")
        info.addWidget(self.link_info)
        info.addStretch(1)
        dh.addLayout(info, 1)
        left.addWidget(dev)

        # call banner (only while a call is ringing or running)
        self.banner = GlassCard(radius=22, tint=200, accent=C.GREEN)
        bn = QVBoxLayout(self.banner)
        bn.setContentsMargins(20, 14, 20, 14)
        bn.setSpacing(8)
        self.banner_title = QLabel("Incoming call")
        self.banner_title.setStyleSheet(f"color: {C.GREEN}; font-size: 10px; font-weight: 700; letter-spacing: 2px;")
        self.banner_who = QLabel("")
        self.banner_who.setStyleSheet(f"color: {C.TEXT}; font-size: 20px; font-weight: 700;")
        self.banner_who.setWordWrap(True)
        bn.addWidget(self.banner_title)
        bn.addWidget(self.banner_who)
        brow2 = QHBoxLayout()
        self.btn_answer = GlowButton("Answer", "primary")
        self.btn_reject = GlowButton("Reject", "danger")
        self.btn_hangup = GlowButton("Hang up", "danger")
        self.btn_answer.clicked.connect(lambda _=False: self.command.emit("answer", ""))
        self.btn_reject.clicked.connect(lambda _=False: self.command.emit("reject", ""))
        self.btn_hangup.clicked.connect(lambda _=False: self.command.emit("hangup", ""))
        for b in (self.btn_answer, self.btn_reject, self.btn_hangup):
            brow2.addWidget(b)
        bn.addLayout(brow2)
        self.banner.hide()
        left.addWidget(self.banner)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_timer)

        # the three big actions
        self._actions = []
        arow = QHBoxLayout()
        arow.setSpacing(10)
        self.btn_find = PhoneAction("📣", "Find phone")
        self.btn_find.clicked.connect(lambda _=False: self.command.emit("ring_stop" if self._ringing else "ring", ""))
        arow.addWidget(self.btn_find)
        self._actions.append(self.btn_find)
        for glyph, caption, act in (("🔒", "Lock", "lock"), ("🖼", "Screenshot", "screenshot")):
            b = PhoneAction(glyph, caption)
            b.clicked.connect(lambda _=False, a=act: self.command.emit(a, ""))
            arow.addWidget(b)
            self._actions.append(b)
        left.addLayout(arow)

        # notifications
        nh = QHBoxLayout()
        nh.setContentsMargins(4, 4, 2, 0)
        nt = QLabel("Notifications")
        nt.setFont(font(13, QFont.Weight.Bold))
        nh.addWidget(nt)
        self.notif_count = QLabel("")
        self.notif_count.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
        nh.addWidget(self.notif_count)
        nh.addStretch(1)
        self._clear_all = _link_btn("Clear all")
        self._clear_all.clicked.connect(lambda _=False: self.mark_all_read())
        nh.addWidget(self._clear_all)
        left.addLayout(nh)

        nscroll = QScrollArea()
        nscroll.setWidgetResizable(True)
        nscroll.setFrameShape(QFrame.Shape.NoFrame)
        nscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nscroll.viewport().setAutoFillBackground(False)
        ninner = QWidget()
        ninner.setAutoFillBackground(False)
        self._notif_lay = QVBoxLayout(ninner)
        self._notif_lay.setContentsMargins(0, 0, 6, 0)
        self._notif_lay.setSpacing(8)
        self._notif_empty = QLabel("No new notifications.\nSMS, WhatsApp and Telegram previews show up here.")
        self._notif_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notif_empty.setWordWrap(True)
        self._notif_empty.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; padding: 26px 10px;")
        self._notif_lay.addWidget(self._notif_empty)
        self._notif_lay.addStretch(1)
        nscroll.setWidget(ninner)
        left.addWidget(nscroll, 1)
        body.addWidget(left_w)

        # ── right column: Messages · Calls · Actions ─────────────────────────
        right = GlassCard(radius=24, tint=140)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(18, 10, 18, 14)
        rl.setSpacing(8)
        tabs = QHBoxLayout()
        tabs.setSpacing(2)
        self._tabs = [_Tab("Messages"), _Tab("Calls"), _Tab("Actions")]
        for i, t in enumerate(self._tabs):
            t.clicked.connect(lambda _=False, n=i: self._show_tab(n))
            tabs.addWidget(t)
        tabs.addStretch(1)
        rl.addLayout(tabs)
        self._stack = QStackedWidget()
        rl.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_messages_tab())
        self._stack.addWidget(self._build_calls_tab())
        self._stack.addWidget(self._build_actions_tab())
        body.addWidget(right, 1)

        self._show_tab(0)
        self._set_online(False)
        self._sync_unread()

    # ── tabs ───────────────────────────────────────────────────────────────
    def _build_messages_tab(self) -> QWidget:
        self._msg_stack = QStackedWidget()

        # page 0: conversation list
        lst = QWidget()
        ll = QVBoxLayout(lst)
        ll.setContentsMargins(0, 4, 0, 0)
        ll.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search messages")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._render_conversations())
        ll.addWidget(self._search)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setAutoFillBackground(False)
        self._conv_lay = QVBoxLayout(inner)
        self._conv_lay.setContentsMargins(0, 0, 4, 0)
        self._conv_lay.setSpacing(2)
        sc.setWidget(inner)
        ll.addWidget(sc, 1)
        foot = QLabel("Previews are read-only and kept in memory only.")
        foot.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 9px;")
        ll.addWidget(foot)
        self._msg_stack.addWidget(lst)

        # page 1: one conversation
        th = QWidget()
        tl = QVBoxLayout(th)
        tl.setContentsMargins(0, 4, 0, 0)
        tl.setSpacing(8)
        head = QHBoxLayout()
        back = _link_btn("‹ Back")
        back.clicked.connect(lambda _=False: self._close_thread())
        head.addWidget(back)
        self._thread_title = QLabel("")
        self._thread_title.setFont(font(13, QFont.Weight.Bold))
        head.addWidget(self._thread_title, 1)
        self._thread_call = _link_btn("📞 Call")
        self._thread_call.clicked.connect(lambda _=False: self._call_thread())
        head.addWidget(self._thread_call)
        tl.addLayout(head)
        tsc = QScrollArea()
        tsc.setWidgetResizable(True)
        tsc.setFrameShape(QFrame.Shape.NoFrame)
        tsc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tsc.viewport().setAutoFillBackground(False)
        tin = QWidget()
        tin.setAutoFillBackground(False)
        self._thread_lay = QVBoxLayout(tin)
        self._thread_lay.setContentsMargins(0, 0, 6, 0)
        self._thread_lay.setSpacing(8)
        tsc.setWidget(tin)
        self._thread_scroll = tsc
        tl.addWidget(tsc, 1)
        self._msg_stack.addWidget(th)
        return self._msg_stack

    def _build_calls_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("Recent calls")
        t.setFont(font(13, QFont.Weight.Bold))
        head.addWidget(t)
        head.addStretch(1)
        clr = _link_btn("Clear")
        clr.clicked.connect(lambda _=False: self._clear_calls())
        head.addWidget(clr)
        lay.addLayout(head)
        self.calls = QTextEdit()
        self.calls.setReadOnly(True)
        self.calls.setFrameShape(QFrame.Shape.NoFrame)
        self.calls.setPlaceholderText("Calls on the phone show up here — incoming, answered and missed.")
        self.calls.document().setMaximumBlockCount(200)
        self.calls.setStyleSheet(f"QTextEdit {{ background: transparent; border: none; color: {C.TEXT_MED}; font-size: 12px; padding: 2px; }}")
        lay.addWidget(self.calls, 1)
        hint = QLabel("To place a call, say “Call <name or number>” or use Call on a notification.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        lay.addWidget(hint)
        return w

    def _build_actions_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        items = (("📍", "Location", "location"), ("🔦", "Torch on", "flashlight"), ("🔦", "Torch off", "flashlight_off"),
                 ("🔋", "Battery", "battery"), ("🔔", "Alerts", "notifications"), ("🏠", "Home", "home"))
        for i, (glyph, caption, act) in enumerate(items):
            b = PhoneAction(glyph, caption)
            b.clicked.connect(lambda _=False, a=act: self.command.emit(a, ""))
            grid.addWidget(b, i // 3, i % 3)
            self._actions.append(b)
        lay.addLayout(grid)
        send = GlowButton("📁 Send file to phone…", "primary")
        send.setMinimumHeight(40)
        send.clicked.connect(self._send_file)
        lay.addWidget(send)
        self._actions.append(send)
        lay.addStretch(1)
        return w

    def _show_tab(self, n: int):
        for i, t in enumerate(self._tabs):
            t.setChecked(i == n)
        self._stack.setCurrentIndex(n)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _battery_css(self, value: int, color: str):
        self.battery.setValue(value)
        self.battery.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.08); border: none; border-radius: 4px; } "
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}")
        self.battery_pct.setText(f"{value}%" if value > 0 else "--")
        self.battery_pct.setStyleSheet(f"color: {color if value > 0 else C.TEXT_MED}; font-size: 13px; font-weight: 700;")

    def _set_online(self, on: bool):
        self._online = on
        self.connection.setText("● CONNECTED" if on else "● OFFLINE")
        self.connection.setStyleSheet(_dot_css(C.GREEN if on else C.RED))
        self.glyph.set_online(on)
        self._notif_empty.setText(
            "You're all caught up.\nNew SMS, WhatsApp and Telegram previews appear here." if on
            else "Phone not connected.\nOpen the Jarvis App on your phone and pair it from Remote Control.")
        for b in (self.btn_answer, self.btn_reject, self.btn_hangup, *self._actions):
            b.setEnabled(on)

    def set_link_provider(self, fn):
        """fn() -> (url, fingerprint). Asked whenever the page is shown, so it is never stale."""
        self._link_provider = fn

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_link()

    def refresh_link(self):
        if not self._link_provider:
            return
        try:
            url, fp = self._link_provider()
        except Exception:
            return
        if not url:
            return
        if str(url).startswith("https://"):
            self.link_info.setText(f"🔒 {url} · encrypted")
            self.link_info.setToolTip(f"Certificate SHA-256\n{fp}" if fp else "")
        else:
            self.link_info.setText(f"⚠ {url} · plain HTTP (not encrypted)")
            self.link_info.setToolTip("")

    def _send_file(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Send a file to the phone")
        if path:
            self.command.emit("send_file", path)

    def _log_call(self, text: str, color: str | None = None):
        color = color or C.TEXT_MED
        self.calls.append(
            f'<span style="color:{C.TEXT_DIM}">{time.strftime("%H:%M")}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}">{_html.escape(text)}</span>')

    def _clear_calls(self):
        self.calls.clear()

    def _update_timer(self):
        if self._call_started:
            sec = int(time.time() - self._call_started)
            self.banner_title.setText(f"ON A CALL  ·  {sec // 60:02d}:{sec % 60:02d}")

    # ── events from the phone ───────────────────────────────────────────────
    def on_call(self, event: dict):
        if not isinstance(event, dict):
            return
        kind = event.get("event")
        who = event.get("name") or event.get("number") or "Unknown number"
        if kind == "incoming_call":
            self.banner_title.setText("INCOMING CALL")
            self.banner_who.setText(who)
            self.btn_answer.show()
            self.btn_reject.show()
            self.btn_hangup.hide()
            self.banner.show()
            self._call_started = 0.0
            self._tick.stop()
            self._log_call(f"📞 Incoming — {who}", C.ACC)
        elif kind == "call_active":
            self.banner_who.setText(who if (event.get("name") or event.get("number")) else self.banner_who.text() or "Call")
            self.btn_answer.hide()
            self.btn_reject.hide()
            self.btn_hangup.show()
            self.banner.show()
            if not self._call_started:
                self._call_started = time.time()
                self._log_call(f"✅ Connected — {self.banner_who.text()}", C.GREEN)
            self._tick.start()
            self._update_timer()
        elif kind == "call_ended":
            if self._call_started:
                sec = int(time.time() - self._call_started)
                self._log_call(f"⏹ Ended — {self.banner_who.text()} ({sec // 60}:{sec % 60:02d})")
            self._end_call_ui()
        elif kind == "missed_call":
            self._log_call(f"❌ Missed — {who}", C.RED)
            self._end_call_ui()
        elif kind in ("ring_started", "ring_stopped"):
            self._ringing = kind == "ring_started"
            if self._ringing:
                self.btn_find.set_caption("🔕", "Stop ringing")
            else:
                self.btn_find.set_caption("📣", "Find phone")

    def _end_call_ui(self):
        self._call_started = 0.0
        self._tick.stop()
        self.banner.hide()

    def set_devices(self, devices):
        safe = [item for item in devices if isinstance(item, dict)] if isinstance(devices, list) else []
        if not safe:
            self.device_name.setText("No phone connected")
            self.device_details.setText("Pair an Android phone to see its battery and notifications.")
            self._battery_css(0, C.TEXT_DIM)
            self._set_online(False)
            self._end_call_ui()
            return
        phone = safe[-1]
        name = str(phone.get("device_name") or "Android phone").strip()[:80] or "Android phone"
        battery = phone.get("battery_percent")
        info = []
        if isinstance(battery, int) and 0 <= battery <= 100:
            color = C.GREEN if battery > 40 else (C.AMBER if battery > 15 else C.RED)
            self._battery_css(battery, color)
        else:
            self._battery_css(0, C.TEXT_DIM)
        if phone.get("charging") is True:
            info.append("Charging ⚡")
        if len(safe) > 1:
            info.append(f"+{len(safe) - 1} more connected")
        self.device_name.setText(name)
        self.device_details.setText(" · ".join(info) if info else "Link is up")
        self._set_online(True)
        self.refresh_link()

    # ── notifications & messages ────────────────────────────────────────────
    def add_message(self, event):
        if not isinstance(event, dict):
            return
        text = str(event.get("text") or "").strip()
        if not text:
            return
        try:
            ts = int(event.get("timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts > 10_000_000_000:          # the server sends milliseconds
            ts //= 1000
        item = {
            "id": self._next_id,
            "app": str(event.get("app") or "Message")[:24],
            "sender": str(event.get("sender") or "").strip()[:120],
            "text": text[:600],
            "ts": ts if ts > 0 else int(time.time()),
            "unread": True,
        }
        self._next_id += 1
        key = item["sender"] or item["app"]
        viewing = self._thread_key == key and self._msg_stack.currentIndex() == 1
        if viewing:
            item["unread"] = False
        self._items.append(item)
        if len(self._items) > self.MAX_ITEMS:
            del self._items[: len(self._items) - self.MAX_ITEMS]
        if item["unread"]:
            card = NotificationCard(item)
            card.dismissed.connect(self._dismiss)
            card.call.connect(lambda who: self.command.emit("call", who))
            self._cards[item["id"]] = card
            self._notif_lay.insertWidget(1, card)       # index 0 is the "empty" hint
            fade_in(card, 240)
        self._sync_unread()
        if viewing:
            self._fill_thread(key)

    def _dismiss(self, nid: int):
        for it in self._items:
            if it["id"] == nid:
                it["unread"] = False
                break
        self._sync_unread()

    def mark_all_read(self):
        for it in self._items:
            it["unread"] = False
        self._sync_unread()

    def clear_messages(self):
        self._items.clear()
        self._thread_key = None
        self._msg_stack.setCurrentIndex(0)
        self._sync_unread()

    def _sync_unread(self):
        ids = {it["id"] for it in self._items if it["unread"]}
        for nid in list(self._cards):
            if nid not in ids:
                card = self._cards.pop(nid)
                self._notif_lay.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
        self._notif_empty.setVisible(not self._cards)
        self._clear_all.setVisible(bool(self._cards))
        self.notif_count.setText(f"({len(ids)})" if ids else "")
        total_unread = len(ids)
        self._tabs[0].setText(f"Messages  ({total_unread})" if total_unread else "Messages")
        self._render_conversations()

    def _render_conversations(self):
        _clear_layout(self._conv_lay)
        needle = self._search.text().strip().lower()
        groups: dict[str, list] = {}
        for it in self._items:
            groups.setdefault(it["sender"] or it["app"], []).append(it)
        rows = sorted(groups.items(), key=lambda kv: kv[1][-1]["ts"], reverse=True)
        shown = 0
        for key, items in rows:
            last = items[-1]
            if needle and needle not in key.lower() and not any(needle in i["text"].lower() for i in items):
                continue
            row = ConversationRow(last["app"], key, last["text"], _when_text(last["ts"]),
                                  sum(1 for i in items if i["unread"]))
            row.clicked.connect(lambda _=False, k=key: self._open_thread(k))
            self._conv_lay.addWidget(row)
            shown += 1
        if not shown:
            msg = "No messages match your search." if needle else "No messages yet.\nPhone previews appear here once notification access is enabled in the Jarvis App."
            empty = QLabel(msg)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; padding: 40px 10px;")
            self._conv_lay.addWidget(empty)
        self._conv_lay.addStretch(1)

    def _open_thread(self, key: str):
        self._thread_key = key
        for it in self._items:
            if (it["sender"] or it["app"]) == key:
                it["unread"] = False
        self._fill_thread(key)
        self._msg_stack.setCurrentIndex(1)
        self._sync_unread()
        QTimer.singleShot(0, self._scroll_thread_bottom)

    def _fill_thread(self, key: str):
        msgs = [it for it in self._items if (it["sender"] or it["app"]) == key]
        self._thread_title.setText(key)
        self._thread_call.setVisible(bool(msgs and msgs[-1]["sender"]))
        _clear_layout(self._thread_lay)
        for it in msgs:
            bubble = QLabel(
                f'{_html.escape(it["text"]).replace(chr(10), "<br>")}'
                f'<br><span style="color:{C.TEXT_DIM}; font-size:9px">{_html.escape(it["app"])} · {_when_text(it["ts"])}</span>')
            bubble.setTextFormat(Qt.TextFormat.RichText)
            bubble.setWordWrap(True)
            bubble.setMaximumWidth(380)
            bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bubble.setStyleSheet(
                f"background: rgba(255,255,255,0.07); color: {C.TEXT}; border-radius: 14px; "
                "padding: 9px 13px; font-size: 12px;")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(bubble)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self._thread_lay.addWidget(holder)
        self._thread_lay.addStretch(1)
        QTimer.singleShot(0, self._scroll_thread_bottom)

    def _scroll_thread_bottom(self):
        bar = self._thread_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _close_thread(self):
        self._thread_key = None
        self._msg_stack.setCurrentIndex(0)

    def _call_thread(self):
        if self._thread_key:
            self.command.emit("call", self._thread_key)

#by ASDcuber
