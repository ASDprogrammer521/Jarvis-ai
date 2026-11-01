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
    return "The Jarvis App currently supports only status, notify, and open_url."

TOOL = {
    "name": "phone_control",
    "description": "Check the paired Jarvis App connection, show a message on the phone, or open a safe HTTP(S) URL.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | notify | open_url"},
            "value": {"type": "STRING", "description": "Message text or HTTP(S) URL"},
        },
        "required": ["action"],
    },
    "handler": run,
}

#by ASDcuber
