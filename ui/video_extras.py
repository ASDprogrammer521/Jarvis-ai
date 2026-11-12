"""Parts of the HUD video player: the "Videos" overlay (suggested videos with thumbnails, shown over the video)
and the ⚙ player-settings pop-up. The buttons that open them live in the player's own control bar (VideoBar)."""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap
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


# ── vector icons (Feather-style, drawn at any size, tinted to the HUD colours) ─────────────────────────────
try:
    from PyQt6.QtSvg import QSvgRenderer
except Exception:                      # QtSvg missing: buttons fall back to plain text glyphs
    QSvgRenderer = None

_ICONS = {
    "thumb_up": '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>',
    "thumb_down": '<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>',
    "bell": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "rewind": '<polygon points="11 19 2 12 11 5 11 19"/><polygon points="22 19 13 12 22 5 22 19"/>',
    "forward": '<polygon points="13 19 22 12 13 5 13 19"/><polygon points="2 19 11 12 2 5 2 19"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="3"/>',
    "play": '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z"/>',
    "pause": '<rect x="5.5" y="4" width="4.5" height="16" rx="1.4"/><rect x="14" y="4" width="4.5" height="16" rx="1.4"/>',
    "close": '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
}
_FALLBACK = {"thumb_up": "+1", "thumb_down": "-1", "bell": "!", "grid": "#", "settings": "*", "rewind": "<<",
             "forward": ">>", "stop": "[]", "play": ">", "pause": "||", "close": "x"}
_ALWAYS_FILLED = ("play", "pause", "stop")
_CACHE: dict = {}


def icon_pixmap(name: str, color: str, size: int, filled: bool = False) -> QPixmap | None:
    """The icon as a crisp pixmap (rendered at 2x for high-DPI screens). None if QtSvg isn't available."""
    if QSvgRenderer is None:
        return None
    key = (name, color, size, filled)
    pm = _CACHE.get(key)
    if pm is None:
        fill = color if (filled or name in _ALWAYS_FILLED) else "none"
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
               f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>')
        r = QSvgRenderer(QByteArray(svg.encode()))
        scale = 2
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        _CACHE[key] = pm
    return pm


