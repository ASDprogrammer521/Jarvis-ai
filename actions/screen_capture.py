from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from pathlib import Path

from actions._common import cfg, clip_write, human_size, log, open_path

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
_REC: dict = {"stop": None, "path": None, "frames": 0, "thread": None, "started": 0.0, "error": ""}


def _folder(kind: str) -> Path:
    base = Path.home() / ("Pictures" if kind == "shots" else "Videos") / "Jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _grab(region=None, monitor: int = 1):
    from PIL import Image
    try:
        import mss
        with mss.mss() as s:
            mons = s.monitors
            mon = mons[0] if monitor == 0 else mons[min(max(1, monitor), len(mons) - 1)]
            if region:
                x, y, w, h = region
                mon = {"left": mon["left"] + x, "top": mon["top"] + y, "width": w, "height": h}
            shot = s.grab(mon)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except ImportError:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=(monitor == 0))
        return img.crop((region[0], region[1], region[0] + region[2], region[1] + region[3])) if region else img


def _clip_image(path: Path) -> bool:
    try:
        if _OS == "Windows":
            cmd = ["powershell", "-NoProfile", "-STA", "-Command",
                   f"Add-Type -AssemblyName System.Windows.Forms,System.Drawing; [System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{path}'))"]
        elif _OS == "Darwin":
            cmd = ["osascript", "-e", f'set the clipboard to (read (POSIX file "{path}") as «class PNGf»)']
        else:
            cmd = ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(path)]
        return subprocess.run(cmd, capture_output=True, timeout=10, **_HIDE).returncode == 0
    except Exception:
        return False


def _region(text) -> tuple | None:
    try:
        x, y, w, h = [int(float(v)) for v in str(text).replace(";", ",").split(",")]
        return (x, y, w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def screenshot(p: dict, player) -> str:
    delay = max(0.0, min(30.0, float(p.get("delay") or 0)))
    mon = 0 if str(p.get("monitor") or "").lower() in ("all", "0") else int(p.get("monitor") or 1)
    if p.get("hide_jarvis", True) and hasattr(player, "_win"):
        try:
            player._win.showMinimized()
            delay = max(delay, 0.6)
        except Exception:
            pass
    time.sleep(delay)
    try:
        img = _grab(_region(p.get("region")), mon)
    finally:
        if hasattr(player, "_win"):
            try:
                player._win.showNormal()
            except Exception:
                pass
    path = _folder("shots") / time.strftime("screenshot_%Y%m%d_%H%M%S.png")
    img.save(str(path))
    copied = _clip_image(path) if p.get("copy", True) else False
    if p.get("open"):
        open_path(path)
    return f"Screenshot saved ({img.width}×{img.height}){' and copied to the clipboard' if copied else ''}: {path}"


def _record_loop(seconds: float, fps: int, monitor: int, path: Path) -> None:
    import cv2
    import numpy as np
    stop = _REC["stop"]
    writer = None
    try:
        t0 = time.time()
        step = 1.0 / fps
        nxt = t0
        while not stop.is_set() and time.time() - t0 < seconds:
            frame = np.array(_grab(None, monitor))
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            _REC["frames"] += 1
            nxt += step
            time.sleep(max(0.0, nxt - time.time()))
    except Exception as e:
        _REC["error"] = str(e)
    finally:
        if writer is not None:
            writer.release()


def record_start(p: dict) -> str:
    if _REC["thread"] is not None and _REC["thread"].is_alive():
        return "A screen recording is already running, sir."
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return "Sir, I need OpenCV for recording: pip install opencv-python"
    seconds = max(3.0, min(900.0, float(p.get("seconds") or 120)))
    fps = max(5, min(30, int(p.get("fps") or 12)))
    mon = int(p.get("monitor") or 1)
    path = _folder("rec") / time.strftime("recording_%Y%m%d_%H%M%S.mp4")
    _REC.update(stop=threading.Event(), path=path, frames=0, started=time.time(), error="")
    t = threading.Thread(target=_record_loop, args=(seconds, fps, mon, path), daemon=True, name="screen-recorder")
    _REC["thread"] = t
    t.start()
    return f"Recording the screen, sir (up to {seconds:.0f} s). Say 'stop recording' when you're done."


def record_stop(p: dict) -> str:
    t = _REC["thread"]
    if t is None:
        return "No recording is running, sir."
    _REC["stop"].set()
    t.join(timeout=8)
    path = _REC["path"]
    if _REC["error"]:
        return f"The recording failed: {_REC['error']}"
    if path and Path(path).exists() and _REC["frames"]:
        secs = time.time() - _REC["started"]
        if p.get("open"):
            open_path(path)
        return f"Recording saved ({secs:.0f} s, {human_size(Path(path).stat().st_size)}): {path}"
    return "The recording was empty, sir."


def ocr(p: dict) -> str:
    try:
        import pytesseract
    except ImportError:
        return "Sir, I need OCR: pip install pytesseract (and install the Tesseract program)."
    custom = cfg().get("tesseract_path")
    if custom:
        pytesseract.pytesseract.tesseract_cmd = custom
    from PIL import Image
    src = str(p.get("path") or "").strip().strip('"')
    img = Image.open(src) if src and os.path.exists(src) else _grab(_region(p.get("region")), int(p.get("monitor") or 1))
    try:
        text = pytesseract.image_to_string(img, lang=str(p.get("language") or "eng")).strip()
    except Exception as e:
        return f"OCR failed: {e}"
    if not text:
        return "I couldn't find any text on the screen, sir."
    try:
        clip_write(text)
        tail = " (copied to your clipboard)"
    except Exception:
        tail = ""
    return f"Read {len(text)} characters{tail}:\n{text[:1200]}"


def screen_capture(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "screenshot").lower().strip()
    try:
        if action in ("screenshot", "capture", "shot"):
            return screenshot(p, player)
        if action in ("record", "record_start", "start_recording"):
            return record_start(p)
        if action in ("record_stop", "stop", "stop_recording"):
            return record_stop(p)
        if action in ("ocr", "read_text", "read_screen"):
            return ocr(p)
        if action == "list":
            files = sorted(_folder("shots").glob("*.png"))[-8:]
            return "Recent screenshots:\n" + "\n".join(f"• {f.name}" for f in reversed(files)) if files else "No screenshots yet, sir."
    except ImportError as e:
        return f"Sir, I need the '{e.name}' package: pip install {e.name}"
    except Exception as e:
        return f"Screen capture failed: {e}"
    return "Unknown action. Available: screenshot, record, stop, ocr, list."


TOOL = {
    "name": "screen_capture",
    "description": (
        "Takes screenshots (full screen, one monitor or a region, optional delay, copied to the clipboard), records "
        "the screen to an MP4 video (start / stop), and reads text from the screen or an image with OCR "
        "(copied to the clipboard). Use for 'take a screenshot', 'record my screen', 'read the text on my screen'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "screenshot | record | stop | ocr | list"},
            "delay": {"type": "NUMBER", "description": "Seconds to wait before the screenshot"},
            "monitor": {"type": "STRING", "description": "Monitor number (1 = main) or 'all'"},
            "region": {"type": "STRING", "description": "x,y,width,height of the area to capture"},
            "seconds": {"type": "NUMBER", "description": "Maximum recording length (default 120)"},
            "path": {"type": "STRING", "description": "Image file to OCR instead of the screen"},
            "language": {"type": "STRING", "description": "OCR language, e.g. eng, rus"},
            "open": {"type": "BOOLEAN", "description": "Open the result when done"},
        },
    },
    "handler": screen_capture,
}

# by ASDcuber521
