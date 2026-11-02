"""Video playback inside the Jarvis HUD, powered by mpv (python-mpv + libmpv).

mpv renders straight into a native window placed over the HUD media panel (GPU decoding, sound,
60 fps, perfect A/V sync, seeking). YouTube links are resolved with yt-dlp; plain-text requests
("a good minecraft video", "Parrot X2 new video") are searched on YouTube first.
Keys while the video has focus: Space pause · ←/→ seek 5 s · ↑/↓ volume · F / F11 / double-click full screen · Esc leave full screen.
"""
from __future__ import annotations
import os, re, sys, threading, time
from pathlib import Path
from urllib.parse import quote, urlparse
_ACTIVE_LOCK=threading.Lock()
_ACTIVE_STOP: threading.Event | None=None
_ROOT=Path(__file__).resolve().parent.parent
_MPV_HELP=("HUD video needs mpv: 1) pip install python-mpv  2) put libmpv next to main.py "
           "(Windows: download libmpv from https://sourceforge.net/projects/mpv-player-windows/files/libmpv/ "
           "and copy libmpv-2.dll — or mpv-2.dll — into the Jarvis folder; Linux: sudo apt install libmpv2; macOS: brew install mpv).")

def _import_mpv():
    """Import python-mpv, letting a libmpv DLL that sits in the Jarvis folder be found."""
    if sys.platform=="win32":
        for folder in (_ROOT,_ROOT/"config",Path.cwd()):
            if folder.is_dir():
                try: os.add_dll_directory(str(folder))
                except (AttributeError,OSError): pass
                os.environ["PATH"]=str(folder)+os.pathsep+os.environ.get("PATH","")
    import mpv
    return mpv