class PlayerButton(QPushButton):
    """Flat glass button for the player bar: a vector icon (and an optional label), highlighted on hover,
    tinted with `color` when switched on (like / dislike / subscribed). Never takes keyboard focus."""

    def __init__(self, icon: str, tip: str = "", text: str = "", size: int = 34, icon_px: int = 18, color: str | None = None):
        super().__init__()
        self._icon, self._text, self._px = icon, text, icon_px
        self._color = color or C.PRI
        self._on = False
        self._size = size
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)          # never steal Space / arrows from the video
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tip:
            self.setToolTip(tip)
        self._fit()

    def _font(self) -> QFont:
        f = QFont("Segoe UI", 9)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _fit(self):
        if self._text:
            w = 12 + self._px + 6 + QFontMetrics(self._font()).horizontalAdvance(self._text) + 14
            self.setFixedSize(w, self._size)
        else:
            self.setFixedSize(self._size, self._size)

    def set_icon(self, icon: str):
        if icon != self._icon:
            self._icon = icon
            self.update()

    def set_text(self, text: str):
        self._text = text
        self._fit()
        self.update()

    def set_active(self, on: bool, color: str | None = None):
        self._on = bool(on)
        if color:
            self._color = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        hover, down = self.underMouse(), self.isDown()
        col = QColor(self._color)
        if self._on:
            bg, border = QColor(col.red(), col.green(), col.blue(), 52), QColor(col.red(), col.green(), col.blue(), 150)
        elif down:
            bg, border = QColor(255, 255, 255, 46), QColor(255, 255, 255, 0)
        elif hover:
            bg, border = QColor(255, 255, 255, 30), QColor(255, 255, 255, 0)
        else:
            bg = QColor(255, 255, 255, 14 if self._text else 0)
            border = QColor(255, 255, 255, 22 if self._text else 0)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        tint = self._color if self._on else (C.TEXT if hover or down else C.TEXT_MED)
        px = self._px
        ix = 12 if self._text else (r.width() - px) / 2
        iy = (r.height() - px) / 2
        pm = icon_pixmap(self._icon, tint, px, filled=self._on)
        if pm is not None:
            p.drawPixmap(QPointF(ix, iy), pm)
        else:
            p.setPen(QColor(tint))
            p.setFont(self._font())
            p.drawText(QRectF(ix, 0, px + 6, r.height()), Qt.AlignmentFlag.AlignCenter, _FALLBACK.get(self._icon, "?"))
        if self._text:
            p.setPen(QColor(tint))
            p.setFont(self._font())
            p.drawText(QRectF(ix + px + 6, 0, r.width() - ix - px - 6, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        p.end()


class PlayButton(QPushButton):
    """The big round play / pause button — cyan-to-violet gradient with a soft glow on hover."""

    def __init__(self, size: int = 44):
        super().__init__()
        self.kind = "pause"
        self.setFixedSize(size + 8, size + 8)
        self._d = size
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_kind(self, kind: str, tip: str = ""):
        if kind != self.kind:
            self.kind = kind
            self.update()
        if tip and tip != self.toolTip():
            self.setToolTip(tip)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        d = self._d / 2
        if self.underMouse():
            glow = QColor(C.PRI)
            glow.setAlpha(55)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, d + 4, d + 4)
        g = QLinearGradient(c.x() - d, c.y() - d, c.x() + d, c.y() + d)
        lo = 0.82 if self.isDown() else 1.0
        a, b = QColor(C.PRI), QColor(C.ACC)
        for col in (a, b):
            col.setRgb(int(col.red() * lo), int(col.green() * lo), int(col.blue() * lo))
        g.setColorAt(0, a)
        g.setColorAt(1, b)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, d, d)
        px = 20
        pm = icon_pixmap(self.kind, "#061019", px)
        if pm is not None:
            off = 1.5 if self.kind == "play" else 0          # a play triangle looks centred when nudged right
            p.drawPixmap(QPointF(c.x() - px / 2 + off, c.y() - px / 2), pm)
        p.end()



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
        self.setStyleSheet(f"SuggestCard {{ background: {rgba('#ffffff', .045)}; border: 1px solid {rgba('#ffffff', .06)}; border-radius: 12px; }}"
                           f"SuggestCard:hover {{ background: {rgba(C.PRI, .14)}; border: 1px solid {rgba(C.PRI, .55)}; }}")
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
        self.setStyleSheet("#videosOv { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0b1122, stop:1 #05070f); "
                           f"border: 1px solid {rgba(C.PRI, .30)}; }}")
        self._items: list = []
        self._cols = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 12, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        head = QLabel("Up next")
        head.setStyleSheet(f"color: {C.TEXT}; font-size: 15px; font-weight: 700; background: transparent;")
        top.addWidget(head)
        sub = QLabel("related videos — click to play")
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent; padding-left: 8px;")
        top.addWidget(sub)
        top.addStretch()
        x = PlayerButton("close", "Back to the video", size=30, icon_px=14, color=C.RED)
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
            "QComboBox::drop-down { border: none; width: 18px; }"
            f"QComboBox:hover {{ border: 1px solid {rgba(C.PRI, .5)}; }}"
            f"QComboBox QAbstractItemView {{ background: #0c1220; color: {C.TEXT}; selection-background-color: {rgba(C.PRI, .4)}; }}"
            f"QSlider::groove:horizontal {{ height: 4px; background: {rgba(C.TEXT_MED, .25)}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {C.PRI}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {C.PRI}; width: 12px; margin: -5px 0; border-radius: 6px; }}")
        self.setFixedWidth(300)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 14, 16, 14)
        self._lay.setSpacing(10)
        title = QLabel("Player settings")
        title.setStyleSheet(f"color: {C.PRI}; font-size: 11px; font-weight: 700; letter-spacing: 2px; background: transparent;")
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
            b.setFixedHeight(32)
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
