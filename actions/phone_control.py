from __future__ import annotations
import re
from pathlib import Path
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
        "find_phone": "ring",
        "find": "ring",
        "locate": "ring",
        "stop_ring": "ring_stop",
        "stop_find": "ring_stop",
        "search_contacts": "contacts",
        "find_contact": "contacts",
        "call_name": "call",
        "send": "send_file",
        "transfer": "send_file",
        "last_call": "call_info",
        "who_called": "call_info",
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
    if action == "call" and _looks_like_name(value):
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "call_contact", "value": value[:60]})
        return (f"Looking up \"{value}\" in the phone's contacts 📇 — the result comes back in a moment. "
                "If several people match, ask the user which one."
                if sent else "The call was not placed because the Jarvis App is disconnected.")
    if action == "contacts":
        if not value:
            return "Tell me which contact to look for."
        sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "contacts", "value": value[:60]})
        return f"Searching contacts for \"{value}\" 📇" if sent else "The Jarvis App is disconnected."
    if action == "call_info":
        last = getattr(dashboard, "last_call", None) or {}
        if not last:
            return "No call events from the phone yet (the app needs the Phone and Call log permissions)."
        who = last.get("name") or last.get("number") or "an unknown number"
        label = {"incoming_call": "is ringing", "call_active": "is in progress", "call_ended": "just ended",
                 "missed_call": "was missed"}.get(last.get("event"), last.get("event", ""))
        return f"The last call with {who} {label}."
    if action == "send_file":
        return _send_file(dashboard, value)
    if action == "call":
        number = _clean_number(value)
        if not number:
            return "Give me a phone number or a contact name to call."
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
    return ("The Jarvis App supports: status, call (number or contact name), contacts, answer, reject, hangup, "
            "call_state, call_info, sms, ring (find phone), ring_stop, send_file, notify, open_url, open_app, "
            "lock, unlock, home, flashlight, flashlight_off, location, battery, notifications, screenshot, "
            "volume_up, volume_down.")


_SIMPLE = {
    "ring": ("Phone is ringing loudly — say 'stop ringing' when you find it", "ring"),
    "ring_stop": ("Stopped the phone ringing", "ring_stop"),
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


_BLOCKED_PARTS = {".ssh", ".gnupg", "certs"}
_BLOCKED_NAMES = {"api_keys.json", "jarvis.key", "id_rsa", "id_ed25519", ".env"}


def _looks_like_name(value: str) -> bool:
    """A contact name has letters; a phone number does not."""
    return len(re.findall(r"[^\W\d_]", str(value or ""), flags=re.UNICODE)) >= 2


def _send_file(dashboard, value: str) -> str:
    """PC → phone: hand out a one-file, 15-minute link and tell the phone to fetch it."""
    if not value:
        return "Give me the path of the file to send to the phone."
    path = Path(value.strip().strip('"')).expanduser()
    if not path.is_file():
        return f"I can't find the file {path}."
    parts = {p.lower() for p in path.resolve().parts}
    if path.name.lower() in _BLOCKED_NAMES or parts & _BLOCKED_PARTS:
        return "I won't send keys, certificates or credential files to the phone."
    if not hasattr(dashboard, "share_file"):
        return "File sharing needs the updated Jarvis dashboard."
    try:
        url_path, name = dashboard.share_file(path)
    except Exception as exc:
        return f"Could not prepare the file: {exc}"
    sent = _push_phone(dashboard, {"type": "phone_cmd", "action": "fetch_file", "url": url_path, "name": name})
    return (f"Sending {name} to the phone 📁 — it lands in Downloads/Jarvis."
            if sent else "The file was not sent because the Jarvis App is disconnected.")


def _clean_number(raw) -> str:
    """Keep digits and one leading '+'; reject anything that is not a plausible phone number."""
    raw = str(raw or "").strip()
    number = ("+" if raw.startswith("+") else "") + re.sub(r"\D", "", raw)
    return number if 3 <= len(re.sub(r"\D", "", number)) <= 15 else ""

TOOL = {
    "name": "phone_control",
    "description": (
        "Controls the user's paired Android phone through the Jarvis App: MAKE A PHONE CALL (action=call, value=a number OR a contact name like 'Akam' — "
        "the phone looks the name up in its address book), answer / reject / hang up a call, say who is calling "
        "(call_info), FIND THE PHONE (ring loudly, even if silent), send a file from this PC to the phone "
        "(send_file, value=path), send an SMS (value='number|text'), show a message, open a link or an app, lock / wake "
        "the phone, flashlight, location, battery, notifications, screenshot, volume. "
        "Incoming calls are announced automatically; when the user says answer / reject, call this tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | call | contacts | call_info | send_file | ring | ring_stop | answer | reject | hangup | call_state | sms | notify | open_url | open_app | lock | unlock | home | flashlight | flashlight_off | location | battery | notifications | screenshot | volume_up | volume_down"},
            "value": {"type": "STRING", "description": "Phone number OR contact name (call), name (contacts), file path on this PC (send_file), 'number|text' (sms), message text (notify), HTTP(S) URL (open_url) or app name (open_app)"},
        },
        "required": ["action"],
    },
    "handler": run,
}

#by ASDcuber
