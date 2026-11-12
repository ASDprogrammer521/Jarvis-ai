"""Gmail + Google Calendar for Jarvis.

"Bugun qanday xatlar keldi?", "Juma kuni soat 15:00 ga uchrashuv qo'y", "Ertangi rejalarim?"

One-time setup (README → Gmail & Calendar):
  1. Google Cloud Console → enable *Gmail API* and *Google Calendar API*.
  2. Create an OAuth client of type "Desktop app" and download its JSON.
  3. Save it as  config/google_credentials.json
  4. Say "connect Google" — a browser opens once, you approve, done.
     The token is stored in config/google_token.json (owner-only).

Gmail access is READ-ONLY (Jarvis never sends or deletes mail). Calendar can read, add and delete events.
"""
from __future__ import annotations

import base64
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone

from actions._common import BASE_DIR, log

CREDS_FILE = BASE_DIR / "config" / "google_credentials.json"
TOKEN_FILE = BASE_DIR / "config" / "google_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
_LOCK = threading.Lock()
_SVC: dict = {}

NEED_SETUP = (
    "Sir, Google isn't connected yet. Download an OAuth 'Desktop app' client JSON from Google Cloud Console "
    f"(Gmail API + Calendar API enabled), save it as {CREDS_FILE}, then say 'connect Google'."
)

# ── date / time parsing (English, Uzbek, Russian) ──────────────────────────────
_WEEKDAYS = {
    0: ("monday", "mon", "dushanba", "du", "понедельник"),
    1: ("tuesday", "tue", "seshanba", "se", "вторник"),
    2: ("wednesday", "wed", "chorshanba", "chor", "среда"),
    3: ("thursday", "thu", "payshanba", "pay", "четверг"),
    4: ("friday", "fri", "juma", "ju", "пятница"),
    5: ("saturday", "sat", "shanba", "sha", "суббота"),
    6: ("sunday", "sun", "yakshanba", "yak", "воскресенье"),
}
_REL = {
    "today": 0, "bugun": 0, "сегодня": 0,
    "tomorrow": 1, "ertaga": 1, "завтра": 1,
    "day after tomorrow": 2, "indinga": 2, "послезавтра": 2,
    "yesterday": -1, "kecha": -1, "вчера": -1,
}


def _local_tz() -> timezone:
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def parse_day(text, default: date | None = None) -> date | None:
    """today/ertaga/juma/friday/2026-11-06 → date (weekday names mean the NEXT such day, today included)."""
    s = str(text or "").strip().lower()
    if not s:
        return default
    today = date.today()
    if s in _REL:
        return today + timedelta(days=_REL[s])
    for wd, names in _WEEKDAYS.items():
        if s.replace(" kuni", "") in names:
            return today + timedelta(days=(wd - today.weekday()) % 7)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", s)  # 06.11 or 06.11.2026
    if m:
        y = int(m[3]) if m[3] else today.year
        y += 2000 if y < 100 else 0
        return date(y, int(m[2]), int(m[1]))
    return default


