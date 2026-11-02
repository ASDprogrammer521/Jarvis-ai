"""Local/direct-URL/YouTube video playback in the Jarvis HUD (audio via ffplay when available)."""
from __future__ import annotations
import os, re, shutil, subprocess, threading, time
from pathlib import Path
from urllib.parse import quote, urlparse
_ACTIVE_LOCK=threading.Lock()
_ACTIVE_STOP: threading.Event | None=None

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
    except ImportError as exc: raise RuntimeError("Video search needs optional yt-dlp: pip install yt-dlp") from exc
    # Try several search routes: some yt-dlp builds don't know the 'ytsearchdate' prefix.
    q=quote(query)
    routes=[]
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
    def ok(e):
        dur=e.get("duration")
        return e.get("live_status") not in ("is_live","is_upcoming") and (dur is None or 45<=dur<=4*3600)
    pick=next((e for e in entries if ok(e)),entries[0])
    url=pick.get("url") or f"https://www.youtube.com/watch?v={pick.get('id')}"
    if not url.startswith("http"): url=f"https://www.youtube.com/watch?v={pick.get('id') or url}"
    return url,str(pick.get("title") or query)

def _resolve_stream(source: str) -> tuple[str, str | None, str | None]:
    """Return (video_url, audio_url, user_agent). audio_url may equal video_url (muxed) or be None."""
    if not _is_youtube(source): return source, source, None
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("YouTube HUD playback needs optional yt-dlp: pip install yt-dlp") from exc
    # YouTube rarely offers muxed formats now, so ask for separate video + audio streams.
    selectors=("bv*[height<=720]+ba/b[height<=720]/bv*+ba/b","bv*/b","best")
    last_exc: Exception | None=None; info=None
    for fmt in selectors:
        opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":fmt,"format_sort":["res:720","fps","vcodec:h264"]}
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
    if video and not audio:  # muxed single format carries its own audio
        muxed=next((f for f in fmts if _url(f)==video),{})
        if muxed.get("acodec") not in (None,"none"): audio=video
    if not video: video=_url(info)
    if not video: raise RuntimeError("Could not resolve a playable YouTube stream.")
    ua=next((f.get("http_headers",{}).get("User-Agent") for f in fmts if f.get("http_headers")),None) or (info.get("http_headers") or {}).get("User-Agent")
    return video, audio, ua

