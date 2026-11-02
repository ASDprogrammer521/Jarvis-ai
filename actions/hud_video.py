"""Local/direct-URL/YouTube video playback in the Jarvis HUD (audio via ffplay when available)."""
from __future__ import annotations
import re, shutil, subprocess, threading, time
from pathlib import Path
from urllib.parse import urlparse
_ACTIVE_LOCK=threading.Lock()
_ACTIVE_STOP: threading.Event | None=None

def _is_youtube(source: str) -> bool:
    host=(urlparse(source).hostname or "").lower().removeprefix("www.")
    return host in {"youtube.com","youtu.be","m.youtube.com","music.youtube.com","youtube-nocookie.com"}

def _validate_source(source: str) -> str:
    value=str(source or "").strip()
    if not value or len(value)>2048: raise ValueError("Provide a video file path or an HTTP(S) URL (max 2048 characters).")
    if re.match(r"^https?://",value,re.IGNORECASE):
        parsed=urlparse(value)
        if not parsed.hostname or parsed.username or parsed.password: raise ValueError("The video URL must have a host and no embedded credentials.")
        return value
    if "://" in value: raise ValueError("Only local files and HTTP(S) video URLs are supported.")
    path=Path(value).expanduser()
    if not path.is_file(): raise ValueError(f"Local video file was not found: {path}")
    return str(path.resolve())

def _resolve_stream(source: str) -> tuple[str, str | None]:
    """Return (video_url, audio_url). audio_url may equal video_url (muxed) or be None."""
    if not _is_youtube(source): return source, source
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("YouTube HUD playback needs optional yt-dlp: pip install yt-dlp") from exc
    # YouTube rarely offers muxed formats now, so ask for separate video + audio streams.
    selectors=("bv*[height<=720]+ba/b[height<=720]/bv*+ba/b","bv*/b","best")
    last_exc: Exception | None=None; info=None
    for fmt in selectors:
        opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":fmt}
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
    return video, audio

def _start_audio(url: str | None):
    """Play the audio track with ffplay (no window). Returns the process or None."""
    exe=shutil.which("ffplay")
    if not url or not exe: return None
    try:
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        return subprocess.Popen([exe,"-nodisp","-vn","-autoexit","-loglevel","quiet",url],
                                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
    except Exception: return None

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
        import cv2
        stream,audio_url=_resolve_stream(source); capture=cv2.VideoCapture(); params=[]
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
        audio_proc=_start_audio(audio_url)
        note="" if audio_proc else " (no sound: install ffmpeg/ffplay for audio)"
        _log(ui,f"MEDIA: HUD playback started — {title}{note}")
        t0=time.monotonic(); idx=0; min_gap=1.0/30.0; last_shown=0.0
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
    try: source=_validate_source(params.get("source",""))
    except Exception as exc: return str(exc)
    ui=_ui_for(player)
    if ui is None: return "HUD video cannot start because the media panel is unavailable. Nothing was opened."
    if bool(getattr(getattr(ui,"_win",None),"_cam_run",False)): return "The HUD media panel is in camera mode. Close the camera panel before starting video."
    try: import cv2 # noqa: F401
    except ImportError: return "HUD video needs optional OpenCV: pip install opencv-python"
    if _is_youtube(source):
        try: import yt_dlp # noqa: F401
        except ImportError: return "YouTube HUD playback needs optional yt-dlp: pip install yt-dlp"
    parsed=urlparse(source); title=str(params.get("title") or Path(parsed.path).name or "HUD VIDEO").strip()[:60] or "HUD VIDEO"
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

TOOL={"name":"play_hud_video","description":"Play a local video file, direct HTTP(S) video URL or YouTube URL in Jarvis's HUD, with sound (needs ffplay) and a full-screen button. YouTube needs yt-dlp; all need OpenCV. Use action='stop' to stop playback.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"play (default) or stop"},"source":{"type":"STRING","description":"Local file path or direct HTTP(S)/YouTube URL"},"title":{"type":"STRING","description":"Optional short HUD title"}},"required":[]},"handler":play_hud_video}

#by ASDcuber521
