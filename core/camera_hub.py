"""One camera, several features.

A webcam can only be opened by one program at a time, so hand gestures and face recognition share this single
capture loop. The loop runs only while at least one of them is switched on (or a face is being enrolled) and
releases the camera as soon as nothing needs it.
"""
from __future__ import annotations

import os
import threading
import time

from core import face_id, gesture

FACE_EVERY = 0.4          # seconds between face checks (gestures are checked on every frame)
KNOWN_COOLDOWN = 45.0     # don't greet the same person again within this many seconds
UNKNOWN_COOLDOWN = 60.0
ENROLL_SAMPLES = 6
ENROLL_TIMEOUT = 20.0


class CameraHub:
    """Callbacks run on the camera thread — the UI must hand them over to the Qt thread.

    on_gesture(action_id, gesture_id) · on_face(kind, name) · on_status(text)
    kind: known | unknown | enrolled | enroll_failed
    """

    def __init__(self, on_gesture, on_face, on_status=None):
        self.on_gesture = on_gesture
        self.on_face = on_face
        self.on_status = on_status or (lambda s: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._g = False
        self._f = False
        self._enroll: dict | None = None
        self._lock = threading.Lock()
        self.status = "off"
        self.current_gesture: str | None = None
        self.visible: list[str] = []        # names (or "unknown") seen in the last face check
        self.seen_at = 0.0

    # ── control ──────────────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def refresh(self):
        """Re-read the on/off switches and start or stop the camera accordingly."""
        self._g = gesture.is_enabled()
        self._f = face_id.is_enabled()
        if self._wanted():
            if not self.running:
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-camera")
                self._thread.start()
        elif self.running:
            self.stop()
        else:
            self._set("off")

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t is not threading.current_thread():
            t.join(timeout=4)
        self._thread = None
        self._set("off")

    def enroll(self, name: str):
        with self._lock:
            self._enroll = {"name": name.strip()[:40], "vecs": [], "t0": time.time(), "last": 0.0}
        self.refresh()          # starts the camera if it was off

    def _wanted(self) -> bool:
        return self._g or self._f or self._enroll is not None

    def _set(self, s: str):
        self.status = s
        try:
            self.on_status(s)
        except Exception:
            pass

    # ── loop ─────────────────────────────────────────────────────────────────────
    def _open(self):
        import cv2
        idx = gesture.get_camera()
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError("camera is busy or not found")
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # much faster than raw frames on most webcams
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)                              # always the newest frame, no lag
        except Exception:
            pass
        return cap

    def _run(self):
        cap = hands = engine = None
        tracker = gesture.GestureTracker()
        last_face = 0.0
        last_known: dict[str, float] = {}
        last_unknown = 0.0
        unknown_streak = 0
        try:
            self._set("starting…")
            import cv2
            cap = self._open()
            self._set("active")
            while not self._stop.is_set():
                if not self._wanted():
                    break
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.03)
                    continue
                now = time.time()

                # ── gestures ──
                if self._g:
                    if hands is None:
                        hands = gesture.HandReader()
                    lm = hands.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    fired = tracker.update(gesture.classify(lm) if lm else None, now)
                    self.current_gesture = tracker.current
                    if fired:
                        self.on_gesture(fired[1], fired[0])
                else:
                    if hands is not None:
                        hands.close()
                        hands = None
                    self.current_gesture = None

                # ── faces ──
                enroll = self._enroll
                if (self._f or enroll) and now - last_face >= FACE_EVERY:
                    last_face = now
                    if engine is None:
                        self._set("loading face model…")
                        engine = face_id.FaceEngine()
                        self._set("active")
                    faces = engine.detect(frame)
                    if enroll is not None:
                        self._enroll_step(engine, frame, faces, enroll, now)
                    if self._f:
                        seen = []
                        for f in faces:
                            name, _ = engine.identify(engine.embed(frame, f))
                            seen.append(name or "unknown")
                        self.visible, self.seen_at = seen, now
                        for name in {s for s in seen if s != "unknown"}:
                            if now - last_known.get(name, 0.0) > KNOWN_COOLDOWN:   # back after a break, not just still sitting there
                                self.on_face("known", name)
                            last_known[name] = now
                        if "unknown" in seen and face_id.names():
                            unknown_streak += 1
                            if unknown_streak >= 3 and now - last_unknown > UNKNOWN_COOLDOWN and face_id.alert_unknown():
                                last_unknown = now
                                self.on_face("unknown", "")
                        else:
                            unknown_streak = 0
                else:
                    if not self._f and engine is not None and enroll is None:
                        engine = None
                        self.visible = []
                time.sleep(0.005)
        except ImportError as e:
            self._set(f"missing package: pip install opencv-python mediapipe ({e.name})")
        except Exception as e:
            self._set(f"error: {e}")
            if self._enroll is not None:
                name, self._enroll = self._enroll["name"], None
                self.on_face("enroll_failed", f"{name}: {e}")
        finally:
            if cap is not None:
                cap.release()
            if hands is not None:
                hands.close()
            self.current_gesture = None
            self.visible = []
            if not self.status.startswith(("error", "missing")):
                self._set("off")

    def _enroll_step(self, engine, frame, faces, enroll, now):
        if now - enroll["t0"] > ENROLL_TIMEOUT:
            self._enroll = None
            self.on_face("enroll_failed", f"{enroll['name']}: I didn't see a clear face — look straight at the camera")
            return
        if len(faces) != 1 or float(faces[0][-1]) < 0.9 or now - enroll["last"] < 0.5:
            return
        enroll["last"] = now
        enroll["vecs"].append(engine.embed(frame, faces[0]))
        if len(enroll["vecs"]) >= ENROLL_SAMPLES:
            face_id.add_person(enroll["name"], enroll["vecs"])
            self._enroll = None
            self.on_face("enrolled", enroll["name"])
