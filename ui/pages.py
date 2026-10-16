from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ui.fx import GlassCard, GlowButton, mix
from ui.theme import C, patch_cfg, qcol, read_cfg, rgba
from ui.widgets import IconButton, MetricTile, draw_icon, font


class LogoMark(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 46)
        self._t = 0.0
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(120)

    def _tick(self):
        if self.isVisible():
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


class NavItem(QPushButton):

    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(parent)
        self.icon_kind = icon
        self.label = text
        self.setCheckable(True)
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
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
        p.setPen(qcol(C.TEXT) if on else col)
        p.setFont(font(11, QFont.Weight.DemiBold if on else QFont.Weight.Medium))
        p.drawText(QRectF(r.left() + 50, r.top(), r.width() - 56, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)


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
        self.mic = IconButton("mic", 44, True, "Mute / unmute  F4")
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
    t.setFont(font(12, QFont.Weight.Bold))
    return t


class ActionTile(QPushButton):

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.icon_kind, self.label = icon, label
        self.setFixedSize(92, 92)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
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
        box = QRectF((self.width() - 52) / 2, 4, 52, 52)
        g = QLinearGradient(box.topLeft(), box.bottomRight())
        g.setColorAt(0, QColor(255, 255, 255, int(16 + 26 * self._h)))
        g.setColorAt(1, qcol(C.PRI, int(10 + 40 * self._h)))
        p.setBrush(QBrush(g))
        p.setPen(QPen(qcol(C.PRI, int(40 + 150 * self._h)), 1))
        p.drawRoundedRect(box, 15, 15)
        draw_icon(p, self.icon_kind, box.adjusted(14, 14, -14, -14), mix(qcol(C.TEXT_MED), qcol(C.PRI), self._h), 1.9)
        p.setPen(qcol(C.TEXT_MED) if self._h < 0.5 else qcol(C.TEXT))
        p.setFont(font(9))
        p.drawText(QRectF(0, 60, self.width(), 30), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.label)


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

# by ASDcuber521
