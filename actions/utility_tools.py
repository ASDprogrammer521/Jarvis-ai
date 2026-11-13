from __future__ import annotations

import ast
import math
import operator
import random
import re
import secrets
import string
import time
from datetime import date, datetime

from actions._common import clip_write, open_path, output_dir, safe_name, unique_path

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FN = {"sqrt": math.sqrt, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil, "log": math.log10, "ln": math.log,
       "log2": math.log2, "exp": math.exp, "factorial": math.factorial, "min": min, "max": max, "pow": pow,
       "sin": lambda x: math.sin(math.radians(x)), "cos": lambda x: math.cos(math.radians(x)),
       "tan": lambda x: math.tan(math.radians(x)), "asin": lambda x: math.degrees(math.asin(x)),
       "acos": lambda x: math.degrees(math.acos(x)), "atan": lambda x: math.degrees(math.atan(x))}
_CONST = {"pi": math.pi, "e": math.e, "tau": math.tau}
_WORDS = [(r"\bto the power of\b", "**"), (r"\bmultiplied by\b|\btimes\b|×", "*"), (r"\bdivided by\b|÷", "/"),
          (r"\bplus\b", "+"), (r"\bminus\b", "-"), (r"\bmod(?:ulo)?\b", "%"), (r"\^", "**")]


def _ev(n):
    if isinstance(n, ast.Expression):
        return _ev(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 1000:
            raise ValueError("exponent too large")
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FN and not n.keywords:
        return _FN[n.func.id](*[_ev(a) for a in n.args])
    raise ValueError("unsupported expression")


def calculate(expr: str) -> str:
    s = (expr or "").lower().replace(",", "").replace("what is", "").replace("calculate", "").strip().rstrip("?=")
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"((\1)/100*(\2))", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"((\1)/100)", s)
    for pat, rep in _WORDS:
        s = re.sub(pat, rep, s)
    s = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", s)
    try:
        v = _ev(ast.parse(s, mode="eval"))
    except ZeroDivisionError:
        return "That divides by zero, sir."
    except Exception:
        return f"I couldn't evaluate “{expr}”, sir."
    if isinstance(v, float):
        v = round(v, 10)
        if v == int(v) and abs(v) < 1e15:
            v = int(v)
    return f"{expr.strip()} = {v:,}" if isinstance(v, int) else f"{expr.strip()} = {v}"


U = {
    "length": {"m": 1, "meter": 1, "metre": 1, "km": 1000, "kilometer": 1000, "cm": .01, "centimeter": .01, "mm": .001, "millimeter": .001,
               "mi": 1609.344, "mile": 1609.344, "yd": .9144, "yard": .9144, "ft": .3048, "foot": .3048, "feet": .3048, "in": .0254, "inch": .0254, "nmi": 1852},
    "mass": {"kg": 1, "kilogram": 1, "g": .001, "gram": .001, "mg": 1e-6, "lb": .45359237, "pound": .45359237, "oz": .028349523, "ounce": .028349523,
             "t": 1000, "tonne": 1000, "st": 6.35029318, "stone": 6.35029318},
    "volume": {"l": 1, "liter": 1, "litre": 1, "ml": .001, "milliliter": .001, "gal": 3.785411784, "gallon": 3.785411784, "qt": .946352946,
               "pt": .473176473, "cup": .2365882365, "floz": .0295735296, "tbsp": .0147867648, "tsp": .00492892159},
    "speed": {"mps": 1, "kmh": 1 / 3.6, "kph": 1 / 3.6, "mph": .44704, "kn": .514444, "knot": .514444},
    "area": {"m2": 1, "km2": 1e6, "ha": 1e4, "hectare": 1e4, "acre": 4046.8564224, "ft2": .09290304, "sqft": .09290304, "cm2": 1e-4},
    "data": {"byte": 1, "kb": 1024, "kilobyte": 1024, "mb": 1024 ** 2, "megabyte": 1024 ** 2, "gb": 1024 ** 3, "gigabyte": 1024 ** 3,
             "tb": 1024 ** 4, "terabyte": 1024 ** 4, "bit": .125},
    "time": {"s": 1, "sec": 1, "second": 1, "min": 60, "minute": 60, "h": 3600, "hour": 3600, "d": 86400, "day": 86400, "wk": 604800, "week": 604800},
}
CUR = {"dollar": "USD", "dollars": "USD", "usd": "USD", "euro": "EUR", "euros": "EUR", "pound": "GBP", "pounds": "GBP", "yen": "JPY",
       "yuan": "CNY", "ruble": "RUB", "rouble": "RUB", "som": "UZS", "sum": "UZS", "soum": "UZS", "lira": "TRY", "tenge": "KZT",
       "rupee": "INR", "won": "KRW", "dirham": "AED", "zloty": "PLN", "franc": "CHF"}
