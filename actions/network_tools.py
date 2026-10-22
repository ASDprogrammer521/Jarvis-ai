from __future__ import annotations

import os
import platform
import re
import socket
import subprocess
import time

from actions._common import log

_OS = platform.system()
_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}


def _run(cmd: list, timeout: int = 12) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace", **_HIDE)
    return (r.stdout or "") + (r.stderr or "")


def _wifi() -> tuple:
    try:
        if _OS == "Windows":
            out = _run(["netsh", "wlan", "show", "interfaces"])
            ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
            sig = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M)
            return (ssid.group(1).strip() if ssid else None, int(sig.group(1)) if sig else None)
        if _OS == "Darwin":
            out = _run(["networksetup", "-getairportnetwork", "en0"])
            m = re.search(r"Network:\s*(.+)", out)
            return (m.group(1).strip() if m else None, None)
        out = _run(["nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"])
        for line in out.splitlines():
            parts = line.split(":")
            if parts and parts[0] == "yes":
                return (parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None)
    except Exception:
        pass
    return (None, None)


def _public_ip() -> str | None:
    try:
        import requests
        return requests.get("https://api.ipify.org", timeout=4).text.strip()
    except Exception:
        return None


def info() -> str:
    import psutil
    lines = []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith("127."):
                lines.append(f"• {name}: {a.address}")
    ssid, sig = _wifi()
    pub = _public_ip()
    head = [f"Internet: {'connected' if pub else 'not reachable'}"]
    if pub:
        head.append(f"Public IP: {pub}")
    if ssid:
        head.append(f"Wi-Fi: {ssid}" + (f" (signal {sig}%)" if sig is not None else ""))
    return "\n".join(head + ["Local addresses:"] + (lines or ["• none"]))


def _tcp_latency(host: str, port: int, n: int = 4) -> list:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=3):
                out.append((time.perf_counter() - t) * 1000)
        except OSError:
            pass
        time.sleep(0.15)
    return out


def ping(host: str, count: int = 4) -> str:
    host = host.strip() or "1.1.1.1"
    if not re.fullmatch(r"[A-Za-z0-9.\-:]+", host):
        return "That doesn't look like a valid host name, sir."
    flag = "-n" if _OS == "Windows" else "-c"
    try:
        out = _run(["ping", flag, str(count), host], timeout=count * 4 + 5)
        loss = re.search(r"(\d+)%\s*(?:packet )?loss", out) or re.search(r"\((\d+)% loss\)", out)
        avg = re.search(r"Average = (\d+)ms", out) or re.search(r"= [\d.]+/([\d.]+)/", out)
        if avg:
            return f"{host}: average {float(avg.group(1)):.0f} ms" + (f", {loss.group(1)}% packet loss." if loss else ".")
    except Exception:
        pass
    ms = _tcp_latency(host, 443) or _tcp_latency(host, 80)
    if ms:
        return f"{host}: about {sum(ms) / len(ms):.0f} ms (connection time, {len(ms)}/4 replies)."
    return f"{host} did not answer, sir — it may be down or you may be offline."


def speed(seconds: float = 8.0) -> str:
    import requests
    down = up = None
    t0 = time.perf_counter()
    got = 0
    try:
        with requests.get("https://speed.cloudflare.com/__down?bytes=40000000", stream=True, timeout=10) as r:
            for chunk in r.iter_content(1 << 16):
                got += len(chunk)
                if time.perf_counter() - t0 > seconds:
                    break
        dt = time.perf_counter() - t0
        down = got * 8 / dt / 1e6 if dt > 0 else None
    except Exception:
        pass
    try:
        payload = os.urandom(6 * 1024 * 1024)
        t1 = time.perf_counter()
        requests.post("https://speed.cloudflare.com/__up", data=payload, timeout=15)
        up = len(payload) * 8 / (time.perf_counter() - t1) / 1e6
    except Exception:
        pass
    lat = _tcp_latency("1.1.1.1", 443, 3)
    if down is None and up is None:
        return "The speed test couldn't reach the internet, sir."
    parts = []
    if down is not None:
        parts.append(f"download {down:.0f} Mbps")
    if up is not None:
        parts.append(f"upload {up:.0f} Mbps")
    if lat:
        parts.append(f"latency {sum(lat) / len(lat):.0f} ms")
    return "Speed test: " + ", ".join(parts) + "."


def network_tools(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "info").lower().strip()
    try:
        if action in ("info", "status", "ip", "wifi", "check"):
            text = info()
        elif action == "ping":
            return ping(str(p.get("host") or "1.1.1.1"), int(p.get("count") or 4))
        elif action in ("speed", "speedtest", "speed_test"):
            log("[Network] Running speed test…", player)
            return speed()
        else:
            return "Unknown action. Available: info, ping, speed."
    except ImportError as e:
        return f"Sir, I need the '{e.name}' package: pip install {e.name}"
    except Exception as e:
        return f"Network check failed: {e}"
    if player is not None and hasattr(player, "show_content"):
        player.show_content("NETWORK", text)
    return text


TOOL = {
    "name": "network_tools",
    "description": (
        "Network helper: shows whether the internet works, the public and local IP address and the Wi-Fi name and "
        "signal, pings a website or server, and runs an internet speed test (download, upload, latency). "
        "Use for 'am I online', 'what is my IP', 'test my internet speed', 'ping google'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "info | ping | speed"},
            "host": {"type": "STRING", "description": "Host or IP for ping, e.g. google.com"},
            "count": {"type": "INTEGER", "description": "Ping packets (default 4)"},
        },
    },
    "handler": network_tools,
}

# by ASDcuber521