def _download_libmpv(log=lambda m: None) -> Path:
    """Windows: fetch libmpv-2.dll (one time, ~30 MB) from the shinchiro mpv builds into the Jarvis folder."""
    import json, shutil, subprocess, tempfile, urllib.request
    target=_ROOT/"libmpv-2.dll"
    if target.is_file(): return target
    api="https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
    headers={"User-Agent":"Jarvis-AI","Accept":"application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=30) as r: release=json.load(r)
    assets=[a for a in release.get("assets",[]) if re.match(r"^mpv-dev-x86_64-(?!v3)\S+\.7z$",a.get("name",""))]
    if not assets: raise RuntimeError("no libmpv build found in the latest release")
    asset=assets[0]; log(f"MEDIA: Downloading libmpv (one time, {asset.get('size',0)//1048576} MB) — {asset['name']}")
    with tempfile.TemporaryDirectory() as tmp:
        archive=Path(tmp)/asset["name"]; out=Path(tmp)/"out"; out.mkdir()
        req=urllib.request.Request(asset["browser_download_url"],headers={"User-Agent":"Jarvis-AI"})
        with urllib.request.urlopen(req,timeout=120) as r, open(archive,"wb") as f: shutil.copyfileobj(r,f)
        extracted=False
        tar=shutil.which("tar")  # Windows 10+ ships bsdtar, which reads .7z
        if tar:
            extracted=subprocess.run([tar,"-xf",str(archive),"-C",str(out)],capture_output=True).returncode==0
        if not extracted:
            try:
                import py7zr
                with py7zr.SevenZipFile(archive) as z: z.extractall(out)
                extracted=True
            except Exception: pass
        if not extracted: raise RuntimeError("could not unpack the .7z (install 7-Zip or run: pip install py7zr)")
        dll=next(out.rglob("libmpv-2.dll"),None) or next(out.rglob("mpv-2.dll"),None)
        if dll is None: raise RuntimeError("libmpv-2.dll was not inside the archive")
        shutil.copyfile(dll,target)
    log("MEDIA: libmpv installed")
    return target

def _mpv_problem() -> str | None:
    try: _import_mpv(); return None
    except ImportError: return "python-mpv is not installed. "+_MPV_HELP
    except OSError as exc:
        if sys.platform=="win32": return None  # the worker downloads libmpv automatically
        return f"libmpv was not found ({exc}). "+_MPV_HELP

def _is_youtube(source: str) -> bool:
    host=(urlparse(source).hostname or "").lower().removeprefix("www.")
    return host in {"youtube.com","youtu.be","m.youtube.com","music.youtube.com","youtube-nocookie.com"}

def _looks_like_path(value: str) -> bool:
    return bool(re.search(r"[\\/]",value) or re.search(r"\.(mp4|mkv|webm|avi|mov|m4v|flv|wmv|ts)$",value,re.IGNORECASE))

def _validate_source(source: str) -> str:
    value=str(source or "").strip()
    if not value or len(value)>2048: raise ValueError("Provide a video file path, an HTTP(S) URL, or a search query (max 2048 characters).")
    if not re.match(r"^[a-z][a-z0-9+.-]*://",value,re.IGNORECASE) and not _looks_like_path(value):
        return "search:"+value  # plain words -> search YouTube
    if re.match(r"^https?://",value,re.IGNORECASE):
        parsed=urlparse(value)
        if not parsed.hostname or parsed.username or parsed.password: raise ValueError("The video URL must have a host and no embedded credentials.")
        return value
    if "://" in value: raise ValueError("Only local files and HTTP(S) video URLs are supported.")
    path=Path(value).expanduser()
    if not path.is_file(): raise ValueError(f"Local video file was not found: {path}")
    return str(path.resolve())

def _search_video(query: str,latest: bool=False) -> tuple[str,str]:
    """Find a YouTube video for a text query. Returns (watch_url, title)."""
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("Video search needs yt-dlp: pip install yt-dlp") from exc
    # Try several search routes: some yt-dlp builds don't know the 'ytsearchdate' prefix.
    q=quote(query); routes=[]
    if latest: routes+=[f"https://www.youtube.com/results?search_query={q}&sp=CAI%3D",f"ytsearchdate10:{query}"]
    routes+=[f"ytsearch10:{query}",f"https://www.youtube.com/results?search_query={q}"]
    opts={"quiet":True,"no_warnings":True,"extract_flat":True,"skip_download":True}
    entries=[]; last_exc: Exception | None=None
    for route in routes:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(route,download=False)
            entries=[e for e in (info.get("entries") or []) if e and (e.get("id") or e.get("url"))]
            if entries: break
        except Exception as exc: last_exc=exc
    if not entries: raise RuntimeError(f"No YouTube results for: {query}. Update yt-dlp with 'pip install -U yt-dlp'. ({last_exc})")
    def ok(e,max_len):
        dur=e.get("duration")
        return e.get("live_status") not in ("is_live","is_upcoming") and (dur is None or 45<=dur<=max_len)
    # prefer ordinary videos (up to 2 h) but long ones (4 h and more) are fine when nothing else matches
    pick=next((e for e in entries if ok(e,2*3600)),None) or next((e for e in entries if ok(e,10**9)),entries[0])
    url=pick.get("url") or f"https://www.youtube.com/watch?v={pick.get('id')}"
    if not url.startswith("http"): url=f"https://www.youtube.com/watch?v={pick.get('id') or url}"
    return url,str(pick.get("title") or query)

def _resolve_stream(source: str) -> tuple[str, str | None, str | None]:
    """Return (video_url, audio_url, user_agent). audio_url is None when the source is a single file/stream."""
    if not _is_youtube(source): return source, None, None
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("YouTube HUD playback needs yt-dlp: pip install yt-dlp") from exc
    # YouTube serves video and audio separately; mpv plays them together (--audio-file).
    selectors=("bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b","bv*/b","best")
    last_exc: Exception | None=None; info=None
    for fmt in selectors:
        opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":fmt,"format_sort":["res:1080","fps","vcodec:h264"]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(source,download=False)
            break
        except Exception as exc: last_exc=exc
    if info is None: raise RuntimeError(f"yt-dlp could not find a playable format. Update it with 'pip install -U yt-dlp'. ({last_exc})")
    fmts=info.get("requested_formats") or info.get("requested_downloads") or [info]
    def _url(f):
        u=f.get("url"); return u if isinstance(u,str) and u.startswith(("http://","https://")) else None
    video=next((_url(f) for f in fmts if f.get("vcodec") not in (None,"none") and _url(f)),None)
    audio=next((_url(f) for f in fmts if f.get("acodec") not in (None,"none") and f.get("vcodec") in (None,"none") and _url(f)),None)
    if not video: video=_url(info)
    if not video: raise RuntimeError("Could not resolve a playable YouTube stream.")
    ua=next((f.get("http_headers",{}).get("User-Agent") for f in fmts if f.get("http_headers")),None) or (info.get("http_headers") or {}).get("User-Agent")
    return video, audio, ua

def stop_hud_video() -> str:
    with _ACTIVE_LOCK: event=_ACTIVE_STOP
    if event is None: return "No HUD video is currently playing."
    event.set(); return "HUD video stop requested."

def _ui_for(player):
    if player is None: return None
    if callable(getattr(player,"start_mpv_window",None)): return player
    ui=getattr(player,"ui",None)
    return ui if callable(getattr(ui,"start_mpv_window",None)) else None

def _log(ui,message: str):
    try:
        if ui is not None: ui.write_log(message)
    except Exception: pass

def _play_worker(source: str,title: str,ui,stop_event: threading.Event):
    player=None; window_open=False
    try:
        try: mpv=_import_mpv()
        except OSError:
            if sys.platform!="win32": raise
            try: _download_libmpv(lambda m: _log(ui,m))
            except Exception as exc: raise RuntimeError(f"libmpv download failed ({exc}). "+_MPV_HELP) from exc
            mpv=_import_mpv()
        if stop_event.is_set(): return
        if source.startswith("search:"):
            latest=source.startswith("search:latest:")
            query=source.split(":",2)[2] if latest else source[len("search:"):]
            _log(ui,f"MEDIA: Searching YouTube — {query}")
            source,found=_search_video(query,latest)
            if not title or title==query[:60]: title=found[:60]
            _log(ui,f"MEDIA: Found — {found}")
        if stop_event.is_set(): return
        stream,audio_url,ua=_resolve_stream(source)
        if stop_event.is_set(): return
        # The HUD creates the native window mpv draws into (must happen on the GUI thread).
        result={"ready":threading.Event(),"wid":None,"error":None}
        window_open=True; ui.start_mpv_window(title,result)
        if not result["ready"].wait(8) or result["error"] or not result["wid"]:
            raise RuntimeError(f"Could not create the HUD video window ({result['error'] or 'timeout'}).")
        try:
            import locale; locale.setlocale(locale.LC_NUMERIC,"C")  # libmpv requires the C numeric locale
        except Exception: pass
        opts=dict(wid=str(result["wid"]),input_default_bindings=True,input_vo_keyboard=True,osc=False,ytdl=False,idle="yes",
                  hwdec="auto-safe",keep_open="no",cache="yes",demuxer_max_bytes="400MiB",demuxer_max_back_bytes="150MiB",
                  network_timeout=30,volume=100)
        if ua: opts["user_agent"]=ua
        player=mpv.MPV(**opts)
        state={"error":None}
        @player.event_callback("end-file")
        def _end(event):  # noqa: ANN001
            try:
                d=event.as_dict() if hasattr(event,"as_dict") else {}
                if "error" in str(d.get("reason","")).lower(): state["error"]=str(d.get("file_error") or d)
            except Exception: pass
        def _key(cmd):
            def handler(key_state="d-",key_name="",key_char=""):
                if str(key_state)[:1] in ("d","p"):
                    try: ui.mpv_command(cmd)
                    except Exception: pass
            return handler
        for key,cmd in (("f","fs"),("F11","fs"),("MBTN_LEFT_DBL","fs"),("ESC","esc")):
            try: player.register_key_binding(key,_key(cmd))
            except Exception: pass
        if audio_url and audio_url!=stream: player.loadfile(stream,**{"audio-file":f"%{len(audio_url.encode())}%{audio_url}"})  # %n% = length-prefixed value, safe for any characters
        else: player.loadfile(stream)
        _log(ui,f"MEDIA: HUD playback started — {title}")
        started=False; t0=time.monotonic()
        while not stop_event.is_set():
            if stop_event.wait(0.25): break
            try: idle=bool(player.idle_active)
            except Exception: break  # mpv shut down (window closed)
            if state["error"] and not started: raise RuntimeError(f"mpv could not play this video: {state['error']}")
            if not idle: started=True
            elif started: break
            elif time.monotonic()-t0>60: raise RuntimeError("mpv could not open the video (timeout).")
        _log(ui,f"MEDIA: HUD playback {'stopped' if stop_event.is_set() else 'ended'} — {title}")
    except ImportError: _log(ui,"ERR: HUD video playback failed — python-mpv is not installed. "+_MPV_HELP)
    except OSError as exc: _log(ui,f"ERR: HUD video playback failed — libmpv was not found ({exc}). "+_MPV_HELP)
    except Exception as exc: _log(ui,f"ERR: HUD video playback failed — {exc}")
    finally:
        if player is not None:
            try: player.terminate()
            except Exception: pass
        if window_open:
            try: ui.stop_mpv_window()
            except Exception: pass
        global _ACTIVE_STOP
        with _ACTIVE_LOCK:
            if _ACTIVE_STOP is stop_event: _ACTIVE_STOP=None

def play_hud_video(parameters: dict,response=None,player=None,session_memory=None) -> str:
    params=parameters or {}; action=str(params.get("action","play")).strip().lower()
    if action=="stop": return stop_hud_video()
    if action!="play": return "Unknown action. Use action='play' or action='stop'."
    query=str(params.get("query") or "").strip()
    try: source=_validate_source(query or params.get("source",""))
    except Exception as exc: return str(exc)
    if source.startswith("search:") and bool(params.get("latest")): source="search:latest:"+source[len("search:"):]
    ui=_ui_for(player)
    if ui is None: return "HUD video cannot start because the media panel is unavailable. Nothing was opened."
    if bool(getattr(getattr(ui,"_win",None),"_cam_run",False)): return "The HUD media panel is in camera mode. Close the camera panel before starting video."
    problem=_mpv_problem()
    if problem: return problem
    if _is_youtube(source) or source.startswith("search:"):
        try: import yt_dlp # noqa: F401
        except ImportError: return "YouTube HUD playback needs yt-dlp: pip install yt-dlp"
    if source.startswith("search:"): default_title=source.split(":",2)[2] if source.startswith("search:latest:") else source[len("search:"):]
    else: default_title=Path(urlparse(source).path).name
    title=str(params.get("title") or default_title or "HUD VIDEO").strip()[:60] or "HUD VIDEO"
    global _ACTIVE_STOP
    stop_hud_video(); event=threading.Event()
    with _ACTIVE_LOCK: _ACTIVE_STOP=event
    worker=threading.Thread(target=_play_worker,args=(source,title,ui,event),daemon=True,name="jarvis-hud-video")
    try: worker.start()
    except Exception as exc:
        with _ACTIVE_LOCK:
            if _ACTIVE_STOP is event: _ACTIVE_STOP=None
        return f"Could not start HUD video playback: {exc}"
    return "HUD video playback started in the background (mpv, with sound). Space pauses, arrow keys seek and change volume, F or double-click toggles full screen. Use action='stop' to stop it. The stream and delivery are not verified."

TOOL={"name":"play_hud_video","description":"WATCH a video in Jarvis's HUD (mpv player with sound, seeking, 60 fps and full screen). Use this whenever the user asks to play/put on/watch a video: pass a YouTube link or local file in source, OR just describe it in query (e.g. 'good minecraft video', 'Parrot X2 new video') and Jarvis finds one on YouTube; set latest=true when they want the newest. Videos of any length work, including multi-hour ones. Use action='stop' to stop playback.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"play (default) or stop"},"source":{"type":"STRING","description":"Local file path or direct HTTP(S)/YouTube URL"},"query":{"type":"STRING","description":"What to watch, in plain words; Jarvis searches YouTube and plays the best match"},"latest":{"type":"BOOLEAN","description":"With query: pick the newest upload instead of the most relevant"},"title":{"type":"STRING","description":"Optional short HUD title"}},"required":[]},"handler":play_hud_video}

#by ASDcuber521
