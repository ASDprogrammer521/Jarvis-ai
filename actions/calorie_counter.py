from __future__ import annotations

import mimetypes
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from actions._common import DATA_DIR, ask_json, json_load, json_save, log

STORE = DATA_DIR / "nutrition.json"
_LOCK = threading.Lock()

ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
MEALS = ("breakfast", "lunch", "dinner", "snack")

FOODS = {
    "egg": (143, 12.6, 0.7, 9.5, 50), "rice": (130, 2.7, 28, 0.3, 160), "bread": (265, 9, 49, 3.2, 30),
    "toast": (265, 9, 49, 3.2, 30), "chicken breast": (165, 31, 0, 3.6, 150), "chicken": (190, 27, 0, 8, 150),
    "beef": (250, 26, 0, 17, 150), "steak": (271, 25, 0, 19, 200), "pasta": (158, 5.8, 31, 0.9, 200),
    "potato": (87, 1.9, 20, 0.1, 170), "fries": (312, 3.4, 41, 15, 120), "banana": (89, 1.1, 23, 0.3, 118),
    "apple": (52, 0.3, 14, 0.2, 180), "orange": (47, 0.9, 12, 0.1, 130), "milk": (61, 3.2, 4.8, 3.3, 240),
    "yogurt": (59, 10, 3.6, 0.4, 170), "cheese": (402, 25, 1.3, 33, 30), "butter": (717, 0.9, 0.1, 81, 10),
    "oats": (389, 17, 66, 7, 40), "oatmeal": (71, 2.5, 12, 1.5, 234), "salad": (20, 1.4, 3.7, 0.2, 100),
    "pizza": (266, 11, 33, 10, 110), "burger": (295, 17, 24, 14, 200), "sandwich": (250, 12, 30, 9, 180),
    "salmon": (208, 20, 0, 13, 150), "tuna": (132, 29, 0, 1, 100), "avocado": (160, 2, 8.5, 15, 150),
    "peanut butter": (588, 25, 20, 50, 32), "almonds": (579, 21, 22, 50, 28), "chocolate": (546, 5, 61, 31, 40),
    "cola": (42, 0, 10.6, 0, 330), "coffee": (2, 0.3, 0, 0, 240), "beans": (127, 8.7, 22, 0.5, 170),
    "lentils": (116, 9, 20, 0.4, 200), "plov": (190, 6.5, 26, 7, 300), "lagman": (140, 6, 20, 4, 350),
    "samsa": (310, 9, 30, 17, 120), "shashlik": (230, 22, 2, 15, 150), "manti": (190, 9, 22, 7, 100),
    "soup": (45, 2.5, 6, 1.2, 300), "ice cream": (207, 3.5, 24, 11, 100), "cake": (350, 4, 52, 14, 90),
}
UNIT_G = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "kg": 1000, "ml": 1, "l": 1000, "cup": 240, "cups": 240,
          "tbsp": 15, "tsp": 5, "slice": 30, "slices": 30, "oz": 28.35}


def _today(d: str | None = None) -> str:
    if not d:
        return datetime.now().strftime("%Y-%m-%d")
    d = str(d).strip().lower()
    if d == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if d == "today":
        return _today()
    return d


def _load() -> dict:
    return json_load(STORE, {"profile": {}, "log": {}})


def _save(data: dict) -> None:
    json_save(STORE, data)


def compute_plan(profile: dict) -> dict:
    w, h, a = float(profile["weight_kg"]), float(profile["height_cm"]), float(profile["age"])
    male = str(profile.get("sex", "male")).lower().startswith("m")
    bmr = 10 * w + 6.25 * h - 5 * a + (5 if male else -161)
    tdee = bmr * ACTIVITY.get(str(profile.get("activity", "moderate")).lower(), 1.55)
    goal = str(profile.get("goal", "maintain")).lower()
    pace = float(profile.get("pace_kg_week") or 0.5)
    if goal.startswith("l"):
        target = tdee - min(1000, pace * 7700 / 7)
    elif goal.startswith("g"):
        target = tdee + min(600, pace * 7700 / 7 * 0.6)
    else:
        target = tdee
    target = max(target, 1500 if male else 1200)
    protein = (2.0 if goal.startswith("l") else 1.8) * w
    fat = 0.27 * target / 9
    carbs = max(0.0, (target - protein * 4 - fat * 9) / 4)
    return {"bmr": round(bmr), "tdee": round(tdee), "calories": round(target / 10) * 10,
            "protein": round(protein), "carbs": round(carbs), "fat": round(fat)}


