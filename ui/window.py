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

from PyQt6.QtCore import QCoreApplication, QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient, QSurfaceFormat
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

import ui.theme as ui_theme
from ui.fx import GL_ENABLED, Backdrop, GlassCard, GlowButton, ModalLayer, Stage3D, Toggle, fade_in, slide_to
from ui.metrics import _metrics
from ui.panels import APP_VERSION, ConfirmPanel, RemotePanel, SettingsPanel, SetupPanel
from ui.theme import C, DEFAULT_ACCENT, apply_accent, build_qss, patch_cfg, qcol, read_cfg, rgba
from ui.pages import DashboardPage, InputBar, LogoMark, NavItem
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
            m.setGeometry(W - 400, 12, 388, 316)
        k = self.floats.get("clip")
        if k is not None and k.isVisible():
            k.setGeometry(int((W - min(W - 40, 620)) / 2), 12, min(W - 40, 620), 96)
        t = self.floats.get("toast")
        if t is not None and t.isVisible():
            t.adjustSize()
            t.move(int((W - t.width()) / 2), 14)


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _reconfig_sig = pyqtSignal()
    _cam_stream_sig = pyqtSignal(bool)
    _cam_frame_sig = pyqtSignal(bytes)
    _phone_frame_sig = pyqtSignal(str)
    _media_frame_sig = pyqtSignal(bytes, str)
    _confirm_sig = pyqtSignal(str, str)
    _confirm_hide_sig = pyqtSignal()
    _wake_dl_sig = pyqtSignal(bool, str)
    _update_sig = pyqtSignal(object)
    _toast_sig = pyqtSignal(str)

    def __init__(self, face_path: str = ""):
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
        self._confirm_sig.connect(self._show_confirm)
        self._confirm_hide_sig.connect(self._hide_confirm)
        self._wake_dl_sig.connect(self._on_wake_dl)
        self._update_sig.connect(self._on_update)
        self._toast_sig.connect(self._toast)

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

        side = GlassCard(radius=26, tint=140)
        side.setFixedWidth(228)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 14)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(LogoMark())
        bcol = QVBoxLayout()
        bcol.setSpacing(0)
        self.title = QLabel(self.assistant_name.upper())
        tf = font(15, QFont.Weight.Bold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self.title.setFont(tf)
        bcol.addWidget(self.title)
        sub_l = QLabel("Your AI Assistant")
        sub_l.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        bcol.addWidget(sub_l)
        brand.addLayout(bcol, 1)
        sl.addLayout(brand)
        sl.addSpacing(16)
        self.nav: dict = {}
        for key, icon, label in (("home", "home", "Home"), ("chat", "chat", "Chat"), ("dashboard", "dashboard", "Dashboard"),
                                 ("voice", "mic", "Voice & AI"), ("settings", "gear", "Settings")):
            b = NavItem(icon, label)
            b.clicked.connect(lambda _=False, k=key: self._nav(k))
            self.nav[key] = b
            sl.addWidget(b)
        sl.addStretch()
        self.perf = QLabel("")
        self.perf.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        self.perf.setVisible(bool(read_cfg().get("show_perf", False)))
        sl.addWidget(self.perf)
        crow = QHBoxLayout()
        cl = QLabel("Compact Mode")
        cl.setStyleSheet(f"color: {C.TEXT_MED};")
        crow.addWidget(cl)
        crow.addStretch()
        self.compact_toggle = Toggle(False)
        self.compact_toggle.toggled.connect(self._compact_toggled)
        crow.addWidget(self.compact_toggle)
        sl.addLayout(crow)
        sl.addSpacing(8)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 10px;")
        by = QLabel("by ASDcuber521")
        by.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; letter-spacing: 1px;")
        sl.addWidget(ver)
        sl.addWidget(by)
        root.addWidget(side)

        col = QVBoxLayout()
        col.setSpacing(12)
        head = GlassCard(radius=24, tint=130)
        head.setFixedHeight(68)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 0, 14, 0)
        hl.setSpacing(14)
        self.pill = StatePill()
        hl.addWidget(self.pill)
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color: {C.TEXT_MED};")
        hl.addWidget(self.sub)
        hl.addStretch()
        self.clock = QLabel("--:--")
        self.clock.setFont(font(15, QFont.Weight.Bold))
        self.date = QLabel("")
        self.date.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px;")
        cb = QVBoxLayout()
        cb.setSpacing(0)
        cb.addWidget(self.clock, 0, Qt.AlignmentFlag.AlignRight)
        cb.addWidget(self.date, 0, Qt.AlignmentFlag.AlignRight)
        hl.addLayout(cb)
        fs = IconButton("full", 40, tip="Fullscreen  F11")
        fs.clicked.connect(self.toggle_fullscreen)
        hl.addWidget(fs)
        col.addWidget(head)
        self._refresh_sub()

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
        tag.setStyleSheet(f"color: {C.PRI}; font-size: 13px;")
        hv.addWidget(tag)
        hv.addSpacing(6)
        self.home_bar = InputBar(attach=False)
        self.home_bar.setMaximumWidth(700)
        hv.addWidget(self.home_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        chips = QHBoxLayout()
        chips.setSpacing(10)
        chips.addStretch()
        for label, kind in (("Open apps", "apps"), ("Search web", "web"), ("System info", "sys"), ("Create task", "task")):
            c = GlowButton(label, "ghost", pill=True)
            c.setMinimumHeight(34)
            c.clicked.connect(lambda _=False, k=kind: self._chip(k))
            chips.addWidget(c)
        chips.addStretch()
        hv.addLayout(chips)
        hv.addSpacing(4)
        self.pages.addWidget(home)

        chat = GlassCard(radius=26, tint=130)
        cv = QVBoxLayout(chat)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(10)
        ch = QHBoxLayout()
        ct = QLabel("Conversation")
        ct.setFont(font(13, QFont.Weight.Bold))
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
        col.addWidget(self.pages, 1)
        root.addLayout(col, 1)

        self._bars = [self.home_bar, self.chat_bar]
        for bar in self._bars:
            bar.submitted.connect(self._send)
            bar.mic_clicked.connect(self.toggle_mute)
            bar.attach_clicked.connect(self._browse)
            bar.detach_clicked.connect(self.clear_file)
        self._sync_nav()

        self._content = self._make_content()
        self._media = self._make_media()
        self._clip = self._make_clip()
        self._toast_w = GlassCard(self.host, radius=18, tint=210, accent=C.PRI)
        tl = QHBoxLayout(self._toast_w)
        tl.setContentsMargins(16, 9, 16, 9)
        self._toast_lbl = QLabel()
        tl.addWidget(self._toast_lbl)
        self._toast_w.hide()
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
        x = IconButton("close", 26, flat=True)
        x.clicked.connect(self._close_media_user)
        h.addWidget(x)
        l.addLayout(h)
        self._media_lbl = QLabel()
        self._media_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self._media_lbl, 1)
        return c

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
        self.perf.setVisible(on)
        patch_cfg(show_perf=on)

    def _refresh_sub(self):
        who = f", {self.user_name}" if self.user_name else ""
        self.sub.setText(f"Ready to assist you{who}.")

    def _tick(self):
        if self.perf.isVisible():
            st = self.stage
            mode = "GPU" if GL_ENABLED else "CPU"
            self.perf.setText(f"{mode} · {st.fps:.0f} fps · {st._ms:.1f} ms")
        self.clock.setText(time.strftime("%H:%M"))
        self.date.setText(time.strftime("%a %d %b %Y"))
        if self._page == "dashboard" and self.dash.isVisible():
            self.dash.tick(_metrics.snapshot())

    def _nav(self, key: str):
        if key in ("home", "chat", "dashboard"):
            self._goto(key)
        elif key == "voice":
            self.open_settings("voice")
        elif key == "settings":
            self.open_settings("general")
        self._sync_nav()

    def _goto(self, key: str):
        self._page = key
        self.pages.setCurrentIndex({"home": 0, "chat": 1, "dashboard": 2}[key])
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
        self._refresh_sub()
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
        p = ConfirmPanel(f"Update to v{info.get('remote_version')}?",
                         "Your config and memory are preserved. Restart after the update finishes.")
        p.answered.connect(lambda ok: self._do_update(ok))
        self.modal.present(p, 460, 230, dismissable=False)

    def _do_update(self, ok: bool):
        self.modal.dismiss()
        if not ok:
            return
        self.write_log("SYS: Installing update…")

        def work():
            try:
                from core.updater import apply_update
                r = apply_update()
                self._log_sig.emit(f"SYS: {r.get('message', 'Update finished — restart to apply.')}")
            except Exception as e:
                self._log_sig.emit(f"ERR: update — {e}")
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
        self.modal.present(RemotePanel(info, self._remote_info), 440, 560)

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
            self._media.hide()

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
                362, 262, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

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
            362, 262, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._media_timer.start(6000)

    def show_media_frame(self, data: bytes, title: str = ""):
        self._media_frame_sig.emit(bytes(data or b""), str(title or ""))

    def _on_media_frame(self, data: bytes, title: str):
        if not data:
            if not self._cam_run:
                self._media.hide()
            return
        if self._cam_run:
            return
        img = QImage.fromData(data)
        if img.isNull():
            return
        if not self._media.isVisible() or self._media_title.text() != (title or "VIDEO"):
            self._media_title.setText(title or "VIDEO")
            self._media.show()
            self.host.layout_floats()
        self._media.raise_()
        self._media_lbl.setPixmap(QPixmap.fromImage(img).scaled(
            362, 262, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._media_timer.start(4000)

    def _close_media(self):
        if not self._cam_run:
            self._media.hide()

    def _close_media_user(self):
        self._cam_run = False
        self._media.hide()

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

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_F4:
            self.toggle_mute()
        elif k == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_F12:
            self.enter_compact()
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

    def closeEvent(self, e):
        self._cam_run = False
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
        "on_push_to_talk", "ptt_hold", "wake_get_state",
    }

    def __init__(self, face_path: str = ""):
        if QApplication.instance() is None and GL_ENABLED:
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
            try:
                QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
            except Exception:
                pass
        object.__setattr__(self, "_app", QApplication.instance() or QApplication(sys.argv))
        self._app.setApplicationName("Jarvis")
        self._app.setFont(font(10))
        object.__setattr__(self, "_win", MainWindow(face_path))
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

    def notify_phone_connected(self):
        self._win.notify_phone_connected()

    def show_confirm(self, title: str, detail: str = ""):
        self._win.show_confirm(title, detail)

    def hide_confirm(self):
        self._win.hide_confirm()

    def prompt_reconfig(self):
        self._win.prompt_reconfig()

# by ASDcuber521
