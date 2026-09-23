"""
Control a linked phone via Jarvis App (WebSocket) or optional ADB.

Primary path: phone opens http://<PC-IP>:8000/jarvis-app and Connects.
Jarvis then pushes commands to the phone over the live link.
ADB is optional for deeper system control (lock, screenshots, etc.).
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path




def _adb_available() -> bool:
    return shutil.which("adb") is not None


def _run_adb(args: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["adb", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out."
    except Exception as e:
        return False, str(e)


def _devices() -> list[str]:
    if not _adb_available():
        return []
    ok, out = _run_adb(["devices"])
    if not ok:
        return []
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devs.append(parts[0])
    return devs


def _get_dashboard():
    """Access the running DashboardServer instance."""
    try:
        from dashboard.server import get_active_dashboard
        d = get_active_dashboard()
        if d is not None:
            return d
    except Exception:
        pass
    # Fallback: walk loaded modules for Jarvis engine
    try:
        import sys
        for mod in list(sys.modules.values()):
            if mod is None:
                continue
            for attr in ("_dashboard", "dashboard"):
                d = getattr(mod, attr, None)
                if d is not None and hasattr(d, "send_to_phones_sync"):
                    return d
            eng = getattr(mod, "engine", None) or getattr(mod, "app", None)
            if eng is not None:
                d = getattr(eng, "_dashboard", None)
                if d is not None:
                    return d
    except Exception:
        pass
    return None


def _phone_web_linked(dash) -> bool:
    try:
        return bool(dash and dash.phone_linked())
    except Exception:
        return False


def _push_phone(dash, payload: dict) -> int:
    """Send JSON to all linked phones; works from Gemini tool thread."""
    if dash is None:
        return 0
    # Preferred: thread-safe helper on DashboardServer
    if hasattr(dash, "send_to_phones_sync"):
        try:
            n = int(dash.send_to_phones_sync(payload) or 0)
            if n > 0:
                return n
        except Exception as e:
            print(f"[phone_control] sync push failed: {e}")
    # Fallback async bridge
    try:
        loop = getattr(dash, "_loop", None)
        if loop is not None and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(dash.send_to_phones(payload), loop)
            return int(fut.result(timeout=5) or 0)
    except Exception as e:
        print(f"[phone_control] loop push failed: {e}")
    return 0


def run(action: str = "status", value: str = "", **kwargs) -> str:
    # Support both TOOL.run style and legacy phone_control(parameters) style
    if isinstance(action, dict):
        parameters = action
        action = (parameters.get("action") or "status").strip().lower()
        value = (parameters.get("value") or "").strip()
    else:
        action = (action or "status").strip().lower()
        value = (value or "").strip()
        if not value and isinstance(kwargs.get("parameters"), dict):
            value = (kwargs["parameters"].get("value") or "").strip()
            action = (kwargs["parameters"].get("action") or action).strip().lower()

    dash = _get_dashboard()
    web_ok = _phone_web_linked(dash)
    adb_devs = _devices()
    adb_ok = bool(adb_devs)

    if action in ("status", "list", "list_devices", "devices"):
        parts = []
        if web_ok:
            try:
                n = dash.phone_count()
            except Exception:
                n = 1
            parts.append(f"Jarvis App CONNECTED ({n} client(s)) — phone control is live.")
        else:
            parts.append("Jarvis App: not linked. Open http://<PC-IP>:8000/jarvis-app on the phone and Connect.")
        if adb_ok:
            parts.append(f"ADB devices: {', '.join(adb_devs)}.")
        else:
            parts.append("ADB: no device (optional — only needed for deep system control).")
        if web_ok or adb_ok:
            return "Phone ready. " + " ".join(parts)
        return "No phone linked. " + " ".join(parts)

    # ── Web / Jarvis App path ─────────────────────────────────────────────
    if web_ok:
        if action in ("notify", "message", "say", "alert"):
            text = value or "Message from Jarvis"
            n = _push_phone(dash, {"type": "phone_cmd", "action": "notify", "text": text})
            return f"Sent to phone screen ({n} client(s)): {text}"

        if action in ("open_url", "url", "open_link"):
            if not value:
                return "Provide a URL to open on the phone."
            n = _push_phone(dash, {"type": "phone_cmd", "action": "open_url", "url": value})
            return f"Asked phone to open URL ({n}): {value}"

        if action in ("open_app", "app"):
            app = (value or "").strip()
            # Native app command — Android Jarvis App opens by package/name
            n = _push_phone(dash, {
                "type": "phone_cmd",
                "action": "open_app",
                "value": app,
                "text": app,
            })
            if n <= 0:
                return (
                    "Phone not linked right now. Open Jarvis App on the phone, "
                    "enter IP + pairing key, wait for Connected, then try again."
                )
            return f"Sent open-app '{app}' to phone ({n} client(s))."

        if action in ("type_text", "type", "text"):
            if not value:
                return "Provide text to show on the phone."
            n = _push_phone(dash, {"type": "phone_cmd", "action": "notify", "text": value})
            return f"Displayed on phone ({n}): {value}"

        # For ADB-only actions, fall through if ADB available
        if action in ("lock", "unlock", "home", "back", "volume", "screenshot", "battery") and not adb_ok:
            n = _push_phone(dash, {
                "type": "phone_cmd",
                "action": "notify",
                "text": f"Jarvis requested: {action} {value}".strip(),
            })
            return (
                f"Phone is linked via Jarvis App, but '{action}' needs ADB for full system control. "
                f"Notified the phone instead ({n}). Enable USB debugging for deep control."
            )

    # ── ADB path ──────────────────────────────────────────────────────────
    if not adb_ok:
        if web_ok:
            return "Phone is linked (Jarvis App). Use notify/message/open_url, or enable ADB for system actions."
        return (
            "No phone linked. On the phone open http://<PC-IP>:8000/jarvis-app, "
            "enter the pairing key, tap Connect. Optional: enable USB debugging for ADB."
        )

    serial = adb_devs[0]
    pre = ["-s", serial]

    if action == "lock":
        ok, msg = _run_adb([*pre, "shell", "input", "keyevent", "26"])
        return "Phone locked." if ok else f"Lock failed: {msg}"

    if action == "unlock":
        _run_adb([*pre, "shell", "input", "keyevent", "26"])
        ok, msg = _run_adb([*pre, "shell", "input", "keyevent", "82"])
        return "Unlock attempted." if ok else f"Unlock failed: {msg}"

    if action == "home":
        ok, msg = _run_adb([*pre, "shell", "input", "keyevent", "3"])
        return "Home pressed." if ok else msg

    if action == "back":
        ok, msg = _run_adb([*pre, "shell", "input", "keyevent", "4"])
        return "Back pressed." if ok else msg

    if action in ("volume", "volume_up", "volume_down"):
        code = "24" if "up" in action or (value or "").lower() == "up" else "25"
        ok, msg = _run_adb([*pre, "shell", "input", "keyevent", code])
        return "Volume adjusted." if ok else msg

    if action in ("type_text", "type"):
        if not value:
            return "Provide text to type."
        safe = value.replace(" ", "%s")
        ok, msg = _run_adb([*pre, "shell", "input", "text", safe])
        return f"Typed: {value}" if ok else msg

    if action == "screenshot":
        remote = "/sdcard/jarvis_shot.png"
        ok, msg = _run_adb([*pre, "shell", "screencap", "-p", remote])
        if not ok:
            return f"Screenshot failed: {msg}"
        local_dir = Path.home() / "Downloads"
        local_dir.mkdir(exist_ok=True)
        local = local_dir / f"jarvis_phone_{int(time.time())}.png"
        ok2, msg2 = _run_adb([*pre, "pull", remote, str(local)])
        return f"Screenshot saved: {local}" if ok2 else f"Pull failed: {msg2}"

    if action == "battery":
        ok, msg = _run_adb([*pre, "shell", "dumpsys", "battery"])
        if not ok:
            return msg
        level = "?"
        for line in msg.splitlines():
            if "level:" in line.lower():
                level = line.split(":")[-1].strip()
                break
        return f"Phone battery level: {level}%"

    if action in ("open_app", "app") and value:
        ok, msg = _run_adb([*pre, "shell", "monkey", "-p", value, "-c",
                            "android.intent.category.LAUNCHER", "1"])
        return f"Launched {value}." if ok else f"Open app failed: {msg}"

    if action in ("notify", "message"):
        return f"(ADB mode) Cannot show UI notify without App. Link Jarvis App for on-screen messages."

    return f"Unknown or unsupported phone action '{action}'."


# Legacy entry point some loaders expect
def phone_control(parameters: dict, player=None, session_memory=None) -> str:
    return run(parameters if isinstance(parameters, dict) else {"action": "status"})

TOOL = {
    "name": "phone_control",
    "description": (
        "Control or query the user's phone linked through Jarvis App "
        "(or ADB if available). Use for phone status, send a message to the "
        "phone screen, open a URL on the phone, or ADB actions when connected. "
        "If Jarvis App is linked, the phone IS connected — do not say it is offline."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "status | notify | message | open_url | open_app | "
                    "lock | unlock | home | back | volume | type_text | "
                    "screenshot | battery | list_devices"
                ),
            },
            "value": {
                "type": "STRING",
                "description": "Extra argument: message text, URL, app name, volume level",
            },
        },
        "required": ["action"],
    },
    "handler": run,
}
