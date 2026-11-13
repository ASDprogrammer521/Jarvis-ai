"""Local-First Smart Home Core.

Everything here talks to devices *directly on the local network* — no cloud account, no internet. A device address
that resolves outside the private LAN (or loopback / link-local) is refused, and HTTP redirects are never followed,
so a misconfigured or hijacked device cannot bounce a request out to the internet.

Supported out of the box (stdlib only, `tinytuya` and `opencv` are used if installed):
  shelly · tasmota · wled · tuya (local key) · http (your own on/off URLs) · wol (wake-on-LAN) · camera (snapshot URL or RTSP)

The phone app reaches the same functions over the existing encrypted WebSocket ({"type": "home", ...}), see
dashboard/server.py, so the PC acts as the home hub and nothing leaves the house.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from actions._common import DATA_DIR, json_load, json_save, output_dir, safe_name, unique_path

STORE = DATA_DIR / "smart_home.json"
KINDS = ("shelly", "tasmota", "wled", "tuya", "http", "wol", "camera")
_LOCK = threading.RLock()
_TIMEOUT = 3.0


# ── safety: LAN only ─────────────────────────────────────────────────────────────
def _is_local(host: str) -> bool:
    host = urllib.parse.urlsplit("//" + (host or "").strip()).hostname or ""   # accepts "192.168.1.5:8080" too
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _http(dev: dict, path_or_url: str, method: str = "GET", body: dict | None = None, raw: bool = False):
    url = path_or_url if path_or_url.startswith("http") else f"http://{dev['host']}{path_or_url}"
    host = urllib.parse.urlsplit(url).hostname or ""
    if not _is_local(host):
        raise PermissionError(f"{host or 'address'} is not on your local network — refused")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if dev.get("user"):
        tok = base64.b64encode(f"{dev['user']}:{dev.get('password', '')}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    with _OPENER.open(req, timeout=_TIMEOUT) as r:
        payload = r.read(8_000_000 if raw else 200_000)
    if raw:
        return payload
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except ValueError:
        return payload.decode("utf-8", "replace")


# ── store ────────────────────────────────────────────────────────────────────────
def _load() -> dict:
    d = json_load(STORE, {}) or {}
    d.setdefault("devices", {})
    d.setdefault("scenes", {})
    return d


def _save(d: dict) -> None:
    json_save(STORE, d)


def _match(d: dict, target: str) -> list[str]:
    t = (target or "").strip().lower()
    if not t or t in ("all", "everything"):
        return [n for n, v in d["devices"].items() if v["kind"] not in ("camera", "wol")]
    if t.startswith("room:"):
        t = t[5:]
        return [n for n, v in d["devices"].items() if v.get("room", "").lower() == t]
    exact = [n for n in d["devices"] if n.lower() == t]
    if exact:
        return exact
    part = [n for n in d["devices"] if t in n.lower()]
    return part or [n for n, v in d["devices"].items() if v.get("room", "").lower() == t]


# ── per-protocol drivers ─────────────────────────────────────────────────────────
def _rgb(value: str) -> tuple[int, int, int] | None:
    names = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
             "warm": (255, 170, 70), "yellow": (255, 220, 0), "orange": (255, 120, 0), "purple": (150, 60, 255),
             "pink": (255, 90, 190), "cyan": (0, 220, 255)}
    v = (value or "").strip().lower()
    if v in names:
        return names[v]
    m = re.fullmatch(r"#?([0-9a-f]{6})", v)
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else None


def _pct(value) -> int | None:
    m = re.search(r"\d+", str(value or ""))
    return max(0, min(100, int(m.group()))) if m else None


def _drive(dev: dict, cmd: str, value: str = "") -> str:
    kind = dev["kind"]
    if kind == "shelly":
        return _shelly(dev, cmd)
    if kind == "tasmota":
        return _tasmota(dev, cmd, value)
    if kind == "wled":
        return _wled(dev, cmd, value)
    if kind == "tuya":
        return _tuya(dev, cmd, value)
    if kind == "http":
        key = {"on": "on_url", "off": "off_url", "toggle": "toggle_url", "status": "status_url"}.get(cmd)
        if not key or not dev.get(key):
            raise ValueError(f"no {cmd} URL configured")
        out = _http(dev, dev[key])
        return str(out)[:80] if cmd == "status" else "ok"
    if kind == "wol":
        if cmd != "on":
            raise ValueError("a wake-on-LAN device can only be switched on")
        return _wol(dev)
    if kind == "camera":
        if cmd in ("snapshot", "status", "on"):
            return _snapshot(dev)
        raise ValueError("cameras support snapshot")
    raise ValueError(f"unknown kind {kind}")


def _shelly(dev: dict, cmd: str) -> str:
    ch = int(dev.get("channel", 0))
    if cmd == "status":
        try:
            st = _http(dev, f"/rpc/Switch.GetStatus?id={ch}")
            return "on" if st.get("output") else "off"
        except (urllib.error.HTTPError, AttributeError):
            st = _http(dev, f"/relay/{ch}")
            return "on" if st.get("ison") else "off"
    if cmd not in ("on", "off", "toggle"):
        raise ValueError("shelly supports on / off / toggle")
    try:
        if cmd == "toggle":
            _http(dev, f"/rpc/Switch.Toggle?id={ch}")
        else:
            _http(dev, f"/rpc/Switch.Set?id={ch}&on={'true' if cmd == 'on' else 'false'}")
    except urllib.error.HTTPError:                       # Gen1 firmware
        _http(dev, f"/relay/{ch}?turn={cmd}")
    return cmd


def _tasmota(dev: dict, cmd: str, value: str) -> str:
    def c(s: str):
        return _http(dev, "/cm?cmnd=" + urllib.parse.quote(s))
    if cmd in ("on", "off", "toggle"):
        c(f"Power {cmd}")
        return cmd
    if cmd == "status":
        return str(c("Power").get("POWER", "?")).lower()
    if cmd == "brightness" and _pct(value) is not None:
        c(f"Dimmer {_pct(value)}")
        return f"{_pct(value)}%"
    if cmd == "color" and _rgb(value):
        c("Color #%02x%02x%02x" % _rgb(value))
        return value
    raise ValueError(f"tasmota can't do {cmd}")


def _wled(dev: dict, cmd: str, value: str) -> str:
    if cmd == "status":
        s = _http(dev, "/json/state")
        return f"{'on' if s.get('on') else 'off'}, {round(s.get('bri', 0) / 2.55)}%"
    state: dict = {}
    if cmd in ("on", "off"):
        state["on"] = cmd == "on"
    elif cmd == "toggle":
        state["on"] = "t"
    elif cmd == "brightness" and _pct(value) is not None:
        state.update(on=True, bri=round(_pct(value) * 2.55))
    elif cmd == "color" and _rgb(value):
        state.update(on=True, seg=[{"col": [list(_rgb(value))]}])
    else:
        raise ValueError(f"wled can't do {cmd}")
    _http(dev, "/json/state", "POST", state)
    return cmd


def _tuya(dev: dict, cmd: str, value: str) -> str:
    try:
        import tinytuya
    except ImportError:
        raise RuntimeError("tuya support needs: pip install tinytuya")
    if not _is_local(dev["host"]):
        raise PermissionError("tuya device address is not on your local network — refused")
    d = tinytuya.BulbDevice(dev["device_id"], dev["host"], dev["local_key"])
    d.set_version(float(dev.get("version", 3.3)))
    d.set_socketTimeout(_TIMEOUT)
    if cmd == "on":
        d.turn_on()
    elif cmd == "off":
        d.turn_off()
    elif cmd == "toggle":
        on = bool(d.status().get("dps", {}).get("20", d.status().get("dps", {}).get("1")))
        d.turn_off() if on else d.turn_on()
    elif cmd == "status":
        dps = d.status().get("dps", {})
        return "on" if (dps.get("20") or dps.get("1")) else "off"
    elif cmd == "brightness" and _pct(value) is not None:
        d.set_brightness_percentage(_pct(value))
    elif cmd == "color" and _rgb(value):
        d.set_colour(*_rgb(value))
    else:
        raise ValueError(f"tuya can't do {cmd}")
    return cmd


def _wol(dev: dict) -> str:
    mac = re.sub(r"[^0-9a-fA-F]", "", dev.get("mac", ""))
    if len(mac) != 12:
        raise ValueError("a valid MAC address is needed")
    packet = b"\xff" * 6 + bytes.fromhex(mac) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (dev.get("broadcast", "255.255.255.255"), 9))
    return "wake packet sent"


def _snapshot(dev: dict) -> str:
    out = unique_path(output_dir("SmartHome"), safe_name(dev["name"], "camera"), ".jpg")
    if dev.get("snapshot_url"):
        out.write_bytes(_http(dev, dev["snapshot_url"], raw=True))
        return f"snapshot saved: {out}"
    rtsp = dev.get("rtsp_url")
    if not rtsp:
        raise ValueError("camera needs snapshot_url or rtsp_url")
    if not _is_local(urllib.parse.urlsplit(rtsp).hostname or ""):
        raise PermissionError("camera address is not on your local network — refused")
    try:
        import cv2
    except ImportError:
        raise RuntimeError("RTSP snapshots need opencv-python")
    cap = cv2.VideoCapture(rtsp)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise RuntimeError("couldn't read a frame from the camera")
    cv2.imwrite(str(out), frame)
    return f"snapshot saved: {out}"


# ── discovery ────────────────────────────────────────────────────────────────────
def _lan_prefix() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))          # no packet is sent; just selects the LAN interface
            ip = s.getsockname()[0]
        return ".".join(ip.split(".")[:3]) if ipaddress.ip_address(ip).is_private else None
    except OSError:
        return None


def _probe(ip: str) -> dict | None:
    dev = {"host": ip}
    for kind, path, test in (("shelly", "/shelly", lambda r: isinstance(r, dict) and ("type" in r or "gen" in r)),
                             ("wled", "/json/info", lambda r: isinstance(r, dict) and "leds" in r),
                             ("tasmota", "/cm?cmnd=Status", lambda r: isinstance(r, dict) and "Status" in r)):
        try:
            r = _http(dev, path)
        except Exception:
            continue
        if test(r):
            return {"kind": kind, "host": ip, "name": r.get("name") or r.get("id") or r.get("Status", {}).get("DeviceName") or f"{kind}-{ip.split('.')[-1]}"}
    return None


def discover() -> list[dict]:
    prefix = _lan_prefix()
    if not prefix:
        return []
    with ThreadPoolExecutor(48) as ex:
        return [r for r in ex.map(_probe, [f"{prefix}.{i}" for i in range(1, 255)]) if r]


# ── command entry point (voice tool + phone WebSocket) ───────────────────────────────
def run_command(p: dict) -> str:
    action = str(p.get("action") or "list").lower().strip().replace(" ", "_")
    target = str(p.get("target") or p.get("name") or "")
    value = str(p.get("value") or "")
    with _LOCK:
        d = _load()

    if action == "list":
        if not d["devices"]:
            return "No smart-home devices yet. Say 'scan my network' or add one with its IP address."
        return "; ".join(f"{n} ({v['kind']}{', ' + v['room'] if v.get('room') else ''})" for n, v in d["devices"].items())

    if action == "discover":
        found = discover()
        known = {v["host"] for v in d["devices"].values()}
        new = [f for f in found if f["host"] not in known]
        if not found:
            return "I found no Shelly, Tasmota or WLED devices on your network."
        return ("Found: " + ", ".join(f"{f['name']} ({f['kind']} at {f['host']})" for f in found)
                + (". Say 'add' with a name to save one." if new else ". All are already saved."))

    if action == "add":
        name, kind = (p.get("name") or "").strip(), str(p.get("kind") or "").lower()
        host = (p.get("host") or "").strip()
        if not name or kind not in KINDS:
            return f"Give me a name and a kind: {', '.join(KINDS)}."
        if kind != "wol" and not _is_local(host or urllib.parse.urlsplit(str(p.get("rtsp_url") or "")).hostname or ""):
            return "That address isn't on your local network, so I won't add it."
        dev = {k: p[k] for k in ("host", "room", "mac", "broadcast", "device_id", "local_key", "version", "channel", "user",
                                 "password", "on_url", "off_url", "toggle_url", "status_url", "snapshot_url", "rtsp_url") if p.get(k) not in (None, "")}
        dev.update(kind=kind, name=name)
        with _LOCK:
            d["devices"][name] = dev
            _save(d)
        return f"Saved {name} ({kind})."

    if action == "remove":
        names = _match(d, target)
        if not names:
            return f"No device called '{target}'."
        with _LOCK:
            for n in names:
                d["devices"].pop(n, None)
            _save(d)
        return f"Removed {', '.join(names)}."

    if action == "scene_add":
        steps = p.get("steps")
        sname = (p.get("scene") or target).strip()
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except ValueError:
                steps = None
        if not sname or not isinstance(steps, list) or not steps:
            return "A scene needs a name and steps like [{\"target\":\"lamp\",\"action\":\"on\"}]."
        with _LOCK:
            d["scenes"][sname] = [{k: s.get(k, "") for k in ("target", "action", "value")} for s in steps if isinstance(s, dict)]
            _save(d)
        return f"Scene '{sname}' saved with {len(d['scenes'][sname])} steps."

    if action == "scene_run":
        scene = next((v for n, v in d["scenes"].items() if n.lower() == target.lower()), None)
        if scene is None:
            return f"No scene '{target}'. Scenes: {', '.join(d['scenes']) or 'none'}."
        return " | ".join(run_command(dict(step)) for step in scene)

    if action == "all_off":
        action, target = "off", "all"

    cmd = {"turn_on": "on", "turn_off": "off", "dim": "brightness", "colour": "color", "photo": "snapshot"}.get(action, action)
    if cmd not in ("on", "off", "toggle", "status", "brightness", "color", "snapshot"):
        return f"Unknown smart-home action '{action}'."
    names = _match(d, target)
    if not names:
        return f"I don't know a device called '{target}'." if target else "Which device?"
    results = []
    for n in names:
        try:
            results.append(f"{n}: {_drive(d['devices'][n], cmd, value)}")
        except Exception as e:
            results.append(f"{n}: failed ({e})")
    return "; ".join(results)


def smart_home(parameters: dict, player=None) -> str:
    if str((parameters or {}).get("action") or "").lower() in ("open", "show", "open_page", "dashboard"):
        if player is not None and hasattr(player, "module_command"):
            player.module_command("smart_home_page", "show")
            return "Opening the Smart Home page."
    try:
        out = run_command(parameters or {})
    except Exception as e:
        out = f"Sir, the smart-home hub failed: {e}"
    if player is not None:
        try:
            player.write_log(f"[Home] {out}")
        except Exception:
            pass
    return out


TOOL = {
    "name": "smart_home",
    "description": (
        "Local-first smart home hub — controls lights, plugs, LED strips, IP cameras and wake-on-LAN PCs/TVs directly on the "
        "home network (Shelly, Tasmota, WLED, Tuya, custom HTTP). No cloud. Use for 'turn off the living room light', "
        "'set the desk lamp to 40%', 'make the strip blue', 'take a snapshot from the door camera', 'wake the media PC', "
        "'scan my network for devices', 'run the movie scene', 'everything off', 'what devices do I have'. "
        "Not for the phone (use phone_control) or Spotify."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "on | off | toggle | status | brightness | color | snapshot | list | discover | add | remove | scene_add | scene_run | all_off | open (show the Smart Home page)"},
            "target": {"type": "STRING", "description": "Device name, 'room:kitchen', or 'all'"},
            "value": {"type": "STRING", "description": "Brightness 0-100 or a colour name / #RRGGBB"},
            "name": {"type": "STRING", "description": "Name for a new device"},
            "kind": {"type": "STRING", "description": "shelly | tasmota | wled | tuya | http | wol | camera (when adding)"},
            "host": {"type": "STRING", "description": "Device LAN IP or hostname (when adding)"},
            "room": {"type": "STRING", "description": "Room name (when adding)"},
            "mac": {"type": "STRING", "description": "MAC address (wol devices)"},
            "device_id": {"type": "STRING", "description": "Tuya device id"},
            "local_key": {"type": "STRING", "description": "Tuya local key"},
            "snapshot_url": {"type": "STRING", "description": "Camera snapshot URL on the LAN"},
            "rtsp_url": {"type": "STRING", "description": "Camera RTSP URL on the LAN"},
            "on_url": {"type": "STRING", "description": "LAN URL that switches a custom http device on"},
            "off_url": {"type": "STRING", "description": "LAN URL that switches a custom http device off"},
            "scene": {"type": "STRING", "description": "Scene name"},
            "steps": {"type": "STRING", "description": "JSON list of {target, action, value} steps for scene_add"},
        },
        "required": ["action"],
    },
    "handler": smart_home,
}