_RATES: dict = {}


def _unit(name: str) -> str:
    n = re.sub(r"[^a-z0-9/°]", "", str(name or "").lower())
    n = {"c": "c", "celsius": "c", "°c": "c", "f": "f", "fahrenheit": "f", "°f": "f", "k": "k", "kelvin": "k", "km/h": "kmh", "m/s": "mps"}.get(n, n)
    if n.endswith("s") and n[:-1] in sum((list(d) for d in U.values()), []) + list(CUR):
        n = n[:-1]
    if n == "feet":
        n = "foot"
    return n


def convert(value: float, a: str, b: str) -> str:
    ua, ub = _unit(a), _unit(b)
    if ua in ("c", "f", "k") and ub in ("c", "f", "k"):
        c = value if ua == "c" else (value - 32) * 5 / 9 if ua == "f" else value - 273.15
        out = c if ub == "c" else c * 9 / 5 + 32 if ub == "f" else c + 273.15
        return f"{value:g}°{ua.upper()} = {out:.2f}°{ub.upper()}"
    for cat, table in U.items():
        if ua in table and ub in table:
            out = value * table[ua] / table[ub]
            return f"{value:g} {a} = {out:,.6g} {b}"
    ca = CUR.get(ua) or (ua.upper() if len(ua) == 3 and ua.isalpha() else None)
    cb = CUR.get(ub) or (ub.upper() if len(ub) == 3 and ub.isalpha() else None)
    if ca and cb:
        import requests
        t = _RATES.get(ca)
        if not t or time.time() - t[0] > 3600:
            r = requests.get(f"https://open.er-api.com/v6/latest/{ca}", timeout=6).json()
            if r.get("result") != "success":
                return f"I couldn't get the exchange rate for {ca}, sir."
            t = (time.time(), r["rates"])
            _RATES[ca] = t
        if cb not in t[1]:
            return f"I don't know the currency {cb}, sir."
        return f"{value:,.2f} {ca} ≈ {value * t[1][cb]:,.2f} {cb} (live rate {t[1][cb]:.4f})"
    return f"I can't convert {a} to {b}, sir — they are different kinds of units."


