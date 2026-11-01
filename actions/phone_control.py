from __future__ import annotations
import re
from urllib.parse import urlsplit

def _get_dashboard():
    try:
        from dashboard.server import get_active_dashboard
        return get_active_dashboard()
    except Exception:
        return None

def _push_phone(dashboard, message: dict) -> int:
    try:
        return int(dashboard.send_to_phones_sync(message) or 0)
    except Exception as exc:
        print(f"Phone command could not be sent: {exc}")
        return 0

def run(action=None, value="", **kwargs):
    if isinstance(action, dict):
        params = action
        action = params.get("action") or params.get("command") or "status"
        value = value or params.get("value") or params.get("text") or params.get("url") or ""
    elif isinstance(kwargs.get("parameters"), dict):
        params = kwargs["parameters"]
        action = action or params.get("action") or params.get("command") or "status"
        value = value or params.get("value") or params.get("text") or params.get("url") or ""
    value = str(value or "").strip()
    action = str(action or "status").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "list_devices": "status",
        "phone_status": "status",
        "message": "notify",
        "say": "notify",
        "alert": "notify",
        "text": "notify",
        "type_text": "notify",
        "url": "open_url",
        "open_link": "open_url",
        "phone": "call",
        "dial": "call",
        "ring": "call",
        "call_status": "call_state",
        "answer_call": "answer",
        "pick_up": "answer",
        "reject_call": "reject",
        "decline": "reject",
        "hang_up": "hangup",
        "end_call": "hangup",
        "end": "hangup",
        "sms": "sms",
        "torch": "flashlight",
        "flashlight_on": "flashlight",
        "torch_on": "flashlight",
        "torch_off": "flashlight_off",
        "where": "location",
        "app": "open_app",
        "launch": "open_app",
        "lock_phone": "lock",
        "wake": "unlock",
    }
    action = aliases.get(action, action)
    dashboard = _get_dashboard()
    if dashboard is None:
        return "Jarvis Dashboard is not running. Start Jarvis on the computer first."
    try:
        count = int(dashboard.phone_count())
    except Exception:
        count = 0
    if action == "status":
        if count:
            return f"Jarvis App connected ✅ ({count} client(s))."
        return "Jarvis App is not connected. Open the Jarvis App page on the phone and complete pairing."
    if count <= 0:
        return "Jarvis App is not connected. Pair the phone before sending a command."
    if action == "notify":
        if not value:
            return "Provide the message text to show on the phone."
        text = value[:500]
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "notify", "text": text})
        return f"Notification sent 🔔 ({sent} client(s)): {text}" if sent else "The message was not sent because the Jarvis App is disconnected."
    if action == "open_url":
        if not value:
            return "Provide an HTTP(S) URL to open on the phone."
        if value.lower().startswith(("http://", "https://")):
            url = value
        else:
            scheme_candidate = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
            host_with_port = re.match(r"^[A-Za-z0-9.-]+:\d+(?:/|$)", value)
            if scheme_candidate and not host_with_port:
                return "Only HTTP(S) URLs without embedded credentials are allowed."
            url = f"https://{value}"
        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                return "Only HTTP(S) URLs without embedded credentials are allowed."
            _ = parsed.port
        except ValueError:
            return "The URL format is invalid."
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "open_url", "url": url})
        return f"URL sent to the phone 🌐 ({sent} client(s)): {url}" if sent else "The URL was not sent because the Jarvis App is disconnected."
    if action == "call":
        number = _clean_number(value)
        if not number:
            return "Give me a phone number to call (digits, optionally starting with +)."
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "call", "value": number})
        return (f"Calling {number} on the phone 📞 — the phone may ask for Phone permission the first time."
                if sent else "The call was not placed because the Jarvis App is disconnected.")
    if action == "sms":
        number, _, body = value.partition("|")
        number = _clean_number(number)
        body = body.strip()
        if not number or not body:
            return "For an SMS give: value = '<number>|<message text>'."
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "sms", "value": f"{number}|{body[:500]}"})
        return f"SMS to {number} handed to the phone 💬." if sent else "The SMS was not sent because the Jarvis App is disconnected."
    if action in _SIMPLE:
        label, wire = _SIMPLE[action]
        msg = {"type": "phone_cmd", "action": wire}
        if action == "open_app":
            if not value:
                return "Tell me which app to open on the phone."
            msg["value"] = value[:80]
        sent = _push_phone(dashboard, msg)
        return f"{label} 📱" if sent else "The command was not sent because the Jarvis App is disconnected."
    return ("The Jarvis App supports: status, notify, open_url, open_app, call, answer, reject, hangup, "
            "call_state, sms, lock, unlock, home, flashlight, flashlight_off, location, battery, "
            "notifications, screenshot, volume_up, volume_down.")


_SIMPLE = {
    "answer": ("Answer requested", "answer"),
    "reject": ("Reject requested", "reject"),
    "hangup": ("Hang-up requested", "hangup"),
    "call_state": ("Asked the phone for its call state — the reply shows in the log", "call_status"),
    "lock": ("Lock requested", "lock"),
    "unlock": ("Wake / unlock requested (a PIN or fingerprint is still needed)", "unlock"),
    "home": ("Phone sent to the home screen", "home"),
    "flashlight": ("Flashlight on", "flashlight"),
    "flashlight_off": ("Flashlight off", "flashlight_off"),
    "location": ("Asked the phone for its location", "location"),
    "battery": ("Asked the phone for its battery level", "battery"),
    "notifications": ("Asked the phone for its notifications", "notifications"),
    "screenshot": ("Screenshot requested — allow it on the phone", "screenshot"),
    "volume_up": ("Phone volume up", "volume_up"),
    "volume_down": ("Phone volume down", "volume_down"),
    "open_app": ("App launch requested", "open_app"),
}


def _clean_number(raw) -> str:
    """Keep digits and one leading '+'; reject anything that is not a plausible phone number."""
    raw = str(raw or "").strip()
    number = ("+" if raw.startswith("+") else "") + re.sub(r"\D", "", raw)
    return number if 3 <= len(re.sub(r"\D", "", number)) <= 15 else ""

TOOL = {
    "name": "phone_control",
    "description": (
        "Controls the user's paired Android phone through the Jarvis App: MAKE A PHONE CALL (action=call, value=number), "
        "answer / reject / hang up a call, check call state, send an SMS (value='number|text'), show a message, "
        "open a link or an app, lock / wake the phone, flashlight, location, battery, notifications, screenshot, volume. "
        "A call needs a phone NUMBER — if the user gives only a name, ask for the number; never invent one."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | call | answer | reject | hangup | call_state | sms | notify | open_url | open_app | lock | unlock | home | flashlight | flashlight_off | location | battery | notifications | screenshot | volume_up | volume_down"},
            "value": {"type": "STRING", "description": "Phone number (call), 'number|text' (sms), message text (notify), HTTP(S) URL (open_url) or app name (open_app)"},
        },
        "required": ["action"],
    },
    "handler": run,
}

#by ASDcuber
