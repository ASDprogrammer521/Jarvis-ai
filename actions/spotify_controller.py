from __future__ import annotations

import base64
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from actions._common import cfg, log

try:
    import requests
except ImportError:
    requests = None

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
VK = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD}
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read user-read-playback-state user-modify-playback-state"
_TOKENS: dict = {}


def _run(cmd: list[str], timeout: int = 8) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_HIDE)
    return (r.stdout or "").strip()


def _osa(script: str) -> str:
    return _run(["osascript", "-e", script])


def _key(name: str) -> None:
    import ctypes
    u = ctypes.windll.user32
    u.keybd_event(VK[name], 0, 0, 0)
    u.keybd_event(VK[name], 0, 2, 0)


def _playerctl(*args: str) -> str:
    if shutil.which("playerctl"):
        return _run(["playerctl", "-p", "spotify", *args])
    raise RuntimeError("install 'playerctl' (sudo apt install playerctl) to control Spotify on Linux")


def _mpris(method: str) -> None:
    _run(["dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2",
          f"org.mpris.MediaPlayer2.Player.{method}"])


def _spotify_running() -> bool:
    try:
        import psutil
        return any((p.info["name"] or "").lower().startswith("spotify") for p in psutil.process_iter(["name"]))
    except Exception:
        return True


