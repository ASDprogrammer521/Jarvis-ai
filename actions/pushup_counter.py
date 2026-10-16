from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from datetime import datetime

from actions._common import BASE_DIR, DATA_DIR, json_load, json_save, log

STORE = DATA_DIR / "workouts.json"
MODEL_PATH = BASE_DIR / "config" / "models" / "pose_landmarker_lite.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")

L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP, L_AN, R_AN = 11, 12, 13, 14, 15, 16, 23, 24, 27, 28
SIDES = {"L": (L_SH, L_EL, L_WR, L_HIP, L_AN), "R": (R_SH, R_EL, R_WR, R_HIP, R_AN)}

DOWN_ANGLE = 105.0
UP_ANGLE = 150.0
DEEP_ANGLE = 92.0
MIN_ALIGN = 155.0
MIN_REP_SECONDS = 0.6
MIN_VIS = 0.45

_SESSION: "Session | None" = None
_LOCK = threading.Lock()


def _angle(a, b, c) -> float:
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n < 1e-9:
        return 180.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


class RepCounter:

    def __init__(self):
        self.reps = 0
        self.good = 0
        self.state = "idle"
        self.position_ok = False
        self.angle = 180.0
        self.align = 180.0
        self.feedback = "Get into push-up position (side view)"
        self.rep_log: list[dict] = []
        self.issues = {"shallow": 0, "sagging hips": 0, "piked hips": 0}
        self._smooth: deque = deque(maxlen=3)
        self._min_angle = 180.0
        self._min_align = 180.0
        self._t_down = 0.0
        self._last_rep_t = 0.0
        self.last_event = ""

    def _pick_side(self, lm):
        best, score = None, 0.0
        for name, idx in SIDES.items():
            vis = sum(lm[i][2] for i in idx) / len(idx)
            if vis > score:
                best, score = name, vis
        return (best, score) if score >= MIN_VIS else (None, score)

    def update(self, lm, aspect: float = 1.0, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        side, _ = self._pick_side(lm)
        if side is None:
            self.position_ok = False
            self.feedback = "I can't see you clearly — step back so your whole body is in view"
            return None
        sh, el, wr, hip, an = [(lm[i][0] * aspect, lm[i][1]) for i in SIDES[side]]
        self._smooth.append(_angle(sh, el, wr))
        self.angle = sum(self._smooth) / len(self._smooth)
        self.align = _angle(sh, hip, an)
        span = an[0] - sh[0]
        t_line = (hip[0] - sh[0]) / span if abs(span) > 1e-6 else 0.5
        hip_off = hip[1] - (sh[1] + (an[1] - sh[1]) * t_line)
        dx, dy = abs(an[0] - sh[0]), abs(an[1] - sh[1])
        self.position_ok = dx > 0.12 and dy / (dx + 1e-6) < 0.75
        if not self.position_ok:
            if self.state == "down":
                self.state = "up"
            self.feedback = "Get into push-up position (side view)"
            return None

        event = None
        if self.state in ("idle", "up"):
            if self.angle >= UP_ANGLE:
                self.state = "up"
                self.feedback = "Ready — lower down"
            if self.state == "up" and self.angle < DOWN_ANGLE:
                self.state = "down"
                self._t_down = now
                self._min_angle = self.angle
                self._min_align = self.align
                self._hip_below = hip_off > 0
                self.feedback = "Good — now push up"
        elif self.state == "down":
            self._min_angle = min(self._min_angle, self.angle)
            if self.align < self._min_align:
                self._min_align = self.align
                self._hip_below = hip_off > 0
            if self.angle >= UP_ANGLE:
                dur = now - self._t_down
                if dur >= MIN_REP_SECONDS and now - self._last_rep_t >= MIN_REP_SECONDS:
                    event = self._finish_rep(now, dur)
                self.state = "up"
        return event

    def _finish_rep(self, now: float, dur: float) -> str:
        problems = []
        if self._min_angle > DOWN_ANGLE - 5:
            problems.append("shallow")
        if self._min_align < MIN_ALIGN:
            problems.append("sagging hips" if self._hip_below else "piked hips")
        self.reps += 1
        self._last_rep_t = now
        good = not problems
        if good:
            self.good += 1
        for p in problems:
            self.issues[p] = self.issues.get(p, 0) + 1
        depth = "deep" if self._min_angle <= DEEP_ANGLE else "good depth" if self._min_angle <= DOWN_ANGLE else "shallow"
        self.rep_log.append({"n": self.reps, "min_elbow": round(self._min_angle), "body_line": round(self._min_align),
                             "seconds": round(dur, 2), "good": good, "issues": problems})
        if good:
            self.feedback = f"Rep {self.reps} — {depth}, clean form"
        else:
            tips = {"shallow": "go lower", "sagging hips": "tighten your core, hips up",
                    "piked hips": "lower your hips, straight line"}
            self.feedback = f"Rep {self.reps} — " + ", ".join(tips.get(x, x) for x in problems)
        self.last_event = self.feedback
        return self.feedback

    _hip_below = True

    def summary(self) -> dict:
        n = len(self.rep_log)
        return {"reps": self.reps, "good_reps": self.good,
                "avg_elbow_depth": round(sum(r["min_elbow"] for r in self.rep_log) / n) if n else 0,
                "avg_rep_seconds": round(sum(r["seconds"] for r in self.rep_log) / n, 2) if n else 0,
                "issues": {k: v for k, v in self.issues.items() if v}}


class _Pose:

    def __init__(self):
        self.mode = None
        self._lm = None
        self._t0 = time.time()
        import mediapipe as mp
        self.mp = mp
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "pose"):
            self._lm = mp.solutions.pose.Pose(model_complexity=0, min_detection_confidence=0.5, min_tracking_confidence=0.5)
            self.mode = "legacy"
            return
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        self._ensure_model()
        opts = vision.PoseLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO, num_poses=1)
        self._lm = vision.PoseLandmarker.create_from_options(opts)
        self.mode = "tasks"

    @staticmethod
    def _ensure_model():
        if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1_000_000:
            return
        import requests
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print("[Pushup] Downloading pose model (~6 MB)…")
        r = requests.get(MODEL_URL, stream=True, timeout=30)
        r.raise_for_status()
        tmp = MODEL_PATH.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 16):
                fh.write(chunk)
        tmp.replace(MODEL_PATH)

    def detect(self, rgb):
        if self.mode == "legacy":
            res = self._lm.process(rgb)
            if not res.pose_landmarks:
                return None
            return [(l.x, l.y, l.visibility) for l in res.pose_landmarks.landmark]
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        res = self._lm.detect_for_video(img, int((time.time() - self._t0) * 1000))
        if not res.pose_landmarks:
            return None
        return [(l.x, l.y, getattr(l, "visibility", 1.0) or 0.0) for l in res.pose_landmarks[0]]

    def close(self):
        try:
            self._lm.close()
        except Exception:
            pass