def password(length: int, symbols: bool) -> str:
    length = max(8, min(64, length))
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits] + ([ "!@#$%^&*()-_=+?" ] if symbols else [])
    chars = [secrets.choice(p) for p in pools]
    allc = "".join(pools)
    chars += [secrets.choice(allc) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


ZONES = {"tashkent": "Asia/Tashkent", "samarkand": "Asia/Samarkand", "new york": "America/New_York", "los angeles": "America/Los_Angeles",
         "chicago": "America/Chicago", "toronto": "America/Toronto", "mexico city": "America/Mexico_City", "sao paulo": "America/Sao_Paulo",
         "london": "Europe/London", "paris": "Europe/Paris", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid", "rome": "Europe/Rome",
         "moscow": "Europe/Moscow", "kyiv": "Europe/Kyiv", "istanbul": "Europe/Istanbul", "cairo": "Africa/Cairo", "dubai": "Asia/Dubai",
         "baku": "Asia/Baku", "almaty": "Asia/Almaty", "bishkek": "Asia/Bishkek", "dushanbe": "Asia/Dushanbe", "ashgabat": "Asia/Ashgabat",
         "karachi": "Asia/Karachi", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "dhaka": "Asia/Dhaka", "bangkok": "Asia/Bangkok",
         "singapore": "Asia/Singapore", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
         "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo", "sydney": "Australia/Sydney", "auckland": "Pacific/Auckland", "utc": "UTC"}


def time_in(place: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    key = (place or "").strip().lower()
    name = ZONES.get(key) or (place or "").strip().replace(" ", "_")
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return f"I don't know the time zone for '{place}', sir. Try a big city name."
    now = datetime.now(tz)
    local = datetime.now().astimezone()
    diff = (now.utcoffset() - local.utcoffset()).total_seconds() / 3600
    rel = "the same time as here" if diff == 0 else f"{abs(diff):g} h {'ahead of' if diff > 0 else 'behind'} you"
    return f"In {place.title()} it's {now:%H:%M} on {now:%A, %d %B} (UTC{now:%z}), {rel}."


def days_until(text: str) -> str:
    s = (text or "").strip()
    today = date.today()
    for fmt, has_year in (("%Y-%m-%d", True), ("%d.%m.%Y", True), ("%d/%m/%Y", True), ("%B %d %Y", True), ("%d %B %Y", True),
                          ("%B %d", False), ("%b %d", False), ("%d %B", False), ("%d.%m", False)):
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if not has_year:
            d = d.replace(year=today.year)
            if d < today:
                d = d.replace(year=today.year + 1)
        n = (d - today).days
        if n == 0:
            return f"{d:%d %B %Y} is today!"
        return f"{abs(n)} days {'until' if n > 0 else 'since'} {d:%d %B %Y} (about {abs(n) // 7} weeks)."
    return "I couldn't read that date, sir. Try '2026-12-31' or 'December 31'."


def utility_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "calculate").lower().strip()
    try:
        if action in ("calculate", "calc", "math"):
            return calculate(str(p.get("expression") or p.get("text") or ""))
        if action in ("convert", "unit", "currency"):
            if p.get("value") is None:
                return "Sir, which amount should I convert?"
            return convert(float(p["value"]), str(p.get("from_unit") or ""), str(p.get("to_unit") or ""))
        if action == "password":
            pw = password(int(p.get("length") or 16), bool(p.get("symbols", True)))
            try:
                clip_write(pw)
                copied = " It's copied to your clipboard."
            except Exception:
                copied = ""
            shown = False
            if player is not None and hasattr(player, "show_content"):
                player.show_content("PASSWORD", pw)
                shown = True
            if copied or shown:
                return f"Generated a strong {len(pw)}-character password.{' It is on screen.' if shown else ''}{copied} Do not read it out loud."
            return f"Password (do not read aloud): {pw}"
        if action in ("qr", "qr_code"):
            import qrcode
            data = str(p.get("text") or "").strip()
            if not data:
                return "Sir, what should the QR code contain?"
            path = unique_path(output_dir("QR"), safe_name(data, "qr", 24), ".png")
            qrcode.make(data).save(str(path))
            open_path(path)
            return f"QR code created and opened. Saved to {path}."
        if action in ("time_in", "time", "timezone"):
            return time_in(str(p.get("place") or "UTC"))
        if action in ("days_until", "countdown", "date"):
            return days_until(str(p.get("date") or p.get("text") or ""))
        if action in ("random", "dice", "coin", "pick"):
            kind = str(p.get("kind") or action)
            if kind == "coin":
                return random.choice(["Heads.", "Tails."])
            if kind == "pick" and p.get("text"):
                opts = [o.strip() for o in re.split(r"[,;|]|\bor\b", str(p["text"])) if o.strip()]
                return f"I pick: {random.choice(opts)}." if opts else "Give me some options, sir."
            if kind == "number":
                lo, hi = int(p.get("minimum") or 1), int(p.get("maximum") or 100)
                return f"{random.randint(min(lo, hi), max(lo, hi))}"
            return f"You rolled a {random.randint(1, max(2, int(p.get('sides') or 6)))}."
    except ImportError as e:
        return f"Sir, I need the '{e.name}' package: pip install {e.name}"
    except Exception as e:
        return f"That didn't work: {e}"
    return "Unknown action. Available: calculate, convert, password, qr, time_in, days_until, random."


TOOL = {
    "name": "utility_tools",
    "description": (
        "Everyday utilities: calculator (math, percentages, sqrt, trig), unit and live currency conversion "
        "(km↔miles, kg↔lb, °C↔°F, GB, USD→UZS…), strong password generator (copied to the clipboard, never read aloud), "
        "QR code maker, current time in any city, days until a date, dice/coin/random pick."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "calculate | convert | password | qr | time_in | days_until | random"},
            "expression": {"type": "STRING", "description": "Math expression for calculate, e.g. '15% of 240' or 'sqrt(144)+3^2'"},
            "value": {"type": "NUMBER", "description": "Amount to convert"},
            "from_unit": {"type": "STRING", "description": "Unit or currency to convert from"},
            "to_unit": {"type": "STRING", "description": "Unit or currency to convert to"},
            "length": {"type": "INTEGER", "description": "Password length (8-64, default 16)"},
            "symbols": {"type": "BOOLEAN", "description": "Include symbols in the password (default true)"},
            "text": {"type": "STRING", "description": "QR content, or comma-separated options for a random pick"},
            "place": {"type": "STRING", "description": "City or IANA zone for time_in"},
            "date": {"type": "STRING", "description": "Target date for days_until, e.g. 2026-12-31"},
            "kind": {"type": "STRING", "description": "dice | coin | number | pick (for random)"},
            "sides": {"type": "INTEGER", "description": "Dice sides (default 6)"},
            "minimum": {"type": "INTEGER", "description": "Random number minimum"},
            "maximum": {"type": "INTEGER", "description": "Random number maximum"},
        },
    },
    "handler": utility_tools,
}

# by ASDcuber521
