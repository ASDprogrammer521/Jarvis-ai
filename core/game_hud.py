"""Game HUD & Voice Trainer — the engine behind the in-game overlay (no Qt in here).

Keeps timers (with spoken 10-second warnings and optional repeat, e.g. "Roshan every 8 minutes"), a tactical-tip
banner, per-game key-bind cheat sheets, interval "coach" cues (check the minimap, drink water, posture…) and short
guided training routines (aim warm-up, eye break, stretch). The overlay (ui/game_hud.py) just draws `snapshot()`;
voice announcements go out through the `speak` callback that the assistant tool hands in.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from actions._common import DATA_DIR, json_load, json_save

STORE = DATA_DIR / "game_hud.json"
WARN_AT = 10.0                 # seconds before a timer ends that it is announced
TIP_SECONDS = 9.0
MAX_TIMERS = 8

# guided routines: (spoken / shown step, seconds)
ROUTINES: dict[str, list[tuple[str, int]]] = {
    "aim_warmup": [("Loosen up: roll your wrists and shoulders", 20), ("Slow tracking — follow a target smoothly", 45),
                   ("Flick shots — big, fast, accurate", 45), ("Micro-adjustments — small precise corrections", 40),
                   ("Rest your eyes, shake out your hand", 15)],
    "eye_break": [("Look at something 6 metres away", 20), ("Blink slowly ten times", 10), ("Back to the game", 5)],
    "stretch": [("Neck: tilt left, hold", 15), ("Neck: tilt right, hold", 15), ("Wrists: pull fingers back gently", 20),
                ("Stand up and roll your shoulders", 20)],
}
DEFAULT_COACH = ["Check the minimap", "Drink some water", "Sit up straight and relax your shoulders",
                 "Check cooldowns and resources"]


DEFAULT_SETTINGS = {"corner": "top-right", "opacity": 0.82, "show_fps": True, "show_clock": True,
                    "clock_24h": True, "show_session": True, "show_binds": True}


class GameHud:
    def __init__(self):
        self._lock = threading.RLock()
        self.speak = None                       # set by the tool: speak(text) → Gemini says it
        self.log = lambda s: None
        self.timers: dict[int, dict] = {}
        self._next_id = 1
        self.tips: deque = deque(maxlen=4)      # (text, until)
        self.coach: dict | None = None          # {every, cues, next, i}
        self.routine: dict | None = None        # {name, steps, i, ends}
        self.started = time.time()
        self.game = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        data = json_load(STORE, {}) or {}
        self.profiles: dict = data.get("profiles", {})
        self.settings: dict = dict(DEFAULT_SETTINGS, **data.get("settings", {}))
        self.fps = None                         # core.fps_meter.FpsMeter, created on first use
        self.game = data.get("game", "")

    # ── persistence ──────────────────────────────────────────────────────────────
    def save(self):
        with self._lock:
            json_save(STORE, {"profiles": self.profiles, "settings": self.settings, "game": self.game})

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.started = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="game-hud")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self.fps is not None:
            self.fps.stop()

    def sync_fps(self):
        """Run the FPS meter only while the HUD shows it."""
        from core.fps_meter import FpsMeter
        if self.settings.get("show_fps"):
            if self.fps is None:
                self.fps = FpsMeter()
            self.fps.start()
        elif self.fps is not None:
            self.fps.stop()

    def set_setting(self, key: str, value) -> None:
        if key in DEFAULT_SETTINGS:
            self.settings[key] = value
            self.save()
            if key == "show_fps":
                self.sync_fps()

    def _say(self, text: str, instruction: str | None = None):
        self.log(f"[GameHUD] {text}")
        if self.speak:
            try:
                self.speak(f"[GameHUD] {instruction or text}")
            except Exception:
                pass

    # ── timers ───────────────────────────────────────────────────────────────────
    def add_timer(self, name: str, seconds: float, repeat: bool = False) -> int:
        seconds = max(1.0, min(6 * 3600.0, float(seconds)))
        with self._lock:
            if len(self.timers) >= MAX_TIMERS:
                oldest = min(self.timers)
                del self.timers[oldest]
            tid = self._next_id
            self._next_id += 1
            self.timers[tid] = {"name": (name or f"Timer {tid}")[:24], "total": seconds,
                                "ends": time.time() + seconds, "repeat": bool(repeat), "warned": False}
        self.start()
        return tid

    def stop_timer(self, name: str = "") -> int:
        name = (name or "").strip().lower()
        with self._lock:
            ids = [i for i, t in self.timers.items() if not name or name in t["name"].lower() or name == "all"]
            for i in ids:
                del self.timers[i]
        return len(ids)

    # ── tips / binds / coach / routines ──────────────────────────────────────────
    def add_tip(self, text: str, seconds: float = TIP_SECONDS):
        with self._lock:
            self.tips.append((text.strip()[:160], time.time() + seconds))
        self.start()

    def set_binds(self, game: str, binds: list[dict]):
        game = (game or self.game or "default").strip()[:40]
        clean = [{"key": str(b.get("key", ""))[:14], "action": str(b.get("action", ""))[:34]}
                 for b in binds if b.get("key") and b.get("action")][:14]
        with self._lock:
            self.profiles.setdefault(game, {})["binds"] = clean
            self.game = game
        self.save()
        return game, len(clean)

    def use_game(self, game: str):
        with self._lock:
            self.game = (game or "").strip()[:40]
        self.save()

    def binds(self) -> list[dict]:
        return list((self.profiles.get(self.game) or {}).get("binds", []))

    def set_coach(self, every_minutes: float, cues: list[str] | None = None):
        with self._lock:
            if every_minutes <= 0:
                self.coach = None
            else:
                every = max(0.5, min(120.0, float(every_minutes))) * 60.0
                self.coach = {"every": every, "cues": [c for c in (cues or DEFAULT_COACH) if c], "next": time.time() + every, "i": 0}
        self.start()

    def start_routine(self, name: str) -> bool:
        steps = ROUTINES.get(name)
        if not steps:
            return False
        with self._lock:
            self.routine = {"name": name, "steps": steps, "i": 0, "ends": time.time() + steps[0][1]}
        self._say(f"{name.replace('_', ' ')}: {steps[0][0]}", f"Training routine started. Say this step in one short sentence: {steps[0][0]}.")
        self.start()
        return True

    def stop_routine(self):
        with self._lock:
            self.routine = None

    def clear(self):
        with self._lock:
            self.timers.clear()
            self.tips.clear()
            self.coach = None
            self.routine = None

    # ── tick ─────────────────────────────────────────────────────────────────────
    def _loop(self):
        while not self._stop.wait(0.25):
            try:
                self._tick(time.time())
            except Exception as e:
                self.log(f"ERR: game hud — {e}")

    def _tick(self, now: float):
        speak_later: list[tuple[str, str]] = []
        with self._lock:
            for tid, t in list(self.timers.items()):
                left = t["ends"] - now
                if not t["warned"] and left <= WARN_AT and t["total"] > WARN_AT * 1.5:
                    t["warned"] = True
                    speak_later.append((f"{t['name']} in {int(WARN_AT)} s",
                                        f"Heads-up: '{t['name']}' ends in ten seconds. Say it in a few words."))
                if left <= 0:
                    speak_later.append((f"{t['name']} — NOW", f"Timer '{t['name']}' is up. Say it in a few words."))
                    self.tips.append((f"⏱ {t['name']} — NOW", now + 6))
                    if t["repeat"]:
                        t["ends"] = now + t["total"]
                        t["warned"] = False
                    else:
                        del self.timers[tid]
            c = self.coach
            if c and now >= c["next"]:
                cue = c["cues"][c["i"] % len(c["cues"])]
                c["i"] += 1
                c["next"] = now + c["every"]
                self.tips.append((cue, now + TIP_SECONDS))
                speak_later.append((cue, f"Coach reminder, say it in a few words: {cue}."))
            r = self.routine
            if r and now >= r["ends"]:
                r["i"] += 1
                if r["i"] >= len(r["steps"]):
                    self.routine = None
                    speak_later.append(("Routine finished", "The training routine is finished. Congratulate the player in a few words."))
                else:
                    text, secs = r["steps"][r["i"]]
                    r["ends"] = now + secs
                    speak_later.append((text, f"Next training step, say it in one short sentence: {text}."))
        for text, instruction in speak_later:
            self._say(text, instruction)

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            timers = [{"name": t["name"], "left": max(0.0, t["ends"] - now), "total": t["total"], "repeat": t["repeat"]}
                      for t in sorted(self.timers.values(), key=lambda t: t["ends"])]
            tips = [x for x, until in self.tips if until > now]
            r = self.routine
            routine = None
            if r:
                text, secs = r["steps"][r["i"]]
                routine = {"name": r["name"], "text": text, "left": max(0.0, r["ends"] - now), "total": secs,
                           "step": r["i"] + 1, "of": len(r["steps"])}
            return {"game": self.game, "session": now - self.started, "timers": timers, "tips": tips[-2:],
                    "routine": routine, "binds": self.binds() if self.settings.get("show_binds", True) else [], "coach": bool(self.coach),
                    "corner": self.settings.get("corner", "top-right"), "opacity": float(self.settings.get("opacity", 0.82)),
                    "show_fps": bool(self.settings.get("show_fps")), "show_clock": bool(self.settings.get("show_clock")),
                    "clock_24h": bool(self.settings.get("clock_24h")), "show_session": bool(self.settings.get("show_session")),
                    "fps": self.fps.read() if self.fps is not None else None,
                    "fps_state": (self.fps.state if self.fps is not None else "idle"),
                    "wall": time.strftime("%H:%M" if self.settings.get("clock_24h", True) else "%I:%M %p")}


_HUD: GameHud | None = None


def get_hud() -> GameHud:
    global _HUD
    if _HUD is None:
        _HUD = GameHud()
    return _HUD
