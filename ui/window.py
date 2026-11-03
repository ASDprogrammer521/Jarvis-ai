from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCursor, QDesktopServices, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient, QSurfaceFormat
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSizePolicy, QSlider, QStackedWidget, QStyle, QTextEdit, QVBoxLayout, QWidget,
)

import ui.theme as ui_theme
from ui.fx import GL_ENABLED, Backdrop, GlassCard, GlowButton, ModalLayer, Stage3D, Toggle, fade_in, slide_to
from ui.metrics import _metrics
from ui.panels import APP_VERSION, ConfirmPanel, RemotePanel, SettingsPanel, SetupPanel
from ui.theme import C, DEFAULT_ACCENT, apply_accent, build_qss, patch_cfg, qcol, read_cfg, rgba
from ui.video_extras import EXTRA_H, PlayerSettings, VideoExtras
from ui.pages import DashboardPage, InputBar, LogoMark, NavItem, PhonePage, Sidebar
from ui.widgets import ChatView, IconButton, StatePill, font

_OS = platform.system()
_WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}


BASE_DIR = ui_theme.ROOT
APP_ID = "jarvis-ai"


class CompactMic(QWidget):
    clicked = pyqtSignal()
    restore = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(72, 72)
        self.muted = False
        self.amp = 0.0
        self._drag: QPoint | None = None
        self._moved = False
        self._t = QTimer(self)
        self._t.timeout.connect(self.update)
        self._t.start(50)

    def paintEvent(self, _):
        from ui.widgets import draw_icon
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = qcol(C.RED if self.muted else C.PRI)
        g = QRadialGradient(36, 36, 36)
        g.setColorAt(0.55, QColor(col.red(), col.green(), col.blue(), int(60 + 120 * self.amp)))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(0, 0, 72, 72)
        p.setBrush(qcol(C.PANEL, 235))
        p.setPen(QPen(col, 1.6))
        p.drawEllipse(10, 10, 52, 52)
        draw_icon(p, "mic_off" if self.muted else "mic", QRectF(21, 21, 30, 30), col, 2.0)

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._moved = True
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if not self._moved:
            self.clicked.emit()
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.restore.emit()


class StageHost(QWidget):

    def __init__(self, stage: Stage3D, parent=None):
        super().__init__(parent)
        self.stage = stage
        stage.setParent(self)
        self.floats: dict[str, QWidget] = {}
        self.media_full = False

    def resizeEvent(self, e):
        self.stage.setGeometry(0, 0, self.width(), self.height())
        self.layout_floats()
        super().resizeEvent(e)

    def layout_floats(self):
        W, H = self.width(), self.height()
        c = self.floats.get("content")
        if c is not None and c.isVisible():
            h = int(min(320, H * 0.5))
            c.setGeometry(18, H - h - 10, W - 36, h)
        m = self.floats.get("media")
        if m is not None and m.isVisible():
            if self.media_full:
                m.setGeometry(0, 0, W, H)
            else:
                media_w = min(960, max(360, min(int(W * 0.66), W - 28)))
                extra = getattr(self, "media_extra", 0)
                if int(media_w * 9 / 16) + 58 + extra > H - 24:      # tall panel (suggestions row): shrink the video, keep 16:9
                    media_w = max(360, min(media_w, int((H - 24 - 58 - extra) * 16 / 9)))
                media_h = max(220, min(H - 24, int(media_w * 9 / 16) + 58 + extra))
                m.setGeometry(max(12, W - media_w - 12), 12, media_w, media_h)
        k = self.floats.get("clip")
        if k is not None and k.isVisible():
            k.setGeometry(int((W - min(W - 40, 620)) / 2), 12, min(W - 40, 620), 96)
        t = self.floats.get("toast")
        if t is not None and t.isVisible():
            t.adjustSize()
            t.move(int((W - t.width()) / 2), 14)


class SeekSlider(QSlider):
    """Seek bar for the HUD video: a click or drag jumps straight to that position (a plain QSlider only pages)."""
    seek_to = pyqtSignal(int)

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(0, 1000)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dragging = False

    def _val(self, x) -> int:
        x = max(0, min(int(x), self.width()))
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), x, max(1, self.width()))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.setValue(self._val(e.position().x()))
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.setValue(self._val(e.position().x()))
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.dragging and e.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.seek_to.emit(self._val(e.position().x()))
            e.accept()
        else:
            super().mouseReleaseEvent(e)


def _fmt_clock(sec: float) -> str:
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _video_icon_shapes(kind: str, cx: float, cy: float, s: float) -> list:
    """Vector shapes (button pixels) of the YouTube-style player icons:
    ("poly", [(x, y), ...]) or ("rect", x, y, w, h, radius). Drawn white by VideoIconButton."""
    if kind == "play":
        return [("poly", [(cx - .38 * s, cy - .52 * s), (cx - .38 * s, cy + .52 * s), (cx + .56 * s, cy)])]
    if kind == "pause":
        w, g = .30 * s, .22 * s
        return [("rect", cx - g / 2 - w, cy - .5 * s, w, s, w * .3), ("rect", cx + g / 2, cy - .5 * s, w, s, w * .3)]
    if kind == "stop":
        return [("rect", cx - .45 * s, cy - .45 * s, .9 * s, .9 * s, .18 * s)]
    tw, th = .52 * s, .5 * s  # "back" / "fwd": two triangles side by side
    out = []
    for x0 in (cx - tw, cx):
        if kind == "fwd":
            out.append(("poly", [(x0, cy - th), (x0, cy + th), (x0 + tw, cy)]))
        else:
            out.append(("poly", [(x0 + tw, cy - th), (x0 + tw, cy + th), (x0, cy)]))
    return out


class VideoIconButton(QPushButton):
    """YouTube-style player button: dark rounded rectangle with a white play / pause / stop / rewind / forward icon
    (rewind / forward also show a small label such as "5m"). Never takes keyboard focus."""

    def __init__(self, kind: str, label: str = "", tip: str = "", width: int = 46):
        super().__init__()
        self.kind = kind
        self.label = label
        self.setFixedSize(width, 30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # never steal Space / arrows from the video
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tip:
            self.setToolTip(tip)

    def set_kind(self, kind: str, tip: str = ""):
        if kind != self.kind:
            self.kind = kind
            self.update()
        if tip and tip != self.toolTip():
            self.setToolTip(tip)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        if self.isDown():
            bg = QColor(122, 122, 130)
        elif self.underMouse():
            bg = QColor(98, 98, 106)
        else:
            bg = QColor(66, 66, 72)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 9, 9)
        white = QColor(255, 255, 255)
        w, h = r.width(), r.height()
        icx, cy = w / 2, h / 2
        if self.label:
            icx = w * (.30 if self.kind == "back" else .70)
            f = QFont(self.font())
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(white)
            tr = QRectF(w * .50, 0, w * .44, h) if self.kind == "back" else QRectF(w * .06, 0, w * .44, h)
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, self.label)
        p.setBrush(white)
        p.setPen(QPen(white, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for sh in _video_icon_shapes(self.kind, icx, cy, 12.0):
            if sh[0] == "poly":
                p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in sh[1]]))
            else:
                _, x, y, rw, rh, rad = sh
                p.drawRoundedRect(QRectF(x, y, rw, rh), rad, rad)
        p.end()


class VideoBar(QWidget):
    """Control strip for HUD video: seek bar, time, -5 min / pause / +5 min / stop, buffer status.
    Used under the video in the media panel and, in full screen, inside the floating FsOverlay."""
    ctl = pyqtSignal(str, object)     # ("pause", None) | ("seek", seconds)
    seek_fraction = pyqtSignal(int)   # 0..1000 of the whole video
    stop = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setStyleSheet("background: transparent;")
        self._hold_until = 0.0
        bl = QVBoxLayout(self)
        bl.setContentsMargins(0, 2, 0, 0)
        bl.setSpacing(4)
        self.slider = SeekSlider()
        self.slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 4px; background: {rgba(C.TEXT_MED, .25)}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {C.PRI}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {C.PRI}; width: 12px; margin: -5px 0; border-radius: 6px; }}")
        self.slider.seek_to.connect(self._on_seek)
        bl.addWidget(self.slider)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.time_lbl = QLabel("0:00 / --:--")
        self.time_lbl.setStyleSheet("color: #eef1ff; font-size: 12px; font-weight: 600;")
        row.addWidget(self.time_lbl)
        row.addStretch()

        self.back_btn = VideoIconButton("back", "5m", "Back 5 minutes (Shift+Left)", 62)
        self.back_btn.clicked.connect(lambda: self.ctl.emit("seek", -300))
        self.play_btn = VideoIconButton("pause", "", "Pause (Space)", 50)
        self.play_btn.clicked.connect(lambda: self.ctl.emit("pause", None))
        self.fwd_btn = VideoIconButton("fwd", "5m", "Forward 5 minutes (Shift+Right)", 62)
        self.fwd_btn.clicked.connect(lambda: self.ctl.emit("seek", 300))
        self.stop_btn = VideoIconButton("stop", "", "Stop", 42)
        self.stop_btn.clicked.connect(lambda: self.stop.emit())
        for b_ in (self.back_btn, self.play_btn, self.fwd_btn, self.stop_btn):
            row.addWidget(b_)
        row.addStretch()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {C.ACC}; font-size: 10px; font-weight: 700;")
        row.addWidget(self.status_lbl)
        bl.addLayout(row)

    def _on_seek(self, v: int):
        self._hold_until = time.monotonic() + 1.5  # keep the bar where the user dropped it until mpv has sought
        self.seek_fraction.emit(v)

    def reset(self):
        self.slider.setValue(0)
        self.time_lbl.setText("0:00 / --:--")
        self.status_lbl.setText("")
        self.play_btn.set_kind("pause", "Pause (Space)")

    def refresh(self, st: dict):
        pos, dur = st["pos"], st["dur"]
        sl = self.slider
        if sl.dragging and dur > 0:
            pos = dur * sl.value() / 1000.0
        elif dur > 0 and time.monotonic() >= self._hold_until:
            sl.setValue(int(max(0.0, min(1.0, pos / dur)) * 1000))
        self.time_lbl.setText(f"{_fmt_clock(pos)} / {_fmt_clock(dur) if dur > 0 else '--:--'}")
        if st["paused"] and not st["buffering"]:
            self.play_btn.set_kind("play", "Play (Space)")
        else:
            self.play_btn.set_kind("pause", "Pause (Space)")
        if st["buffering"]:
            status = "BUFFERING…"
        else:
            parts = []
            if st["cache"] >= 1:
                parts.append(f"buffer {st['cache']:.0f}s")
            if st["drops"] > 0:
                parts.append(f"dropped {st['drops']}")
            status = "  ·  ".join(parts)
        self.status_lbl.setText(status)