def _targets(data: dict) -> tuple[dict, bool]:
    prof = data.get("profile") or {}
    try:
        if prof:
            return compute_plan(prof), True
    except Exception:
        pass
    return {"calories": 2000, "protein": 100, "carbs": 250, "fat": 65, "bmr": 0, "tdee": 0}, False


def _local_estimate(text: str) -> dict | None:
    items, total = [], dict(calories=0.0, protein=0.0, carbs=0.0, fat=0.0)
    parts = re.split(r",|\band\b|\bwith\b|\+|;|\bva\b|\bи\b", text.lower())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        key = max((k for k in FOODS if k in part), key=len, default=None)
        if key is None:
            continue
        kcal, p, c, f, piece = FOODS[key]
        grams = piece
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g|gram|grams|ml|l|cups?|tbsp|tsp|slices?|oz)\b", part)
        if m:
            grams = float(m.group(1).replace(",", ".")) * UNIT_G[m.group(2)]
        else:
            q = re.search(r"(?:^|\s)(\d+(?:[.,]\d+)?)\s*(?:x\s*)?(?!\d)", part)
            if q:
                grams = float(q.group(1).replace(",", ".")) * piece
        k = grams / 100.0
        it = dict(name=key, grams=round(grams), calories=round(kcal * k), protein_g=round(p * k, 1),
                  carbs_g=round(c * k, 1), fat_g=round(f * k, 1))
        items.append(it)
        total["calories"] += it["calories"]
        total["protein"] += it["protein_g"]
        total["carbs"] += it["carbs_g"]
        total["fat"] += it["fat_g"]
    if not items:
        return None
    return {"items": items, "total": {k: round(v, 1) for k, v in total.items()}, "source": "local food table (approximate)"}


SYSTEM = (
    "You are a precise nutrition analyst. Estimate the nutrition of the described or pictured meal. "
    "Reply with ONE JSON object and nothing else: "
    '{"items":[{"name":str,"grams":number,"calories":number,"protein_g":number,"carbs_g":number,"fat_g":number}],'
    '"total":{"calories":number,"protein":number,"carbs":number,"fat":number},"confidence":"low"|"medium"|"high"}. '
    "Use realistic portion sizes when none are given, count cooking oil, and make total equal the sum of items."
)


def estimate(description: str, image_path: str | None = None) -> dict | None:
    contents = None
    if image_path:
        p = Path(str(image_path)).expanduser()
        if p.exists():
            try:
                from google.genai import types
                mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
                contents = [types.Part.from_bytes(data=p.read_bytes(), mime_type=mime),
                            f"Estimate this meal. {description or ''}".strip()]
            except Exception as e:
                print(f"[Nutrition] image load failed: {e}")
    if contents is None and description:
        contents = f"Meal: {description}"
    res = None
    if contents is not None:
        res = ask_json(contents, SYSTEM, default=None, timeout_ms=45_000)
    if isinstance(res, dict) and isinstance(res.get("total"), dict) and res["total"].get("calories") is not None:
        t = res["total"]
        res["total"] = {k: round(float(t.get(k) or 0), 1) for k in ("calories", "protein", "carbs", "fat")}
        res["source"] = "AI estimate"
        return res
    if description:
        return _local_estimate(description)
    return None


def _day_totals(entries: list) -> dict:
    t = dict(calories=0.0, protein=0.0, carbs=0.0, fat=0.0)
    for e in entries:
        for k in t:
            t[k] += float(e.get(k) or 0)
    return {k: round(v) for k, v in t.items()}


def _bar(value: float, target: float, width: int = 14) -> str:
    frac = 0 if target <= 0 else min(1.0, value / target)
    n = round(frac * width)
    return "█" * n + "░" * (width - n)


