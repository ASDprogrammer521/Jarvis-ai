"""Smart Home page — every device as its own glass card (icon, name, kind · room · address, live state, controls).

Everything runs through actions.smart_home.run_command, i.e. directly on the local network; nothing here talks to the cloud.
Network calls happen on worker threads and report back with signals, so the window never freezes on a slow device.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QSlider, QVBoxLayout, QWidget)

from ui.fx import GlassCard, GlowButton
from ui.pages import PageHeader
from ui.theme import C, rgba
from ui.widgets import draw_icon, font

ICON = {"shelly": "plug", "tasmota": "plug", "wled": "strip", "tuya": "bulb", "http": "bolt", "wol": "monitor", "camera": "camera"}
COLORS = (("warm", "#ffaa46"), ("white", "#ffffff"), ("red", "#ff3b3b"), ("green", "#3bff7a"), ("blue", "#3b7bff"), ("purple", "#a03cff"))
DIMMABLE = ("wled", "tasmota", "tuya")
CARD_W = 300


class Glyph(QWidget):
    """Round icon that glows when the device is on."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind, self.on = kind, None
        self.setFixedSize(58, 58)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(29, 29)
        col = QColor(C.GREEN if self.on else C.TEXT_DIM if self.on is False else C.PRI)
        if self.on:
            g = QRadialGradient(c, 29)
            g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 90))
            g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
            p.setBrush(g)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(c, 29, 29)
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 36))
        p.setPen(QPen(col, 1.4))
        p.drawEllipse(c, 22, 22)
        draw_icon(p, ICON.get(self.kind, "bolt"), QRectF(14, 14, 30, 30), col, 1.9)