def _launch_app(wait: float = 6.0) -> bool:
    if _spotify_running():
        return True
    try:
        if _OS == "Windows":
            import os
            os.startfile("spotify:")
        elif _OS == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        else:
            subprocess.Popen(["spotify"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    end = time.time() + wait
    while time.time() < end:
        if _spotify_running():
            time.sleep(2.0)
            return True
        time.sleep(0.4)
    return False


def _to_uri(text: str) -> str | None:
    t = str(text or "").strip()
    if t.startswith("spotify:"):
        return t
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(track|album|playlist|artist|show|episode)/([A-Za-z0-9]+)", t)
    return f"spotify:{m.group(1)}:{m.group(2)}" if m else None


def _basic() -> tuple[str, str] | None:
    c = cfg()
    cid, sec = c.get("spotify_client_id"), c.get("spotify_client_secret")
    return (cid, sec) if cid and sec else None


def _token_request(data: dict) -> dict:
    cid, sec = _basic()
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token", data=data,
                      headers={"Authorization": f"Basic {auth}"}, timeout=10)
    r.raise_for_status()
    return r.json()


def _app_token() -> str | None:
    if requests is None or not _basic():
        return None
    t = _TOKENS.get("app")
    if t and t[1] > time.time() + 30:
        return t[0]
    j = _token_request({"grant_type": "client_credentials"})
    _TOKENS["app"] = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    return j["access_token"]


def _user_token() -> str | None:
    rt = cfg().get("spotify_refresh_token")
    if requests is None or not _basic() or not rt:
        return None
    t = _TOKENS.get("user")
    if t and t[1] > time.time() + 30:
        return t[0]
    j = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    _TOKENS["user"] = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    return j["access_token"]


def _api(method: str, path: str, token: str, **kw):
    r = requests.request(method, f"https://api.spotify.com/v1{path}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10, **kw)
    return r


def _search(query: str, kind: str) -> tuple[str, str] | None:
    tok = _user_token() or _app_token()
    if not tok:
        return None
    r = _api("GET", "/search", tok, params={"q": query, "type": kind, "limit": 5})
    if r.status_code != 200:
        return None
    items = (r.json().get(kind + "s") or {}).get("items") or []
    items = [i for i in items if i]
    if not items:
        return None
    it = items[0]
    label = it.get("name", "")
    if kind == "track":
        label += " — " + ", ".join(a["name"] for a in it.get("artists", [])[:2])
    return it["uri"], label


def _my_playlist(query: str) -> tuple[str, str] | None:
    tok = _user_token()
    if not tok:
        return None
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in ("my", "the", "playlist", "mine", "a")]
    if not words:
        return None
    url, best = "/me/playlists?limit=50", None
    while url and best is None:
        r = _api("GET", url.replace("https://api.spotify.com/v1", ""), tok)
        if r.status_code != 200:
            break
        j = r.json()
        for pl in j.get("items") or []:
            name = (pl or {}).get("name", "").lower()
            if pl and all(w in name for w in words):
                best = (pl["uri"], pl["name"])
                break
        url = j.get("next")
    return best


def _play_uri(uri: str) -> str:
    tok = _user_token()
    body = {"uris": [uri]} if ":track:" in uri or ":episode:" in uri else {"context_uri": uri}
    if tok and ":search:" not in uri:
        for attempt in range(2):
            r = _api("PUT", "/me/player/play", tok, json=body)
            if r.status_code in (200, 202, 204):
                return "api"
            if r.status_code == 404 and attempt == 0:
                _launch_app()
                devs = _api("GET", "/me/player/devices", tok)
                try:
                    items = devs.json().get("devices") or []
                    if items:
                        _api("PUT", "/me/player", tok, json={"device_ids": [items[0]["id"]], "play": False})
                        time.sleep(1.0)
                except Exception:
                    pass
                continue
            break
    _launch_app()
    if _OS == "Darwin":
        _osa(f'tell application "Spotify" to play track "{uri}"')
    elif _OS == "Windows":
        import os
        os.startfile(uri if ":search:" in uri else uri + ":play")
    else:
        try:
            _mpris_open(uri)
        except Exception:
            subprocess.Popen(["xdg-open", uri])
    return "app"


def _mpris_open(uri: str) -> None:
    _run(["dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2",
          "org.mpris.MediaPlayer2.Player.OpenUri", f"string:{uri}"])


def _transport(action: str) -> None:
    if _OS == "Windows":
        if action in ("resume", "toggle"):
            _launch_app()
        _key({"toggle": "playpause", "pause": "playpause", "resume": "playpause", "next": "next", "previous": "prev"}[action])
    elif _OS == "Darwin":
        _osa('tell application "Spotify" to ' + {"toggle": "playpause", "pause": "pause", "resume": "play",
                                                  "next": "next track", "previous": "previous track"}[action])
    else:
        try:
            _playerctl({"toggle": "play-pause", "pause": "pause", "resume": "play", "next": "next", "previous": "previous"}[action])
        except RuntimeError:
            _mpris({"toggle": "PlayPause", "pause": "Pause", "resume": "Play", "next": "Next", "previous": "Previous"}[action])


def _state() -> str:
    try:
        if _OS == "Darwin":
            return _osa('tell application "Spotify" to player state as string').lower()
        if _OS != "Windows":
            return _playerctl("status").lower()
    except Exception:
        pass
    return ""


def _win_title() -> str:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found: list[str] = []
    try:
        import psutil
    except ImportError:
        return ""
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            if psutil.Process(pid.value).name().lower() != "spotify.exe":
                return True
        except Exception:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value and buf.value.lower() not in ("spotify", "spotify free", "spotify premium", "default ime", "msctfime ui"):
                found.append(buf.value)
        return True
    user32.EnumWindows(proc(cb), 0)
    return found[0] if found else ""


def _now_playing() -> str:
    if _OS == "Darwin":
        if not _spotify_running():
            return "Spotify isn't running, sir."
        out = _osa('tell application "Spotify" to (name of current track) & " | " & (artist of current track)')
        name, _, artist = out.partition(" | ")
        st = _state()
        return f"{'Playing' if 'play' in st else 'Paused on'}: {name} by {artist}." if name else "Nothing is playing, sir."
    if _OS == "Windows":
        t = _win_title()
        return f"Now playing: {t}." if t else "Nothing seems to be playing in Spotify, sir."
    out = _playerctl("metadata", "--format", "{{title}} | {{artist}}")
    name, _, artist = out.partition(" | ")
    return f"{'Playing' if 'play' in _state() else 'Paused on'}: {name} by {artist}." if name else "Nothing is playing, sir."


def _set_volume(level: int | None, delta: int = 0) -> str:
    if _OS == "Darwin":
        cur = int(_osa('tell application "Spotify" to sound volume') or 50)
        new = max(0, min(100, level if level is not None else cur + delta))
        _osa(f'tell application "Spotify" to set sound volume to {new}')
        return f"Spotify volume {new}%."
    if _OS == "Windows":
        try:
            from pycaw.pycaw import AudioUtilities
            for s in AudioUtilities.GetAllSessions():
                if s.Process and s.Process.name().lower() == "spotify.exe":
                    vol = s.SimpleAudioVolume
                    cur = int(round(vol.GetMasterVolume() * 100))
                    new = max(0, min(100, level if level is not None else cur + delta))
                    vol.SetMasterVolume(new / 100.0, None)
                    return f"Spotify volume {new}%."
        except Exception as e:
            print(f"[Spotify] pycaw: {e}")
        steps = max(1, round(abs(delta if level is None else 10) / 2))
        for _ in range(steps):
            _key("volup" if (level is None and delta > 0) or (level is not None and level >= 50) else "voldown")
        return "Adjusted the system volume, sir."
    cur = float(_playerctl("volume") or 0.5)
    new = max(0.0, min(1.0, level / 100.0 if level is not None else cur + delta / 100.0))
    _playerctl("volume", f"{new:.2f}")
    return f"Spotify volume {round(new * 100)}%."


def _rewind(seconds: int | None) -> str:
    if seconds:
        try:
            if _OS == "Darwin":
                _osa(f'tell application "Spotify" to set player position to ((player position) - {seconds})')
                return f"Went back {seconds} seconds."
            if _OS == "Linux":
                _playerctl("position", f"{seconds}-")
                return f"Went back {seconds} seconds."
            tok = _user_token()
            if tok:
                pr = _api("GET", "/me/player", tok).json()
                pos = max(0, int(pr.get("progress_ms", 0)) - seconds * 1000)
                _api("PUT", "/me/player/seek", tok, params={"position_ms": pos})
                return f"Went back {seconds} seconds."
        except Exception as e:
            print(f"[Spotify] seek: {e}")
    if _OS == "Darwin":
        _osa('tell application "Spotify" to set player position to 0')
    else:
        _transport("previous") if _OS != "Linux" else _playerctl("position", "0")
    return "Restarted the track, sir."


def _login(player) -> str:
    if requests is None or not _basic():
        return ("Sir, add 'spotify_client_id' and 'spotify_client_secret' (free at developer.spotify.com/dashboard) "
                "to config/api_keys.json, and register http://127.0.0.1:8888/callback as the Redirect URI. Then ask me to log in again.")
    port = int(cfg().get("spotify_redirect_port") or 8888)
    redirect = f"http://127.0.0.1:{port}/callback"
    got: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Jarvis is connected to Spotify. You can close this tab.</h2>")

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", port), H)
    srv.timeout = 1
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {"client_id": _basic()[0], "response_type": "code", "redirect_uri": redirect, "scope": SCOPES})
    import webbrowser
    webbrowser.open(url)
    end = time.time() + 120
    while time.time() < end and not got.get("code"):
        srv.handle_request()
    srv.server_close()
    if not got.get("code"):
        return "Spotify login timed out, sir."
    try:
        j = _token_request({"grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect})
        from memory.config_manager import _patch_config
        _patch_config(spotify_refresh_token=j["refresh_token"])
        _TOKENS["user"] = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    except Exception as e:
        return f"Spotify login failed, sir: {e}"
    return "Connected to your Spotify account, sir. I can now play your own playlists and liked songs."


def _play(p: dict, player) -> str:
    query = str(p.get("query") or "").strip()
    kind = str(p.get("type") or "").lower()
    if not query:
        _transport("resume")
        return "Resuming Spotify, sir."
    uri = _to_uri(query)
    label = query
    if uri is None:
        if kind in ("", "playlist") and re.search(r"\b(my|mine)\b", query.lower() + " " + str(p.get("scope") or "")):
            hit = _my_playlist(query)
            if hit:
                uri, label = hit
        order = [kind] if kind in ("track", "playlist", "album", "artist") else (
            ["playlist", "track"] if "playlist" in query.lower() else ["track", "playlist", "album", "artist"])
        q = re.sub(r"\b(playlist|song|track|album|my|play)\b", " ", query, flags=re.I).strip() or query
        for k in order:
            if uri:
                break
            try:
                hit = _search(q, k)
            except Exception as e:
                print(f"[Spotify] search: {e}")
                hit = None
            if hit:
                uri, label = hit
    if uri is None:
        uri = "spotify:search:" + urllib.parse.quote(query)
        _play_uri(uri)
        return (f"I opened a Spotify search for '{query}', sir. For one-step playback, add spotify_client_id and "
                "spotify_client_secret to the config.")
    how = _play_uri(uri)
    log(f"[Spotify] {uri} via {how}", player)
    return f"Playing {label} on Spotify, sir."


def spotify_controller(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "play").lower().strip()
    try:
        if action in ("play", "search"):
            return _play(p, player)
        if action in ("pause", "stop"):
            _transport("pause")
            return "Paused, sir."
        if action in ("resume", "continue"):
            _transport("resume")
            return "Resuming, sir."
        if action in ("toggle", "playpause"):
            _transport("toggle")
            return "Toggled playback, sir."
        if action in ("next", "skip"):
            _transport("next")
            return "Skipping to the next track, sir."
        if action in ("previous", "back", "prev"):
            _transport("previous")
            return "Going to the previous track, sir."
        if action in ("rewind", "restart"):
            return _rewind(int(p["seconds"]) if p.get("seconds") else None)
        if action in ("volume", "set_volume"):
            return _set_volume(max(0, min(100, int(p.get("level", 50)))))
        if action in ("volume_up", "louder"):
            return _set_volume(None, int(p.get("amount") or 10))
        if action in ("volume_down", "quieter"):
            return _set_volume(None, -int(p.get("amount") or 10))
        if action in ("now_playing", "current", "status"):
            return _now_playing()
        if action == "login":
            return _login(player)
        return "Unknown action. Available: play, pause, resume, next, previous, rewind, volume, volume_up, volume_down, now_playing, login."
    except Exception as e:
        return f"Sir, Spotify control failed: {e}"


TOOL = {
    "name": "spotify_controller",
    "description": (
        "Controls the Spotify desktop app: play a song, artist, album or playlist by name ('play my chill playlist', "
        "'play Believer'), pause, resume, skip, previous, rewind/restart, set or change the volume, and tell what "
        "is playing. Use for any music request that mentions Spotify or asks to play/pause/skip/change volume of music."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play | pause | resume | next | previous | rewind | volume | volume_up | volume_down | now_playing | login"},
            "query": {"type": "STRING", "description": "What to play: song, artist, album or playlist name, or a Spotify link"},
            "type": {"type": "STRING", "description": "track | playlist | album | artist (optional hint)"},
            "level": {"type": "INTEGER", "description": "Volume 0-100 for action=volume"},
            "amount": {"type": "INTEGER", "description": "Step for volume_up / volume_down (default 10)"},
            "seconds": {"type": "INTEGER", "description": "For rewind: how many seconds to go back (omit to restart the track)"},
        },
    },
    "handler": spotify_controller,
}

# by ASDcuber521
