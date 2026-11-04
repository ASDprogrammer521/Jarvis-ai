"""Video playback inside the Jarvis HUD, powered by mpv (python-mpv + libmpv).

mpv renders straight into a native window placed over the HUD media panel (GPU decoding, sound,
60 fps, perfect A/V sync, seeking). YouTube links are resolved with yt-dlp; plain-text requests
("a good minecraft video", "Parrot X2 new video") are searched on YouTube first.
Keys: Space pause · ←/→ seek 5 s · Shift+←/→ seek 5 min · ↑/↓ volume · F / F11 / double-click full screen · Esc leave full screen.
The HUD shows a control bar under the video (position/length, seek bar, -5 min / pause / +5 min / stop).
"""
from __future__ import annotations
import collections, os, queue, re, sys, threading, time
from pathlib import Path
from urllib.parse import quote, urlparse
_ACTIVE_LOCK=threading.Lock()
_ACTIVE_STOP: threading.Event | None=None
_ROOT=Path(__file__).resolve().parent.parent
_MPV_HELP=("HUD video needs mpv: 1) pip install python-mpv  2) put libmpv next to main.py "
           "(Windows: download libmpv from https://sourceforge.net/projects/mpv-player-windows/files/libmpv/ "
           "and copy libmpv-2.dll — or mpv-2.dll — into the Jarvis folder; Linux: sudo apt install libmpv2; macOS: brew install mpv).")

# Videos longer than this are played at most at _LONG_VIDEO_MAX_HEIGHT (multi-hour 1080p streams are heavy).
_LONG_VIDEO_SECS=3600
_LONG_VIDEO_MAX_HEIGHT=720

# Playback control: the HUD / key handlers put commands in _CMD_Q, the worker thread applies them to mpv and
# publishes the player state in _STATE (so the GUI thread never talks to libmpv directly).
_CMD_Q: "queue.Queue[tuple]"=queue.Queue()
_STATE_LOCK=threading.Lock()
_STATE={"active":False,"pos":0.0,"dur":0.0,"paused":False,"buffering":False,"cache":0.0,"drops":0}
# key -> (command, value); used for the mpv window's own key bindings (the HUD window has the same map in Qt)
_CONTROL_KEYS=(("SPACE","pause",None),("LEFT","seek",-5),("RIGHT","seek",5),("Shift+LEFT","seek",-300),
               ("Shift+RIGHT","seek",300),("UP","volume",5),("DOWN","volume",-5))

# ── player preferences (saved in config/api_keys.json as hud_*), current video info, "up next" list ──
_PREFS={"quality":0,"speed":1.0,"autoplay":False,"loop":False}   # quality: max height in px, 0 = auto
_META: dict={}
_SUGGEST: list=[]
_PLAYED: set=set()
_META_LOCK=threading.Lock()

def _load_prefs():
    try:
        from memory.config_manager import load_api_keys
        c=load_api_keys()
        _PREFS.update(quality=int(c.get("hud_quality",0) or 0),speed=float(c.get("hud_speed",1.0) or 1.0),
                      autoplay=bool(c.get("hud_autoplay",False)),loop=bool(c.get("hud_loop",False)))
    except Exception: pass

def get_prefs() -> dict:
    return dict(_PREFS)

def set_pref(key: str,value):
    if key not in _PREFS: return
    _PREFS[key]=value
    try:
        from memory.config_manager import _patch_config
        _patch_config(**{f"hud_{key}":value})
    except Exception: pass

def get_video_meta() -> dict:
    """Info about the current YouTube video: id, title, channel, channel_id, heights (available resolutions)."""
    with _META_LOCK: return dict(_META)

def get_suggestions() -> list:
    with _META_LOCK: return list(_SUGGEST)

def _set_meta(info: dict,source: str):
    heights=sorted({int(f["height"]) for f in (info.get("formats") or []) if f.get("height") and f.get("vcodec") not in (None,"none")})
    with _META_LOCK:
        _META.clear()
        _META.update(id=info.get("id") or "",title=info.get("title") or "",channel=info.get("channel") or info.get("uploader") or "",
                     channel_id=info.get("channel_id") or "",url=info.get("webpage_url") or source,heights=heights,
                     youtube=True,quality=_PREFS["quality"])
        if _META["id"]: _PLAYED.add(_META["id"])

