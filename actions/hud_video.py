"""Muted local/direct-URL video playback in the Jarvis HUD."""
from __future__ import annotations
import re, threading, time
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

def _resolve_stream(source: str) -> str:
    if not _is_youtube(source): return source
    try: import yt_dlp
    except ImportError as exc: raise RuntimeError("YouTube HUD playback needs optional yt-dlp: pip install yt-dlp") from exc
    opts={"quiet":True,"no_warnings":True,"noplaylist":True,"format":"best[height<=720]/best"}
    with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(source,download=False)
    stream=info.get("url")
    if not stream and info.get("requested_downloads"): stream=info["requested_downloads"][0].get("url")
    if not isinstance(stream,str) or not stream.startswith(("http://","https://")): raise RuntimeError("Could not resolve a playable YouTube stream.")
    return stream

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
    capture=None
    try:
        import cv2
        stream=_resolve_stream(source); capture=cv2.VideoCapture(); params=[]
        for prop_name,timeout in (("CAP_PROP_OPEN_TIMEOUT_MSEC",5000),("CAP_PROP_READ_TIMEOUT_MSEC",3000)):
            prop=getattr(cv2,prop_name,None)
            if prop is not None: params.extend([prop,timeout])
        try:
            if params and hasattr(cv2,"CAP_FFMPEG"): capture.open(stream,cv2.CAP_FFMPEG,params)
            else: capture.open(stream)
        except (TypeError,cv2.error):
            capture.release(); capture=cv2.VideoCapture(stream)
        if not capture.isOpened(): raise RuntimeError("OpenCV could not open the video; check URL, codec, and FFmpeg support.")
        fps=capture.get(getattr(cv2,"CAP_PROP_FPS",5)) or 24.0; delay=1.0/max(1.0,min(float(fps),30.0))
        _log(ui,f"MEDIA: Muted HUD playback started — {title}")
        while not stop_event.is_set():
            started=time.monotonic(); ok,frame=capture.read()
            if not ok: break
            h,w=frame.shape[:2]; scale=min(1.0,960.0/max(w,1),540.0/max(h,1))
            if scale<1.0: frame=cv2.resize(frame,(max(1,int(w*scale)),max(1,int(h*scale))))
            ok,encoded=cv2.imencode(".jpg",frame,[int(getattr(cv2,"IMWRITE_JPEG_QUALITY",1)),82])
            if ok: ui.show_media_frame(encoded.tobytes(),title)
            stop_event.wait(max(0.0,delay-(time.monotonic()-started)))
        _log(ui,f"MEDIA: HUD playback {'stopped' if stop_event.is_set() else 'ended'} — {title}")
    except Exception as exc: _log(ui,f"ERR: HUD video playback failed — {exc}")
    finally:
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
    return "Muted HUD video playback started in the background. Close the HUD media panel or use action='stop' to stop it. The stream and delivery are not verified."

TOOL={"name":"play_hud_video","description":"Play a local video file or direct HTTP(S) video URL silently in Jarvis's HUD. YouTube URLs require optional yt-dlp and OpenCV. Use action='stop' to stop playback. Audio is not played.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"play (default) or stop"},"source":{"type":"STRING","description":"Local file path or direct HTTP(S)/YouTube URL"},"title":{"type":"STRING","description":"Optional short HUD title"}},"required":[]},"handler":play_hud_video}

#by ASDcuber521