class FsOverlay(QWidget):
    """Floating control bar over the full-screen mpv window. Shown while the mouse moves (or the video is
    paused / buffering) and hidden a few seconds later; it never takes keyboard focus."""

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setObjectName("fsOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowOpacity(0.93)
        self.setStyleSheet(f"#fsOverlay {{ background: #0b0f1c; border: 1px solid {rgba(C.PRI, .35)}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 8, 18, 8)
        self.bar = VideoBar()
        lay.addWidget(self.bar)


class MpvWindow(QWidget):
    """Frameless native window that mpv renders into. It floats over the HUD media panel
    (the same window goes full screen, so playback never restarts)."""
    want_toggle = pyqtSignal()
    key_handler = None  # set by the HUD: handles Space / arrows (see MainWindow._video_key)

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background: #000;")
        self.setWindowTitle("Jarvis video")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_F, Qt.Key.Key_F11) or (k == Qt.Key.Key_Escape and self.isFullScreen()):
            self.want_toggle.emit()
        elif self.key_handler is not None and self.key_handler(e):
            pass
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.want_toggle.emit()


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _reconfig_sig = pyqtSignal()
    _cam_stream_sig = pyqtSignal(bool)
    _cam_frame_sig = pyqtSignal(bytes)
    _phone_frame_sig = pyqtSignal(str)
    _media_frame_sig = pyqtSignal(bytes, str)
    _mpv_open_sig = pyqtSignal(object)
    _mpv_close_sig = pyqtSignal()
    _mpv_cmd_sig = pyqtSignal(str)
    _confirm_sig = pyqtSignal(str, str)
    _confirm_hide_sig = pyqtSignal()
    _wake_dl_sig = pyqtSignal(bool, str)
    _update_sig = pyqtSignal(object)
    _toast_sig = pyqtSignal(str)
    _phone_event_sig = pyqtSignal(object)
    _profile_sig = pyqtSignal(str)
    _tasks_sig = pyqtSignal()
    _update_done_sig = pyqtSignal(object)
    _restart_sig = pyqtSignal()
    _quit_sig = pyqtSignal()
    _gesture_sig = pyqtSignal(str, str)
    _gesture_status_sig = pyqtSignal(str)
    _face_sig = pyqtSignal(str, str)
    _media_info_sig = pyqtSignal(object)
    _media_sugg_sig = pyqtSignal(object)
    _vx_state_sig = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        cfg = read_cfg()
        self.assistant_name = (cfg.get("assistant_name") or "JARVIS").strip() or "JARVIS"
        self.user_name = cfg.get("user_name") or ""
        col = (cfg.get("ui_color") or "").strip()
        if col and col.lower() != DEFAULT_ACCENT:
            apply_accent(col)
        self.setStyleSheet(build_qss())
        self.setWindowTitle(self.assistant_name.upper())
        self.setMinimumSize(960, 640)
        self.resize(1200, 780)
        self.setAcceptDrops(True)
        scr = QApplication.primaryScreen().availableGeometry()
        self.move((scr.width() - 1200) // 2, max(0, (scr.height() - 780) // 2))

        self.on_text_command = None
        self.on_remote_clicked = None
        self.on_interrupt = None
        self.on_voice_change = None
        self.on_audio_device_change = None
        self.get_plugins = None
        self.get_plugin_settings = None
        self.on_wake_toggle = None
        self.on_wake_manual = None
        self.on_wake_install = None
        self.on_push_to_talk = None
        self.ptt_hold = None
        self.wake_get_state = None
        self._muted = False
        self._ready = False
        self._current_file: str | None = None
        self._state = "INITIALISING"
        self._ptt_on = False
        self._ptt_down = False
        self._cam_run = False
        self._media_lock = threading.Lock()
        self._media_pending = None
        self._media_queued = False
        self._media_scene_paused = False
        self._mpv_win = None
        self._compact: CompactMic | None = None
        self._t0 = time.time()
        self._confirm_panel = None
        self._settings_open = False
        self._page = "home"
        self._settings_page = "general"
        self._last_clip = ""

        self.backdrop = Backdrop()
        self.setCentralWidget(self.backdrop)
        self.backdrop.aurora = bool(cfg.get("fx_aurora", True))
        self.backdrop.stars = bool(cfg.get("fx_stars", True))
        self.backdrop.speed = float(cfg.get("fx_speed", 1.0))
        self.stage = Stage3D()
        self.backdrop.stage = self.stage
        self.stage.particles = bool(cfg.get("fx_particles", True))
        self.stage.speed = float(cfg.get("fx_speed", 1.0))
        self.stage.set_model(str(cfg.get("stage_model") or "holo"))
        self.stage.show_status = False
        self.stage.on_gpu_event = self._on_gpu_event
        self.stage.quality = str(cfg.get("quality") or "auto")
        self._build()
        self.modal = ModalLayer(self.backdrop)
        self.modal.closed.connect(self._on_modal_closed)
        self.modal.opened.connect(lambda: self._pause_scene(True))

        self._log_sig.connect(self._on_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._cam_stream_sig.connect(self._camera_toggle)
        self._cam_frame_sig.connect(self._camera_frame)
        self._phone_frame_sig.connect(self._phone_frame)
        self._media_frame_sig.connect(self._on_media_frame)
        self._mpv_open_sig.connect(self._mpv_open)
        self._mpv_close_sig.connect(self._hide_media)
        self._mpv_cmd_sig.connect(self._mpv_cmd)
        self._mpv_timer = QTimer(self)
        self._mpv_timer.timeout.connect(self._mpv_tick)
        self._confirm_sig.connect(self._show_confirm)
        self._confirm_hide_sig.connect(self._hide_confirm)
        self._wake_dl_sig.connect(self._on_wake_dl)
        self._update_sig.connect(self._on_update)
        self._toast_sig.connect(self._toast)
        self._phone_event_sig.connect(self._on_phone_event)
        self._profile_sig.connect(self.apply_profile)
        self._tasks_sig.connect(lambda: self.dash.tasks.reload())
        self._update_done_sig.connect(self._on_update_done)
        self._restart_sig.connect(self.restart_app)
        self._quit_sig.connect(QApplication.quit)
        self._gesture_sig.connect(self._run_gesture_action)
        self._gesture_status_sig.connect(self._on_gesture_status)
        self._face_sig.connect(self._on_face_event)
        self._media_info_sig.connect(self._on_media_info)
        self._media_sugg_sig.connect(self._on_media_suggestions)
        self._vx_state_sig.connect(lambda k, on: self._extras.set_state(k, on))
        self.gesture_status = "off"
        self.camera = None
        QTimer.singleShot(2500, self._camera_autostart)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        self._tick()
        try:
            from memory.config_manager import get_push_to_talk_enabled
            self._ptt_on = bool(get_push_to_talk_enabled())
        except Exception:
            pass
        try:
            QApplication.clipboard().dataChanged.connect(self._on_clip)
        except Exception:
            pass
        QTimer.singleShot(250, self._boot)
        QTimer.singleShot(2500, self._check_gpu)
        QTimer.singleShot(9000, self._auto_update_check)

    def _boot(self):
        try:
            from memory.config_manager import is_configured
            ok = is_configured()
        except Exception:
            ok = True
        if ok:
            self._ready = True
        else:
            self._show_setup()

    def _build(self):
        root = QHBoxLayout(self.backdrop)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # Left rail: icons only at rest, slides open (with labels) while the mouse is over it.
        # It floats over the page area; this spacer keeps the pages clear of the slim rail.
        self.side = side = Sidebar(self.backdrop)
        reserve = QWidget()
        reserve.setFixedWidth(Sidebar.COLLAPSED)
        root.addWidget(reserve)

        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(3, 0, 0, 0)
        brand.setSpacing(10)
        brand.addWidget(LogoMark())
        self.brand_txt = QWidget()
        bcol = QVBoxLayout(self.brand_txt)
        bcol.setContentsMargins(0, 0, 0, 0)
        bcol.setSpacing(0)
        self.title = QLabel(self.assistant_name.upper())
        tf = font(15, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self.title.setFont(tf)
        bcol.addWidget(self.title)
        sub_l = QLabel("Your AI Assistant")
        sub_l.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        bcol.addWidget(sub_l)
        brand.addWidget(self.brand_txt, 1)
        sl.addLayout(brand)
        sl.addSpacing(14)
        self.nav: dict = {}
        for key, icon, label in (("home", "home", "Home"), ("chat", "chat", "Chat"), ("dashboard", "dashboard", "Dashboard"),
                                 ("phone", "phone", "Phone"), ("voice", "mic", "Voice & AI"), ("settings", "gear", "Settings")):
            b = NavItem(icon, label)
            b.setFixedHeight(46)
            b.clicked.connect(lambda _=False, k=key: self._nav(k))
            side.progress.connect(b.set_k)
            self.nav[key] = b
            sl.addWidget(b)
        sl.addStretch()
        self.perf = QLabel("")
        self.perf.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        self.perf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._perf_pref = bool(read_cfg().get("show_perf", False))
        sl.addWidget(self.perf)

        # status block: mic state · clock · date · fullscreen
        self.pill = StatePill()
        sl.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignHCenter)
        self.clock = QLabel("--:--")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date = QLabel("")
        self.date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        sl.addWidget(self.clock)
        sl.addWidget(self.date)
        fs = IconButton("full", 34, tip=f"Fullscreen  {__import__('ui.theme', fromlist=['hotkeys']).hotkeys()['fullscreen']}")
        fs.clicked.connect(self.toggle_fullscreen)
        sl.addWidget(fs, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addSpacing(4)

        crow = QHBoxLayout()
        self.compact_lbl = QLabel("Compact Mode")
        self.compact_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        crow.addWidget(self.compact_lbl)
        crow.addStretch()
        self.compact_toggle = Toggle(False)
        self.compact_toggle.toggled.connect(self._compact_toggled)
        crow.addWidget(self.compact_toggle)
        sl.addLayout(crow)
        sl.addSpacing(4)
        self.ver_lbl = QLabel(f"v{APP_VERSION}")
        self.ver_lbl.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 10px;")
        self.by_lbl = QLabel("by ASDcuber521")
        self.by_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; letter-spacing: 1px;")
        sl.addWidget(self.ver_lbl)
        sl.addWidget(self.by_lbl)
        self._side_txt = None
        side.progress.connect(self._side_progress)
        self._side_progress(0.0)

        col = QVBoxLayout()
        col.setSpacing(12)

        self.pages = QStackedWidget()
        home = QWidget()
        hv = QVBoxLayout(home)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(6)
        self.host = StageHost(self.stage)
        hv.addWidget(self.host, 1)
        self.hero_title = QLabel(self.assistant_name.upper())
        hf = font(30, QFont.Weight.Bold)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 14)
        self.hero_title.setFont(hf)
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hv.addWidget(self.hero_title)
        tag = QLabel("Always here. Always listening.")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet(f"color: {C.PRI}; font-size: 14px; letter-spacing: 1px;")
        hv.addWidget(tag)
        hv.addSpacing(6)
        self.home_bar = InputBar(attach=False)
        self.home_bar.setMinimumWidth(460)
        self.home_bar.setMaximumWidth(900)
        bar_row = QHBoxLayout()               # stretch on both sides: the bar fills the width up to 900px
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.addStretch(1)
        bar_row.addWidget(self.home_bar, 12)
        bar_row.addStretch(1)
        hv.addLayout(bar_row)
        chips = QHBoxLayout()
        chips.setSpacing(10)
        chips.addStretch()
        for label, kind in (("Open apps", "apps"), ("Search web", "web"), ("System info", "sys"), ("Create task", "task")):
            c = GlowButton(label, "ghost", pill=True)
            c.setMinimumHeight(38)
            c.clicked.connect(lambda _=False, k=kind: self._chip(k))
            chips.addWidget(c)
        chips.addStretch()
        hv.addLayout(chips)
        hv.addSpacing(4)
        self.pages.addWidget(home)

        chat = GlassCard(radius=26, tint=130)
        cv = QVBoxLayout(chat)
        cv.setContentsMargins(26, 18, 26, 18)
        cv.setSpacing(12)
        ch = QHBoxLayout()
        ct = QLabel("Conversation")
        ct.setFont(font(14, QFont.Weight.Bold))
        ch.addWidget(ct)
        ch.addStretch()
        clr = IconButton("close", 32, tip="Clear conversation", flat=True)
        ch.addWidget(clr)
        cv.addLayout(ch)
        self.chat = ChatView()
        clr.clicked.connect(self.chat.clear)
        cv.addWidget(self.chat, 1)
        self.chat_bar = InputBar()
        cv.addWidget(self.chat_bar)
        self.pages.addWidget(chat)

        self.dash = DashboardPage()
        self.dash.quick.connect(self._quick)
        self.dash.toast.connect(self._toast)
        self.pages.addWidget(self.dash)
        self.phone_page = PhonePage()
        self.phone_page.command.connect(self._phone_command)
        self.phone_page.toast.connect(self._toast)
        self.pages.addWidget(self.phone_page)
        col.addWidget(self.pages, 1)
        root.addLayout(col, 1)

        self._bars = [self.home_bar, self.chat_bar]
        for bar in self._bars:
            bar.submitted.connect(self._send)
            bar.mic_clicked.connect(self.toggle_mute)
            bar.attach_clicked.connect(self._browse)
            bar.detach_clicked.connect(self.clear_file)
        self._sync_nav()
        side.reposition()
        side.raise_()

        self._content = self._make_content()
        self._media = self._make_media()
        self._clip = self._make_clip()
        self._toast_w = GlassCard(self.host, radius=18, tint=210, accent=C.PRI)
        tl = QHBoxLayout(self._toast_w)
        tl.setContentsMargins(16, 9, 16, 9)
        self._toast_lbl = QLabel()
        tl.addWidget(self._toast_lbl)
        self._toast_w.hide()
        self._alert_w = GlassCard(self.host, radius=26, tint=225, accent=C.RED)
        al = QVBoxLayout(self._alert_w)
        al.setContentsMargins(46, 26, 46, 26)
        al.setSpacing(4)
        self._alert_title = QLabel("⚠  UNKNOWN PERSON")
        self._alert_title.setFont(font(24, QFont.Weight.Bold))
        self._alert_title.setStyleSheet(f"color: {C.RED};")
        self._alert_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._alert_sub = QLabel("An unrecognised face is in front of the camera")
        self._alert_sub.setStyleSheet(f"color: {C.TEXT_MED};")
        self._alert_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        al.addWidget(self._alert_title)
        al.addWidget(self._alert_sub)
        self._alert_w.hide()
        self._alert_timer = QTimer(self)
        self._alert_timer.setSingleShot(True)
        self._alert_timer.timeout.connect(self._alert_done)
        self._alert_blink = QTimer(self)
        self._alert_blink.timeout.connect(self._alert_pulse)
        self._alert_on = False
        self.host.floats = {"content": self._content, "media": self._media,
                            "clip": self._clip, "toast": self._toast_w}
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast_w.hide)
        self._media_timer = QTimer(self)
        self._media_timer.setSingleShot(True)
        self._media_timer.timeout.connect(self._close_media)

    def _make_content(self) -> GlassCard:
        c = GlassCard(self.host, radius=22, tint=190)
        c.hide()
        l = QVBoxLayout(c)
        l.setContentsMargins(20, 14, 14, 16)
        h = QHBoxLayout()
        self._content_title = QLabel()
        self._content_title.setFont(font(11, QFont.Weight.Bold))
        self._content_title.setStyleSheet(f"color: {C.PRI};")
        h.addWidget(self._content_title)
        h.addStretch()
        x = IconButton("close", 30, flat=True)
        x.clicked.connect(lambda: c.hide())
        h.addWidget(x)
        l.addLayout(h)
        self._content_text = QTextEdit()
        self._content_text.setReadOnly(True)
        self._content_text.setFrameShape(QFrame.Shape.NoFrame)
        self._content_text.viewport().setAutoFillBackground(False)
        self._content_text.setStyleSheet(f"QTextEdit {{ background: transparent; border: none; color: {C.TEXT_MED}; font-size: 13px; }}")
        l.addWidget(self._content_text)
        return c

    def _make_media(self) -> GlassCard:
        c = GlassCard(self.host, radius=20, tint=200, accent=C.ACC)
        c.hide()
        l = QVBoxLayout(c)
        l.setContentsMargins(12, 10, 10, 12)
        h = QHBoxLayout()
        self._media_title = QLabel("CAMERA")
        self._media_title.setStyleSheet(f"color: {C.ACC}; font-weight: 700; letter-spacing: 2px; font-size: 10px;")
        h.addWidget(self._media_title)
        h.addStretch()
        self._media_full_btn = IconButton("full", 26, flat=True, tip="Full screen (Esc to exit)")
        self._media_full_btn.clicked.connect(self._toggle_media_full)
        h.addWidget(self._media_full_btn)
        x = IconButton("close", 26, flat=True)
        x.clicked.connect(self._close_media_user)
        h.addWidget(x)
        l.addLayout(h)
        self._media_lbl = QLabel()
        self._media_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._media_lbl.setMinimumSize(1, 1)
        self._media_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._media_lbl.mouseDoubleClickEvent = lambda e: self._toggle_media_full()
        l.addWidget(self._media_lbl, 1)
        l.addWidget(self._make_video_bar())
        self._extras = VideoExtras()
        self._extras.hide()
        self._extras.like.connect(lambda: self._vx_rate("like"))
        self._extras.dislike.connect(lambda: self._vx_rate("dislike"))
        self._extras.subscribe.connect(self._vx_subscribe)
        self._extras.next_clicked.connect(lambda: self._video_ctl("next"))
        self._extras.pick.connect(lambda url, title: self._video_ctl("play_url", (url, title)))
        self._extras.settings_clicked.connect(self._vx_open_settings)
        self._vx_rating = "none"
        self._vx_subscribed = False
        self._vx_settings = None
        return c

    def _make_video_bar(self) -> QWidget:
        """Control bar shown under the video while mpv plays."""
        bar = VideoBar()
        bar.ctl.connect(self._video_ctl)
        bar.seek_fraction.connect(self._mpv_seek_fraction)
        bar.stop.connect(self._close_media_user)
        bar.hide()
        self._mpv_bar = bar
        return bar

    def _make_clip(self) -> GlassCard:
        c = GlassCard(self.host, radius=20, tint=210, accent=C.PRI)
        c.hide()
        l = QVBoxLayout(c)
        l.setContentsMargins(16, 10, 10, 10)
        l.setSpacing(6)
        top = QHBoxLayout()
        lab = QLabel("CLIPBOARD")
        lab.setStyleSheet(f"color: {C.PRI}; font-weight: 700; letter-spacing: 2px; font-size: 10px;")
        top.addWidget(lab)
        self._clip_prev = QLabel()
        self._clip_prev.setStyleSheet(f"color: {C.TEXT_MED};")
        top.addWidget(self._clip_prev, 1)
        x = IconButton("close", 24, flat=True)
        x.clicked.connect(c.hide)
        top.addWidget(x)
        l.addLayout(top)
        row = QHBoxLayout()
        for label, fmt in (("Translate", "Translate this text to English: {t}"), ("Summarise", "Summarise this: {t}"),
                           ("Explain", "Explain this: {t}"), ("Fix", "Fix grammar and spelling: {t}")):
            b = GlowButton(label)
            b.setMinimumHeight(28)
            b.clicked.connect(lambda _=False, f=fmt: self._clip_act(f))
            row.addWidget(b)
        l.addLayout(row)
        return c

    def _on_clip(self):
        try:
            if self.modal.is_open():
                return
            t = QApplication.clipboard().text() or ""
            if len(t.strip()) < 24 or t == self._last_clip or not self._ready:
                return
            self._last_clip = t
            pv = " ".join(t.split())
            self._clip_prev.setText(f"“{pv[:70]}{'…' if len(pv) > 70 else ''}”")
            self._clip.show()
            self.host.layout_floats()
            self._clip.raise_()
            fade_in(self._clip, 240)
            QTimer.singleShot(12000, self._clip.hide)
        except Exception:
            pass

    def _clip_act(self, fmt: str):
        self._clip.hide()
        self._send(fmt.format(t=self._last_clip[:800]))

    def set_perf(self, on: bool):
        self._perf_pref = bool(on)
        self.perf.setVisible(bool(on) and bool(self._side_txt))
        patch_cfg(show_perf=on)

    def _side_progress(self, k: float):
        """Show or hide the side bar's text as it opens and closes (icons are always visible)."""
        wide = k > 0.72
        if wide == self._side_txt:
            return
        self._side_txt = wide
        self.brand_txt.setVisible(wide)
        self.date.setVisible(wide)
        self.compact_lbl.setVisible(wide)
        self.ver_lbl.setVisible(wide)
        self.by_lbl.setVisible(wide)
        self.perf.setVisible(wide and self._perf_pref)
        self.clock.setFont(font(15 if wide else 11, QFont.Weight.Bold))

    def _tick(self):
        if self._perf_pref:
            st = self.stage
            mode = "GPU" if GL_ENABLED else "CPU"
            self.perf.setText(f"{mode} · {st.fps:.0f} fps · {st._ms:.1f} ms")
        self.clock.setText(time.strftime("%H:%M"))
        self.date.setText(time.strftime("%a %d %b %Y"))
        if self._page == "dashboard" and self.dash.isVisible():
            self.dash.tick(_metrics.snapshot())

    def _nav(self, key: str):
        if key in ("home", "chat", "dashboard", "phone"):
            self._goto(key)
        elif key == "voice":
            self.open_settings("voice")
        elif key == "settings":
            self.open_settings("general")
        self._sync_nav()

    def _goto(self, key: str):
        self._page = key
        self.pages.setCurrentIndex({"home": 0, "chat": 1, "dashboard": 2, "phone": 3}[key])
        self._sync_nav()

    def _sync_nav(self):
        for k, b in self.nav.items():
            if self._settings_open:
                on = (k == "voice" and self._settings_page == "voice") or (k == "settings" and self._settings_page != "voice")
            else:
                on = k == self._page
            b.setChecked(on)

    def _chip(self, kind: str):
        if kind == "apps":
            self.home_bar.set_text("Open ")
        elif kind == "web":
            self.home_bar.set_text("Search the web for ")
        elif kind == "sys":
            self._send("Show me my system status: CPU, memory and battery.")
        elif kind == "task":
            self._goto("dashboard")
            self.dash.tasks.focus_input()

    def add_activity(self, text: str):
        self.dash.activity.add(text)

    def _compact_toggled(self, on: bool):
        if on:
            QTimer.singleShot(150, self._enter_compact_from_toggle)

    def _enter_compact_from_toggle(self):
        self.compact_toggle.setChecked(False)
        self.enter_compact()

    def _quick(self, key: str):
        try:
            if key == "folder":
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path.home() / "Documents")))
                self.add_activity("Opened the Documents folder")
            elif key == "screenshot":
                self.take_screenshot()
            elif key == "music":
                self._spotify("resume", "Playing music")
            elif key == "calc":
                self._launch({"Windows": [["calc.exe"]], "Darwin": [["open", "-a", "Calculator"]],
                              "Linux": [["gnome-calculator"], ["kcalc"], ["xcalc"]]}, "Calculator")
            elif key == "notepad":
                self._launch({"Windows": [["notepad.exe"]], "Darwin": [["open", "-a", "TextEdit"]],
                              "Linux": [["gedit"], ["kate"], ["mousepad"]]}, "Notepad")
            elif key == "web":
                webbrowser.open("https://www.google.com")
                self.add_activity("Opened the web browser")
        except Exception as e:
            self._toast(f"⚠ {e}")

    def _launch(self, table: dict, name: str):
        for cmd in table.get(_OS, []):
            try:
                subprocess.Popen(cmd, **_WIN_HIDE)
                self.add_activity(f"Opened {name}")
                return
            except Exception:
                continue
        self._toast(f"Couldn't open {name}")

    def _spotify(self, action: str, note: str):
        def work():
            try:
                from actions import spotify_controller as sc
                sc.spotify_controller({"action": action})
            except Exception as e:
                self._log_sig.emit(f"ERR: Spotify — {e}")
        threading.Thread(target=work, daemon=True).start()
        self.add_activity(note)

    def take_screenshot(self):
        self.showMinimized()
        QTimer.singleShot(500, self._grab_screen)

    def _grab_screen(self):
        try:
            out = Path.home() / "Pictures" / "Jarvis"
            out.mkdir(parents=True, exist_ok=True)
            path = out / time.strftime("screenshot_%Y%m%d_%H%M%S.png")
            QApplication.primaryScreen().grabWindow(0).save(str(path))
            self.add_activity("Screenshot saved")
            self._toast(f"Screenshot saved to Pictures/Jarvis")
        except Exception as e:
            self._toast(f"⚠ Screenshot failed: {e}")
        finally:
            self.showNormal()
            self.activateWindow()

    def _check_gpu(self):
        if GL_ENABLED and hasattr(self.backdrop, "isValid") and not self.backdrop.isValid():
            patch_cfg(hw_accel=False)
            self.write_log("SYS: GPU rendering is unavailable on this system — switched to software mode. Restart Jarvis.")

    def _on_gpu_event(self, why: str):
        patch_cfg(gpu_holo=False)
        self.write_log(f"SYS: GPU hologram renderer unavailable ({why}) — using the standard renderer.")

    def set_gpu_holo(self, on: bool):
        self.stage.gpu_enabled = bool(on and GL_ENABLED)
        patch_cfg(gpu_holo=bool(on))
        self._toast("GPU hologram renderer " + ("on" if on else "off"))

    _HUD_MAP = {"sphere": "globe", "core": "crystal", "armor": "holo"}

    def profile_summary(self, name: str) -> str:
        from memory.config_manager import get_profile
        pr = get_profile(name)
        hud = self._HUD_MAP.get(str(pr.get("hud")), str(pr.get("hud")))
        talk = "push-to-talk" if pr.get("talk_mode") == "push" else "open microphone"
        return f"3D model: {hud.title()} · {talk} · graphics quality: {pr.get('quality', 'auto')}"

    def apply_profile(self, name: str, announce: bool = True):
        from memory.config_manager import get_profile, set_active_profile
        name = str(name or "home").lower()
        if name not in ("home", "work", "game"):
            return
        set_active_profile(name)
        pr = get_profile(name)
        hud = self._HUD_MAP.get(str(pr.get("hud") or "holo").lower(), str(pr.get("hud") or "holo").lower())
        self.set_model(hud)
        self.set_quality(str(pr.get("quality") or "auto"))
        if pr.get("talk_mode") in ("push", "open"):
            self.toggle_ptt(pr.get("talk_mode") == "push")
        self.add_activity(f"Profile: {name.title()}")
        self.write_log(f"SYS: Profile → {name.title()} ({self.profile_summary(name)})")
        if announce:
            self._toast(f"Profile: {name.title()}")

    def set_quality(self, q: str):
        self.stage.quality = q
        patch_cfg(quality=q)

    def set_hw_accel(self, on: bool):
        patch_cfg(hw_accel=on)
        self._toast("GPU acceleration " + ("on" if on else "off") + " — restart to apply")

    def _cycle_model(self):
        m = self.stage.cycle_model()
        patch_cfg(stage_model=m)
        self._toast(f"3D model: {m.title()}")

    def open_settings(self, page: str = "general"):
        if self.modal.is_open():
            return
        self._settings_open = True
        self._settings_page = page
        panel = SettingsPanel(self)
        panel.show_page(page)
        self.modal.present(panel, 900, 620)
        self._sync_nav()

    def close_modal(self):
        self.modal.dismiss()

    def _pause_scene(self, on: bool):
        on = bool(on) or getattr(self, "_media_scene_paused", False)
        self.backdrop.paused = on
        self.stage.paused = on
        if not on:
            self.stage._tm.setInterval(24)
        if not on:
            self.backdrop._dirty = True

    def _on_modal_closed(self):
        self._pause_scene(False)
        self._settings_open = False
        self._sync_nav()

    def set_accent(self, hx: str, save: bool = True):
        if not apply_accent(hx):
            return
        self.setStyleSheet(build_qss())
        for w in self.findChildren(QWidget):
            w.update()
        self.title.update()
        if save:
            patch_cfg(ui_color=C.PRI)

    def set_model(self, name: str):
        self.stage.set_model(name)
        patch_cfg(stage_model=self.stage.model)

    def set_speed(self, v: float):
        self.stage.speed = v
        self.backdrop.speed = v
        patch_cfg(fx_speed=v)

    def metrics_visible(self) -> bool:
        return False

    def set_effect(self, key: str, on: bool):
        if key == "aurora":
            self.backdrop.aurora = on
            self.backdrop._dirty = True
            patch_cfg(fx_aurora=on)
        elif key == "stars":
            self.backdrop.stars = on
            self.backdrop._dirty = True
            patch_cfg(fx_stars=on)
        elif key == "particles":
            self.stage.particles = on
            patch_cfg(fx_particles=on)

    def apply_names(self, name: str, user: str):
        name = (name or "").strip() or "JARVIS"
        self.assistant_name = name
        self.user_name = (user or "").strip()
        self.title.setText(name.upper())
        self.hero_title.setText(name.upper())
        self.setWindowTitle(name.upper())
        try:
            from memory.config_manager import save_assistant_config
            save_assistant_config(name, self.user_name)
        except Exception:
            patch_cfg(assistant_name=name, user_name=self.user_name)
        self._toast("Names saved")

    def apply_voice(self, name: str):
        try:
            from memory.config_manager import save_voice
            save_voice(name)
        except Exception:
            patch_cfg(voice_name=name)
        self.write_log(f"SYS: Voice → {name}")
        if self.on_voice_change:
            try:
                self.on_voice_change()
            except Exception:
                pass

    def toggle_wake(self, on: bool, toggle=None):
        if not self.on_wake_toggle:
            return
        try:
            res = self.on_wake_toggle(on)
        except Exception as e:
            self.write_log(f"ERR: wake word — {e}")
            return
        if res == "need_download":
            if toggle is not None:
                toggle.setChecked(False)
            self.write_log("SYS: Downloading wake-word model…")
            self._wake_install()
        else:
            self.write_log(f"SYS: Wake word {'enabled' if on else 'disabled'}.")

    def _wake_install(self):
        if not self.on_wake_install:
            return

        def work():
            try:
                ok, msg = self.on_wake_install()
            except Exception as e:
                ok, msg = False, str(e)
            self._wake_dl_sig.emit(bool(ok), str(msg))
        threading.Thread(target=work, daemon=True).start()

    def _on_wake_dl(self, ok: bool, msg: str):
        self.write_log(f"SYS: {msg}")
        if ok and self.on_wake_toggle:
            try:
                self.on_wake_toggle(True)
            except Exception:
                pass

    def toggle_ptt(self, on: bool):
        self._ptt_on = on
        scope = ""
        if self.on_push_to_talk:
            try:
                scope = self.on_push_to_talk(on) or ""
            except Exception:
                pass
        self.write_log(f"SYS: Push-to-talk {'on' if on else 'off'}{f' ({scope})' if scope else ''}.")

    def wake_manual(self):
        if self.on_wake_manual:
            try:
                self.on_wake_manual()
            except Exception:
                pass

    def _launch_cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        exe = sys.executable
        if _OS == "Windows" and exe.lower().endswith("python.exe"):
            w = exe[:-10] + "pythonw.exe"
            exe = w if os.path.exists(w) else exe
        return [exe, str(BASE_DIR / "main.py")]

    def _autostart_file(self) -> Path:
        if _OS == "Darwin":
            return Path.home() / "Library/LaunchAgents/com.asdcuber.jarvis.plist"
        return Path.home() / ".config/autostart/jarvis.desktop"

    def autostart_enabled(self) -> bool:
        if _OS == "Windows":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                    winreg.QueryValueEx(k, "Jarvis")
                return True
            except Exception:
                return False
        return self._autostart_file().exists()

    def set_autostart(self, on: bool):
        cmd = self._launch_cmd()
        try:
            if _OS == "Windows":
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                                    0, winreg.KEY_SET_VALUE) as k:
                    if on:
                        winreg.SetValueEx(k, "Jarvis", 0, winreg.REG_SZ, " ".join(f'"{c}"' for c in cmd))
                    else:
                        try:
                            winreg.DeleteValue(k, "Jarvis")
                        except FileNotFoundError:
                            pass
            else:
                f = self._autostart_file()
                if on:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    if _OS == "Darwin":
                        args = "".join(f"<string>{c}</string>" for c in cmd)
                        f.write_text('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                                     '<key>Label</key><string>com.asdcuber.jarvis</string>'
                                     f'<key>ProgramArguments</key><array>{args}</array>'
                                     '<key>RunAtLoad</key><true/></dict></plist>', encoding="utf-8")
                    else:
                        f.write_text("[Desktop Entry]\nType=Application\nName=Jarvis\n"
                                     f"Exec={' '.join(chr(34) + c + chr(34) for c in cmd)}\n"
                                     f"Path={BASE_DIR}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
                elif f.exists():
                    f.unlink()
            self._toast("Auto-start " + ("enabled" if on else "disabled"))
        except Exception as e:
            self.write_log(f"ERR: auto-start — {e}")

    def create_shortcut(self):
        cmd = self._launch_cmd()
        desk = Path.home() / "Desktop"
        try:
            desk.mkdir(exist_ok=True)
            if _OS == "Windows":
                lnk = desk / "Jarvis.lnk"
                args = " ".join(f'"{c}"' for c in cmd[1:])
                ico = BASE_DIR / "config" / "jarvis.ico"
                ps = ("$s=(New-Object -COM WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';"
                      "$s.Arguments='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s';$s.Save()"
                      % (lnk, cmd[0], args.replace("'", "''"), BASE_DIR, ico))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, **_WIN_HIDE)
            elif _OS == "Darwin":
                f = desk / "Jarvis.command"
                f.write_text(f"#!/bin/bash\ncd \"{BASE_DIR}\"\n{' '.join(chr(34) + c + chr(34) for c in cmd)}\n")
                f.chmod(0o755)
            else:
                f = desk / "Jarvis.desktop"
                f.write_text("[Desktop Entry]\nType=Application\nName=Jarvis\n"
                             f"Exec={' '.join(chr(34) + c + chr(34) for c in cmd)}\nPath={BASE_DIR}\nTerminal=false\n")
                f.chmod(0o755)
            self._toast("Desktop shortcut created")
        except Exception as e:
            self.write_log(f"ERR: shortcut — {e}")

    def check_updates(self):
        self._toast("Checking for updates…")

        def work():
            try:
                from core.updater import check_for_updates
                self._update_sig.emit(check_for_updates())
            except Exception as e:
                self._update_sig.emit({"ok": False, "message": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _on_update(self, info):
        if not isinstance(info, dict) or not info.get("ok"):
            self.write_log(f"ERR: update check — {(info or {}).get('message', 'failed')}")
            return
        if not info.get("update_available"):
            self._toast(f"You're up to date ({info.get('local_version', '')})")
            return
        notes = (info.get("notes") or "").strip().replace("\n", " ")[:170]
        if info.get("frozen"):
            title = f"Install version {info.get('remote_version')}?"
            detail = "Jarvis downloads the latest release, closes, installs it and starts again. Your settings and memory are kept."
        else:
            title = f"Update to v{info.get('remote_version')}?"
            detail = (notes + " — " if notes else "") + "Your settings, memory and plugins are kept, and a backup lets you roll back."
        p = ConfirmPanel(title, detail)
        p.answered.connect(lambda ok: self._do_update(ok))
        self.modal.present(p, 480, 250, dismissable=False)

    def _do_update(self, ok: bool):
        self.modal.dismiss()
        if not ok:
            return
        self.write_log("SYS: Installing update…")

        def work():
            try:
                from core.updater import apply_update
                self._update_done_sig.emit(apply_update())
            except Exception as e:
                self._update_done_sig.emit({"ok": False, "message": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def _on_update_done(self, r):
        r = r if isinstance(r, dict) else {}
        if r.get("open_url"):
            webbrowser.open(r["open_url"])
        self.write_log(f"{'SYS' if r.get('ok') else 'ERR'}: {r.get('message', 'Update finished.')}")
        if r.get("quit_now"):
            QTimer.singleShot(1500, QApplication.quit)
        elif r.get("ok") and not r.get("manual"):
            QTimer.singleShot(400, self._ask_restart)

    def _ask_restart(self):
        if self.modal.is_open():
            self.modal.dismiss()
        p = ConfirmPanel("Update installed", "Restart Jarvis now to use the new version?")
        p.answered.connect(self._restart_answer)
        QTimer.singleShot(330, lambda: self.modal.present(p, 460, 220, dismissable=False))

    def _restart_answer(self, ok: bool):
        self.modal.dismiss()
        if ok:
            QTimer.singleShot(350, self.restart_app)

    def restart_app(self):
        cmd = self._launch_cmd()
        try:
            if _OS == "Windows":
                subprocess.Popen(["cmd", "/c", "timeout /t 2 /nobreak >nul & start \"\" " + subprocess.list2cmdline(cmd)],
                                 cwd=str(BASE_DIR), **_WIN_HIDE)
            else:
                subprocess.Popen(["sh", "-c", 'sleep 2; exec "$@"', "sh", *cmd], cwd=str(BASE_DIR), start_new_session=True)
        except Exception as e:
            self.write_log(f"ERR: restart — {e}")
            return
        QApplication.quit()

    def _auto_update_check(self):
        cfg = read_cfg()
        if not cfg.get("auto_update_check", True) or time.time() - float(cfg.get("last_update_check", 0) or 0) < 12 * 3600:
            return

        def work():
            try:
                from core.updater import check_for_updates
                info = check_for_updates()
                patch_cfg(last_update_check=time.time())
                if info.get("ok") and info.get("update_available"):
                    self._toast_sig.emit(f"⬆ Update {info.get('remote_version')} is available — Settings → About")
                    self._log_sig.emit(f"SYS: {info.get('message')}. Open Settings → About to install it.")
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def open_store(self):
        info = self._remote_info()
        if info:
            webbrowser.open(f"{info[0]}/plugin-store")
        else:
            self.write_log("SYS: Plugin store needs the remote dashboard (pip install fastapi uvicorn cryptography).")

    def _remote_info(self):
        if not self.on_remote_clicked:
            return None
        try:
            return self.on_remote_clicked()
        except Exception:
            return None

    def open_remote(self):
        info = self._remote_info()
        if not info:
            self.write_log("SYS: Remote dashboard unavailable.")
            return
        self.modal.present(RemotePanel(info, self._remote_info), 440, 610)

    # ── camera features: hand gestures + face recognition ────────────────────────
    def _camera_hub(self):
        if self.camera is None:
            from core.camera_hub import CameraHub
            self.camera = CameraHub(
                on_gesture=lambda a, g: self._gesture_sig.emit(a, g),
                on_face=lambda k, n: self._face_sig.emit(k, n),
                on_status=lambda s: self._gesture_status_sig.emit(s))
        return self.camera

    def _camera_autostart(self):
        try:
            self._camera_hub().refresh()
        except Exception as e:
            self.write_log(f"ERR: camera — {e}")

    def _camera_refresh(self):
        threading.Thread(target=self._camera_hub().refresh, daemon=True).start()

    def set_gestures_enabled(self, on: bool):
        from core import gesture
        gesture.set_enabled(on)
        self._camera_refresh()
        self.write_log("SYS: Gesture control on — the camera is in use." if on else "SYS: Gesture control off.")

    def set_face_enabled(self, on: bool):
        from core import face_id
        face_id.set_enabled(on)
        self._camera_refresh()
        self.write_log("SYS: Face recognition on — the camera is in use. (First start downloads ~37 MB of models.)"
                       if on else "SYS: Face recognition off.")

    def _on_gesture_status(self, s: str):
        self.gesture_status = s
        if s.startswith(("error", "missing")):
            self.write_log(f"ERR: camera — {s}")
            self._toast(f"Camera: {s[:60]}")

    def _on_face_event(self, kind: str, name: str):
        from core import face_id
        if kind == "known":
            self._toast(f"👋 {name} is here")
            self.write_log(f"SYS: Recognised {name}.")
            if face_id.greet_enabled() and self.on_text_command:
                try:
                    self.on_text_command(f"[FaceID] {name} just appeared in front of the camera. Greet them by name in one short friendly sentence.")
                except Exception:
                    pass
        elif kind == "unknown":
            self.write_log("SYS: An unrecognised face is in front of the camera.")
            self._show_unknown_alert()
        elif kind == "enrolled":
            self._toast(f"✅ Saved {name}'s face")
            self.write_log(f"SYS: Face saved for {name}.")
        elif kind == "enroll_failed":
            self._toast("Face not saved — try again")
            self.write_log(f"ERR: face — {name}")

    def _show_unknown_alert(self):
        """Red card in the middle of the HUD for ~4 s, then Jarvis says it out loud."""
        w = self._alert_w
        w.adjustSize()
        w.move(int((self.host.width() - w.width()) / 2), int(self.host.height() * 0.36))
        w.show()
        w.raise_()
        fade_in(w, 220)
        self._alert_on = True
        self._alert_blink.start(450)
        self._alert_timer.start(4000)

    def _alert_pulse(self):
        self._alert_title.setStyleSheet(f"color: {C.RED if int(time.time() * 2) % 2 else C.TEXT};")

    def _alert_done(self):
        self._alert_blink.stop()
        self._alert_w.hide()
        self._alert_on = False
        if self.on_text_command:
            try:
                self.on_text_command("[FaceID] An unknown person has been in front of the camera. "
                                     "Warn the user out loud in one short sentence, calmly, like a security system.")
            except Exception:
                pass

    def enroll_face(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return "Whose face is it? Type a name first."
        self._camera_hub().enroll(name)
        self._toast(f"Look at the camera, {name}…")
        return f"Look straight at the camera for a few seconds to save {name}."

    def face_command(self, action: str, name: str = "") -> str:
        """Used by the voice tool (actions/face_id.py)."""
        from core import face_id
        hub = self._camera_hub()
        if action == "enroll":
            return self.enroll_face(name)
        if action == "list":
            n = face_id.names()
            return ("Saved faces: " + ", ".join(n)) if n else "No faces saved yet."
        if action == "forget":
            return f"Forgot {name}." if face_id.forget(name) else f"I don't have a face saved for {name}."
        if action == "who":
            if not hub.running or not face_id.is_enabled():
                return "Face recognition is off. Turn it on in Settings → Face ID."
            if time.time() - hub.seen_at > 3 or not hub.visible:
                return "I can't see anyone right now."
            return "I can see: " + ", ".join(hub.visible).replace("unknown", "someone I don't know") + "."
        return "Unknown face action."

    def _run_gesture_action(self, action: str, gesture_id: str):
        from core.gesture import ACTIONS, GESTURES
        try:
            if action == "toggle_mic":
                self.toggle_mute()
            elif action == "wake_toggle":
                self.wake_manual()
            elif action == "open_settings":
                self.open_settings("general")
            elif action == "fullscreen":
                self.toggle_fullscreen()
            elif action == "screenshot":
                import pyautogui
                from actions._common import output_dir, unique_path
                path = unique_path(output_dir("Screenshots"), "gesture", ".png")
                pyautogui.screenshot().save(str(path))
                self._toast(f"📸 Saved {path.name}")
                return
            else:
                import pyautogui
                key = {"play_pause": "playpause", "next_track": "nexttrack", "prev_track": "prevtrack",
                       "volume_up": "volumeup", "volume_down": "volumedown", "volume_mute": "volumemute"}.get(action)
                if key:
                    pyautogui.press(key)
            self._toast(f"{GESTURES.get(gesture_id, ('', ''))[0]} → {ACTIONS.get(action, action)}")
        except Exception as e:
            self.write_log(f"ERR: gesture action {action} — {e}")

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def enter_compact(self):
        if self._compact is None:
            self._compact = CompactMic()
            self._compact.clicked.connect(self.toggle_mute)
            self._compact.restore.connect(self.exit_compact)
        self._compact.muted = self._muted
        scr = QApplication.primaryScreen().availableGeometry()
        self._compact.move(scr.right() - 100, scr.bottom() - 120)
        self._compact.show()
        self.hide()

    def exit_compact(self):
        if self._compact is not None:
            self._compact.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @property
    def muted(self) -> bool:
        return self._muted

    def toggle_mute(self):
        self._muted = not self._muted
        self.stage.muted = self._muted
        for bar in self._bars:
            bar.set_live(not self._muted)
        if self._compact is not None:
            self._compact.muted = self._muted
        self._apply_state("MUTED" if self._muted else self._state)
        self.write_log(f"SYS: Microphone {'muted' if self._muted else 'live'}.")

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Attach a file")
        if p:
            self.set_file(p)

    def set_file(self, path: str):
        self._current_file = path
        for bar in self._bars:
            bar.set_file(Path(path).name)
        self._toast(f"Attached {Path(path).name}")

    def clear_file(self):
        self._current_file = None
        for bar in self._bars:
            bar.set_file(None)

    @property
    def current_file(self):
        return self._current_file

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.set_file(u.toLocalFile())
                break

    def _send(self, text: str):
        self.write_log(f"You: {text}")
        if self.on_text_command:
            try:
                self.on_text_command(text)
            except Exception as e:
                self.write_log(f"ERR: {e}")

    _STATE_COL = {"SPEAKING": "ACC2", "LISTENING": "GREEN", "THINKING": "AMBER", "PROCESSING": "AMBER",
                  "SLEEPING": "TEXT_DIM", "MUTED": "RED"}

    def set_state(self, s: str):
        self._state_sig.emit(str(s))

    def _apply_state(self, s: str):
        s = s.upper()
        if s != "MUTED":
            self._state = s
        self.stage.state = s
        self.stage.speaking = s == "SPEAKING"
        label = "MUTED" if self._muted else s
        col = getattr(C, self._STATE_COL.get(label, "PRI"))
        self.pill.set(label, col)

    def write_log(self, text: str):
        self._log_sig.emit(str(text))

    def _on_log(self, text: str):
        text = text.strip()
        if not text:
            return
        if text.startswith("You:"):
            self.add_activity("You asked: " + text[4:].strip())
        elif text.startswith("SYS:"):
            self.add_activity(text[4:].strip())
        if text.startswith("SYS:"):
            self.chat.add("sys", "", text[4:].strip())
        elif text.startswith("ERR:"):
            self.chat.add("err", "", text[4:].strip())
            self._toast("⚠ " + text[4:].strip()[:90])
        elif text.startswith("[Phone]"):
            self.chat.add("sys", "", text)
        else:
            m = re.match(r"^\[?([^:\]]{1,24})\]?:\s*(.*)$", text, re.S)
            if m and m.group(1).strip().lower() in ("you", "web"):
                self.chat.add("user", "", m.group(2))
            elif m:
                self.chat.add("ai", m.group(1).strip(), m.group(2))
            else:
                self.chat.add("sys", "", text)

    def show_content(self, title: str, text: str):
        self._content_sig.emit(title, text)

    def _show_content(self, title: str, text: str):
        self._content_title.setText(str(title).upper())
        self._content_text.setPlainText(str(text))
        self._content.show()
        self.host.layout_floats()
        self._content.raise_()
        end = self._content.pos()
        self._content.move(end.x(), end.y() + 40)
        slide_to(self._content, end, 360)
        fade_in(self._content, 300)

    def _toast(self, msg: str):
        self._toast_lbl.setText(msg)
        self._toast_w.show()
        self.host.layout_floats()
        self._toast_w.raise_()
        fade_in(self._toast_w, 200)
        self._toast_timer.start(3200)

    def phone_event(self, event):
        if isinstance(event, dict):
            self._phone_event_sig.emit(dict(event))

    def _on_phone_event(self, event):
        if not isinstance(event, dict):
            return
        if event.get("type") == "phone_devices":
            self.phone_page.set_devices(event.get("devices") or [])
        elif event.get("type") == "phone_notification":
            self.phone_page.add_message(event)
        elif event.get("type") == "phone_call":
            self.phone_page.on_call(event)
            who = event.get("name") or event.get("number") or "unknown number"
            if event.get("event") == "incoming_call":
                self._toast_sig.emit(f"📞 Incoming call — {who}")
            elif event.get("event") == "missed_call":
                self._toast_sig.emit(f"❌ Missed call — {who}")

    on_phone_command = None          # set by main: fn(action, value)

    def _phone_command(self, action, value):
        if self.on_phone_command:
            self.on_phone_command(str(action), str(value))
        else:
            self._toast_sig.emit("Phone control is not ready yet")

    def notify_phone_connected(self):
        self._toast_sig.emit("📱 Phone connected")

    def _camera_toggle(self, on: bool):
        if on and not self._cam_run:
            self._cam_run = True
            self._media_title.setText("CAMERA")
            self._media.show()
            self.host.layout_floats()
            fade_in(self._media, 260)
            threading.Thread(target=self._cam_worker, daemon=True).start()
        elif not on:
            self._cam_run = False
            self._hide_media()

    def _cam_worker(self):
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            while self._cam_run and cap.isOpened():
                ok, frame = cap.read()
                if ok:
                    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok2:
                        self._cam_frame_sig.emit(buf.tobytes())
                time.sleep(0.05)
            cap.release()
        except Exception as e:
            self._log_sig.emit(f"ERR: camera — {e}")
            self._cam_run = False

    def _camera_frame(self, data: bytes):
        img = QImage.fromData(data)
        if not img.isNull() and self._media.isVisible():
            self._media_lbl.setPixmap(QPixmap.fromImage(img).scaled(
                self._media_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def start_camera_stream(self):
        self._cam_stream_sig.emit(True)

    def stop_camera_stream(self):
        self._cam_run = False
        self._cam_stream_sig.emit(False)

    def show_phone_screen_frame(self, b64: str):
        self._phone_frame_sig.emit(b64)

    def _phone_frame(self, b64: str):
        try:
            img = QImage.fromData(base64.b64decode(b64))
        except Exception:
            return
        if img.isNull() or self._cam_run:
            return
        if not self._media.isVisible():
            self._media_title.setText("PHONE SCREEN")
            self._media.show()
            self.host.layout_floats()
            fade_in(self._media, 260)
        self._media_lbl.setPixmap(QPixmap.fromImage(img).scaled(
            self._media_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._media_timer.start(6000)

    def show_media_frame(self, data: bytes, title: str = ""):
        with self._media_lock:
            self._media_pending = (bytes(data or b""), str(title or ""))
            if self._media_queued:
                return
            self._media_queued = True
        self._media_frame_sig.emit(b"", "")

    def _on_media_frame(self, _d: bytes = b"", _t: str = ""):
        with self._media_lock:
            pending, self._media_pending = self._media_pending, None
            self._media_queued = False
        if pending is None:
            return
        data, title = pending
        if not data:
            if not self._cam_run:
                self._hide_media()
            return
        if self._cam_run:
            return
        img = QImage.fromData(data)
        if img.isNull():
            return
        self._show_video_image(img, title)

    def _show_video_image(self, img, title: str):
        if not self._media.isVisible() or self._media_title.text() != (title or "VIDEO"):
            self._media_title.setText(title or "VIDEO")
            self._media.show()
            self.host.layout_floats()
        self._set_media_scene(True)
        self._media.raise_()
        self._media_lbl.setPixmap(QPixmap.fromImage(img.scaled(
            self._media_lbl.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
        self._media_timer.stop()  # video panel is closed by the player (empty frame) or the user, not by a timeout

    # ── mpv video: a native window floats over the media panel and mpv draws into it ──
    def start_mpv_window(self, title, result):
        self._mpv_open_sig.emit((title, result))

    def stop_mpv_window(self):
        self._mpv_close_sig.emit()

    def mpv_command(self, cmd: str):
        self._mpv_cmd_sig.emit(str(cmd))

    def _mpv_cmd(self, cmd: str):
        if cmd == "fs":
            self._toggle_media_full()
        elif cmd == "esc":
            self._exit_media_full()

    def _mpv_open(self, payload):
        title, result = payload
        try:
            self._mpv_close()
            vw = MpvWindow(self)
            vw.want_toggle.connect(self._toggle_media_full)
            vw.key_handler = self._video_key
            self._mpv_win = vw
            self._mpv_bar.reset()
            self._mpv_bar.show()
            ov = FsOverlay(vw)  # full-screen control bar (owned by the video window, so it stays on top of it)
            ov.bar.ctl.connect(self._video_ctl)
            ov.bar.seek_fraction.connect(self._mpv_seek_fraction)
            ov.bar.stop.connect(self._close_media_user)
            self._fs_overlay = ov
            self._fs_cursor = None
            self._fs_until = 0.0
            self.host.media_extra = 76
            fw = QApplication.focusWidget()
            if isinstance(fw, (QLineEdit, QTextEdit)):
                fw.clearFocus()  # so Space / arrows reach the video instead of a text box
            self.setFocus()
            self._media_title.setText(title or "VIDEO")
            self._media_lbl.clear()
            self._media_timer.stop()
            if not self._media.isVisible():
                self._media.show()
            self.host.layout_floats()
            self._media.raise_()
            self._set_media_scene(True)
            self._sync_mpv_geometry()
            vw.show()
            result["wid"] = int(vw.winId())
            self._mpv_timer.start(100)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            result["ready"].set()

    def _sync_mpv_geometry(self):
        vw = self._mpv_win
        if vw is None or vw.isFullScreen():
            return
        if self.isMinimized() or not self._media.isVisible():
            vw.hide()
            return
        lbl = self._media_lbl
        rect = QRect(lbl.mapToGlobal(QPoint(0, 0)), lbl.size())
        if vw.geometry() != rect:
            vw.setGeometry(rect)
        if not vw.isVisible():
            vw.show()

    def _mpv_close(self):
        self._mpv_timer.stop()
        if getattr(self, "_mpv_bar", None) is not None:
            self._mpv_bar.hide()
        ov, self._fs_overlay = getattr(self, "_fs_overlay", None), None
        if ov is not None:
            try:
                ov.hide()
            except Exception:
                pass
        self.host.media_extra = 0
        if getattr(self, "_extras", None) is not None:
            self._extras.hide()
        vw, self._mpv_win = self._mpv_win, None
        if vw is not None:
            try:
                vw.close()
                vw.deleteLater()
            except Exception:
                pass

    # ── HUD video: info, "up next", like / dislike / subscribe, settings ──
    def media_info(self, meta: dict):
        self._media_info_sig.emit(dict(meta or {}))

    def media_suggestions(self, items: list):
        self._media_sugg_sig.emit(list(items or []))

    def _on_media_info(self, meta: dict):
        if self._mpv_win is None:
            return
        if meta.get("title"):
            self._media_title.setText(str(meta["title"])[:80].upper())
        yt = bool(meta.get("youtube"))
        self._vx_meta = meta
        self._vx_rating, self._vx_subscribed = "none", False
        if yt:
            self._extras.set_info(meta)
        self._extras.setVisible(yt)
        self.host.media_extra = 76 + (EXTRA_H + 6 if yt else 0)
        self.host.layout_floats()
        self._sync_mpv_geometry()

    def _on_media_suggestions(self, items: list):
        if self._mpv_win is not None:
            self._extras.set_suggestions(items)

    def _vx_open_settings(self, pos):
        try:
            from actions.hud_video import get_prefs
            if self._vx_settings is None:
                self._vx_settings = PlayerSettings(self)
                self._vx_settings.changed.connect(self._video_ctl)
            self._vx_settings.open_at(pos, getattr(self, "_vx_meta", {}) or {}, get_prefs())
        except Exception as e:
            self.write_log(f"ERR: player settings — {e}")

    def _vx_rate(self, kind: str):
        want = "none" if self._vx_rating == kind else kind          # pressing again removes the rating

        def work():
            try:
                from actions import youtube_actions as ya
                from actions.hud_video import get_video_meta
                msg = ya.rate(get_video_meta().get("id", ""), want)
                if not msg.startswith("✗"):
                    self._vx_rating = want
                    self._vx_state_sig.emit(kind, want == kind)
                self._toast_sig.emit(msg)
            except Exception as e:
                self._toast_sig.emit(f"✗ {e}")
        self._toast_sig.emit("Talking to YouTube… (the first time a browser opens to sign in)")
        threading.Thread(target=work, daemon=True).start()

    def _vx_subscribe(self):
        def work():
            try:
                from actions import youtube_actions as ya
                from actions.hud_video import get_video_meta
                m = get_video_meta()
                msg = ya.subscribe(m.get("channel_id", ""), m.get("channel", ""))
                if not msg.startswith("✗"):
                    self._vx_state_sig.emit("sub", True)
                self._toast_sig.emit(msg)
            except Exception as e:
                self._toast_sig.emit(f"✗ {e}")
        self._toast_sig.emit("Talking to YouTube… (the first time a browser opens to sign in)")
        threading.Thread(target=work, daemon=True).start()

    # ── HUD video controls ──
    def _video_ctl(self, cmd: str, value=None):
        try:
            from actions.hud_video import video_control
            video_control(cmd, value)
        except Exception:
            pass

    def _mpv_seek_fraction(self, v: int):
        try:
            from actions.hud_video import get_video_state
            dur = get_video_state()["dur"]
        except Exception:
            return
        if dur > 0:
            self._video_ctl("seek_abs", dur * max(0, min(1000, v)) / 1000.0)

    def _video_key(self, e) -> bool:
        """Space = pause, ←/→ = 5 s, Shift+←/→ = 5 min, ↑/↓ = volume. True when the key was used."""
        mods = e.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        k = e.key()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Space:
            if not e.isAutoRepeat():
                self._video_ctl("pause")
        elif k == Qt.Key.Key_Left:
            self._video_ctl("seek", -300 if shift else -5)
        elif k == Qt.Key.Key_Right:
            self._video_ctl("seek", 300 if shift else 5)
        elif k == Qt.Key.Key_Up:
            self._video_ctl("volume", 5)
        elif k == Qt.Key.Key_Down:
            self._video_ctl("volume", -5)
        else:
            return False
        return True

    def _mpv_tick(self):
        self._sync_mpv_geometry()
        self._update_mpv_bar()

    def _update_mpv_bar(self):
        if self._mpv_win is None:
            return
        try:
            from actions.hud_video import get_video_state
            st = get_video_state()
        except Exception:
            return
        if self._mpv_bar.isVisible():
            self._mpv_bar.refresh(st)
        ov = getattr(self, "_fs_overlay", None)
        if ov is not None:
            self._update_fs_overlay(ov, st)

    def _update_fs_overlay(self, ov, st: dict):
        """Full screen: show the control bar while the mouse moves (or paused/buffering), hide it after 3 s."""
        vw = self._mpv_win
        if vw is None or not vw.isFullScreen() or not vw.isVisible():
            if ov.isVisible():
                ov.hide()
            return
        now = time.monotonic()
        pos = QCursor.pos()
        if pos != self._fs_cursor or (ov.isVisible() and ov.geometry().contains(pos)):
            self._fs_cursor = pos
            self._fs_until = now + 3.0
        if now < self._fs_until or st["paused"] or st["buffering"]:
            g = vw.geometry()
            w, h = max(480, min(g.width() - 80, 1100)), 84
            rect = QRect(g.x() + (g.width() - w) // 2, g.y() + g.height() - h - 40, w, h)
            if ov.geometry() != rect:
                ov.setGeometry(rect)
            if not ov.isVisible():
                ov.show()
                ov.raise_()
            ov.bar.refresh(st)
        elif ov.isVisible():
            ov.hide()

    def _close_media(self):
        if not self._cam_run:
            self._hide_media()

    def _hide_media(self):
        self._mpv_close()
        self._set_media_scene(False)
        self._media.hide()

    def _toggle_media_full(self):
        vw = self._mpv_win
        if vw is None:
            return
        if vw.isFullScreen():
            vw.showNormal()
            self._sync_mpv_geometry()
        else:
            try:
                scr = self.screen() or QApplication.primaryScreen()
                if scr is not None:
                    vw.setGeometry(scr.geometry())
            except Exception:
                pass
            self._fs_until = time.monotonic() + 3.5
            vw.showFullScreen()
            vw.activateWindow()
            vw.setFocus()

    def _exit_media_full(self):
        vw = self._mpv_win
        if vw is not None and vw.isFullScreen():
            self._toggle_media_full()

    def _set_media_scene(self, on: bool):
        """Freeze the animated HUD background while a video plays; resume afterwards."""
        on = bool(on)
        if on == self._media_scene_paused:
            return
        self._media_scene_paused = on
        self._pause_scene(self.modal.is_open() or on)

    def _close_media_user(self):
        self._cam_run = False
        try:
            from actions.hud_video import stop_hud_video
            stop_hud_video()
        except Exception:
            pass
        if self._mpv_win is not None:
            self._mpv_win.hide()
            self._set_media_scene(False)
            self._media.hide()
        else:
            self._hide_media()

    def show_confirm(self, title: str, detail: str = ""):
        self._confirm_sig.emit(title, detail)

    def hide_confirm(self):
        self._confirm_hide_sig.emit()

    def _show_confirm(self, title: str, detail: str):
        if self.modal.is_open():
            self.modal.dismiss()
        p = ConfirmPanel(title, detail)
        p.answered.connect(self._confirm_answer)
        self._confirm_panel = p
        self.modal.present(p, 460, 240, dismissable=False)

    def _confirm_answer(self, ok: bool):
        try:
            from core import confirm
            confirm.resolve(ok)
        except Exception as e:
            self.write_log(f"ERR: confirm — {e}")
        self._hide_confirm()

    def _hide_confirm(self):
        if self._confirm_panel is not None:
            self._confirm_panel = None
            self.modal.dismiss()

    def prompt_reconfig(self):
        self._reconfig_sig.emit()

    def _show_setup(self):
        self._ready = False
        detected = {"Darwin": "mac", "Windows": "windows"}.get(_OS, "linux")
        p = SetupPanel(detected)
        p.done.connect(self._setup_done)
        if self.modal.is_open():
            self.modal.dismiss()
            QTimer.singleShot(320, lambda: self.modal.present(p, 480, 420, dismissable=False))
        else:
            self.modal.present(p, 480, 420, dismissable=False)

    def _setup_done(self, key: str, os_key: str):
        try:
            from memory.config_manager import load_api_keys, save_api_keys
            save_api_keys(key)
            patch_cfg(os_system=os_key)
            try:
                from core.installer import install_for_config
                cfg = load_api_keys()
                threading.Thread(target=lambda: install_for_config(cfg, self.write_log), daemon=True).start()
            except Exception:
                pass
        except Exception as e:
            self.write_log(f"ERR: could not save key — {e}")
            return
        self.modal.dismiss()
        self._ready = True
        self.write_log("SYS: API key saved.")

    def reload_hotkeys(self):
        """Re-read the shortcuts after Settings changed them."""
        from ui.theme import hotkeys
        self._hk_map = {seq: act for act, seq in hotkeys().items()}

    def _hotkey_action(self, e):
        if not hasattr(self, "_hk_map"):
            self.reload_hotkeys()
        try:
            return self._hk_map.get(QKeySequence(e.keyCombination()).toString())
        except Exception:
            return None

    def keyPressEvent(self, e):
        k = e.key()
        hk = self._hotkey_action(e)
        if hk == "mute":
            self.toggle_mute()
        elif hk == "fullscreen":
            self.toggle_fullscreen()
        elif hk == "compact":
            self.enter_compact()
        elif self._mpv_win is not None and not self.modal.is_open() and self._video_key(e):
            pass
        elif k == Qt.Key.Key_Escape and self.host.media_full:
            self._exit_media_full()
        elif k == Qt.Key.Key_Escape and self.isFullScreen() and not self.modal.is_open():
            self.showNormal()
        elif (self._ptt_on and k == Qt.Key.Key_Space and e.modifiers() & Qt.KeyboardModifier.ControlModifier
              and not e.isAutoRepeat() and not self._ptt_down):
            self._ptt_down = True
            if self.ptt_hold:
                self.ptt_hold(True)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if self._ptt_down and not e.isAutoRepeat() and e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Control):
            self._ptt_down = False
            if self.ptt_hold:
                self.ptt_hold(False)
        super().keyReleaseEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "modal"):
            self.modal.setGeometry(self.backdrop.rect())
        if getattr(self, "_mpv_win", None) is not None:
            self._sync_mpv_geometry()

    def moveEvent(self, e):
        super().moveEvent(e)
        if getattr(self, "_mpv_win", None) is not None:
            self._sync_mpv_geometry()

    def closeEvent(self, e):
        if self.camera is not None:
            self.camera.stop()
        self._close_media_user()
        self._mpv_close()
        if self._compact is not None:
            self._compact.close()
        super().closeEvent(e)
        QApplication.quit()


class _Root:

    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        sys.exit(self._app.exec())


class JarvisUI:
    _FORWARD = {
        "on_text_command", "on_remote_clicked", "on_interrupt", "on_voice_change", "on_audio_device_change",
        "get_plugins", "get_plugin_settings", "on_wake_toggle", "on_wake_manual", "on_wake_install",
        "on_push_to_talk", "ptt_hold", "wake_get_state", "on_phone_command", "face_command",
    }

    def __init__(self):
        if QApplication.instance() is None and GL_ENABLED:
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
            try:
                QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
            except Exception:
                pass
        object.__setattr__(self, "_app", QApplication.instance() or QApplication(sys.argv))
        self._app.setApplicationName("Jarvis")
        self._app.setFont(font(10))
        object.__setattr__(self, "_win", MainWindow())
        object.__setattr__(self, "root", _Root(self._app))
        self._extra: dict = {}
        icon = BASE_DIR / "config" / "jarvis.ico"
        if icon.exists():
            from PyQt6.QtGui import QIcon
            self._win.setWindowIcon(QIcon(str(icon)))
        self._win.show()

    def __setattr__(self, name, value):
        if name in self._FORWARD:
            setattr(self._win, name, value)
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name in ("_win", "_app", "root", "_extra"):
            raise AttributeError(name)
        if name in self._FORWARD:
            return getattr(self._win, name)
        if name in self._extra:
            return self._extra[name]
        raise AttributeError(name)

    @property
    def muted(self) -> bool:
        return self._win.muted

    @property
    def current_file(self):
        return self._win.current_file

    def set_phone_link_provider(self, fn):
        self._win.phone_page.set_link_provider(fn)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.3)

    def write_log(self, text: str):
        self._win.write_log(text)

    def set_state(self, s: str):
        self._win.set_state(s)

    def set_audio_level(self, level: float):
        self._win.stage.set_audio_level(level)
        if self._win._compact is not None:
            self._win._compact.amp = max(0.0, min(1.0, float(level)))

    def push_visemes(self, frames, hop: float, at: float):
        self._win.stage.push_visemes(frames, hop, at)

    def show_content(self, title: str, text: str):
        self._win.show_content(title, text)

    def start_camera_stream(self):
        self._win.start_camera_stream()

    def stop_camera_stream(self):
        self._win.stop_camera_stream()

    def show_phone_screen_frame(self, b64: str):
        self._win.show_phone_screen_frame(b64)

    def show_media_frame(self, data: bytes, title: str = ""):
        self._win.show_media_frame(data, title)

    def media_info(self, meta):
        self._win.media_info(meta)

    def media_suggestions(self, items):
        self._win.media_suggestions(items)

    def start_mpv_window(self, title, result):
        self._win.start_mpv_window(title, result)

    def stop_mpv_window(self):
        self._win.stop_mpv_window()

    def mpv_command(self, cmd):
        self._win.mpv_command(cmd)

    def notify_phone_connected(self):
        self._win.notify_phone_connected()

    def phone_event(self, event):
        self._win.phone_event(event)

    def show_confirm(self, title: str, detail: str = ""):
        self._win.show_confirm(title, detail)

    def hide_confirm(self):
        self._win.hide_confirm()

    def prompt_reconfig(self):
        self._win.prompt_reconfig()

    def apply_profile(self, name: str):
        self._win._profile_sig.emit(str(name))

    def refresh_tasks(self):
        self._win._tasks_sig.emit()

    def restart_app(self):
        self._win._restart_sig.emit()

    def quit_app(self):
        self._win._quit_sig.emit()

#by ASDcuber