def _start_audio(url: str | None,ua: str | None=None):
    """Play the audio track with ffplay (no window). Returns the process or None."""
    exe=shutil.which("ffplay")
    if not url or not exe: return None
    try:
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        cmd=[exe,"-nodisp","-vn","-autoexit","-loglevel","quiet"]+(["-user_agent",ua] if ua and url.startswith("http") else [])+[url]
        return subprocess.Popen(cmd,
                                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
    except Exception: return None

def _pump_ffmpeg(stream: str,ua: str | None,ui,title: str,stop_event: threading.Event,on_start) -> bool:
    """Decode with ffmpeg (handles reconnects/headers, real-time pace) and push JPEG frames to the HUD.
    Returns False if ffmpeg is unavailable or produced nothing (caller falls back to OpenCV)."""
    exe=shutil.which("ffmpeg")
    if not exe: return False
    cmd=[exe,"-loglevel","error","-nostdin"]
    if stream.startswith("http"):
        cmd+=["-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5"]
        if ua: cmd+=["-user_agent",ua]
    cmd+=["-re","-i",stream,"-an","-sn","-vf","scale='min(1600,iw)':-2","-q:v","4","-f","image2pipe","-vcodec","mjpeg","-"]
    proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    frames=0; buf=b""; started=False
    try:
        while not stop_event.is_set():
            chunk=proc.stdout.read(65536)
            if not chunk: break
            buf+=chunk
            while True:
                a=buf.find(b"\xff\xd8")
                if a<0: buf=b""; break
                b=buf.find(b"\xff\xd9",a+2)
                if b<0: buf=buf[a:]; break
                if not started: started=True; on_start()
                ui.show_media_frame(buf[a:b+2],title); frames+=1; buf=buf[b+2:]
    finally:
        try: proc.kill()
        except Exception: pass
        try: proc.stdout.close(); proc.wait(timeout=2)
        except Exception: pass
    return frames>0

def stop_hud_video() -> str:
    with _ACTIVE_LOCK: event=_ACTIVE_STOP
    if event is None: return "No HUD video is currently playing."
    event.set(); return "HUD video stop requested."

def _ui_for(player):
    if player is None: return None
    if callable(getattr(player,"show_media_frame",None)): return player
    ui=getattr(player,"ui",None)
    return ui if callable(getattr(ui,"show_media_frame",None)) else None

def _log(ui,message: str):
    try:
        if ui is not None: ui.write_log(message)
    except Exception: pass

def _play_worker(source: str,title: str,ui,stop_event: threading.Event):
    capture=None; audio_proc=None
    try:
        if source.startswith("search:"):
            latest=source.startswith("search:latest:")
            query=source.split(":",2)[2] if latest else source[len("search:"):]
            _log(ui,f"MEDIA: Searching YouTube — {query}")
            source,found=_search_video(query,latest)
            if not title or title==query[:60]: title=found[:60]
            _log(ui,f"MEDIA: Found — {found}")
        if stop_event.is_set(): return
        stream,audio_url,ua=_resolve_stream(source)
        def _begin():
            nonlocal audio_proc
            audio_proc=_start_audio(audio_url,ua)
            note="" if audio_proc else " (no sound: install ffmpeg/ffplay for audio)"
            _log(ui,f"MEDIA: HUD playback started — {title}{note}")
        if os.environ.get("JARVIS_HUD_BACKEND","").lower()!="ffmpeg" and callable(getattr(ui,"start_native_video",None)):
            # Built-in Qt media engine (bundled with PyQt6, uses the system audio): no ffmpeg install needed.
            result={"done":threading.Event(),"error":None,"frames":0}
            _log(ui,f"MEDIA: HUD playback started — {title}")
            ui.start_native_video(stream,audio_url,title,result)
            while not stop_event.is_set() and not result["done"].is_set(): stop_event.wait(0.2)
            try: ui.stop_native_video()
            except Exception: pass
            if stop_event.is_set() or not result["error"] or result["frames"]>0:
                _log(ui,f"MEDIA: HUD playback {'stopped' if stop_event.is_set() else 'ended'} — {title}"); return
            _log(ui,f"MEDIA: Built-in player failed ({result['error']}); trying ffmpeg")
        if _pump_ffmpeg(stream,ua,ui,title,stop_event,_begin):
            _log(ui,f"MEDIA: HUD playback {'stopped' if stop_event.is_set() else 'ended'} — {title}"); return
        if stop_event.is_set(): return
        import cv2  # fallback when ffmpeg is missing or could not open the stream
        capture=cv2.VideoCapture(); params=[]
        for prop_name,timeout in (("CAP_PROP_OPEN_TIMEOUT_MSEC",5000),("CAP_PROP_READ_TIMEOUT_MSEC",3000)):
            prop=getattr(cv2,prop_name,None)
            if prop is not None: params.extend([prop,timeout])
        try:
            if params and hasattr(cv2,"CAP_FFMPEG"): capture.open(stream,cv2.CAP_FFMPEG,params)
            else: capture.open(stream)
        except (TypeError,cv2.error):
            capture.release(); capture=cv2.VideoCapture(stream)
        if not capture.isOpened(): raise RuntimeError("OpenCV could not open the video; check URL, codec, and FFmpeg support.")
        fps=capture.get(getattr(cv2,"CAP_PROP_FPS",5)) or 24.0
        if not (1.0<=fps<=120.0): fps=24.0
        _begin()
        t0=time.monotonic(); idx=0; min_gap=1.0/60.0; last_shown=0.0
        while not stop_event.is_set():
            # Keep video on the wall clock so it stays in sync with the audio: skip frames when late.
            expected=int((time.monotonic()-t0)*fps)
            while idx<expected and not stop_event.is_set():
                if not capture.grab(): expected=-1; break
                idx+=1
            if expected<0: break
            ok,frame=capture.read()
            if not ok: break
            idx+=1
            wait=(idx/fps)-(time.monotonic()-t0)
            if wait>0 and stop_event.wait(wait): break
            if time.monotonic()-last_shown<min_gap: continue
            last_shown=time.monotonic()
            h,w=frame.shape[:2]; scale=min(1.0,1600.0/max(w,1),900.0/max(h,1))
            if scale<1.0: frame=cv2.resize(frame,(max(1,int(w*scale)),max(1,int(h*scale))))
            ok,encoded=cv2.imencode(".jpg",frame,[int(getattr(cv2,"IMWRITE_JPEG_QUALITY",1)),85])
            if ok: ui.show_media_frame(encoded.tobytes(),title)
        _log(ui,f"MEDIA: HUD playback {'stopped' if stop_event.is_set() else 'ended'} — {title}")
    except Exception as exc: _log(ui,f"ERR: HUD video playback failed — {exc}")
    finally:
        if audio_proc is not None:
            try: audio_proc.terminate(); audio_proc.wait(timeout=2)
            except Exception:
                try: audio_proc.kill()
                except Exception: pass
        if capture is not None:
            try: capture.release()
            except Exception: pass
        try: ui.show_media_frame(b"",title)
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
    if source.startswith("search:"):
        raw=source[len("search:"):]
        source="search:latest:"+raw if bool(params.get("latest")) else source
    ui=_ui_for(player)
    if ui is None: return "HUD video cannot start because the media panel is unavailable. Nothing was opened."
    if bool(getattr(getattr(ui,"_win",None),"_cam_run",False)): return "The HUD media panel is in camera mode. Close the camera panel before starting video."
    try: import cv2 # noqa: F401
    except ImportError: return "HUD video needs optional OpenCV: pip install opencv-python"
    if _is_youtube(source) or source.startswith("search:"):
        try: import yt_dlp # noqa: F401
        except ImportError: return "YouTube HUD playback needs optional yt-dlp: pip install yt-dlp"
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
    return "HUD video playback started in the background (with sound if ffplay is installed). Close the HUD media panel or use action='stop' to stop it. The stream and delivery are not verified."

TOOL={"name":"play_hud_video","description":"WATCH a video in Jarvis's HUD. Use this whenever the user asks to play/put on/watch a video: pass a YouTube link or local file in source, OR just describe it in query (e.g. 'good minecraft video', 'Parrot X2 new video') and Jarvis finds one on YouTube; set latest=true when they want the newest. Plays a local video file, direct HTTP(S) video URL or YouTube URL, with sound (needs ffplay) and a full-screen button. YouTube needs yt-dlp; all need OpenCV. Use action='stop' to stop playback.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"play (default) or stop"},"source":{"type":"STRING","description":"Local file path or direct HTTP(S)/YouTube URL"},"query":{"type":"STRING","description":"What to watch, in plain words; Jarvis searches YouTube and plays the best match"},"latest":{"type":"BOOLEAN","description":"With query: pick the newest upload instead of the most relevant"},"title":{"type":"STRING","description":"Optional short HUD title"}},"required":[]},"handler":play_hud_video}

#by ASDcuber521
