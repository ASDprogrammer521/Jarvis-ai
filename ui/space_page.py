"""Hand Space page — the home of the Iron-Man style workspace: launch it, see what each gesture does, choose the folder
the glass cards come from, write a new note, and decide whether a hand outline is drawn."""
from __future__ import annotations

import math
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from ui.fx import GlassCard, GlowButton, Toggle
from ui.pages import PageHeader
from ui.theme import C, patch_cfg, read_cfg
from ui.widgets import draw_icon, font

GESTURES = (
    ("pinch", "Pinch", "Touch thumb and index finger on a card to grab it and carry it."),
    ("tap", "Tap", "A quick pinch goes into a folder or drive, enlarges a picture, opens a note. Pinch again to close it."),
    ("throw", "Throw", "Let go while your hand moves — the card flies, spins and bounces off the edges."),
    ("claw", "Claw", "Bend your fingers like a claw: every card is pulled to your palm. Open the hand to release."),
    ("two", "Two hands", "Pinch an open picture with both hands to zoom it; one hand drags it around."),
    ("fist", "Back", "Hold a fist for a second: closes the open card, or goes up one folder."),
)
_ICON = {"pinch": "hand", "tap": "bolt", "throw": "send", "claw": "hand", "two": "cube", "fist": "stats"}


