from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QPushButton,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from ui.fx import GL_ENABLED, GlassCard, GlowButton, Toggle, fade_in
from ui.theme import C, DEFAULT_ACCENT, HOTKEY_DEFAULTS, HOTKEY_LABELS, hotkeys, patch_cfg, read_cfg, rgba
from ui.widgets import (
    HueSlider, IconButton, Segmented, divider, font, make_page, section_label, setting_row,
)

ACCENT_PRESETS = ("#3d9bff", "#6ee7ff", "#a78bfa", "#ff7ad9", "#5cffb0", "#ffc857", "#ff6b6b", "#f5f5f5")
def _read_app_version() -> str:
    try:
        from pathlib import Path as _P
        for candidate in (
            _P(__file__).resolve().parent.parent / "VERSION",
            _P(__file__).resolve().parent.parent / "version.txt",
        ):
            if candidate.exists():
                v = candidate.read_text(encoding="utf-8").strip()
                if v:
                    return v
    except Exception:
        pass
    return "0.0.0"


APP_VERSION = _read_app_version()


def _hdr(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    l = QVBoxLayout(w)
    l.setContentsMargins(0, 0, 0, 8)
    l.setSpacing(2)
    t = QLabel(text)
    t.setFont(font(20, QFont.Weight.Bold))
    l.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setStyleSheet(f"color: {C.TEXT_DIM};")
        l.addWidget(s)
    return w


def _safe(timer, fn) -> None:
    """Run a page's refresh; if its widgets were already deleted (page switched), just stop the timer."""
    try:
        fn()
    except RuntimeError:
        timer.stop()


class PluginForm(QWidget):
    _done = pyqtSignal(str, bool, str)

    def __init__(self, sections: list[dict], parent=None):
        super().__init__(parent)
        self._sections = sections
        self._w: dict = {}
        self._t: dict = {}
        self._status: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for sec in sections:
            self._build(lay, sec)
        save = GlowButton("Save plugin settings", "primary")
        save.clicked.connect(self._save_all)
        lay.addWidget(save)
        self._done.connect(self._on_done)

    def _build(self, lay: QVBoxLayout, sec: dict):
        ns = sec.get("namespace") or sec.get("plugin") or "plugin"
        t = QLabel(str(sec.get("title") or ns))
        t.setFont(font(11, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {C.ACC}; margin-top: 10px;")
        lay.addWidget(t)
        values = sec.get("values") or {}
        for f in sec.get("fields") or []:
            if not isinstance(f, dict) or not f.get("key"):
                continue
            key, ftype = f["key"], (f.get("type") or "text").lower()
            stored = values.get(key, f.get("default"))
            lbl = QLabel(str(f.get("label") or key))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            lay.addWidget(lbl)
            if ftype == "choice":
                w = QComboBox()
                w.addItems([str(o) for o in f.get("options", [])])
                if stored is not None:
                    w.setCurrentText(str(stored))
            elif ftype == "toggle":
                w = Toggle(bool(stored))
            else:
                w = QLineEdit("" if stored is None else str(stored))
                if f.get("placeholder"):
                    w.setPlaceholderText(str(f["placeholder"]))
                if ftype == "password":
                    w.setEchoMode(QLineEdit.EchoMode.Password)
            self._w[(ns, key)] = w
            self._t[(ns, key)] = ftype
            if ftype == "toggle":
                lay.addWidget(w, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                lay.addWidget(w)
        act = sec.get("action")
        if isinstance(act, dict) and callable(act.get("run")):
            b = GlowButton(str(act.get("label") or "Test"))
            b.clicked.connect(lambda _=False, n=ns: self._run(n))
            lay.addWidget(b)
        st = QLabel("")
        st.setWordWrap(True)
        self._status[ns] = st
        lay.addWidget(st)

    def _gather(self, ns: str) -> dict:
        out = {}
        for (n, k), w in self._w.items():
            if n != ns:
                continue
            t = self._t[(n, k)]
            out[k] = w.currentText() if t == "choice" else w.isChecked() if t == "toggle" else w.text().strip()
        return out

    def _save_ns(self, ns: str):
        from memory.config_manager import save_plugin_config
        save_plugin_config(ns, self._gather(ns))

    def _save_all(self):
        for s in self._sections:
            ns = s.get("namespace") or s.get("plugin")
            if ns:
                self._save_ns(ns)
                self._status[ns].setText("Saved ✓")
                self._status[ns].setStyleSheet(f"color: {C.GREEN};")

    def _run(self, ns: str):
        sec = next((s for s in self._sections if (s.get("namespace") or s.get("plugin")) == ns), None)
        fn = ((sec or {}).get("action") or {}).get("run")
        if not callable(fn):
            return
        self._save_ns(ns)
        vals = self._gather(ns)
        self._status[ns].setText("Testing…")

        def worker():
            try:
                res = fn(vals)
                ok, msg = (bool(res[0]), str(res[1])) if isinstance(res, tuple) and len(res) == 2 else (bool(res), str(res))
            except Exception as e:
                ok, msg = False, str(e)
            self._done.emit(ns, ok, msg)
        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, ns: str, ok: bool, msg: str):
        lb = self._status.get(ns)
        if lb:
            lb.setText(msg)
            lb.setStyleSheet(f"color: {C.GREEN if ok else C.RED};")


class SettingsPanel(GlassCard):
    PAGES = (("general", "General", "gear"), ("appearance", "Appearance", "cube"),
             ("voice", "Voice & AI", "mic"), ("gestures", "Gestures", "cube"), ("face", "Face ID", "cube"), ("plugins", "Plugins", "stats"),
             ("memory", "Memory", "chat"), ("about", "About", "home"))

    def __init__(self, win, parent=None):
        super().__init__(parent, radius=26, tint=190)
        self.win = win
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setFixedWidth(210)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 22, 12, 18)
        sl.setSpacing(4)
        t = QLabel("Settings")
        t.setFont(font(17, QFont.Weight.Bold))
        sl.addWidget(t)
        s = QLabel(f"{win.assistant_name} · {APP_VERSION}")
        s.setStyleSheet(f"color: {C.TEXT_DIM};")
        sl.addWidget(s)
        sl.addSpacing(14)
        self._nav: dict[str, QPushButton] = {}
        for key, label, _ic in self.PAGES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self._nav[key] = b
            sl.addWidget(b)
        sl.addStretch()
        sig = QLabel("by ASDcuber521")
        sig.setStyleSheet(f"color: {C.TEXT_DIM};")
        sl.addWidget(sig)
        close = GlowButton("Close", "ghost")
        close.clicked.connect(win.close_modal)
        sl.addWidget(close)
        root.addWidget(side)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {rgba('#ffffff', .08)};")
        root.addWidget(sep)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        self._pages: dict[str, QWidget] = {}
        self.show_page("general")

    def _style_nav(self, cur: str):
        for k, b in self._nav.items():
            on = k == cur
            b.setChecked(on)
            b.setStyleSheet(
                f"QPushButton {{ text-align: left; padding-left: 16px; border-radius: 12px; font-weight: 600;"
                f"color: {C.PRI if on else C.TEXT_MED};"
                f"background: {rgba(C.PRI, .14) if on else 'transparent'};"
                f"border: 1px solid {rgba(C.PRI, .35) if on else 'transparent'}; }}"
                f"QPushButton:hover {{ background: {rgba('#ffffff', .06)}; color: {C.TEXT}; }}")

    def show_page(self, key: str):
        self._style_nav(key)
        old = self._pages.pop(key, None)
        if old is not None:
            self._stack.removeWidget(old)
            old.deleteLater()
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(26, 22, 14, 14)
        sc, lay = make_page()
        getattr(self, f"_page_{key}")(lay)
        lay.addStretch()
        pl.addWidget(sc)
        self._pages[key] = page
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
        fade_in(page, 260)

    def _page_general(self, lay):
        w = self.win
        lay.addWidget(_hdr("General", "Identity, startup and window behaviour"))
        name = QLineEdit(w.assistant_name)
        user = QLineEdit(w.user_name)
        name.setFixedWidth(220)
        user.setFixedWidth(220)
        lay.addWidget(setting_row("Assistant name", "Shown in the header and used in conversation", name))
        lay.addWidget(setting_row("Your name", "How the assistant addresses you", user))
        save = GlowButton("Save names", "primary")
        save.clicked.connect(lambda: w.apply_names(name.text(), user.text()))
        lay.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(section_label("Startup"))
        at = Toggle(w.autostart_enabled())
        at.toggled.connect(w.set_autostart)
        lay.addWidget(setting_row("Launch at login", "Start automatically when you sign in", at))
        lay.addWidget(divider())
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        br = Toggle(bool(get_brief_enabled()))
        br.toggled.connect(save_brief_enabled)
        lay.addWidget(setting_row("Morning brief", "Greeting with weather and news on first start", br))
        lay.addWidget(section_label("Profile"))
        from memory.config_manager import get_active_profile_name, set_active_profile
        seg = Segmented([("home", "🏠 Home"), ("work", "💼 Work"), ("game", "🎮 Game")], get_active_profile_name())
        pl = QLabel(w.profile_summary(get_active_profile_name()))
        pl.setWordWrap(True)
        pl.setStyleSheet(f"color: {C.TEXT_DIM}; margin-top: 4px;")

        def pick(k):
            w.apply_profile(k)
            pl.setText(w.profile_summary(k))
        seg.changed.connect(pick)
        lay.addWidget(seg)
        lay.addWidget(pl)
        lay.addWidget(section_label("Window"))
        row = QHBoxLayout()
        for text, fn, closes in (("Fullscreen", w.toggle_fullscreen, True),
                                 ("Compact mode", w.enter_compact, True),
                                 ("Desktop shortcut", w.create_shortcut, False)):
            b = GlowButton(text)
            b.clicked.connect(lambda _=False, f=fn, c=closes: (w.close_modal() if c else None, f()))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    def _page_appearance(self, lay):
        w = self.win
        lay.addWidget(_hdr("Appearance", "Colours, 3D model and visual effects — applied instantly"))
        lay.addWidget(section_label("Accent colour"))
        hue = HueSlider(C.PRI)
        hex_in = QLineEdit(C.PRI)
        hex_in.setFixedWidth(110)
        hue.picked.connect(lambda hx: (hex_in.setText(hx), w.set_accent(hx, False)))
        hue.committed.connect(lambda hx: w.set_accent(hx, True))
        hex_in.editingFinished.connect(lambda: (w.set_accent(hex_in.text(), True), hue.set_color(hex_in.text())))
        top = QHBoxLayout()
        top.addWidget(hue, 1)
        top.addWidget(hex_in)
        lay.addLayout(top)
        sw = QHBoxLayout()
        sw.setSpacing(8)
        for c in ACCENT_PRESETS:
            b = QPushButton()
            b.setFixedSize(30, 30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: {c}; border-radius: 15px; border: 2px solid {rgba('#ffffff', .25)}; }}"
                            f"QPushButton:hover {{ border-color: #ffffff; }}")
            b.clicked.connect(lambda _=False, col=c: (w.set_accent(col, True), hex_in.setText(col), hue.set_color(col)))
            sw.addWidget(b)
        sw.addStretch()
        lay.addLayout(sw)
        lay.addWidget(section_label("3D model"))
        opts = [(m, m.title()) for m in w.stage.model_names()]
        seg = Segmented(opts, w.stage.model)
        seg.changed.connect(w.set_model)
        lay.addWidget(seg)
        hint = QLabel("Tip: drag the model to rotate it · double-click to switch")
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; margin-top: 4px;")
        lay.addWidget(hint)
        lay.addWidget(section_label("Performance"))
        q = Segmented([("auto", "Auto"), ("high", "High quality"), ("lite", "Lightweight")],
                      getattr(w.stage, "quality", "auto"))
        q.changed.connect(w.set_quality)
        lay.addWidget(setting_row("Rendering quality", "Auto drops detail when the PC is struggling", q))
        hw = Toggle(bool(read_cfg().get("hw_accel", True)))
        hw.toggled.connect(w.set_hw_accel)
        state = "active" if GL_ENABLED else "off"
        lay.addWidget(setting_row("GPU acceleration", f"Draws the 3D scene on the graphics card · now: {state} · restart to apply", hw))
        lay.addWidget(divider())
        gh = Toggle(bool(read_cfg().get("gpu_holo", True)))
        gh.toggled.connect(w.set_gpu_holo)
        lay.addWidget(setting_row("GPU hologram renderer", "Draws the Holo model with shaders on the graphics card (very low CPU). Switches itself off if unsupported.", gh))
        lay.addWidget(divider())
        sp = Toggle(bool(read_cfg().get("show_perf", False)))
        sp.toggled.connect(w.set_perf)
        lay.addWidget(setting_row("Show performance stats", "FPS and frame time under the command bar", sp))
        lay.addWidget(divider())
        lay.addWidget(section_label("Effects"))
        for key, title, sub, cur in (
            ("aurora", "Aurora background", "Soft animated colour glow behind everything", w.backdrop.aurora),
            ("stars", "Starfield", "Parallax stars drifting in the background", w.backdrop.stars),
            ("particles", "Orbiting particles", "Particle halo around the 3D model", w.stage.particles),
        ):
            t = Toggle(bool(cur))
            t.toggled.connect(lambda on, k=key: w.set_effect(k, on))
            lay.addWidget(setting_row(title, sub, t))
            lay.addWidget(divider())
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(4, 20)
        sl.setValue(int(w.stage.speed * 10))
        sl.setFixedWidth(200)
        sl.valueChanged.connect(lambda v: w.set_speed(v / 10))
        lay.addWidget(setting_row("Animation speed", "Rotation and background motion", sl))

    def _page_voice(self, lay):
        w = self.win
        from memory.config_manager import (
            AVAILABLE_VOICES, get_push_to_talk_enabled, get_voice, get_wake_word_enabled,
        )
        lay.addWidget(_hdr("Voice & AI", "How the assistant speaks and listens"))
        lay.addWidget(section_label("Voice"))
        seg = Segmented([(v, v) for v in AVAILABLE_VOICES], get_voice())
        seg.changed.connect(w.apply_voice)
        lay.addWidget(seg)
        lay.addWidget(section_label("Listening"))
        wk = Toggle(bool(get_wake_word_enabled()))
        wk.toggled.connect(lambda on: w.toggle_wake(on, wk))
        lay.addWidget(setting_row("Wake word", "Say “Hey Jarvis” to wake the assistant", wk))
        lay.addWidget(divider())
        pt = Toggle(bool(get_push_to_talk_enabled()))
        pt.toggled.connect(w.toggle_ptt)
        lay.addWidget(setting_row("Push-to-talk", "Hold Ctrl+Space to talk", pt))
        lay.addWidget(divider())
        tg = GlowButton("Toggle", "ghost")
        tg.clicked.connect(lambda: w.wake_manual())
        lay.addWidget(setting_row("Sleep / wake now", "Manually toggle the wake-word state", tg))
        lay.addWidget(section_label("Audio devices"))
        try:
            from core.audio_devices import DEFAULT_LABEL, list_devices
            from memory.config_manager import (
                get_input_device, get_output_device, save_input_device, save_output_device,
            )
            boxes = {}
            for kind, cur in (("input", get_input_device()), ("output", get_output_device())):
                cb = QComboBox()
                cb.setFixedWidth(260)
                cb.addItem(DEFAULT_LABEL, "")
                for n in list_devices(kind):
                    cb.addItem(n, n)
                i = cb.findData(cur) if cur else 0
                cb.setCurrentIndex(max(0, i))
                boxes[kind] = cb
                lay.addWidget(setting_row("Microphone" if kind == "input" else "Speaker", "", cb))

            def apply():
                save_input_device(boxes["input"].currentData() or "")
                save_output_device(boxes["output"].currentData() or "")
                if w.on_audio_device_change:
                    w.on_audio_device_change()
                w.write_log("SYS: Audio devices updated.")
            b = GlowButton("Apply devices", "primary")
            b.clicked.connect(apply)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        except Exception as e:
            lay.addWidget(QLabel(f"Audio devices unavailable: {e}"))

    def _page_gestures(self, lay):
        from core import gesture
        w = self.win
        lay.addWidget(_hdr("Hand gestures", "Control Jarvis and your PC by showing a hand to the camera"))
        on = Toggle(gesture.is_enabled())
        lay.addWidget(setting_row("Enable gesture control",
                                  "Uses your webcam while on. Everything is processed on this computer; nothing is recorded or sent.", on))
        status = QLabel("")
        status.setWordWrap(True)
        status.setStyleSheet(f"color: {C.TEXT_DIM};")
        live = QLabel("")
        live.setStyleSheet(f"color: {C.PRI}; font-weight: 600;")
        lay.addWidget(status)
        lay.addWidget(live)

        def refresh():
            st = getattr(w, "gesture_status", "off")
            status.setText(f"Camera: {st}" if gesture.is_enabled() else "Camera: off")
            g = getattr(getattr(w, "camera", None), "current_gesture", None)
            live.setText(f"Seeing: {gesture.GESTURES[g][0]}" if g in gesture.GESTURES else "")

        def toggled(v):
            w.set_gestures_enabled(v)
            QTimer.singleShot(400, refresh)
            for cb in boxes.values():
                cb.setEnabled(v)
        on.toggled.connect(toggled)

        lay.addWidget(section_label("What each gesture does"))
        hint = QLabel("Choose “Nothing” to disable a gesture.")
        hint.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(hint)
        spd = Segmented([(k, v) for k, v in gesture.SPEED_LABELS.items()], gesture.get_speed())
        spd.changed.connect(gesture.set_speed)
        lay.addWidget(setting_row("Response speed", "Fast reacts after ~0.3 s but may misfire; Careful waits ~0.7 s", spd))
        boxes = {}
        current = gesture.get_map()
        for gid, (label, _default) in gesture.GESTURES.items():
            cb = QComboBox()
            cb.setFixedWidth(240)
            for aid, alabel in gesture.ACTIONS.items():
                cb.addItem(alabel, aid)
            cb.setCurrentIndex(max(0, cb.findData(current[gid])))
            cb.setEnabled(gesture.is_enabled())
            cb.currentIndexChanged.connect(lambda _i, g=gid, c=cb: gesture.set_mapping(g, c.currentData()))
            boxes[gid] = cb
            lay.addWidget(setting_row(label, "", cb))
            lay.addWidget(divider())
        reset = GlowButton("Reset to defaults", "ghost")

        def do_reset():
            for gid, (_l, d) in gesture.GESTURES.items():
                gesture.set_mapping(gid, d)
                boxes[gid].setCurrentIndex(max(0, boxes[gid].findData(d)))
        reset.clicked.connect(do_reset)
        lay.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)

        lay.addWidget(section_label("Camera"))
        cam = QComboBox()
        cam.setFixedWidth(160)
        for i in range(4):
            cam.addItem(f"Camera {i}", i)
        cam.setCurrentIndex(max(0, cam.findData(gesture.get_camera())))

        def cam_changed(_i):
            gesture.set_camera(cam.currentData())
            if gesture.is_enabled():
                w.set_gestures_enabled(False)
                QTimer.singleShot(1200, lambda: w.set_gestures_enabled(True))
        cam.currentIndexChanged.connect(cam_changed)
        lay.addWidget(setting_row("Camera", "Pick another one if the wrong camera opens", cam))

        timer = QTimer(status)          # lives and dies with this page's widgets
        timer.timeout.connect(lambda: _safe(timer, refresh))
        timer.start(500)
        refresh()

    def _page_face(self, lay):
        from core import face_id
        w = self.win
        lay.addWidget(_hdr("Face ID", "Let Jarvis recognise the people it sees through the camera"))
        on = Toggle(face_id.is_enabled())
        lay.addWidget(setting_row("Enable face recognition",
                                  "Uses your webcam while on. Only numeric face fingerprints are stored on this PC — no photos, nothing uploaded. "
                                  "The first start downloads ~37 MB of models.", on))
        status = QLabel("")
        status.setWordWrap(True)
        status.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(status)
        seeing = QLabel("")
        seeing.setStyleSheet(f"color: {C.PRI}; font-weight: 600;")
        lay.addWidget(seeing)

        lay.addWidget(section_label("Behaviour"))
        gr = Toggle(face_id.greet_enabled())
        gr.toggled.connect(face_id.set_greet)
        lay.addWidget(setting_row("Greet by voice", "Jarvis says hello when a saved person shows up", gr))
        lay.addWidget(divider())
        al = Toggle(face_id.alert_unknown())
        al.toggled.connect(face_id.set_alert_unknown)
        lay.addWidget(setting_row("Alert on unknown faces", "Show a warning when someone not saved is at the camera", al))

        lay.addWidget(section_label("Saved people"))
        people_box = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(people_box)
        lay.addWidget(holder)

        def render():
            while people_box.count():
                it = people_box.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            n = face_id.names()
            if not n:
                e = QLabel("Nobody saved yet.")
                e.setStyleSheet(f"color: {C.TEXT_DIM};")
                people_box.addWidget(e)
            for name in n:
                rm = GlowButton("Remove", "ghost")
                rm.clicked.connect(lambda _=False, nm=name: (face_id.forget(nm), render()))
                people_box.addWidget(setting_row(f"👤 {name}", "", rm))

        add_row = QHBoxLayout()
        nm = QLineEdit()
        nm.setPlaceholderText("Name, e.g. Akmal")
        nm.setFixedWidth(220)
        add = GlowButton("Add my face", "primary")

        def do_add():
            msg = w.enroll_face(nm.text())
            status.setText(msg)
            nm.clear()
        add.clicked.connect(do_add)
        add_row.addWidget(nm)
        add_row.addWidget(add)
        add_row.addStretch()
        lay.addLayout(add_row)
        tip = QLabel("Face the camera in good light for a few seconds. Add the same person twice (with and without glasses) for better accuracy.")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {C.TEXT_DIM}; margin-top: 6px;")
        lay.addWidget(tip)
        wipe = GlowButton("Delete all saved faces", "ghost")
        wipe.clicked.connect(lambda: (face_id.forget_all(), render()))
        lay.addWidget(wipe, 0, Qt.AlignmentFlag.AlignLeft)
        render()

        def toggled(v):
            w.set_face_enabled(v)
            QTimer.singleShot(500, refresh)
        on.toggled.connect(toggled)

        def refresh():
            cam = getattr(w, "camera", None)
            st = getattr(w, "gesture_status", "off")
            status.setText(f"Camera: {st}" if face_id.is_enabled() else (status.text() if "Look" in status.text() else "Camera: off"))
            vis = getattr(cam, "visible", []) if cam is not None and face_id.is_enabled() else []
            seeing.setText("Seeing: " + ", ".join(vis).replace("unknown", "unknown face") if vis else "")
        timer = QTimer(status)          # lives and dies with this page's widgets
        timer.timeout.connect(lambda: _safe(timer, refresh))
        timer.timeout.connect(lambda: _safe(timer, lambda: render() if len(face_id.names()) != people_box.count() and face_id.names() else None))
        timer.start(700)
        refresh()

    def _page_plugins(self, lay):
        w = self.win
        lay.addWidget(_hdr("Plugins", "Enable or disable extensions and configure them"))
        try:
            from memory.config_manager import save_plugin_enabled
            plugins = w.get_plugins() if w.get_plugins else []
        except Exception:
            plugins = []
        if not plugins:
            lay.addWidget(QLabel("No plugins found."))
        for p in plugins:
            t = Toggle(bool(p.get("enabled")))
            t.setEnabled(bool(p.get("valid", True)))
            t.toggled.connect(lambda on, n=p["name"]: save_plugin_enabled(n, on))
            sub = p.get("description") or ""
            if not p.get("valid", True):
                sub = f"⚠ {p.get('error') or 'invalid plugin'}"
            lay.addWidget(setting_row(p["name"], sub, t))
            lay.addWidget(divider())
        row = QHBoxLayout()
        st = GlowButton("Open plugin store", "primary")
        st.clicked.connect(w.open_store)
        row.addWidget(st)
        row.addStretch()
        lay.addSpacing(8)
        lay.addLayout(row)
        try:
            secs = w.get_plugin_settings() if w.get_plugin_settings else []
        except Exception:
            secs = []
        if secs:
            lay.addWidget(section_label("Plugin settings"))
            lay.addWidget(PluginForm(secs))

    def _page_memory(self, lay):
        w = self.win
        lay.addWidget(_hdr("Memory", "Everything the assistant remembers about you — stored locally"))
        try:
            from memory.memory_manager import all_entries_for_ui, forget
            rows = all_entries_for_ui()
        except Exception as e:
            lay.addWidget(QLabel(f"Memory unavailable: {e}"))
            return
        if not rows:
            lay.addWidget(QLabel("Nothing remembered yet."))
        for r in rows:
            fb = GlowButton("Forget", "ghost")
            fb.setMinimumHeight(30)

            def go(_=False, c=r["category"], k=r["key"]):
                forget(k, c)
                self.show_page("memory")
            fb.clicked.connect(go)
            lay.addWidget(setting_row(f"{r['key'].replace('_', ' ')}  ·  {r['category']}", str(r["value"]), fb))
            lay.addWidget(divider())

    def _page_about(self, lay):
        w = self.win
        lay.addWidget(_hdr(f"{w.assistant_name}", f"{APP_VERSION}  ·  by ASDcuber521"))
        try:
            from core.updater import get_local_version
            ver = get_local_version()
        except Exception:
            ver = "—"
        lay.addWidget(setting_row("Version", f"Installed: {ver}", None))
        au = Toggle(bool(read_cfg().get("auto_update_check", True)))
        au.toggled.connect(lambda on: __import__("ui.theme", fromlist=["patch_cfg"]).patch_cfg(auto_update_check=on))
        lay.addWidget(setting_row("Check for updates automatically", "Looks for a new version once every 12 hours", au))
        up = GlowButton("Check for updates", "primary")
        up.clicked.connect(w.check_updates)
        lay.addWidget(up, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(section_label("Connect"))
        rc = GlowButton("Remote control (phone)", "ghost")
        rc.clicked.connect(lambda: (w.close_modal(), QTimer.singleShot(330, w.open_remote)))
        lay.addWidget(rc, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(section_label("Shortcuts"))
        note = QLabel("Click a box and press the keys you want. Works while the Jarvis window has focus.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(note)
        editors: dict = {}

        def save_hotkey(action: str):
            ed = editors[action]
            seq = ed.keySequence().toString()
            current = hotkeys()
            if not seq:
                seq = HOTKEY_DEFAULTS[action]
            clash = [HOTKEY_LABELS[a] for a, v in current.items() if a != action and v == seq]
            if clash:
                w.write_log(f"SYS: {seq} is already used for {clash[0]}.")
                ed.setKeySequence(QKeySequence(current[action]))
                return
            current[action] = seq
            patch_cfg(hotkeys=current)
            ed.setKeySequence(QKeySequence(seq))
            ed.clearFocus()
            w.reload_hotkeys()

        for action, label in HOTKEY_LABELS.items():
            ed = QKeySequenceEdit(QKeySequence(hotkeys()[action]))
            ed.setMaximumSequenceLength(1)
            ed.setFixedWidth(150)
            ed.editingFinished.connect(lambda a=action: save_hotkey(a))
            editors[action] = ed
            lay.addWidget(setting_row(label, "", ed))
        rs = GlowButton("Reset shortcuts", "ghost")

        def reset_hotkeys():
            patch_cfg(hotkeys=dict(HOTKEY_DEFAULTS))
            for a, ed in editors.items():
                ed.setKeySequence(QKeySequence(HOTKEY_DEFAULTS[a]))
            w.reload_hotkeys()
        rs.clicked.connect(reset_hotkeys)
        lay.addWidget(rs, 0, Qt.AlignmentFlag.AlignLeft)
        for k, d in (("Ctrl+Space", "Push-to-talk (hold)"), ("Esc", "Close panel / exit fullscreen")):
            lay.addWidget(setting_row(k, d, None))


class SetupPanel(GlassCard):
    done = pyqtSignal(str, str)

    def __init__(self, os_key: str, parent=None):
        super().__init__(parent, radius=26, tint=200, accent=C.PRI)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(34, 30, 34, 28)
        lay.setSpacing(10)
        t = QLabel("Welcome")
        t.setFont(font(24, QFont.Weight.Bold))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = QLabel("Enter your Gemini API key to bring the assistant online.")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {C.TEXT_MED};")
        lay.addWidget(s)
        lay.addSpacing(8)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Gemini API key")
        self.key.setMinimumHeight(44)
        lay.addWidget(self.key)
        self.seg = Segmented([("windows", "Windows"), ("mac", "macOS"), ("linux", "Linux")], os_key)
        lay.addWidget(self.seg, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(6)
        go = GlowButton("Connect", "primary")
        go.setMinimumHeight(44)
        go.clicked.connect(self._go)
        self.key.returnPressed.connect(self._go)
        lay.addWidget(go)
        lay.addStretch()
        by = QLabel("by ASDcuber521")
        by.setAlignment(Qt.AlignmentFlag.AlignCenter)
        by.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(by)

    def _go(self):
        k = self.key.text().strip()
        if not k:
            self.key.setStyleSheet(f"border: 1px solid {C.RED};")
            return
        self.done.emit(k, self.seg.current())


class ConfirmPanel(GlassCard):
    answered = pyqtSignal(bool)

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent, radius=24, tint=210, accent=C.AMBER)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(8)
        h = QLabel("⚠  Confirm action")
        h.setFont(font(10, QFont.Weight.Bold))
        h.setStyleSheet(f"color: {C.AMBER};")
        lay.addWidget(h)
        t = QLabel(title)
        t.setFont(font(14, QFont.Weight.Bold))
        t.setWordWrap(True)
        lay.addWidget(t)
        if detail:
            d = QLabel(detail)
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {C.TEXT_MED};")
            lay.addWidget(d)
        lay.addStretch()
        row = QHBoxLayout()
        no = GlowButton("Cancel", "ghost")
        yes = GlowButton("Confirm", "danger")
        no.clicked.connect(lambda: self.answered.emit(False))
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)


class RemotePanel(GlassCard):

    def __init__(self, info: tuple, refresh, parent=None):
        super().__init__(parent, radius=26, tint=200, accent=C.PRI)
        self._refresh = refresh
        self._expiry = time.time() + 600
        self._auto = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 24)
        lay.setSpacing(8)
        t = QLabel("Remote control")
        t.setFont(font(18, QFont.Weight.Bold))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = QLabel("Scan with your phone to control this PC")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(s)
        self.qr = QLabel()
        self.qr.setFixedSize(190, 190)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setStyleSheet("background: white; border-radius: 14px;")
        lay.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignCenter)
        self.url = QLabel()
        self.url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url.setStyleSheet(f"color: {C.PRI};")
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.url)
        self.secure = QLabel()
        self.secure.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.secure.setWordWrap(True)
        self.secure.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.secure.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 9px;")
        lay.addWidget(self.secure)
        self.key = QLabel()
        self.key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key.setFont(font(20, QFont.Weight.Bold))
        self.key.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.key)
        self.timer = QLabel()
        self.timer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(self.timer)
        lay.addStretch()
        row = QHBoxLayout()
        cp = GlowButton("Copy key", "ghost")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.key.text()))
        nk = GlowButton("New key", "primary")
        nk.clicked.connect(self._new)
        row.addWidget(cp)
        row.addWidget(nk)
        lay.addLayout(row)
        self._apply(info)
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(1000)

    def _apply(self, info):
        url, key, auto, manual, fingerprint = (list(info) + ["", "", "", "", ""])[:5]
        self.url.setText(manual or url)
        if str(manual or url).startswith("https://"):
            self.secure.setText("🔒 Encrypted (HTTPS). Your phone will pin this certificate on first pairing."
                                + (f"\nSHA-256  {fingerprint}" if fingerprint else ""))
        else:
            self.secure.setText("⚠ Plain HTTP — set JARVIS_TLS=1 for an encrypted link.")
        self.key.setText(str(key))
        self._expiry = time.time() + 600
        self._qr(auto or url)

    def _qr(self, data: str):
        try:
            import qrcode
            from io import BytesIO
            q = qrcode.QRCode(box_size=5, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            q.add_data(data)
            q.make(fit=True)
            buf = BytesIO()
            q.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self.qr.setPixmap(px.scaled(176, 176, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        except Exception:
            self.qr.setText("pip install\nqrcode[pil]")

    def _new(self):
        try:
            r = self._refresh()
            if r:
                self._apply(r)
        except Exception:
            pass

    def _tick(self):
        left = max(0, int(self._expiry - time.time()))
        self.timer.setText(f"Key expires in {left // 60}:{left % 60:02d}")

# by ASDcuber521
