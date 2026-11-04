"""Parts of the HUD video player: the "Videos" overlay (suggested videos with thumbnails, shown over the video)
and the ⚙ player-settings pop-up. The buttons that open them live in the player's own control bar (VideoBar)."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ui.fx import Toggle
from ui.theme import C, rgba

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)


def _fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chip_css(active: bool = False, color: str | None = None) -> str:
    col = color or C.PRI
    return (f"QPushButton {{ color: {col if active else C.TEXT}; font-weight: 600; font-size: 12px; padding: 0 10px;"
            f"background: {rgba(col, .22) if active else rgba('#ffffff', .07)}; border-radius: 14px;"
            f"border: 1px solid {rgba(col, .6) if active else rgba('#ffffff', .12)}; }}"
            f"QPushButton:hover {{ background: {rgba(col, .30)}; }}")


class SuggestCard(QFrame):
    picked = pyqtSignal(str, str)   # url, title

    def __init__(self, item: dict, thumb_w: int = 200, parent=None):
        super().__init__(parent)
        self._url, self._title = item["url"], item["title"]
        thumb_h = int(thumb_w * 9 / 16)
        self.setFixedSize(thumb_w + 10, thumb_h + 62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(item["title"])
        self.setStyleSheet(f"SuggestCard {{ background: {rgba('#ffffff', .05)}; border-radius: 12px; }}"
                           f"SuggestCard:hover {{ background: {rgba(C.PRI, .20)}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)
        thumb = QLabel()
        thumb.setFixedSize(thumb_w, thumb_h)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(f"background: {rgba('#000000', .4)}; border-radius: 9px;")
        data = item.get("thumb")
        if data:
            pm = QPixmap()
            if pm.loadFromData(data):
                thumb.setPixmap(pm.scaled(thumb_w, thumb_h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                          Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(thumb)
        d = _fmt_dur(item.get("duration"))
        if d:
            badge = QLabel(d, thumb)
            badge.setStyleSheet("color: #fff; background: rgba(0,0,0,175); border-radius: 4px; padding: 0 5px; font-size: 10px;")
            badge.adjustSize()
            badge.move(thumb_w - badge.width() - 5, thumb_h - badge.height() - 5)
        t = QLabel(item["title"])
        t.setWordWrap(True)
        t.setFixedHeight(32)
        t.setStyleSheet(f"color: {C.TEXT}; font-size: 11px; font-weight: 600; background: transparent;")
        lay.addWidget(t)
        ch = QLabel(item.get("channel", ""))
        ch.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
        lay.addWidget(ch)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self._url, self._title)


class VideosOverlay(QWidget):
    """Suggested videos as a thumbnail grid, floating over the video (owned by the video window, so it stays on top
    of it — in the HUD panel and in full screen). Click a card to play that video; ✕ closes."""
    pick = pyqtSignal(str, str)
    CARD_W = 200

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("videosOv")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowOpacity(0.96)
        self.setStyleSheet(f"#videosOv {{ background: #080c18; border: 1px solid {rgba(C.PRI, .35)}; }}")
        self._items: list = []
        self._cols = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 12, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel("VIDEOS  ·  UP NEXT")
        title.setStyleSheet(f"color: {C.PRI}; font-weight: 700; letter-spacing: 2px; font-size: 11px; background: transparent;")
        top.addWidget(title)
        top.addStretch()
        x = QPushButton("✕")
        x.setFixedSize(30, 26)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(f"QPushButton {{ color: {C.TEXT}; background: {rgba('#ffffff', .08)}; border: none; border-radius: 13px; }}"
                        f"QPushButton:hover {{ background: {rgba(C.RED, .5)}; }}")
        x.clicked.connect(self.hide)
        top.addWidget(x)
        root.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            f"QScrollBar:vertical {{ width: 7px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(C.PRI, .5)}; border-radius: 3px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self._body = QWidget()
        self._body.setAutoFillBackground(False)
        self._grid = QGridLayout(self._body)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        self.scroll.setWidget(self._body)
        root.addWidget(self.scroll, 1)
        self.set_items(None)

    def _clear(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def set_items(self, items):
        """None = still loading, [] = nothing found."""
        self._items = items if items is not None else []
        self._clear()
        if not self._items:
            lab = QLabel("Loading videos…" if items is None else "No videos found.")
            lab.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 13px; background: transparent;")
            self._grid.addWidget(lab, 0, 0)
            self._cols = 0
            return
        self._cols = max(1, (self.width() - 40) // (self.CARD_W + 20))
        for i, it in enumerate(self._items):
            c = SuggestCard(it, self.CARD_W)
            c.picked.connect(self._picked)
            self._grid.addWidget(c, i // self._cols, i % self._cols, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid.setRowStretch(len(self._items) // self._cols + 1, 1)
        self._grid.setColumnStretch(self._cols, 1)

    def _picked(self, url: str, title: str):
        self.hide()
        self.pick.emit(url, title)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._items:
            cols = max(1, (self.width() - 40) // (self.CARD_W + 20))
            if cols != self._cols:
                self.set_items(self._items)


class PlayerSettings(QFrame):
    """Pop-up with the player options. Emits changed(command, value) in the words hud_video understands
    (plus "yt_connect", handled by the window)."""
    changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("playerSettings")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#playerSettings {{ background: #0c1220; border: 1px solid {rgba(C.PRI, .45)}; border-radius: 14px; }}"
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
        self._row("Quality", self.quality)
        self._row("Speed", self.speed)
        self._row("Volume", self.volume)
        self._row("Autoplay next video", self.autoplay)
        self._row("Loop this video", self.loop)
        self.mute = QPushButton("Mute / unmute")
        self.yt = QPushButton("Connect YouTube")
        for b in (self.mute, self.yt):
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(chip_css())
            self._lay.addWidget(b)

        self.quality.activated.connect(lambda _i: self.changed.emit("quality", self.quality.currentData()))
        self.speed.activated.connect(lambda _i: self.changed.emit("speed", self.speed.currentData()))
        self.volume.valueChanged.connect(lambda v: self.changed.emit("volume_abs", v))
        self.autoplay.toggled.connect(lambda v: self.changed.emit("autoplay", v))
        self.loop.toggled.connect(lambda v: self.changed.emit("loop", v))
        self.mute.clicked.connect(lambda: self.changed.emit("mute", None))
        self.yt.clicked.connect(lambda: (self.hide(), self.changed.emit("yt_connect", None)))

    def _row(self, label: str, w: QWidget):
        r = QHBoxLayout()
        r.addWidget(QLabel(label), 1)
        r.addWidget(w)
        self._lay.addLayout(r)

    def open_at(self, anchor: QPoint, meta: dict, prefs: dict, yt_connected: bool = False):
        """anchor = global position of the right-top corner of the ⚙ button; opens upwards from it."""
        self.quality.clear()
        self.quality.addItem("Auto", 0)
        for h in sorted({int(x) for x in meta.get("heights") or [] if 144 <= int(x) <= 4320}, reverse=True):
            self.quality.addItem(f"{h}p", h)
        self.quality.setCurrentIndex(max(0, self.quality.findData(int(prefs.get("quality", 0)))))
        self.speed.setCurrentIndex(max(0, self.speed.findData(float(prefs.get("speed", 1.0)))))
        self.autoplay.setChecked(bool(prefs.get("autoplay")))
        self.loop.setChecked(bool(prefs.get("loop")))
        is_yt = bool(meta.get("youtube"))
        self.quality.setEnabled(is_yt)
        self.yt.setVisible(is_yt)
        self.yt.setText("✓ YouTube connected (sign in again)" if yt_connected else "🌐 Connect YouTube (opens a browser)")
        self.adjustSize()
        self.move(max(0, anchor.x() - self.width()), max(0, anchor.y() - self.height() - 8))
        self.show()