def _draw(cv2, frame, lm, counter: RepCounter, elapsed: float, target: int | None):
    h, w = frame.shape[:2]
    ok = counter.position_ok
    col_good, col_warn, col_dim = (120, 255, 160), (80, 170, 255), (180, 180, 180)
    if lm:
        side, _ = counter._pick_side(lm)
        for name, idx in SIDES.items():
            pts = [(int(lm[i][0] * w), int(lm[i][1] * h)) for i in idx]
            color = (col_good if counter.align >= MIN_ALIGN else col_warn) if (name == side and ok) else col_dim
            for a, b in zip(pts, pts[1:]):
                cv2.line(frame, a, b, color, 3, cv2.LINE_AA)
            for p in pts:
                cv2.circle(frame, p, 5, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.rectangle(frame, (0, 0), (w, 58), (20, 16, 12), -1)
    label = f"{counter.reps}" + (f" / {target}" if target else "")
    cv2.putText(frame, label, (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 231, 110), 3, cv2.LINE_AA)
    cv2.putText(frame, f"elbow {counter.angle:.0f}  body {counter.align:.0f}", (150, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1, cv2.LINE_AA)
    cv2.putText(frame, f"{int(elapsed // 60)}:{int(elapsed % 60):02d}   good {counter.good}", (150, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1, cv2.LINE_AA)
    fb = counter.feedback[:52]
    cv2.rectangle(frame, (0, h - 40), (w, h), (20, 16, 12), -1)
    cv2.putText(frame, fb, (12, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                col_good if "clean" in fb or "Good" in fb or "Ready" in fb else col_warn, 2, cv2.LINE_AA)


class Session:

    def __init__(self, player, speak, target, camera, max_minutes, announce):
        self.player, self.speak = player, speak
        self.target, self.camera, self.announce = target, camera, announce
        self.max_seconds = max_minutes * 60
        self.counter = RepCounter()
        self.stop_flag = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="pushup-counter")
        self.started = time.time()
        self.error = ""
        self.finished = False
        self.saved = None

    def _say(self, text: str):
        if self.announce and self.speak:
            try:
                self.speak(text)
            except Exception:
                pass

    def _push(self, cv2, frame):
        fn = getattr(self.player, "show_media_frame", None)
        if fn is None:
            return
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 68])
            if ok:
                fn(buf.tobytes(), "PUSH-UPS")
        except Exception:
            pass

    def _run(self):
        pose = None
        cap = None
        try:
            import cv2
            pose = _Pose()
            cap = cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                raise RuntimeError("I couldn't open the camera — is another app or Jarvis' camera view using it?")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            last_push, last_warn, last_speak_n = 0.0, 0.0, 0
            while not self.stop_flag.is_set():
                t0 = time.time()
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                elapsed = t0 - self.started
                if elapsed > self.max_seconds:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                lm = pose.detect(rgb)
                h, w = frame.shape[:2]
                ev = None
                if lm:
                    ev = self.counter.update(lm, aspect=w / h)
                else:
                    self.counter.position_ok = False
                    self.counter.feedback = "I can't see you — move into the frame"
                if ev:
                    log(f"[Pushup] {ev}", self.player)
                    n = self.counter.reps
                    if self.target and n >= self.target:
                        break
                    if n % 5 == 0 and n != last_speak_n:
                        last_speak_n = n
                        self._say(f"[Workout] The user has done {n} push-ups. Say only the number, like an energetic coach, one short phrase.")
                    elif self.counter.rep_log and not self.counter.rep_log[-1]["good"] and t0 - last_warn > 8:
                        last_warn = t0
                        self._say(f"[Workout] Push-up {n} form issue: {ev}. Give a very short spoken form tip.")
                _draw(cv2, frame, lm, self.counter, elapsed, self.target)
                if t0 - last_push > 0.07:
                    last_push = t0
                    self._push(cv2, frame)
                time.sleep(max(0.0, 0.033 - (time.time() - t0)))
        except Exception as e:
            self.error = str(e)
            log(f"[Pushup] ❌ {e}", self.player)
        finally:
            try:
                if cap is not None:
                    cap.release()
                if pose is not None:
                    pose.close()
            except Exception:
                pass
            self._finish()

    def _finish(self):
        dur = time.time() - self.started
        s = self.counter.summary()
        self.finished = True
        fn = getattr(self.player, "show_media_frame", None)
        if fn:
            try:
                fn(b"", "")
            except Exception:
                pass
        if s["reps"] > 0:
            rec = {"id": uuid.uuid4().hex[:8], "date": datetime.now().strftime("%Y-%m-%d"),
                   "start": datetime.fromtimestamp(self.started).strftime("%H:%M"),
                   "duration_s": round(dur), **s, "rep_details": self.counter.rep_log}
            data = json_load(STORE, {"sessions": []})
            data.setdefault("sessions", []).append(rec)
            json_save(STORE, data)
            self.saved = rec
            msg = _summary_text(rec)
            log(f"[Pushup] Session saved — {msg}", self.player)
            if self.player is not None and hasattr(self.player, "show_content"):
                try:
                    self.player.show_content("WORKOUT COMPLETE", msg)
                except Exception:
                    pass
            self._say(f"[Workout] Session finished. {msg} Congratulate the user in one or two short sentences.")
        elif self.error:
            self._say(f"[Workout] The push-up counter could not run: {self.error}. Tell the user briefly.")
        else:
            log("[Pushup] Session ended with no reps.", self.player)


def _summary_text(rec: dict) -> str:
    mins = rec["duration_s"] / 60
    s = f"{rec['reps']} push-ups in {mins:.1f} min, {rec['good_reps']} with clean form"
    if rec.get("avg_elbow_depth"):
        s += f", average depth {rec['avg_elbow_depth']}° elbow angle"
    if rec.get("issues"):
        s += ". Main issues: " + ", ".join(f"{k} ×{v}" for k, v in rec["issues"].items())
    return s + "."


def _history(days: int) -> str:
    data = json_load(STORE, {"sessions": []})
    sessions = data.get("sessions", [])
    if not sessions:
        return "No push-up workouts logged yet, sir."
    cutoff = datetime.now().timestamp() - days * 86400
    recent = [s for s in sessions if datetime.strptime(s["date"], "%Y-%m-%d").timestamp() >= cutoff]
    if not recent:
        return f"No workouts in the last {days} days, sir."
    total = sum(s["reps"] for s in recent)
    best = max(recent, key=lambda s: s["reps"])
    clean = sum(s["good_reps"] for s in recent)
    by_day: dict[str, int] = {}
    for s in recent:
        by_day[s["date"]] = by_day.get(s["date"], 0) + s["reps"]
    lines = [f"{d}: {n} reps" for d, n in sorted(by_day.items())[-7:]]
    return (f"Last {days} days: {len(recent)} sessions, {total} push-ups ({clean} clean). "
            f"Best set: {best['reps']} on {best['date']}.\n" + "\n".join(lines))


def pushup_counter(parameters: dict, player=None, speak=None) -> str:
    global _SESSION
    p = parameters or {}
    action = str(p.get("action") or "start").lower().strip()

    if action in ("history", "stats"):
        text = _history(int(p.get("days") or 30))
        if player is not None and hasattr(player, "show_content") and "\n" in text:
            player.show_content("PUSH-UP HISTORY", text)
        return text

    with _LOCK:
        if action == "start":
            if _SESSION is not None and not _SESSION.finished:
                return "The push-up counter is already running, sir."
            try:
                import cv2
                import mediapipe
            except ImportError as e:
                return f"Sir, I need extra packages for the push-up counter: pip install opencv-python mediapipe ({e.name} is missing)."
            target = int(p["target_reps"]) if p.get("target_reps") else None
            _SESSION = Session(player, speak, target, int(p.get("camera") or 0),
                               max(1, min(60, int(p.get("max_minutes") or 15))), bool(p.get("announce", True)))
            _SESSION.thread.start()
            log("[Pushup] Counter started", player)
            return ("Push-up counter is live, sir. Put the camera to your side so your whole body is visible, "
                    "get into position and start. Say 'stop' when you're done."
                    + (f" Target: {target} reps." if target else ""))

        if action in ("stop", "finish", "end"):
            if _SESSION is None or _SESSION.finished:
                return "The push-up counter isn't running, sir."
            _SESSION.stop_flag.set()
            _SESSION.thread.join(timeout=4)
            s = _SESSION.counter.summary()
            return (f"Workout stopped. {_summary_text({**s, 'duration_s': time.time() - _SESSION.started})}"
                    if s["reps"] else "Workout stopped — no reps were counted.")

        if action in ("status", "count"):
            if _SESSION is None or _SESSION.finished:
                return "The push-up counter isn't running, sir."
            c = _SESSION.counter
            return f"{c.reps} push-ups so far ({c.good} clean). {c.feedback}."

    return "Unknown action. Available: start, stop, status, history."


TOOL = {
    "name": "pushup_counter",
    "description": (
        "Live push-up counter using the webcam and AI pose detection. Counts reps in real time, checks form "
        "(depth, sagging or piked hips, lockout), gives spoken feedback and logs each workout session. "
        "Actions: start (optionally with a target number of reps), stop, status (current count), history "
        "(past workouts and totals). Use when the user wants to do or count push-ups, or asks about workout progress."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "start | stop | status | history (default start)"},
            "target_reps": {"type": "INTEGER", "description": "Stop automatically after this many reps"},
            "max_minutes": {"type": "INTEGER", "description": "Safety time limit in minutes (default 15)"},
            "camera": {"type": "INTEGER", "description": "Camera index (default 0)"},
            "announce": {"type": "BOOLEAN", "description": "Speak milestones and form tips (default true)"},
            "days": {"type": "INTEGER", "description": "History window in days (default 30)"},
        },
    },
    "handler": pushup_counter,
}

# by ASDcuber521
