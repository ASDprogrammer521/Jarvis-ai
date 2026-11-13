"""Real in-game FPS for the Game HUD, measured with Intel's PresentMon (free, open source).

An overlay cannot see another program's frame rate by itself — only the graphics stack knows it. PresentMon listens to
the Windows present events (ETW) and prints one CSV line per frame; this wrapper reads those lines and reports the
frame rate of whichever program is in the foreground. Nothing is injected into the game, so anti-cheat is not involved.

Setup: download PresentMon (console) from https://github.com/GameTechDev/PresentMon/releases and put the .exe in the
`tools/` folder (or set `presentmon_path` in config/api_keys.json). It needs Administrator rights or membership of the
"Performance Log Users" group.
"""
from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from core.common_utils import project_root

WINDOW = 1.0                      # seconds of frames the FPS figure averages over
_FLAG_SETS = (                    # PresentMon 2.x, then 1.x spellings — the first one the program accepts wins
    ["--output_stdout", "--stop_existing_session", "--no_console_stats"],
    ["--output_stdout", "--stop_existing_session"],
    ["-output_stdout", "-stop_existing_session", "-no_top"],
    ["-output_stdout", "-stop_existing_session"],
)


def find_exe() -> str | None:
    try:
        from memory.config_manager import load_api_keys
        custom = load_api_keys().get("presentmon_path")
    except Exception:
        custom = None
    if custom and Path(custom).is_file():
        return str(custom)
    tools = project_root() / "tools"
    for p in sorted(tools.glob("PresentMon*.exe")) if tools.is_dir() else []:
        return str(p)
    return shutil.which("PresentMon") or shutil.which("PresentMon.exe")


def foreground_exe() -> str:
    """Lower-case executable name of the foreground window ('' when unknown)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        import psutil
        u32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


class FpsMeter:
    def __init__(self, exe: str | None = None, fg=foreground_exe):
        self.exe = exe or find_exe()
        self._fg = fg
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._frames: dict[str, deque] = {}          # app → deque[(arrival time, ms between presents)]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._fg_name, self._fg_at = "", 0.0
        self.state = "idle"                          # idle | missing | starting | running | error: …

    @property
    def available(self) -> bool:
        return bool(self.exe)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self.exe:
            self.state = "missing"
            return
        self._stop.clear()
        self.state = "starting"
        self._thread = threading.Thread(target=self._run, daemon=True, name="fps-meter")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        self.state = "idle" if self.exe else "missing"

    def _spawn(self) -> subprocess.Popen | None:
        for flags in _FLAG_SETS:
            try:
                p = subprocess.Popen([self.exe, *flags], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     bufsize=1, creationflags=0x08000000 if sys.platform == "win32" else 0)
            except OSError as e:
                self.state = f"error: {e}"
                return None
            t0 = time.time()
            while time.time() - t0 < 1.5 and p.poll() is None:
                time.sleep(0.05)
            if p.poll() is None:                     # still alive after 1.5 s → it accepted the flags
                return p
        self.state = "error: PresentMon did not start (run as Administrator?)"
        return None

    def _run(self) -> None:
        p = self._proc = self._spawn()
        if p is None:
            return
        self.state = "running"
        cols: dict[str, int] | None = None
        try:
            for line in p.stdout:
                if self._stop.is_set():
                    break
                row = next(csv.reader([line.strip()]), [])
                if not row:
                    continue
                if cols is None:
                    if "Application" in row:
                        cols = {n: i for i, n in enumerate(row)}
                    continue
                try:
                    app = row[cols["Application"]].lower()
                    ms = float(row[cols["msBetweenPresents"] if "msBetweenPresents" in cols else cols["FrameTime"]])
                except (KeyError, IndexError, ValueError):
                    continue
                now = time.monotonic()
                with self._lock:
                    q = self._frames.setdefault(app, deque(maxlen=1200))
                    q.append((now, ms))
        finally:
            if p.poll() is None:
                p.terminate()
            if not self._stop.is_set() and not self.state.startswith("error"):
                self.state = "error: PresentMon stopped"

    def read(self) -> dict | None:
        """{'fps', 'ms', 'app'} for the foreground program, or None when nothing was presented in the last second."""
        now = time.monotonic()
        if now - self._fg_at > 0.5:
            self._fg_name, self._fg_at = self._fg(), now
        with self._lock:
            if self._fg_name and self._fg_name in self._frames:
                app = self._fg_name
            elif not self._fg_name:                  # foreground unknown (non-Windows / test): busiest app wins
                recent = {a: sum(1 for t, _ in q if now - t <= WINDOW) for a, q in self._frames.items()}
                app = max(recent, key=recent.get) if recent else ""
            else:
                return None
            recent = [ms for t, ms in self._frames.get(app, ()) if now - t <= WINDOW]
        if len(recent) < 2:
            return None
        return {"fps": len(recent) / WINDOW, "ms": sum(recent) / len(recent), "app": app}