class Hero(QWidget):
    """Animated hologram teaser: a wireframe orb with three glass cards bobbing around it."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(230)
        self._t0 = time.time()
        self._tm = QTimer(self)
        self._tm.timeout.connect(self.update)

    def showEvent(self, e):
        super().showEvent(e)
        self._tm.start(33)

    def hideEvent(self, e):
        self._tm.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.time() - self._t0
        cx, cy = self.width() / 2, self.height() / 2
        r = min(self.width(), self.height()) * 0.27
        col = QColor(C.PRI)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(5):                                           # meridians: ellipses squeezed by the rotation angle
            ang = t * 0.7 + k * math.pi / 5
            w = abs(math.cos(ang)) * r
            c = QColor(col)
            c.setAlpha(150)
            p.setPen(QPen(c, 1.3))
            p.drawEllipse(QPointF(cx, cy), max(2.0, w), r)
        for lat in (-0.6, -0.3, 0.0, 0.3, 0.6):                     # parallels
            y = cy + lat * r
            half = math.sqrt(max(0.0, 1 - lat * lat)) * r
            c = QColor(col)
            c.setAlpha(110)
            p.setPen(QPen(c, 1.1))
            p.drawEllipse(QPointF(cx, y), half, half * 0.22)
        for i in range(3):                                           # glass cards drifting around
            a = t * 0.5 + i * 2.094
            x = cx + math.cos(a) * r * 2.0
            y = cy + math.sin(a * 1.3) * r * 0.7 + math.sin(t * 1.4 + i) * 6
            rect = QRectF(x - 50, y - 32, 100, 64)
            fill = QColor(col)
            fill.setAlpha(26)
            p.setBrush(fill)
            edge = QColor(col)
            edge.setAlpha(150)
            p.setPen(QPen(edge, 1.3))
            p.drawRoundedRect(rect, 10, 10)
            p.setPen(QPen(QColor(255, 255, 255, 90), 2))
            p.drawLine(QPointF(x - 36, y - 12), QPointF(x + 20, y - 12))
            p.setPen(QPen(QColor(255, 255, 255, 50), 2))
            p.drawLine(QPointF(x - 36, y + 2), QPointF(x + 34, y + 2))
            p.drawLine(QPointF(x - 36, y + 14), QPointF(x + 4, y + 14))


class NoteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New card")
        self.setMinimumWidth(440)
        f = QFormLayout(self)
        f.setContentsMargins(22, 20, 22, 18)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title")
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Write the note…")
        self.body.setMinimumHeight(140)
        f.addRow("Title", self.title)
        f.addRow("Note", self.body)
        row = QHBoxLayout()
        c = GlowButton("Cancel", "ghost")
        c.clicked.connect(self.reject)
        ok = GlowButton("Save card", "primary")
        ok.clicked.connect(self.accept)
        row.addWidget(c)
        row.addWidget(ok)
        f.addRow(row)


class SpacePage(QWidget):
    toast = pyqtSignal(str)
    open_requested = pyqtSignal()

    def __init__(self, status_fn=None, parent=None):
        super().__init__(parent)
        self._status_fn = status_fn or (lambda: ("off", False))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(PageHeader("Hand Space", "Browse your drives, folders and pictures with your bare hands — webcam only, all local"))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 8, 8)
        body.setSpacing(14)
        root.addLayout(body, 1)

        # ── left: hero + launch + settings + cards ──
        left = QVBoxLayout()
        left.setSpacing(12)
        body.addLayout(left, 1)

        hero = GlassCard(radius=24, tint=170, accent=C.PRI)
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(20, 14, 20, 16)
        hv.setSpacing(8)
        hv.addWidget(Hero())
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        row.addWidget(self.status, 1)
        self.open_b = GlowButton("✋  Open Hand Space", "primary")
        self.open_b.setMinimumHeight(44)
        self.open_b.clicked.connect(self.open_requested.emit)
        row.addWidget(self.open_b)
        hv.addLayout(row)
        left.addWidget(hero)

        opts = GlassCard(radius=20, tint=160)
        ov = QVBoxLayout(opts)
        ov.setContentsMargins(20, 14, 20, 14)
        ov.setSpacing(10)
        ov.addLayout(self._opt_row("Show hand outline", "Draw thin bones of your hand. Off = only the fingertip and pinch rings.",
                                   self._toggle_outline()))
        self.folder_lbl = QLabel("")
        self.folder_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent;")
        self.folder_lbl.setWordWrap(True)
        pick = GlowButton("Choose folder…", "ghost")
        pick.clicked.connect(self._pick_folder)
        clear = GlowButton("Use built-in cards", "ghost")
        clear.clicked.connect(self._clear_folder)
        new = GlowButton("＋  New card", "primary")
        new.clicked.connect(self._new_note)
        fr = QHBoxLayout()
        fr.addWidget(self.folder_lbl, 1)
        for b in (clear, pick, new):
            fr.addWidget(b)
        ov.addLayout(fr)
        left.addWidget(opts)

        head = QLabel("Your cards")
        head.setFont(font(12, QFont.Weight.Bold))
        left.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}QScrollArea>QWidget>QWidget{background:transparent;}")
        self.inner = QWidget()
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(0, 0, 8, 8)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.inner)
        left.addWidget(self.scroll, 1)

        # ── right: gesture guide ──
        guide = GlassCard(radius=24, tint=170)
        guide.setFixedWidth(340)
        gv = QVBoxLayout(guide)
        gv.setContentsMargins(20, 16, 20, 16)
        gv.setSpacing(12)
        t = QLabel("Gestures")
        t.setFont(font(14, QFont.Weight.Bold))
        t.setStyleSheet("background: transparent;")
        gv.addWidget(t)
        for key, name, desc in GESTURES:
            gv.addLayout(self._guide_row(key, name, desc))
        gv.addStretch()
        esc = QLabel("Esc or the ✕ in the corner leaves Hand Space. A held fist also stops hand mouse control.")
        esc.setWordWrap(True)
        esc.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
        gv.addWidget(esc)
        body.addWidget(guide)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_status)

    # ── pieces ───────────────────────────────────────────────────────────────────
    def _opt_row(self, title: str, sub: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(1)
        a = QLabel(title)
        a.setFont(font(11, QFont.Weight.DemiBold))
        a.setStyleSheet("background: transparent;")
        b = QLabel(sub)
        b.setWordWrap(True)
        b.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
        col.addWidget(a)
        col.addWidget(b)
        row.addLayout(col, 1)
        row.addWidget(widget)
        return row

    def _guide_row(self, key: str, name: str, desc: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        ic = _Icon(_ICON[key])
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        a = QLabel(name)
        a.setFont(font(11, QFont.Weight.DemiBold))
        a.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        b = QLabel(desc)
        b.setWordWrap(True)
        b.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 10px; background: transparent;")
        col.addWidget(a)
        col.addWidget(b)
        row.addLayout(col, 1)
        return row

    def _toggle_outline(self) -> Toggle:
        from core import hand_cursor
        tg = Toggle(hand_cursor.show_skeleton())
        tg.toggled.connect(hand_cursor.set_show_skeleton)
        return tg

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        self._reload()
        self._refresh_status()
        self._tick.start(1500)

    def hideEvent(self, e):
        self._tick.stop()
        super().hideEvent(e)

    def _refresh_status(self):
        st, active = self._status_fn()
        if active:
            self.status.setText("● Hand Space is open")
            self.status.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        else:
            bad = str(st).startswith(("error", "missing"))
            self.status.setText("Camera problem — check it in Settings → Gestures" if bad else "Needs your webcam · nothing leaves this computer")
            self.status.setStyleSheet(f"color: {C.RED if bad else C.TEXT_DIM}; background: transparent;")

    # ── cards ────────────────────────────────────────────────────────────────────
    def _folder(self) -> str:
        return str(read_cfg().get("hand_space_folder") or "")

    def _reload(self):
        from core import hand_space
        folder = self._folder()
        self.folder_lbl.setText(f"Pinned next to your drives: {folder}" if folder else "Starts on your drives (C: first). Pin a folder to show it next to them.")
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cards = hand_space.load_cards(folder or None)
        cols = 3
        for i, c in enumerate(cards[:18]):
            card = GlassCard(radius=16, tint=150)
            card.setFixedHeight(92)
            v = QVBoxLayout(card)
            v.setContentsMargins(14, 10, 14, 10)
            v.setSpacing(2)
            t = QLabel(("🖼  " if c.get("image") else "") + c["title"])
            t.setFont(font(10, QFont.Weight.DemiBold))
            t.setStyleSheet("background: transparent;")
            s = QLabel((c.get("text") or "Picture")[:90])
            s.setWordWrap(True)
            s.setAlignment(Qt.AlignmentFlag.AlignTop)
            s.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
            v.addWidget(t)
            v.addWidget(s, 1)
            self.grid.addWidget(card, i // cols, i % cols)
        for k in range(cols):
            self.grid.setColumnStretch(k, 1)

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Folder to pin next to your drives in Hand Space", self._folder())
        if path:
            patch_cfg(hand_space_folder=path)
            self._reload()

    def _clear_folder(self):
        patch_cfg(hand_space_folder="")
        self._reload()

    def _new_note(self):
        dlg = NoteDialog(self)
        if not dlg.exec():
            return
        title = dlg.title.text().strip() or "Untitled"
        text = dlg.body.toPlainText().strip()
        folder = self._folder()
        if not folder:                                             # first note: give the cards a home of their own
            from actions._common import DATA_DIR
            folder = str(DATA_DIR / "hand_space_notes")
            patch_cfg(hand_space_folder=folder)
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in title if ch.isalnum() or ch in " -_")[:50].strip() or "note"
        path, n = root / f"{safe}.md", 2
        while path.exists():
            path, n = root / f"{safe} {n}.md", n + 1
        path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        self.toast.emit(f"Card saved: {path.name}")
        self._reload()


class _Icon(QWidget):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedSize(34, 34)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(C.PRI)
        p.setBrush(QColor(col.red(), col.green(), col.blue(), 30))
        edge = QColor(col)
        edge.setAlpha(130)
        p.setPen(QPen(edge, 1.2))
        p.drawEllipse(QPointF(17, 17), 15.5, 15.5)
        draw_icon(p, self.kind, QRectF(7, 7, 20, 20), col, 1.7)