def _summary(data: dict, day: str) -> str:
    entries = data["log"].get(day, [])
    tgt, personal = _targets(data)
    tot = _day_totals(entries)
    left = tgt["calories"] - tot["calories"]
    lines = [f"Nutrition — {day}"]
    for k, label, unit in (("calories", "Calories", "kcal"), ("protein", "Protein", "g"), ("carbs", "Carbs", "g"), ("fat", "Fat", "g")):
        lines.append(f"{label:<9}{_bar(tot[k], tgt[k])}  {tot[k]:,} / {tgt[k]:,} {unit}")
    lines.append(f"{'Remaining' if left >= 0 else 'Over by'}: {abs(left):,} kcal")
    if not personal:
        lines.append("(default 2000 kcal plan — set your profile for a personal budget)")
    if entries:
        lines.append("")
        for e in entries:
            lines.append(f"{e['time']}  {e['meal'].title():<11}{e['description'][:46]} — {round(e['calories'])} kcal")
    return "\n".join(lines)


def _show(player, title: str, text: str) -> None:
    try:
        if player is not None and hasattr(player, "show_content"):
            player.show_content(title, text)
    except Exception:
        pass


def _fmt(t: dict) -> str:
    return f"{round(t['calories'])} kcal (protein {round(t['protein'])}g, carbs {round(t['carbs'])}g, fat {round(t['fat'])}g)"


def calorie_counter(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "today").lower().strip()
    day = _today(p.get("date"))

    with _LOCK:
        data = _load()
        data.setdefault("log", {})

        if action in ("set_profile", "profile"):
            prof = dict(data.get("profile") or {})
            for k in ("age", "sex", "weight_kg", "height_cm", "activity", "goal", "pace_kg_week"):
                if p.get(k) not in (None, ""):
                    prof[k] = p[k]
            missing = [k for k in ("age", "sex", "weight_kg", "height_cm") if k not in prof]
            if missing:
                data["profile"] = prof
                _save(data)
                return f"Saved. I still need your {', '.join(missing)} to calculate your calorie budget, sir."
            try:
                plan = compute_plan(prof)
            except Exception as e:
                return f"Sir, those profile values don't look right: {e}"
            data["profile"] = prof
            _save(data)
            msg = (f"Profile saved, sir. Daily budget: {plan['calories']} kcal — protein {plan['protein']}g, "
                   f"carbs {plan['carbs']}g, fat {plan['fat']}g. (BMR {plan['bmr']}, maintenance {plan['tdee']} kcal.)")
            _show(player, "NUTRITION PLAN", msg)
            return msg

        if action in ("estimate", "log_meal", "log", "add"):
            desc = str(p.get("description") or "").strip()
            manual = p.get("calories")
            img = p.get("image_path")
            if manual in (None, "") and not desc and not img:
                return "Sir, tell me what you ate, or send a photo."
            if manual not in (None, ""):
                est = {"items": [], "source": "manual entry",
                       "total": {"calories": float(manual), "protein": float(p.get("protein") or 0),
                                 "carbs": float(p.get("carbs") or 0), "fat": float(p.get("fat") or 0)}}
            else:
                log(f"[Nutrition] Estimating: {desc[:60] or 'image'}", player)
                est = estimate(desc, img)
            if not est:
                return "Sir, I couldn't work out the nutrition for that. Tell me the calories and I'll log it."
            t = est["total"]
            conf = est.get("confidence")
            tag = f" ({est['source']}{', ' + conf + ' confidence' if conf else ''})"
            if action == "estimate":
                return f"{desc or 'That meal'}: about {_fmt(t)}{tag}. Not logged."
            meal = str(p.get("meal") or "").lower()
            if meal not in MEALS:
                h = datetime.now().hour
                meal = "breakfast" if h < 11 else "lunch" if h < 16 else "dinner" if h < 22 else "snack"
            entry = {"id": uuid.uuid4().hex[:8], "time": datetime.now().strftime("%H:%M"), "meal": meal,
                     "description": desc or "photo meal", "items": est.get("items", []),
                     "calories": t["calories"], "protein": t["protein"], "carbs": t["carbs"], "fat": t["fat"]}
            data["log"].setdefault(day, []).append(entry)
            _save(data)
            tgt, _ = _targets(data)
            tot = _day_totals(data["log"][day])
            left = tgt["calories"] - tot["calories"]
            msg = (f"Logged {meal}: {entry['description'][:60]} — {_fmt(t)}{tag}. "
                   f"Today {tot['calories']:,} of {tgt['calories']:,} kcal; "
                   f"{abs(left):,} kcal {'left' if left >= 0 else 'over budget'}.")
            _show(player, "NUTRITION", _summary(data, day))
            return msg

        if action in ("today", "summary", "status"):
            text = _summary(data, day)
            _show(player, "NUTRITION", text)
            tgt, _ = _targets(data)
            tot = _day_totals(data["log"].get(day, []))
            left = tgt["calories"] - tot["calories"]
            return (f"{day}: {tot['calories']:,} of {tgt['calories']:,} kcal eaten, {abs(left):,} {'left' if left >= 0 else 'over'}. "
                    f"Protein {tot['protein']}g of {tgt['protein']}g, carbs {tot['carbs']}g of {tgt['carbs']}g, "
                    f"fat {tot['fat']}g of {tgt['fat']}g.")

        if action == "history":
            n = max(1, min(30, int(p.get("days") or 7)))
            tgt, _ = _targets(data)
            rows = []
            for i in range(n):
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                tot = _day_totals(data["log"].get(d, []))
                if data["log"].get(d):
                    rows.append(f"{d}: {tot['calories']:,} kcal (P {tot['protein']} C {tot['carbs']} F {tot['fat']})")
            if not rows:
                return "No meals logged in that period, sir."
            text = f"Last {n} days (budget {tgt['calories']:,} kcal)\n" + "\n".join(rows)
            _show(player, "NUTRITION HISTORY", text)
            return text

        if action in ("undo", "delete_last", "remove"):
            entries = data["log"].get(day, [])
            if not entries:
                return "There is nothing to remove for that day, sir."
            if p.get("description"):
                q = str(p["description"]).lower()
                match = [e for e in entries if q in e["description"].lower()]
                gone = match[-1] if match else None
            else:
                gone = entries[-1]
            if gone is None:
                return "I couldn't find that meal, sir."
            entries.remove(gone)
            _save(data)
            return f"Removed '{gone['description'][:50]}' ({round(gone['calories'])} kcal) from {day}."

        if action == "reset_day":
            data["log"][day] = []
            _save(data)
            return f"Cleared all meals for {day}, sir."

    return "Unknown action. Available: set_profile, log_meal, estimate, today, history, undo, reset_day."


