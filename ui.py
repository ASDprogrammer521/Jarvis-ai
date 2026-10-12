from __future__ import annotations
"""
TEMPORARY STUB — full UI is in the v3.1.0 release artifacts.
Replace this file with the complete ui.py from:
  https://github.com/ASDprogrammer521/Jarvis-ai (upload Jarvis-ui-v3.1.0.zip contents)
or the conversation download.
"""
import sys
from pathlib import Path

# Prefer a full ui.py next to this file named ui_full.py if user drops it there
_full = Path(__file__).resolve().parent / "ui_full.py"
if _full.is_file():
    import runpy
    _ns = runpy.run_path(str(_full), run_name="ui")
    globals().update({k: v for k, v in _ns.items() if not k.startswith("__")})
else:
    # Minimal stub so import does not crash hard — shows clear error in UI
    from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
    from PyQt6.QtCore import Qt

    class MainWindow(QMainWindow):
        def __init__(self, face_path=None):
            super().__init__()
            self.setWindowTitle("JARVIS — UI missing")
            self.setMinimumSize(640, 400)
            w = QWidget()
            lay = QVBoxLayout(w)
            lbl = QLabel(
                "Full ui.py not installed.\n\n"
                "1. Download Jarvis-ui-v3.1.0.zip\n"
                "2. Replace ui.py with the file inside\n"
                "3. Or save it as ui_full.py next to this stub\n\n"
                "Version target: 3.1.0"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #e8f4ff; background: #0b0e14; font-size: 14px;")
            lay.addWidget(lbl)
            self.setCentralWidget(w)
            self.muted = False
            self.on_push_to_talk = None
            self.ptt_hold = None
            self.on_text_command = None
            self.on_remote_clicked = None
            self.on_interrupt = None
            self.on_voice_change = None
            self.on_audio_device_change = None
            self.get_plugins = None
            self.get_plugin_settings = None
            self.request_say = None
            self.wake_is_ready = None
            self.wake_get_state = None
            self.on_wake_toggle = None
            self.on_wake_manual = None
            self.on_wake_install = None

        def write_log(self, msg: str) -> None:
            print(msg)

        def set_state(self, state: str) -> None:
            pass

        def start_camera_stream(self) -> None:
            pass

        def stop_camera_stream(self) -> None:
            pass

    class JarvisUI:
        def __init__(self, face_path=None):
            self._win = MainWindow(face_path)

        def __getattr__(self, name):
            return getattr(self._win, name)

        def show(self):
            self._win.show()

        @property
        def muted(self):
            return self._win.muted

        @muted.setter
        def muted(self, v):
            self._win.muted = v
