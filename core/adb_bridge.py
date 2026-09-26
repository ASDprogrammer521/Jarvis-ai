"""Wireless ADB bridge for deeper phone control.

Requires on the phone (one-time):
  Developer options → Wireless debugging ON
  or: USB once → adb tcpip 5555

When Jarvis App links, we try adb connect <phone-ip>:<port>.
When the last client disconnects, we adb disconnect for safety.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Optional

_lock = threading.Lock()
_phone_ip: Optional[str] = None
_connected_serial: Optional[str] = None
_ports_try = (5555, 37099, 5556, 5037)


def adb_bin() -> Optional[str]:
    return shutil.which("adb")


def _run(args: list[str], timeout: int = 15) -> tuple[bool, str]:
    bin_path = adb_bin()
    if not bin_path:
        return False, "adb not found on PATH (install Android platform-tools)"
    try:
        r = subprocess.run(
            [bin_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "adb timed out"
    except Exception as e:
        return False, str(e)


def devices() -> list[str]:
    ok, out = _run(["devices"])
    if not ok and not out:
        return []
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devs.append(parts[0])
    return devs


def is_ready() -> bool:
    return bool(devices())


def set_phone_ip(ip: str | None) -> None:
    global _phone_ip
    with _lock:
        _phone_ip = (ip or "").strip() or None


def get_phone_ip() -> Optional[str]:
    return _phone_ip


def connect_wireless(ip: str | None = None, ports: tuple[int, ...] | None = None) -> str:
    """Try adb connect to phone IP on common wireless ports."""
    global _connected_serial
    target_ip = (ip or _phone_ip or "").strip()
    if not target_ip:
        return "No phone IP known yet (connect Jarvis App first)."
    if not adb_bin():
        return "adb not installed on this PC."

    set_phone_ip(target_ip)
    ports = ports or _ports_try
    last = ""
    for port in ports:
        serial = f"{target_ip}:{port}"
        ok, out = _run(["connect", serial], timeout=8)
        last = out or ("ok" if ok else "fail")
        # adb connect returns 0 even on "failed to connect" sometimes — check devices
        devs = devices()
        if serial in devs or any(target_ip in d for d in devs):
            _connected_serial = next((d for d in devs if target_ip in d), serial)
            return f"ADB linked: {_connected_serial}"
    # USB device already present?
    devs = devices()
    if devs:
        _connected_serial = devs[0]
        return f"ADB already online: {devs[0]} (USB or previous wireless)"
    return (
        f"ADB connect failed for {target_ip} ({last}). "
        "On phone: Developer options → Wireless debugging ON, "
        "or USB once then: adb tcpip 5555"
    )


def disconnect_all_wireless() -> str:
    """Disconnect wireless adb endpoints (keeps USB if any)."""
    global _connected_serial
    devs = devices()
    msgs = []
    for d in devs:
        if ":" in d:  # wireless serial ip:port
            ok, out = _run(["disconnect", d], timeout=5)
            msgs.append(f"disconnect {d}: {out or ('ok' if ok else 'fail')}")
    if _phone_ip:
        _run(["disconnect", f"{_phone_ip}:5555"], timeout=5)
    _connected_serial = None
    if not msgs:
        return "No wireless ADB session to close."
    return "; ".join(msgs)


def on_phone_app_linked(client_ip: str | None) -> str:
    """Called when Jarvis App WebSocket connects."""
    if client_ip:
        set_phone_ip(client_ip)
    return connect_wireless(client_ip)


def on_phone_app_unlinked() -> str:
    """Called when last remote client disconnects."""
    return disconnect_all_wireless()


def shell(cmd: str, serial: str | None = None, timeout: int = 20) -> tuple[bool, str]:
    devs = devices()
    if not devs:
        return False, "No ADB device"
    ser = serial or _connected_serial or devs[0]
    return _run(["-s", ser, "shell", cmd], timeout=timeout)


def screencap_to(local_path: str) -> tuple[bool, str]:
    devs = devices()
    if not devs:
        return False, "No ADB device"
    ser = _connected_serial or devs[0]
    remote = "/sdcard/jarvis_screen.png"
    ok, msg = _run(["-s", ser, "shell", "screencap", "-p", remote], timeout=20)
    if not ok:
        return False, msg
    ok2, msg2 = _run(["-s", ser, "pull", remote, local_path], timeout=20)
    _run(["-s", ser, "shell", "rm", remote], timeout=5)
    return ok2, msg2 if not ok2 else local_path
