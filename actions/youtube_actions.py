"""Like / dislike / subscribe for the HUD video player (YouTube Data API v3).

Uses the same Google OAuth client as Gmail & Calendar (config/google_credentials.json) but its own token file,
so connecting YouTube never disturbs the Gmail / Calendar sign-in. First use opens a browser once.
In Google Cloud Console also enable **YouTube Data API v3** for the project.
"""
from __future__ import annotations

import os
import threading

from actions._common import BASE_DIR

CREDS_FILE = BASE_DIR / "config" / "google_credentials.json"
TOKEN_FILE = BASE_DIR / "config" / "google_youtube_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
_LOCK = threading.Lock()

NEED_SETUP = ("Google isn't set up for YouTube yet. Save your OAuth 'Desktop app' client as config/google_credentials.json "
              "and enable the YouTube Data API v3 in the same Google Cloud project — see the README.")


def _creds():
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
            _save(creds)
            return creds
        except Exception:
            creds = None
    if not CREDS_FILE.exists():
        raise FileNotFoundError(NEED_SETUP)
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=180)
    _save(creds)
    return creds


def _save(creds) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass


def _yt():
    with _LOCK:
        from googleapiclient.discovery import build
        return build("youtube", "v3", credentials=_creds(), cache_discovery=False)


def _explain(e: Exception) -> str:
    msg = str(e)
    if isinstance(e, FileNotFoundError):
        return msg
    if isinstance(e, ImportError):
        return "Needs: pip install google-api-python-client google-auth-oauthlib"
    if "accessNotConfigured" in msg or "has not been used" in msg:
        return "Enable the YouTube Data API v3 in your Google Cloud project, then try again."
    if "quotaExceeded" in msg:
        return "YouTube API quota is used up for today."
    if "invalid_grant" in msg or "RefreshError" in type(e).__name__:
        TOKEN_FILE.unlink(missing_ok=True)
        return "YouTube sign-in expired — press the button again to sign in."
    if "subscriptionDuplicate" in msg:
        return "You're already subscribed."
    if "forbidden" in msg.lower() or "403" in msg:
        return "YouTube refused this (the video or channel may not allow it)."
    return f"YouTube request failed: {msg[:160]}"


def rate(video_id: str, rating: str) -> str:
    """rating: like | dislike | none"""
    if not video_id:
        return "No YouTube video is playing."
    if rating not in ("like", "dislike", "none"):
        return "Unknown rating."
    try:
        _yt().videos().rate(id=video_id, rating=rating).execute()
    except Exception as e:
        return "✗ " + _explain(e)
    return {"like": "👍 Liked", "dislike": "👎 Disliked", "none": "Rating removed"}[rating]


def subscribe(channel_id: str, channel_name: str = "") -> str:
    if not channel_id:
        return "I couldn't tell which channel this video belongs to."
    try:
        yt = _yt()
        have = yt.subscriptions().list(part="id", mine=True, forChannelId=channel_id).execute().get("items")
        if have:
            return f"Already subscribed to {channel_name or 'this channel'}."
        yt.subscriptions().insert(part="snippet", body={"snippet": {"resourceId": {
            "kind": "youtube#channel", "channelId": channel_id}}}).execute()
    except Exception as e:
        return "✗ " + _explain(e)
    return f"🔔 Subscribed to {channel_name or 'the channel'}"