def parse_time(text) -> tuple[int, int] | None:
    s = str(text or "").strip().lower().replace(".", ":")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    if m[3] == "pm" and h < 12:
        h += 12
    if m[3] == "am" and h == 12:
        h = 0
    return (h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None


def _split_when(p: dict) -> datetime | None:
    """Accepts date + time params, or one ISO 'YYYY-MM-DD HH:MM' string in `start`."""
    start = str(p.get("start") or "").strip()
    d_txt, t_txt = str(p.get("date") or "").strip(), str(p.get("time") or "").strip()
    if start and not (d_txt and t_txt):
        parts = re.split(r"[T ]", start, maxsplit=1)
        d_txt = d_txt or parts[0]
        t_txt = t_txt or (parts[1][:5] if len(parts) > 1 else "")
    d = parse_day(d_txt)
    t = parse_time(t_txt)
    if d is None or t is None:
        return None
    return datetime(d.year, d.month, d.day, t[0], t[1], tzinfo=_local_tz())


# ── auth ───────────────────────────────────────────────────────────────────────
def _creds(interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception:
            creds = None
    if not interactive:
        return None
    if not CREDS_FILE.exists():
        raise FileNotFoundError(NEED_SETUP)
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=180)
    _save_token(creds)
    return creds


def _save_token(creds) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass


def _service(name: str, version: str):
    with _LOCK:
        creds = _creds()
        if creds is None:
            raise PermissionError(NEED_SETUP)
        key = (name, id(creds))
        if key not in _SVC:
            from googleapiclient.discovery import build
            _SVC.clear()
            _SVC[key] = build(name, version, credentials=creds, cache_discovery=False)
        return _SVC[key]


# ── Gmail ──────────────────────────────────────────────────────────────────────
def _hdr(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _short_sender(raw: str) -> str:
    m = re.match(r'^\s*"?([^"<]+?)"?\s*<', raw or "")
    return (m.group(1) if m else (raw or "?")).strip()


def _gmail_list(query: str, limit: int) -> str:
    gm = _service("gmail", "v1")
    ids = gm.users().messages().list(userId="me", q=query, maxResults=limit).execute().get("messages", [])
    if not ids:
        return ""
    lines = []
    for i, ref in enumerate(ids, 1):
        m = gm.users().messages().get(userId="me", id=ref["id"], format="metadata",
                                      metadataHeaders=["From", "Subject", "Date"]).execute()
        unread = "●" if "UNREAD" in m.get("labelIds", []) else " "
        lines.append(f"{i}. {unread} {_short_sender(_hdr(m, 'From'))} — {_hdr(m, 'Subject') or '(no subject)'}  [id:{ref['id']}]")
    return "\n".join(lines)


def _body_text(payload: dict) -> str:
    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            t = walk(sub)
            if t:
                return t
        if data and mime == "text/html":
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        return ""
    return walk(payload).strip()


def _gmail_read(msg_id: str) -> str:
    gm = _service("gmail", "v1")
    m = gm.users().messages().get(userId="me", id=msg_id, format="full").execute()
    body = re.sub(r"\n{3,}", "\n\n", _body_text(m.get("payload", {})))[:2500]
    return (f"From: {_hdr(m, 'From')}\nSubject: {_hdr(m, 'Subject')}\nDate: {_hdr(m, 'Date')}\n\n"
            f"{body or m.get('snippet', '')}")


# ── Calendar ───────────────────────────────────────────────────────────────────
def _fmt_event(ev: dict) -> str:
    s = ev.get("start", {})
    if "dateTime" in s:
        st = datetime.fromisoformat(s["dateTime"]).astimezone(_local_tz())
        when = st.strftime("%a %d %b %H:%M")
    else:
        when = datetime.fromisoformat(s.get("date", "1970-01-01")).strftime("%a %d %b") + " (all day)"
    loc = f" @ {ev['location']}" if ev.get("location") else ""
    return f"{when} — {ev.get('summary', '(no title)')}{loc}  [id:{ev['id']}]"


def _cal_range(d0: date, d1: date) -> list[dict]:
    cal = _service("calendar", "v3")
    tz = _local_tz()
    t0 = datetime(d0.year, d0.month, d0.day, tzinfo=tz).isoformat()
    t1 = datetime(d1.year, d1.month, d1.day, tzinfo=tz).isoformat()
    return cal.events().list(calendarId="primary", timeMin=t0, timeMax=t1, singleEvents=True,
                             orderBy="startTime", maxResults=25).execute().get("items", [])


def _conflicts(start: datetime, end: datetime) -> list[dict]:
    cal = _service("calendar", "v3")
    items = cal.events().list(calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
                              singleEvents=True, orderBy="startTime").execute().get("items", [])
    return [e for e in items if "dateTime" in e.get("start", {})]


def google_workspace(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "").lower().strip()
    try:
        if action in ("connect", "auth", "login", "setup"):
            _creds(interactive=True)
            _SVC.clear()
            return "Google connected, sir. I can now read your Gmail and manage your calendar."

        if action in ("status",):
            return "Google is connected." if _creds() else NEED_SETUP

        # ── Gmail ──
        if action in ("gmail_today", "inbox_today", "today"):
            limit = int(p.get("count") or 10)
            out = _gmail_list("in:inbox newer_than:1d", limit)
            if not out:
                return "No new emails in the last day, sir."
            return "Emails from the last 24 hours (● = unread):\n" + out
        if action in ("gmail_unread", "unread"):
            out = _gmail_list("in:inbox is:unread", int(p.get("count") or 10))
            return ("Unread emails:\n" + out) if out else "No unread emails, sir."
        if action in ("gmail_search", "search"):
            q = str(p.get("query") or "").strip()
            if not q:
                return "What should I search for in your mail, sir?"
            out = _gmail_list(q, int(p.get("count") or 10))
            return out or "Nothing matched in your mail."
        if action in ("gmail_read", "read"):
            mid = str(p.get("id") or "").replace("id:", "").strip()
            if not mid:
                return "Tell me which email (I need its id from the list)."
            return _gmail_read(mid)

        # ── Calendar ──
        if action in ("calendar_list", "events", "agenda", "calendar_today"):
            d0 = parse_day(p.get("date"), date.today())
            days = max(1, min(int(p.get("days") or 1), 14))
            evs = _cal_range(d0, d0 + timedelta(days=days))
            if not evs:
                return f"Nothing on your calendar for {d0.strftime('%a %d %b')}" + (f" (+{days - 1} days)." if days > 1 else ".")
            return "\n".join(_fmt_event(e) for e in evs)
        if action in ("calendar_add", "add_event", "schedule"):
            title = str(p.get("title") or p.get("summary") or "").strip() or "Meeting"
            start = _split_when(p)
            if start is None:
                return "I need the day and the time (e.g. Friday 15:00), sir."
            dur = int(p.get("duration_minutes") or 60)
            end = start + timedelta(minutes=dur)
            if start < datetime.now(_local_tz()) - timedelta(minutes=1):
                return f"{start.strftime('%a %d %b %H:%M')} is already in the past, sir. Which day did you mean?"
            clash = _conflicts(start, end)
            if clash and not p.get("force"):
                return ("That slot overlaps with: " + "; ".join(_fmt_event(e).split("  [id")[0] for e in clash)
                        + ". Say 'add it anyway' to double-book.")
            body = {"summary": title,
                    "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
            if p.get("location"):
                body["location"] = str(p["location"])
            if p.get("description"):
                body["description"] = str(p["description"])
            ev = _service("calendar", "v3").events().insert(calendarId="primary", body=body).execute()
            log(f"[Calendar] Added {title} {start}", player)
            return f"Added to your calendar: {title}, {start.strftime('%A %d %b')} {start.strftime('%H:%M')}–{end.strftime('%H:%M')}. [id:{ev['id']}]"
        if action in ("calendar_delete", "delete_event", "cancel"):
            eid = str(p.get("id") or "").replace("id:", "").strip()
            if not eid:
                day = parse_day(p.get("date"), date.today())
                match = [e for e in _cal_range(day, day + timedelta(days=1))
                         if str(p.get("title") or "").lower() in e.get("summary", "").lower()] if p.get("title") else []
                if len(match) != 1:
                    return "I need the exact event — list the calendar first and give me its id." if not match else \
                        "More than one event matches; please give me the id."
                eid = match[0]["id"]
            _service("calendar", "v3").events().delete(calendarId="primary", eventId=eid).execute()
            return "Event removed from your calendar."
    except PermissionError as e:
        return str(e)
    except FileNotFoundError as e:
        return str(e)
    except ImportError as e:
        return f"Sir, I need extra packages: pip install google-api-python-client google-auth-oauthlib ({e.name} is missing)."
    except Exception as e:
        msg = str(e)
        if "invalid_grant" in msg or "RefreshError" in type(e).__name__:
            TOKEN_FILE.unlink(missing_ok=True)
            return "Your Google sign-in expired. Say 'connect Google' to sign in again."
        return f"Google request failed: {msg[:200]}"
    return "Unknown action. Available: connect, gmail_today, gmail_unread, gmail_search, gmail_read, calendar_list, calendar_add, calendar_delete."


TOOL = {
    "name": "google_workspace",
    "description": (
        "Gmail (read-only) and Google Calendar. Use for: 'bugun qanday xatlar keldi?' / 'what emails came today' → "
        "gmail_today; 'o'qilmagan xatlar' → gmail_unread; 'find the email from X' → gmail_search; reading one email "
        "→ gmail_read with its id; 'bugun/ertaga/bu hafta rejalarim' → calendar_list; 'juma kuni soat 15:00 ga "
        "uchrashuv qo'y' → calendar_add (date=friday|juma|ertaga|YYYY-MM-DD, time=15:00); cancel an event → "
        "calendar_delete. First time: action=connect to sign in with Google."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "connect | status | gmail_today | gmail_unread | gmail_search | gmail_read | calendar_list | calendar_add | calendar_delete"},
            "query": {"type": "STRING", "description": "Gmail search query, e.g. 'from:amazon newer_than:7d'"},
            "id": {"type": "STRING", "description": "Email id or event id from an earlier listing"},
            "count": {"type": "INTEGER", "description": "How many emails to list (default 10)"},
            "title": {"type": "STRING", "description": "Event title"},
            "date": {"type": "STRING", "description": "today | ertaga/tomorrow | weekday name (juma, friday…) | YYYY-MM-DD"},
            "time": {"type": "STRING", "description": "Start time 24h HH:MM, e.g. 15:00"},
            "duration_minutes": {"type": "INTEGER", "description": "Event length, default 60"},
            "days": {"type": "INTEGER", "description": "calendar_list: how many days to show from date (default 1)"},
            "location": {"type": "STRING", "description": "Event location"},
            "description": {"type": "STRING", "description": "Event notes"},
            "force": {"type": "BOOLEAN", "description": "Add the event even if it overlaps another"},
        },
        "required": ["action"],
    },
    "handler": google_workspace,
}