class DeviceCard(GlassCard):
    act = pyqtSignal(str, str, str)                  # device name, action, value

    def __init__(self, name: str, dev: dict):
        super().__init__(radius=22, tint=175, accent=None)
        self.name, self.dev = name, dev
        kind = dev.get("kind", "")
        self.setFixedWidth(CARD_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.glyph = Glyph(kind)
        top.addWidget(self.glyph)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(name)
        t.setFont(font(13, QFont.Weight.Bold))
        t.setStyleSheet("background: transparent;")
        sub_txt = kind.upper() + (f" · {dev['room']}" if dev.get("room") else "")
        sub = QLabel(sub_txt)
        sub.setStyleSheet(f"color: {C.PRI}; font-size: 10px; letter-spacing: 1px; background: transparent;")
        addr = QLabel(dev.get("host") or dev.get("mac") or dev.get("rtsp_url", "")[:28] or "")
        addr.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
        col.addWidget(t)
        col.addWidget(sub)
        col.addWidget(addr)
        top.addLayout(col, 1)
        self.pill = QLabel("…")
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pill.setFixedHeight(22)
        top.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(8)
        if kind == "camera":
            b = GlowButton("📷  Snapshot", "primary")
            b.clicked.connect(lambda: self.act.emit(name, "snapshot", ""))
            row.addWidget(b)
        elif kind == "wol":
            b = GlowButton("⏻  Wake", "primary")
            b.clicked.connect(lambda: self.act.emit(name, "on", ""))
            row.addWidget(b)
        else:
            on = GlowButton("On", "primary")
            on.clicked.connect(lambda: self.act.emit(name, "on", ""))
            off = GlowButton("Off", "ghost")
            off.clicked.connect(lambda: self.act.emit(name, "off", ""))
            tg = GlowButton("⇄", "ghost")
            tg.setFixedWidth(46)
            tg.setToolTip("Toggle")
            tg.clicked.connect(lambda: self.act.emit(name, "toggle", ""))
            row.addWidget(on, 1)
            row.addWidget(off, 1)
            row.addWidget(tg)
        lay.addLayout(row)

        if kind in DIMMABLE:
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(1, 100)
            sl.setValue(70)
            sl.setToolTip("Brightness")
            sl.setStyleSheet(
                f"QSlider::groove:horizontal{{height:5px;background:{rgba(C.PRI, .18)};border-radius:2px;}}"
                f"QSlider::sub-page:horizontal{{background:{C.PRI};border-radius:2px;}}"
                f"QSlider::handle:horizontal{{width:16px;height:16px;margin:-6px 0;border-radius:8px;background:{C.TEXT};}}")
            sl.sliderReleased.connect(lambda: self.act.emit(name, "brightness", str(sl.value())))
            lay.addWidget(sl)
            sw = QHBoxLayout()
            sw.setSpacing(8)
            for cname, hx in COLORS:
                b = QPushButton()
                b.setFixedSize(26, 26)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setToolTip(cname.title())
                b.setStyleSheet(f"QPushButton{{background:{hx};border:2px solid {rgba('#ffffff', .25)};border-radius:13px;}}"
                                f"QPushButton:hover{{border-color:{C.TEXT};}}")
                b.clicked.connect(lambda _=False, c=cname: self.act.emit(name, "color", c))
                sw.addWidget(b)
            sw.addStretch()
            lay.addLayout(sw)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
        lay.addWidget(self.note)
        self.set_state(None, "")

    def set_state(self, on, detail: str = ""):
        """on: True / False / None (unknown) / 'offline'."""
        self.glyph.on = on if isinstance(on, bool) else None
        self.glyph.update()
        text, col = {True: ("ON", C.GREEN), False: ("OFF", C.TEXT_DIM), None: ("—", C.TEXT_DIM), "offline": ("OFFLINE", C.RED)}[on]
        self.pill.setText(f"  {text}  ")
        self.pill.setStyleSheet(f"color:{col};background:{rgba(col, .14)};border:1px solid {rgba(col, .5)};border-radius:11px;"
                                f"font-size:10px;font-weight:700;letter-spacing:1px;")
        self.note.setText(detail)
        self.note.setStyleSheet(f"color: {C.RED if on == 'offline' else C.TEXT_DIM}; font-size: 10px; background: transparent;")


class AddDeviceDialog(QDialog):
    def __init__(self, parent=None, preset: dict | None = None):
        super().__init__(parent)
        from actions.smart_home import KINDS
        self.setWindowTitle("Add device")
        self.setMinimumWidth(420)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(22, 20, 22, 18)
        self.form.setVerticalSpacing(10)
        self.kind = QComboBox()
        self.kind.addItems(KINDS)
        self.f: dict[str, QLineEdit] = {}
        self.form.addRow("Type", self.kind)
        spec = (("name", "Name", "Desk lamp", ()), ("host", "IP address", "192.168.1.20", ("shelly", "tasmota", "wled", "tuya", "http")),
                ("room", "Room", "Office", ()), ("mac", "MAC address", "AA:BB:CC:DD:EE:FF", ("wol",)),
                ("device_id", "Tuya device id", "", ("tuya",)), ("local_key", "Tuya local key", "", ("tuya",)),
                ("snapshot_url", "Snapshot URL", "http://192.168.1.30/snapshot.jpg", ("camera",)),
                ("rtsp_url", "…or RTSP URL", "rtsp://192.168.1.30/stream", ("camera",)),
                ("on_url", "“On” URL", "http://192.168.1.40/on", ("http",)), ("off_url", "“Off” URL", "http://192.168.1.40/off", ("http",)))
        self._kinds: dict[str, tuple] = {}
        for key, label, ph, kinds in spec:
            e = QLineEdit()
            e.setPlaceholderText(ph)
            self.f[key] = e
            self._kinds[key] = kinds
            self.form.addRow(label, e)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color: {C.RED};")
        self.form.addRow(self.err)
        row = QHBoxLayout()
        cancel = GlowButton("Cancel", "ghost")
        cancel.clicked.connect(self.reject)
        ok = GlowButton("Add", "primary")
        ok.clicked.connect(self._ok)
        row.addWidget(cancel)
        row.addWidget(ok)
        self.form.addRow(row)
        self.kind.currentTextChanged.connect(self._sync)
        if preset:
            self.kind.setCurrentText(preset.get("kind", "shelly"))
            for k, v in preset.items():
                if k in self.f:
                    self.f[k].setText(str(v))
        self._sync(self.kind.currentText())

    def _sync(self, kind: str):
        for i, key in enumerate(self.f):
            vis = key in ("name", "room") or kind in self._kinds[key]
            if hasattr(self.form, "setRowVisible"):          # Qt >= 6.4
                self.form.setRowVisible(i + 1, vis)

    def _ok(self):
        d = {"action": "add", "kind": self.kind.currentText()}
        d.update({k: e.text().strip() for k, e in self.f.items() if e.text().strip()})
        from actions.smart_home import run_command
        out = run_command(d)
        if out.startswith("Saved"):
            self.accept()
        else:
            self.err.setText(out)


class SmartHomePage(QWidget):
    toast = pyqtSignal(str)
    _done = pyqtSignal(str, str, str)              # device, action, result text
    _scan_done = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, DeviceCard] = {}
        self._found: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(PageHeader("Smart Home", "Local-first · talks to your devices directly on your home network — no cloud"), 1)
        self.scan_b = GlowButton("🔍  Scan network", "ghost")
        self.scan_b.clicked.connect(self._scan)
        add_b = GlowButton("＋  Add device", "primary")
        add_b.clicked.connect(self._add)
        off_b = GlowButton("⏻  All off", "ghost")
        off_b.clicked.connect(lambda: self._run("", "all_off", "", all_off=True))
        for b in (self.scan_b, add_b, off_b):
            head.addWidget(b)
        head.setContentsMargins(0, 0, 8, 0)
        root.addLayout(head)

        self.scenes = QHBoxLayout()
        self.scenes.setContentsMargins(6, 0, 8, 0)
        self.scenes.setSpacing(8)
        root.addLayout(self.scenes)

        self.found_box = QVBoxLayout()
        self.found_box.setContentsMargins(6, 0, 8, 0)
        root.addLayout(self.found_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}QScrollArea>QWidget>QWidget{background:transparent;}")
        self.inner = QWidget()
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(6, 4, 14, 14)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self.empty = QLabel("No devices yet.\nPress “Scan network” to find Shelly, Tasmota and WLED devices,\nor “Add device” for lights, plugs, cameras and PCs.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 13px;")
        root.addWidget(self.empty)

        self._done.connect(self._on_done)
        self._scan_done.connect(self._on_scan)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.refresh_status)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        self.reload()
        self._poll.start(12000)

    def hideEvent(self, e):
        self._poll.stop()
        super().hideEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_cards()

    def reload(self):
        from actions.smart_home import _load
        d = _load()
        for c in self._cards.values():
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()
        for name, dev in d["devices"].items():
            card = DeviceCard(name, dev)
            card.act.connect(self._run)
            self._cards[name] = card
        self._layout_cards()
        self.empty.setVisible(not self._cards)
        self.scroll.setVisible(bool(self._cards))
        while self.scenes.count():
            it = self.scenes.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if d["scenes"]:
            lbl = QLabel("Scenes")
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; letter-spacing: 1px;")
            self.scenes.addWidget(lbl)
            for sc in d["scenes"]:
                b = GlowButton("▶  " + sc, "ghost", pill=True)
                b.clicked.connect(lambda _=False, s=sc: self._run("", "scene_run", s, scene=True))
                self.scenes.addWidget(b)
            self.scenes.addStretch()
        self.refresh_status()

    def _layout_cards(self):
        while self.grid.count():
            self.grid.takeAt(0)
        cols = max(1, (self.scroll.viewport().width() - 20) // (CARD_W + 16))
        for i, card in enumerate(self._cards.values()):
            self.grid.addWidget(card, i // cols, i % cols)

    # ── talking to devices (always off the UI thread) ────────────────────────────────
    def _run(self, name: str, action: str, value: str, all_off: bool = False, scene: bool = False):
        def work():
            from actions.smart_home import run_command
            if all_off:
                out = run_command({"action": "all_off"})
            elif scene:
                out = run_command({"action": "scene_run", "target": value})
            else:
                out = run_command({"action": action, "target": name, "value": value})
            self._done.emit(name, "all_off" if all_off else "scene" if scene else action, out)
        if name in self._cards and action not in ("status",):
            self._cards[name].note.setText("…")
        threading.Thread(target=work, daemon=True).start()

    def refresh_status(self):
        names = [n for n, c in self._cards.items() if c.dev.get("kind") not in ("camera", "wol")]
        if not names:
            return

        def work():
            from actions.smart_home import run_command
            for n in names:
                self._done.emit(n, "status", run_command({"action": "status", "target": n}))
        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, name: str, action: str, out: str):
        if action in ("all_off", "scene"):
            self.toast.emit(out[:120])
            QTimer.singleShot(600, self.refresh_status)
            return
        card = self._cards.get(name)
        if card is None:
            return
        body = out.split(": ", 1)[1] if ": " in out else out
        if "failed" in body or body.startswith("I don't know"):
            card.set_state("offline", body.replace("failed (", "").rstrip(")")[:90])
            return
        low = body.strip().lower()
        if action == "snapshot" and "saved:" in body:
            path = body.split("saved:", 1)[1].strip()
            card.set_state(None, "Saved " + path.replace("\\", "/").split("/")[-1])
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif action == "status":
            word, _, detail = low.partition(",")
            card.set_state(True if word.strip() == "on" else False if word.strip() == "off" else None,
                           detail.strip() if word.strip() in ("on", "off") else body[:60])
        elif action in ("on", "off"):
            card.set_state(action == "on" if card.dev.get("kind") != "wol" else None, "Wake packet sent" if card.dev.get("kind") == "wol" else "")
        elif action == "toggle":
            self.refresh_status()
        else:
            card.note.setText(body[:90])

    # ── discovery / adding ───────────────────────────────────────────────────────────
    def _scan(self):
        self.scan_b.setEnabled(False)
        self.scan_b.setText("Scanning…")

        def work():
            from actions.smart_home import discover
            try:
                self._scan_done.emit(discover())
            except Exception:
                self._scan_done.emit([])
        threading.Thread(target=work, daemon=True).start()

    def _on_scan(self, found):
        self.scan_b.setEnabled(True)
        self.scan_b.setText("🔍  Scan network")
        from actions.smart_home import _load
        known = {v.get("host") for v in _load()["devices"].values()}
        new = [f for f in found if f["host"] not in known]
        while self.found_box.count():
            it = self.found_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not found:
            self.toast.emit("No Shelly / Tasmota / WLED devices found on this network")
        for f in new:
            row = GlassCard(radius=16, tint=160, accent=C.PRI)
            h = QHBoxLayout(row)
            h.setContentsMargins(16, 8, 10, 8)
            lbl = QLabel(f"Found  <b>{f['name']}</b>  ·  {f['kind']}  ·  {f['host']}")
            lbl.setStyleSheet("background: transparent;")
            h.addWidget(lbl, 1)
            b = GlowButton("Add", "primary")
            b.setFixedWidth(90)
            b.clicked.connect(lambda _=False, x=f, r=row: self._add_found(x, r))
            h.addWidget(b)
            self.found_box.addWidget(row)

    def _add_found(self, f: dict, row: QWidget):
        from actions.smart_home import run_command
        out = run_command({"action": "add", "name": f["name"], "kind": f["kind"], "host": f["host"]})
        self.toast.emit(out)
        row.setParent(None)
        row.deleteLater()
        self.reload()

    def _add(self):
        if AddDeviceDialog(self).exec():
            self.reload()