TOOL = {
    "name": "calorie_counter",
    "description": (
        "Calorie and nutrition tracker. Logs meals from a text description or a food photo (AI-estimated calories, "
        "protein, carbs, fat), keeps a daily log, computes a personal daily calorie budget and macro targets from "
        "the user's profile (age, sex, weight, height, activity, goal), shows what is left today, and history. "
        "Use when the user says what they ate, asks how many calories something has, or asks about their "
        "daily intake, budget, or macros."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "log_meal | estimate | today | history | set_profile | undo | reset_day"},
            "description": {"type": "STRING", "description": "What was eaten, with portions if known, e.g. '2 eggs, toast and a coffee'"},
            "image_path": {"type": "STRING", "description": "Path to a photo of the meal (optional)"},
            "meal": {"type": "STRING", "description": "breakfast | lunch | dinner | snack (auto if omitted)"},
            "calories": {"type": "NUMBER", "description": "Manual calories (skips estimation)"},
            "protein": {"type": "NUMBER", "description": "Manual protein grams"},
            "carbs": {"type": "NUMBER", "description": "Manual carbs grams"},
            "fat": {"type": "NUMBER", "description": "Manual fat grams"},
            "date": {"type": "STRING", "description": "YYYY-MM-DD, 'today' or 'yesterday'"},
            "days": {"type": "INTEGER", "description": "history length in days"},
            "age": {"type": "INTEGER", "description": "set_profile: age in years"},
            "sex": {"type": "STRING", "description": "set_profile: male | female"},
            "weight_kg": {"type": "NUMBER", "description": "set_profile: weight in kg"},
            "height_cm": {"type": "NUMBER", "description": "set_profile: height in cm"},
            "activity": {"type": "STRING", "description": "set_profile: sedentary | light | moderate | active | very_active"},
            "goal": {"type": "STRING", "description": "set_profile: lose | maintain | gain"},
            "pace_kg_week": {"type": "NUMBER", "description": "set_profile: target kg per week (default 0.5)"},
        },
    },
    "handler": calorie_counter,
}

# by ASDcuber521
