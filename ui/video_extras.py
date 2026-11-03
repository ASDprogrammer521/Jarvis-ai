"""Extra controls under the HUD video: 👍 👎 🔔, Next, ⚙ settings, and an "Up next" strip of suggested videos."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ui.fx import Toggle
from ui.theme import C, rgba

EXTRA_H = 162          # total height of VideoExtras (the media panel makes room for it)
THUMB_W, THUMB_H = 148, 83
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def _fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _chip_css(active: bool = False, color: str | None = None) -> str:
    col = color or C.PRI
    return (f"QPushButton {{ color: {col if active else C.TEXT}; font-weight: 600; font-size: 12px; padding: 0 12px;"
            f"background: {rgba(col, .22) if active else rgba('#ffffff', .06)}; border-radius: 15px;"
            f"border: 1px solid {rgba(col, .6) if active else rgba('#ffffff', .10)}; }}"
            f"QPushButton:hover {{ background: {rgba(col, .30)}; }}")


def _chip(text: str, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(30)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setToolTip(tip)
    b.setStyleSheet(_chip_css())
    return b


class SuggestCard(QFrame):
    picked = pyqtSignal(str, str)   # url, title

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self._url, self._title = item["url"], item["title"]
        self.setFixedSize(THUMB_W + 8, 112)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{item['title']}\n{item.get('channel', '')}")
        self.setStyleSheet(f"SuggestCard {{ background: {rgba('#ffffff', .04)}; border-radius: 10px; }}"
                           f"SuggestCard:hover {{ background: {rgba(C.PRI, .18)}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(f"background: {rgba('#000000', .35)}; border-radius: 8px;")
        data = item.get("thumb")
        if data:
            pm = QPixmap()
            if pm.loadFromData(data):
                self.thumb.setPixmap(pm.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                               Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(self.thumb)
        d = _fmt_dur(item.get("duration"))
        if d:
            badge = QLabel(d, self.thumb)
            badge.setStyleSheet("color: #fff; background: rgba(0,0,0,170); border-radius: 4px; padding: 0 4px; font-size: 10px;")
            badge.adjustSize()
            badge.move(THUMB_W - badge.width() - 4, THUMB_H - badge.height() - 4)
        t = QLabel(item["title"])
        t.setWordWrap(True)
        t.setFixedHeight(22)
        t.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 9px; background: transparent;")
        lay.addWidget(t)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self._url, self._title)


class VideoExtras(QWidget):
    like = pyqtSignal()
    dislike = pyqtSignal()
    subscribe = pyqtSignal()
    next_clicked = pyqtSignal()
    settings_clicked = pyqtSignal(QPoint)
    pick = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(EXTRA_H)
        self.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.channel = QLabel("")
        self.channel.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px; font-weight: 600;")
        row.addWidget(self.channel, 1)
        self.b_like = _chip("👍", "Like on YouTube")
        self.b_dis = _chip("👎", "Dislike on YouTube")
        self.b_sub = _chip("🔔 Subscribe", "Subscribe to the channel")
        self.b_next = _chip("⏭ Next", "Play the next suggested video")
        self.b_set = _chip("⚙ Settings", "Quality, speed, volume…")
        self.b_like.clicked.connect(self.like.emit)
        self.b_dis.clicked.connect(self.dislike.emit)
        self.b_sub.clicked.connect(self.subscribe.emit)
        self.b_next.clicked.connect(self.next_clicked.emit)
        self.b_set.clicked.connect(lambda: self.settings_clicked.emit(self.b_set.mapToGlobal(QPoint(self.b_set.width(), 0))))
        for b in (self.b_like, self.b_dis, self.b_sub, self.b_next, self.b_set):
            row.addWidget(b)
        lay.addLayout(row)

        cap = QLabel("UP NEXT")
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 9px; font-weight: 700; letter-spacing: 2px;")
        lay.addWidget(cap)
        self.scroll = QScrollArea()
        self.scroll.setFixedHeight(116)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            f"QScrollBar:horizontal {{ height: 6px; background: transparent; }}"
            f"QScrollBar::handle:horizontal {{ background: {rgba(C.PRI, .5)}; border-radius: 3px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self._body = QWidget()
        self._body.setAutoFillBackground(False)
        self._cards = QHBoxLayout(self._body)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(8)
        self.scroll.setWidget(self._body)
        lay.addWidget(self.scroll)
        self._hint("Loading suggestions…")

    # ── content ──
    def _clear(self):
        while self._cards.count():
            it = self._cards.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _hint(self, text: str):
        self._clear()
        lab = QLabel(text)
        lab.setStyleSheet(f"color: {C.TEXT_DIM};")
        self._cards.addWidget(lab)
        self._cards.addStretch()

    def set_info(self, meta: dict):
        self.channel.setText(f"▶ {meta.get('channel')}" if meta.get("channel") else "")
        for k in ("like", "dislike", "sub"):
            self.set_state(k, False)
        self._hint("Loading suggestions…")

    def set_suggestions(self, items: list):
        if not items:
            self._hint("No suggestions found.")
            return
        self._clear()
        for it in items:
            c = SuggestCard(it)
            c.picked.connect(self.pick.emit)
            self._cards.addWidget(c)
        self._cards.addStretch()

    def set_state(self, kind: str, on: bool):
        if kind == "like":
            self.b_like.setStyleSheet(_chip_css(on, C.PRI))
            self.b_like.setText("👍 Liked" if on else "👍")
            if on:
                self.b_dis.setStyleSheet(_chip_css(False))
                self.b_dis.setText("👎")
        elif kind == "dislike":
            self.b_dis.setStyleSheet(_chip_css(on, C.RED))
            self.b_dis.setText("👎 Disliked" if on else "👎")
            if on:
                self.b_like.setStyleSheet(_chip_css(False))
                self.b_like.setText("👍")
        elif kind == "sub":
            self.b_sub.setStyleSheet(_chip_css(on, C.GREEN if hasattr(C, "GREEN") else C.PRI))
            self.b_sub.setText("🔔 Subscribed" if on else "🔔 Subscribe")


class PlayerSettings(QFrame):
    """Pop-up with the player options. Emits changed(command, value) in the same words hud_video understands."""
    changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            f"PlayerSettings {{ background: #0c1220; border: 1px solid {rgba(C.PRI, .45)}; border-radius: 14px; }}"
            f"QLabel {{ color: {C.TEXT}; font-size: 12px; background: transparent; }}"
            f"QComboBox {{ background: {rgba('#ffffff', .07)}; color: {C.TEXT}; border: 1px solid {rgba('#ffffff', .12)};"
            "border-radius: 8px; padding: 4px 8px; min-width: 96px; }"
            f"QComboBox QAbstractItemView {{ background: #0c1220; color: {C.TEXT}; selection-background-color: {rgba(C.PRI, .4)}; }}"
            f"QSlider::groove:horizontal {{ height: 4px; background: {rgba(C.TEXT_MED, .25)}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {C.PRI}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {C.PRI}; width: 12px; margin: -5px 0; border-radius: 6px; }}")
        self.setFixedWidth(300)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 14, 16, 14)
        self._lay.setSpacing(10)
        title = QLabel("Player settings")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._lay.addWidget(title)

        self.quality = QComboBox()
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}x", s)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 130)
        self.volume.setValue(100)
        self.autoplay = Toggle(False)
        self.loop = Toggle(False)
        self.mute = QPushButton("Mute / unmute")
        self.mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute.setStyleSheet(_chip_css())
        self._row("Quality", self.quality)
        self._row("Speed", self.speed)
        self._row("Volume", self.volume)
        self._row("Autoplay next video", self.autoplay)
        self._row("Loop this video", self.loop)
        self._lay.addWidget(self.mute)

        self.quality.activated.connect(lambda _i: self.changed.emit("quality", self.quality.currentData()))
        self.speed.activated.connect(lambda _i: self.changed.emit("speed", self.speed.currentData()))
        self.volume.valueChanged.connect(lambda v: self.changed.emit("volume_abs", v))
        self.autoplay.toggled.connect(lambda v: self.changed.emit("autoplay", v))
        self.loop.toggled.connect(lambda v: self.changed.emit("loop", v))
        self.mute.clicked.connect(lambda: self.changed.emit("mute", None))

    def _row(self, label: str, w: QWidget):
        r = QHBoxLayout()
        r.addWidget(QLabel(label), 1)
        r.addWidget(w)
        self._lay.addLayout(r)

    def open_at(self, global_right_top: QPoint, meta: dict, prefs: dict):
        self.quality.clear()
        self.quality.addItem("Auto", 0)
        for h in sorted({int(x) for x in meta.get("heights") or [] if 144 <= int(x) <= 4320}, reverse=True):
            self.quality.addItem(f"{h}p", h)
        self.quality.setCurrentIndex(max(0, self.quality.findData(int(prefs.get("quality", 0)))))
        self.speed.setCurrentIndex(max(0, self.speed.findData(float(prefs.get("speed", 1.0)))))
        self.autoplay.setChecked(bool(prefs.get("autoplay")))
        self.loop.setChecked(bool(prefs.get("loop")))
        self.adjustSize()
        # open upwards from the Settings button so it never covers the video controls
        self.move(global_right_top.x() - self.width(), max(0, global_right_top.y() - self.height() - 6))
        self.show()
