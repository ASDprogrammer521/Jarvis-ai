"""Like / dislike / subscribe for the HUD video player — through a real browser window, no API keys.

How it works: Jarvis drives its own browser profile (~/.jarvis_profiles/youtube) with Playwright, using Chrome or
Edge when installed. The first time, a normal browser window opens on Google's sign-in page — you sign in yourself
(Jarvis never sees your password; only the browser profile keeps the session). After that likes and subscriptions
run in a hidden window in a few seconds.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

PROFILE = Path.home() / ".jarvis_profiles" / "youtube"
_LOCK = threading.Lock()
SIGNIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&hl=en&continue=https%3A%2F%2Fwww.youtube.com%2F%3Fhl%3Den"
SIGNIN_TIMEOUT = 300          # seconds the user has to finish signing in

_ARGS = ["--disable-blink-features=AutomationControlled", "--mute-audio", "--autoplay-policy=user-gesture-required",
         "--no-first-run", "--no-default-browser-check"]

NO_BROWSER = ("I couldn't start a browser. Install Google Chrome or Microsoft Edge, or run: playwright install chromium")


def _cfg_set(**kw) -> None:
    try:
        from memory.config_manager import _patch_config
        _patch_config(**kw)
    except Exception:
        pass


def is_connected() -> bool:
    try:
        from memory.config_manager import load_api_keys
        return bool(load_api_keys().get("youtube_connected")) and PROFILE.exists()
    except Exception:
        return False


def _launch(p, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for channel in ("chrome", "msedge", None):       # a real browser looks normal to Google; bundled Chromium is the fallback
        kw = dict(headless=headless, locale="en-US", args=_ARGS, ignore_default_args=["--enable-automation"],
                  viewport={"width": 1280, "height": 900})
        if channel:
            kw["channel"] = channel
        try:
            return p.chromium.launch_persistent_context(str(PROFILE), **kw)
        except Exception as e:
            last = e
    raise RuntimeError(f"{NO_BROWSER} ({str(last)[:120]})")


def _signed_in(page) -> bool:
    try:
        page.wait_for_selector("button#avatar-btn, ytd-masthead #avatar-btn", timeout=9000)
        return True
    except Exception:
        return False


def _signin(p) -> bool:
    """Visible browser → Google sign-in → wait until the YouTube avatar shows up."""
    ctx = _launch(p, headless=False)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        end = time.time() + SIGNIN_TIMEOUT
        while time.time() < end:
            if not ctx.pages:                         # the user closed the window
                return False
            try:
                if "youtube.com" in page.url and page.query_selector("button#avatar-btn"):
                    time.sleep(1.5)                   # let the cookies settle
                    return True
            except Exception:
                if not ctx.pages:
                    return False
            time.sleep(1)
        return False
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def connect() -> str:
    """Open the browser for the one-time YouTube / Google sign-in."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "✗ Needs: pip install playwright  (then: playwright install chromium)"
    with _LOCK:
        try:
            with sync_playwright() as p:
                ok = _signin(p)
        except Exception as e:
            return f"✗ {str(e)[:160]}"
    if ok:
        _cfg_set(youtube_connected=True)
        return "✅ YouTube connected"
    return "✗ Sign-in wasn't finished — try again."


def _first(page, selectors):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


LIKE = ["like-button-view-model button", "#segmented-like-button button", "button[aria-label^='like this video' i]"]
DISLIKE = ["dislike-button-view-model button", "#segmented-dislike-button button", "button[aria-label^='dislike this video' i]"]
SUBSCRIBE = ["ytd-watch-metadata #subscribe-button-shape button", "#owner #subscribe-button-shape button",
             "ytd-watch-metadata ytd-subscribe-button-renderer button", "#owner ytd-subscribe-button-renderer button",
             "yt-subscribe-button-view-model button"]


def _on_watch_page(video_id: str, job):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "✗ Needs: pip install playwright  (then: playwright install chromium)"
    with _LOCK:
        try:
            with sync_playwright() as p:
                for attempt in (1, 2):
                    ctx = _launch(p, headless=True)
                    try:
                        page = ctx.pages[0] if ctx.pages else ctx.new_page()
                        page.goto(f"https://www.youtube.com/watch?v={video_id}&hl=en", wait_until="domcontentloaded", timeout=30000)
                        if _signed_in(page):
                            page.wait_for_selector("ytd-watch-metadata, #above-the-fold", timeout=15000)
                            page.wait_for_timeout(1200)
                            try:
                                page.evaluate("document.querySelector('video') && document.querySelector('video').pause()")
                            except Exception:
                                pass
                            return job(page)
                    finally:
                        try:
                            ctx.close()
                        except Exception:
                            pass
                    if attempt == 1:                   # not signed in → let the user sign in, then retry once
                        if not _signin(p):
                            return "✗ Sign-in wasn't finished — try again."
                        _cfg_set(youtube_connected=True)
                return "✗ Still not signed in."
        except Exception as e:
            return f"✗ {str(e)[:160]}"


def rate(video_id: str, rating: str) -> str:
    """rating: like | dislike | none"""
    if not video_id:
        return "No YouTube video is playing."
    if rating not in ("like", "dislike", "none"):
        return "Unknown rating."

    def job(page):
        like, dis = _first(page, LIKE), _first(page, DISLIKE)
        if like is None or dis is None:
            return "✗ I couldn't find the like buttons on the page (YouTube may have changed its layout)."
        liked = like.get_attribute("aria-pressed") == "true"
        disliked = dis.get_attribute("aria-pressed") == "true"
        if rating == "like":
            if not liked:
                like.click()
            return "👍 Liked"
        if rating == "dislike":
            if not disliked:
                dis.click()
            return "👎 Disliked"
        if liked:
            like.click()
        if disliked:
            dis.click()
        return "Rating removed"
    return _on_watch_page(video_id, job)


def subscribe(video_id: str, channel_name: str = "") -> str:
    if not video_id:
        return "No YouTube video is playing."

    def job(page):
        btn = _first(page, SUBSCRIBE)
        if btn is None:
            return "✗ I couldn't find the Subscribe button (YouTube may have changed its layout)."
        label = ((btn.inner_text() or "") + " " + (btn.get_attribute("aria-label") or "")).lower()
        if "subscribed" in label or "unsubscribe" in label:
            return f"Already subscribed to {channel_name or 'this channel'}."
        btn.click()
        page.wait_for_timeout(900)
        return f"🔔 Subscribed to {channel_name or 'the channel'}"
    return _on_watch_page(video_id, job)
