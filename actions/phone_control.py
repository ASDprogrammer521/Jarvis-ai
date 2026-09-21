"""
Phone control via ADB (Android Debug Bridge).

Requires:
  1. Android phone with USB debugging enabled (or wireless ADB)
  2. `adb` available on PATH

Actions: status, unlock, lock, home, back, open_app, tap, swipe,
         type_text, volume, screenshot, battery, list_devices.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


def _adb_available() -> bool:
    return shutil.which("adb") is not None


def _run_adb(args: list[str], timeout: float = 12.0) -> tuple[bool, str]:
    if not _adb_available():
        return False, (
            "ADB not found. Install Android platform-tools and enable "
            "USB debugging on the phone, then reconnect."
        )
    try:
        r = subprocess.run(
            ["adb"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            **({"creationflags": 0x08000000} if __import__("platform").system() == "Windows" else {}),
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            return False, err or out or f"adb exit {r.returncode}"
        return True, out
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out."
    except Exception as e:
        return False, str(e)


def _devices() -> list[str]:
    ok, out = _run_adb(["devices"])
    if not ok:
        return []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    ids = []
    for ln in lines[1:]:  # skip header
        parts = ln.split()
        if len(parts) >= 2 and parts[1] == "device":
            ids.append(parts[0])
    return ids


def phone_control(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters or {}).get("action", "").strip().lower()
    value  = (parameters or {}).get("value", "") or ""
    value  = str(value).strip()

    if not action:
        return "No phone action specified."

    if player:
        try:
            player.write_log(f"[phone] {action} {value}".strip())
        except Exception:
            pass

    # Always allow status / list without a connected device check first
    if action in ("status", "list", "list_devices", "devices"):
        if not _adb_available():
            return (
                "ADB is not available. Prefer the reverse Jarvis App: "
                "open http://<PC-IP>:8000/jarvis-app on the phone, enter the "
                "pairing key from Dashboard, and connect. Same Wi-Fi required. "
                "Optional: install platform-tools for direct ADB control."
            )
        devs = _devices()
        if not devs:
            return (
                "No phone connected. Plug in via USB (USB debugging ON) "
                "or pair with wireless ADB, then say 'phone status' again."
            )
        return f"Connected phone(s): {', '.join(devs)}. Ready for commands."

    # For all other actions we need at least one device
    devs = _devices()
    if not devs:
        return (
            "No Android phone detected. Enable USB debugging, connect the "
            "phone (or use wireless ADB), then retry."
        )

    if action in ("unlock", "wake"):
        # Wake screen then swipe up (common unlock gesture; PIN not automated)
        _run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        time.sleep(0.3)
        ok, _ = _run_adb(["shell", "input", "keyevent", "KEYCODE_MENU"])
        if not ok:
            _run_adb(["shell", "input", "swipe", "300", "1000", "300", "300"])
        return "Phone screen woken / unlock gesture sent."

    if action in ("lock", "sleep"):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_POWER"])
        return "Phone locked." if ok else f"Could not lock phone: {msg}"

    if action in ("home",):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_HOME"])
        return "Went to Home screen." if ok else f"Home failed: {msg}"

    if action in ("back",):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_BACK"])
        return "Back pressed." if ok else f"Back failed: {msg}"

    if action in ("recent", "recents", "overview"):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_APP_SWITCH"])
        return "Opened recent apps." if ok else f"Recents failed: {msg}"

    if action in ("open", "open_app", "launch"):
        if not value:
            return "Tell me which app to open (e.g. WhatsApp, Chrome, Settings)."
        # Prefer monkey launcher by package alias map
        aliases = {
            "whatsapp": "com.whatsapp",
            "telegram": "org.telegram.messenger",
            "chrome": "com.android.chrome",
            "youtube": "com.google.android.youtube",
            "instagram": "com.instagram.android",
            "settings": "com.android.settings",
            "camera": "com.android.camera",
            "gallery": "com.google.android.apps.photos",
            "maps": "com.google.android.apps.maps",
            "gmail": "com.google.android.gm",
            "spotify": "com.spotify.music",
            "tiktok": "com.zhiliaoapp.musically",
            "discord": "com.discord",
            "phone": "com.android.dialer",
            "messages": "com.google.android.apps.messaging",
            "clock": "com.google.android.deskclock",
        }
        pkg = aliases.get(value.lower().replace(" ", ""), value)
        # Try to launch by package
        ok, msg = _run_adb([
            "shell", "monkey", "-p", pkg, "-c",
            "android.intent.category.LAUNCHER", "1"
        ])
        if ok:
            return f"Opened {value} on the phone."
        # Fallback: am start by intent if user passed a full package
        ok2, msg2 = _run_adb([
            "shell", "am", "start", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", pkg
        ])
        if ok2:
            return f"Opened {value} on the phone."
        return f"Could not open '{value}'. Is it installed? ({msg or msg2})"

    if action in ("tap", "click"):
        # value = "x,y"
        parts = [p.strip() for p in value.replace(" ", ",").split(",") if p.strip()]
        if len(parts) < 2:
            return "Tap needs coordinates like 540,1200."
        try:
            x, y = int(float(parts[0])), int(float(parts[1]))
        except ValueError:
            return "Invalid coordinates for tap."
        ok, msg = _run_adb(["shell", "input", "tap", str(x), str(y)])
        return f"Tapped ({x},{y})." if ok else f"Tap failed: {msg}"

    if action in ("swipe",):
        # value = "x1,y1,x2,y2" optional duration
        parts = [p.strip() for p in value.replace(" ", ",").split(",") if p.strip()]
        if len(parts) < 4:
            return "Swipe needs x1,y1,x2,y2 (optional duration ms)."
        try:
            coords = [str(int(float(p))) for p in parts[:4]]
            dur = str(int(float(parts[4]))) if len(parts) > 4 else "300"
        except ValueError:
            return "Invalid swipe coordinates."
        ok, msg = _run_adb(["shell", "input", "swipe"] + coords + [dur])
        return "Swipe sent." if ok else f"Swipe failed: {msg}"

    if action in ("type", "type_text", "text"):
        if not value:
            return "Nothing to type."
        # Escape spaces for adb input text
        safe = value.replace(" ", "%s").replace("'", "\\'")
        ok, msg = _run_adb(["shell", "input", "text", safe])
        return f"Typed on phone: {value}" if ok else f"Type failed: {msg}"

    if action in ("volume_up", "vol_up"):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_VOLUME_UP"])
        return "Volume up." if ok else msg

    if action in ("volume_down", "vol_down"):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_VOLUME_DOWN"])
        return "Volume down." if ok else msg

    if action in ("mute", "volume_mute"):
        ok, msg = _run_adb(["shell", "input", "keyevent", "KEYCODE_VOLUME_MUTE"])
        return "Mute toggled." if ok else msg

    if action in ("battery", "battery_status"):
        ok, out = _run_adb(["shell", "dumpsys", "battery"])
        if not ok:
            return f"Could not read battery: {out}"
        level = "unknown"
        status = "unknown"
        for line in out.splitlines():
            if "level:" in line:
                level = line.split(":")[-1].strip()
            if "status:" in line:
                status = line.split(":")[-1].strip()
        return f"Phone battery: {level}% (status {status})."

    if action in ("screenshot", "screen"):
        remote = "/sdcard/jarvis_shot.png"
        local_dir = Path.home() / "Downloads"
        local_dir.mkdir(parents=True, exist_ok=True)
        local = local_dir / f"jarvis_phone_{int(time.time())}.png"
        ok, msg = _run_adb(["shell", "screencap", "-p", remote])
        if not ok:
            return f"Screenshot failed: {msg}"
        ok2, msg2 = _run_adb(["pull", remote, str(local)])
        _run_adb(["shell", "rm", remote])
        if ok2:
            return f"Phone screenshot saved to {local}"
        return f"Screenshot captured on phone but pull failed: {msg2}"

    return (
        f"Unknown phone action '{action}'. "
        "Try: status, unlock, lock, home, back, open_app, tap, swipe, "
        "type_text, volume_up, volume_down, battery, screenshot."
    )


TOOL = {
    "name": "phone_control",
    "description": (
        "Control a connected Android phone via ADB. Use when the user asks to "
        "control their phone, unlock/lock it, open an app on the phone, tap, "
        "swipe, type text, change volume, check battery, or take a screenshot. "
        "First call with action=status if unsure whether a phone is connected. "
        "Requires USB debugging (or wireless ADB) and the adb tool installed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: status, unlock, lock, home, back, recent, open_app, "
                    "tap, swipe, type_text, volume_up, volume_down, mute, battery, screenshot"
                ),
            },
            "value": {
                "type": "STRING",
                "description": (
                    "Extra argument depending on action. For open_app: app name "
                    "(WhatsApp, Chrome…). For tap: 'x,y'. For swipe: 'x1,y1,x2,y2'. "
                    "For type_text: the text to type."
                ),
            },
        },
        "required": ["action"],
    },
    "handler": phone_control,
}