def _fetch_suggestions(meta: dict,ui):
    """Related videos: a YouTube search on the current title (flat, fast) — shown under the video, click to play."""
    items=[]
    try:
        import yt_dlp
        q=re.sub(r"[\[\(].*?[\]\)]|#\w+","",meta.get("title") or "").strip() or (meta.get("channel") or "")
        with yt_dlp.YoutubeDL({"quiet":True,"no_warnings":True,"extract_flat":True,"skip_download":True}) as ydl:
            info=ydl.extract_info(f"ytsearch14:{q}",download=False)
        for e in (info.get("entries") or []):
            vid=e.get("id") or ""
            if not vid or vid==meta.get("id") or e.get("live_status") in ("is_live","is_upcoming"): continue
            dur=e.get("duration")
            if dur is not None and dur<45: continue
            items.append({"id":vid,"title":str(e.get("title") or "")[:90],"channel":str(e.get("channel") or e.get("uploader") or ""),
                          "duration":dur,"url":f"https://www.youtube.com/watch?v={vid}",
                          "thumb_url":f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
            if len(items)>=10: break
    except Exception as exc:
        _log(ui,f"MEDIA: couldn't load suggestions ({exc})")
    with _META_LOCK:
        if _META.get("id")!=meta.get("id"): return          # the user already moved on to another video
        _SUGGEST[:]=items
    try:
        import requests
        for it in items:
            try:
                r=requests.get(it["thumb_url"],timeout=6)
                if r.ok: it["thumb"]=r.content
            except Exception: pass
    except Exception: pass
    try:
        with _META_LOCK:
            if _META.get("id")!=meta.get("id"): return
        ui.media_suggestions(items)
    except Exception: pass

def _next_suggestion():
    for it in get_suggestions():
        if it["id"] not in _PLAYED: return it
    return None

_load_prefs()

def get_video_state() -> dict:
    """Snapshot of the current playback state (position/duration in seconds)."""
    with _STATE_LOCK: return dict(_STATE)

def video_control(cmd: str,value=None) -> bool:
    """Queue a control command: pause | play | seek (relative s) | seek_abs (s) | volume (delta). False if no video is active."""
    with _STATE_LOCK: active=_STATE["active"]
    if not active: return False
    _CMD_Q.put((cmd,value)); return True

def _apply_control(player,cmd: str,value):
    if cmd=="pause": player.pause=not bool(player.pause)
    elif cmd=="play": player.pause=False
    elif cmd=="seek": player.command("seek",str(float(value)),"relative")
    elif cmd=="seek_abs": player.command("seek",str(max(0.0,float(value))),"absolute")
    elif cmd=="volume": player.volume=max(0.0,min(130.0,float(player.volume or 100)+float(value)))
    elif cmd=="volume_abs": player.volume=max(0.0,min(130.0,float(value)))
    elif cmd=="mute": player.mute=not bool(player.mute)
    elif cmd=="speed":
        v=max(0.25,min(3.0,float(value))); player.speed=v; set_pref("speed",v)
    elif cmd=="loop":
        on=bool(value); player.loop_file="inf" if on else "no"; set_pref("loop",on)
    elif cmd=="autoplay": set_pref("autoplay",bool(value))

def _poll_state(player):
    def g(name,default=None):
        try:
            v=getattr(player,name)
            return default if v is None else v
        except Exception: return default
    drops=0
    for name in ("frame_drop_count","decoder_frame_drop_count"):
        try: drops+=int(g(name,0) or 0)
        except Exception: pass
    with _STATE_LOCK:
        _STATE.update(pos=float(g("time_pos",_STATE["pos"]) or 0),dur=float(g("duration",0) or 0),paused=bool(g("pause",False)),
                      buffering=bool(g("paused_for_cache",False)),cache=float(g("demuxer_cache_duration",0) or 0),drops=drops)

def _fmt_time(sec: float) -> str:
    sec=int(max(0,sec)); h,rem=divmod(sec,3600); m,s=divmod(rem,60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

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

def _resolve_stream(source: str,max_height: int | None=None) -> tuple[str, str | None, str | None]:
    """Return (video_url, audio_url, user_agent). audio_url is None when the source is a single file/stream."""
    if not _is_youtube(source): return source, None, None
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("YouTube HUD playback needs yt-dlp: pip install yt-dlp") from exc
    # YouTube serves video and audio separately; mpv plays them together (--audio-file).
    cap=_PREFS["quality"] if max_height is None else int(max_height)
    selectors=(f"bv*[height<={cap}]+ba/b[height<={cap}]/bv*+ba/b","bv*/b","best") if cap>0 else ("bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b","bv*/b","best")
    last_exc: Exception | None=None; info=None
    for fmt in selectors:
        opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":fmt,"format_sort":[f"res:{cap or 1080}","fps","vcodec:h264"]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(source,download=False)
            break
        except Exception as exc: last_exc=exc
    if info is None: raise RuntimeError(f"yt-dlp could not find a playable format. Update it with 'pip install -U yt-dlp'. ({last_exc})")
    _full_info=info
    if cap==0 and (info.get("duration") or 0)>_LONG_VIDEO_SECS and (info.get("height") or 0)>_LONG_VIDEO_MAX_HEIGHT:
        h=_LONG_VIDEO_MAX_HEIGHT  # long video: re-pick a lighter format; keep the first result if this fails
        opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
              "format_sort":[f"res:{h}","fps:30","vcodec:h264"]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(source,download=False)
        except Exception: pass
    try: _set_meta(_full_info if _full_info.get("formats") else info,source)
    except Exception: pass
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
    player=None; window_open=False; mpv_errors=collections.deque(maxlen=5)
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
        def _mpv_log(level,prefix,text):  # keep the last mpv errors so a failed/early-ended video can say why
            try:
                if str(level) in ("error","fatal"): mpv_errors.append(f"{prefix}: {str(text).strip()}"[:200])
            except Exception: pass
        try: player=mpv.MPV(log_handler=_mpv_log,loglevel="error",**opts)
        except TypeError: player=mpv.MPV(**opts)  # very old python-mpv without log_handler
        # Long streams: let ffmpeg reconnect when the connection drops (harmless if this build ignores it).
        try: player["stream-lavf-o"]="reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_delay_max=5"
        except Exception: pass
        state={"error":None}
        @player.event_callback("end-file")
        def _end(event):  # noqa: ANN001
            try:
                d=event.as_dict() if hasattr(event,"as_dict") else {}
                payload=d.get("event") if isinstance(d.get("event"),dict) else d
                reason=payload.get("reason",d.get("reason",""))
                if reason==4 or "error" in str(reason).lower(): state["error"]=str(payload.get("file_error") or payload.get("error") or payload)
            except Exception: pass
        def _key(cmd):
            def handler(key_state="d-",key_name="",key_char=""):
                if str(key_state)[:1] in ("d","p"):
                    try: ui.mpv_command(cmd)
                    except Exception: pass
            return handler
        def _ctl(cmd,value):  # Space / arrows while the mpv window itself has keyboard focus
            def handler(key_state="d-",key_name="",key_char=""):
                if str(key_state)[:1] in ("d","p","r"): _CMD_Q.put((cmd,value))
            return handler
        for key,cmd in (("f","fs"),("F11","fs"),("MBTN_LEFT_DBL","fs"),("ESC","esc")):
            try: player.register_key_binding(key,_key(cmd))
            except Exception: pass
        for key,cmd,value in _CONTROL_KEYS:
            try: player.register_key_binding(key,_ctl(cmd,value))
            except Exception: pass
        while not _CMD_Q.empty():  # drop commands left over from a previous video
            try: _CMD_Q.get_nowait()
            except queue.Empty: break
        with _STATE_LOCK: _STATE.update(active=True,pos=0.0,dur=0.0,paused=False,buffering=False,cache=0.0,drops=0)
        if audio_url and audio_url!=stream: player.loadfile(stream,**{"audio-file":f"%{len(audio_url.encode())}%{audio_url}"})  # %n% = length-prefixed value, safe for any characters
        else: player.loadfile(stream)
        _log(ui,f"MEDIA: HUD playback started — {title}")
        started=False; t0=time.monotonic(); last_poll=0.0
        current={"source":source,"title":title}
        try:
            player.speed=_PREFS["speed"]; player.loop_file="inf" if _PREFS["loop"] else "no"
        except Exception: pass
        def _announce():  # tell the HUD what is playing (title, channel, qualities) and load "up next"
            if _is_youtube(current["source"]): meta=get_video_meta()
            else:
                meta={"youtube":False}
                with _META_LOCK: _META.clear(); _SUGGEST[:]=[]
            meta["title"]=meta.get("title") or current["title"]; meta["prefs"]=get_prefs()
            try: ui.media_info(meta)
            except Exception: pass
            if meta.get("youtube"): threading.Thread(target=_fetch_suggestions,args=(meta,ui),daemon=True).start()
        def _switch(src,ttl,start=None):  # play another video in the same HUD window (next / suggestion / quality change)
            nonlocal started,t0
            stream_,audio_,_ua=_resolve_stream(src)
            kw={}
            if start and start>2: kw["start"]=str(int(start))
            if audio_ and audio_!=stream_: kw["audio-file"]=f"%{len(audio_.encode())}%{audio_}"
            player.loadfile(stream_,**kw)
            current["source"]=src; current["title"]=ttl or current["title"]
            started=False; t0=time.monotonic(); state["error"]=None
            with _STATE_LOCK: _STATE.update(pos=float(start or 0),dur=0.0,paused=False,buffering=False)
            _announce()
        _announce()
        while not stop_event.is_set():
            try: cmd,value=_CMD_Q.get(timeout=0.1)
            except queue.Empty: cmd=value=None
            if cmd in ("quality","play_url","next"):
                try:
                    if cmd=="quality":
                        set_pref("quality",int(value or 0)); _switch(current["source"],current["title"],start=get_video_state()["pos"])
                    elif cmd=="play_url": _switch(value[0],value[1])
                    else:
                        nxt=_next_suggestion()
                        if nxt: _switch(nxt["url"],nxt["title"])
                        else: _log(ui,"MEDIA: no next video suggestion yet")
                except Exception as exc: _log(ui,f"ERR: HUD video — {exc}")
            elif cmd is not None:
                try: _apply_control(player,cmd,value)
                except Exception: pass  # e.g. seek before the stream is ready
            now=time.monotonic()
            if cmd is None and now-last_poll<0.25: continue
            last_poll=now
            try: idle=bool(player.idle_active)
            except Exception: break  # mpv shut down (window closed)
            if state["error"]:
                detail=" | ".join(mpv_errors)
                raise RuntimeError(f"mpv could not play this video: {state['error']}"+(f" — {detail}" if detail else ""))
            if not idle: started=True
            elif started:
                nxt=_next_suggestion() if _PREFS["autoplay"] else None
                if nxt:  # autoplay: the video ended, go on with the next suggestion
                    try: _switch(nxt["url"],nxt["title"]); continue
                    except Exception as exc: _log(ui,f"ERR: autoplay failed — {exc}")
                break
            elif now-t0>60: raise RuntimeError("mpv could not open the video (timeout).")
            _poll_state(player)
        with _STATE_LOCK: end_pos,end_dur=_STATE["pos"],_STATE["dur"]
        if stop_event.is_set(): _log(ui,f"MEDIA: HUD playback stopped — {title}")
        elif end_dur and end_pos<end_dur-5:  # the video ended long before its end: say why
            detail=" | ".join(mpv_errors)
            _log(ui,f"ERR: HUD video ended early at {_fmt_time(end_pos)} of {_fmt_time(end_dur)}"+(f" — {detail}" if detail else ""))
        else: _log(ui,f"MEDIA: HUD playback ended — {title}")
    except ImportError: _log(ui,"ERR: HUD video playback failed — python-mpv is not installed. "+_MPV_HELP)
    except OSError as exc: _log(ui,f"ERR: HUD video playback failed — libmpv was not found ({exc}). "+_MPV_HELP)
    except Exception as exc: _log(ui,f"ERR: HUD video playback failed — {exc}")
    finally:
        with _STATE_LOCK: _STATE.update(active=False,pos=0.0,dur=0.0,paused=False,buffering=False,cache=0.0,drops=0)
        if player is not None:
            try: player.terminate()
            except Exception: pass
        if window_open:
            try: ui.stop_mpv_window()
            except Exception: pass
        global _ACTIVE_STOP
        with _ACTIVE_LOCK:
            if _ACTIVE_STOP is stop_event: _ACTIVE_STOP=None

_VOICE_ACTIONS={"pause","resume","toggle","seek","forward","back","rewind","seek_to","volume_up","volume_down","set_volume","mute","unmute","fullscreen","exit_fullscreen","speed","status","like","dislike","unlike","subscribe","connect_youtube","next","suggestions","play_suggestion","quality","autoplay","loop"}

def _voice_control(action: str,params: dict,player) -> str:
    """Spoken control of the HUD player: 'pause', 'skip 2 minutes', 'louder', 'full screen', 'how much is left?'."""
    st=get_video_state()
    if not st.get("active"): return "No HUD video is playing right now."
    def num(key,default):
        try: return float(params.get(key) if params.get(key) is not None else default)
        except (TypeError,ValueError): return float(default)
    meta=get_video_meta()
    if action=="connect_youtube":
        from actions import youtube_actions as ya
        return ya.connect()
    if action in ("like","dislike","unlike","subscribe"):
        if not meta.get("youtube"): return "This isn't a YouTube video, so I can't rate or subscribe."
        from actions import youtube_actions as ya
        if action=="subscribe": return ya.subscribe(meta.get("id",""),meta.get("channel",""))
        return ya.rate(meta.get("id",""),{"like":"like","dislike":"dislike","unlike":"none"}[action])
    if action=="next":
        nxt=_next_suggestion()
        if not nxt: return "I don't have a next video ready yet."
        video_control("next"); return f"Playing next: {nxt['title']}"
    if action=="suggestions":
        items=[x for x in get_suggestions()][:6]
        return ("Up next:\n"+"\n".join(f"{i}. {x['title']}" for i,x in enumerate(items,1))) if items else "No suggestions loaded yet."
    if action=="play_suggestion":
        items=get_suggestions(); i=int(num("amount",1))-1
        if not 0<=i<len(items): return "I don't have a suggestion with that number."
        video_control("play_url",(items[i]["url"],items[i]["title"])); return f"Playing: {items[i]['title']}"
    if action=="quality":
        h=int(num("amount",0)); video_control("quality",h); return f"Switching quality to {h}p…" if h else "Quality set to auto."
    if action in ("autoplay","loop"):
        on=bool(params.get("enabled",True)); video_control(action,on); return f"{action.title()} {'on' if on else 'off'}."
    if action=="status":
        pos,dur=st.get("pos",0.0),st.get("dur",0.0)
        left=f", {_fmt_time(max(0.0,dur-pos))} left" if dur else ""
        return f"{'Paused' if st.get('paused') else 'Playing'} at {_fmt_time(pos)}" + (f" of {_fmt_time(dur)}" if dur else "") + left + "."
    if action=="pause": video_control("pause") if not st.get("paused") else None; return "Paused."
    if action in ("resume",): video_control("play"); return "Playing."
    if action=="toggle": video_control("pause"); return "Resumed." if st.get("paused") else "Paused."
    if action in ("seek","forward","back","rewind"):
        secs=num("seconds",30 if action in ("forward","back","rewind") else 10)
        if action in ("back","rewind"): secs=-abs(secs)
        elif action=="forward": secs=abs(secs)
        video_control("seek",secs); return f"Skipped {'forward' if secs>0 else 'back'} {abs(int(secs))} seconds."
    if action=="seek_to":
        video_control("seek_abs",num("seconds",0)); return f"Jumped to {_fmt_time(num('seconds',0))}."
    if action in ("volume_up","volume_down"):
        step=abs(num("amount",10)); video_control("volume",step if action=="volume_up" else -step)
        return "Volume up." if action=="volume_up" else "Volume down."
    if action=="set_volume":
        v=max(0.0,min(100.0,num("amount",50))); video_control("volume_abs",v); return f"Volume set to {int(v)}%."
    if action in ("mute","unmute"): video_control("mute"); return "Toggled mute."
    if action=="speed":
        v=num("amount",1.0); video_control("speed",v); return f"Playback speed {v:g}x."
    if action in ("fullscreen","exit_fullscreen"):
        ui=_ui_for(player)
        if ui is None: return "The HUD isn't available."
        ui.mpv_command("fs" if action=="fullscreen" else "esc"); return "Full screen toggled." if action=="fullscreen" else "Left full screen."
    return "Unknown control."

def play_hud_video(parameters: dict,response=None,player=None,session_memory=None) -> str:
    params=parameters or {}; action=str(params.get("action","play")).strip().lower()
    if action=="stop": return stop_hud_video()
    if action in _VOICE_ACTIONS: return _voice_control(action,params,player)
    if action!="play": return "Unknown action. Use action='play', 'stop', or a playback control (pause, resume, seek, seek_to, volume_up, volume_down, set_volume, mute, fullscreen, speed, status)."
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
    return "HUD video playback started in the background (mpv, with sound). Space pauses, left/right arrows seek 5 s (Shift = 5 min), up/down change volume, F or double-click toggles full screen; the HUD has a control bar under the video. Use action='stop' to stop it. The stream and delivery are not verified."

TOOL={"name":"play_hud_video","description":"WATCH a video in Jarvis's HUD (mpv player with sound, seeking, 60 fps and full screen). Use this whenever the user asks to play/put on/watch a video: pass a YouTube link or local file in source, OR just describe it in query (e.g. 'good minecraft video', 'Parrot X2 new video') and Jarvis finds one on YouTube; set latest=true when they want the newest. Videos of any length work, including multi-hour ones (videos over 1 hour are played at up to 720p). The HUD shows a control bar under the video; Space pauses, arrows seek. Use action='stop' to stop playback. You can also CONTROL the video by voice with the same tool: action=pause | resume | seek (seconds, negative = back) | forward | back (seconds) | seek_to (absolute seconds) | volume_up | volume_down (amount) | set_volume (amount 0-100) | mute | speed (amount, e.g. 1.5) | fullscreen | exit_fullscreen | status (position / time left) | like | dislike | unlike | subscribe (these use a browser window; the first time the user signs in to YouTube there — action=connect_youtube does that on request) | next | suggestions (list up-next videos) | play_suggestion (amount=number) | quality (amount=height like 720, 0=auto) | autoplay / loop (enabled=true/false). Examples: 'pause' → pause; 'skip 2 minutes' → forward seconds=120; 'go back 30 seconds' → back seconds=30; 'louder' → volume_up; 'make it full screen' → fullscreen; 'how much is left?' → status; 'play from minute 10' → seek_to seconds=600.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"play (default) | stop | like | dislike | unlike | subscribe | connect_youtube | next | suggestions | play_suggestion | quality | autoplay | loop | pause | resume | seek | forward | back | seek_to | volume_up | volume_down | set_volume | mute | speed | fullscreen | exit_fullscreen | status"},"seconds":{"type":"NUMBER","description":"For seek/forward/back: seconds to skip; for seek_to: absolute position in seconds"},"enabled":{"type":"BOOLEAN","description":"autoplay / loop: on or off"},"amount":{"type":"NUMBER","description":"volume_up/down: step in %, set_volume: 0-100, speed: multiplier like 1.5"},"source":{"type":"STRING","description":"Local file path or direct HTTP(S)/YouTube URL"},"query":{"type":"STRING","description":"What to watch, in plain words; Jarvis searches YouTube and plays the best match"},"latest":{"type":"BOOLEAN","description":"With query: pick the newest upload instead of the most relevant"},"title":{"type":"STRING","description":"Optional short HUD title"}},"required":[]},"handler":play_hud_video}

#by ASDcuber521
