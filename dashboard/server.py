"""
dashboard/server.py — JARVIS Local HTTP Dashboard

Explicit HTTP or HTTPS listener on port 8000; loopback by default.
Legacy AES-CBC payload encoding is NOT a substitute for TLS authentication.
Use trusted local code and explicit TLS for remote connections.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import logging
import os
import base64
import hashlib
import json
import re
import secrets
import socket
import string
import sys
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

class _ShutdownNoiseFilter(logging.Filter):
    """Jarvis stops by cancelling its asyncio tasks, which makes uvicorn's lifespan task print a
    harmless 'CancelledError' traceback on exit. Hide only that message; real errors still show."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            return True
        return not ("CancelledError" in text and "lifespan" in text)


def _quiet_shutdown_noise() -> None:
    log = logging.getLogger("uvicorn.error")
    if not any(isinstance(f, _ShutdownNoiseFilter) for f in log.filters):
        log.addFilter(_ShutdownNoiseFilter())


_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

def _resolve_dirs():
    """Resolve BASE_DIR / STATIC_DIR for source and PyInstaller (frozen) builds."""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        exe_dir = Path(sys.executable).resolve().parent
        static_candidates = [
            meipass / "dashboard" / "static",
            exe_dir / "_internal" / "dashboard" / "static",
            exe_dir / "dashboard" / "static",
            meipass / "static",
        ]
        static = next((c for c in static_candidates if c.is_dir()), static_candidates[0])
        base_candidates = [
            exe_dir,
            meipass,
            static.parent.parent if static.name == "static" else meipass,
        ]
        base = next((c for c in base_candidates if c.is_dir()), exe_dir)
        return base, static
    base = Path(__file__).resolve().parent.parent
    static = Path(__file__).resolve().parent / "static"
    return base, static

BASE_DIR, STATIC_DIR = _resolve_dirs()
PORT        = 8000
_ACTIVE_DASHBOARD = None

def get_active_dashboard():
    return _ACTIVE_DASHBOARD
MAX_UPLOAD_MB = 500

_PHONE_APP_PACKAGES = {
    "com.google.android.apps.messaging": "SMS",
    "com.samsung.android.messaging": "SMS",
    "com.android.mms": "SMS",
    "com.miui.mms": "SMS",
    "com.huawei.message": "SMS",
    "com.vivo.messaging": "SMS",
    "com.coloros.mms": "SMS",
    "com.coloros.message": "SMS",
    "com.whatsapp": "WhatsApp",
    "com.whatsapp.w4b": "WhatsApp",
    "org.telegram.messenger": "Telegram",
    "org.telegram.messenger.web": "Telegram",
    "org.thunderdog.challegram": "Telegram",
}

def _sanitize_phone_notification(data):
    if not isinstance(data, dict):
        return None
    package = str(data.get("package") or "").strip()[:120]
    app = _PHONE_APP_PACKAGES.get(package)
    raw_text = data.get("text")
    text = "" if raw_text is None else str(raw_text).strip()
    if not app or not text:
        return None
    sender = str(data.get("sender") or "").strip()[:120]
    text = text[:2500]
    try:
        timestamp = int(data.get("timestamp", 0))
    except (TypeError, ValueError):
        timestamp = 0
    now_ms = int(time.time() * 1000)
    if timestamp <= 0 or timestamp > now_ms + 86400000:
        timestamp = now_ms
    return {"type": "phone_notification", "app": app, "package": package,
            "sender": sender, "text": text, "timestamp": timestamp}


def _sanitize_phone_status(data):
    if not isinstance(data, dict):
        return None
    device_name = str(data.get("device_name") or "Android phone").strip()[:80] or "Android phone"
    try:
        battery = int(data.get("battery_percent"))
        if not 0 <= battery <= 100:
            battery = None
    except (TypeError, ValueError):
        battery = None
    charging = data.get("charging") if isinstance(data.get("charging"), bool) else False
    return {"type": "phone_status", "device_name": device_name,
            "battery_percent": battery, "charging": charging}

_PHONE_EVENTS = {"incoming_call", "call_active", "call_ended", "missed_call", "ring_started", "ring_stopped"}


def _sanitize_phone_event(data):
    """Events come from the phone, and a contact's name is attacker-controllable text
    (it ends up in what Jarvis reads), so keep only plain, short, bracket-free strings."""
    if not isinstance(data, dict):
        return None
    event = str(data.get("event") or "").strip().lower()
    if event not in _PHONE_EVENTS:
        return None
    number = re.sub(r"[^0-9+*#]", "", str(data.get("number") or ""))[:20]
    name = re.sub(r"[^\w .,'’-]", "", str(data.get("name") or ""), flags=re.UNICODE).strip()[:40]
    return {"event": event, "number": number, "name": name}


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "JARVIS Uploads",
        Path.home() / "Documents" / "JARVIS Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"

UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

_AES_SALT = b'JARVIS-DASHBOARD-v1'

def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()

def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')

_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"

def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"JARVIS Dashboard Port {port}"
        prog_rule  = "JARVIS Dashboard Python"
        py_exe     = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return

        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="jarvis_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                bat_path,
                None,
                None,
                0,
            )
            if int(ret) > 32:
                time.sleep(2)
                print(f"[Dashboard] Network setup complete — port {port} is open.")
                print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                print("[Dashboard] Phone connections may fail until JARVIS is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass
        return

    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass

def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")

_ensure_crypto_js()

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"

def _bind_host() -> str:
    configured = os.environ.get("JARVIS_BIND_HOST", "").strip()
    return configured or _local_ip()


def _cert_covers_current_ip(crt_p) -> bool:
    """True when the saved certificate lists this PC's current LAN address."""
    try:
        import ipaddress
        from cryptography import x509
        lan = _local_ip()
        if lan.startswith("127."):
            return True
        cert = x509.load_pem_x509_certificate(Path(crt_p).read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return ipaddress.IPv4Address(lan) in san.get_values_for_type(x509.IPAddress)
    except Exception:
        return True   # unreadable / unexpected: keep what the user has rather than loop


def cert_fingerprint() -> str:
    """SHA-256 fingerprint of the dashboard certificate (AA:BB:…), or '' if there is none."""
    try:
        import hashlib
        import ssl
        pem = (BASE_DIR / "config" / "certs" / "jarvis.crt").read_text(encoding="ascii")
        digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
        return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
    except Exception:
        return ""


def _ensure_certs() -> bool:
    """
    Make sure config/certs holds a TLS key pair, generating a self-signed one the
    first time the dashboard runs.

    The pair is deliberately NOT shipped in the repository. A private key that
    every user downloads is the same as having no private key at all: anyone can
    present a certificate that matches it. Generating locally gives each install
    its own key, costs about a second, and happens exactly once.

    Returns True when a usable pair exists afterwards; False leaves the caller on
    plain HTTP, which still works — the QR code simply encodes http:// instead.
    """
    certs = BASE_DIR / "config" / "certs"
    key_p = certs / "jarvis.key"
    crt_p = certs / "jarvis.crt"
    if key_p.exists() and crt_p.exists():
        if _cert_covers_current_ip(crt_p):
            return True
        # The PC's LAN address changed since the certificate was made: browsers and
        # the phone check the address, so issue a fresh pair for the new one.
        for old in (key_p, crt_p):
            try:
                old.unlink()
            except OSError:
                pass

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("[Dashboard] cryptography not installed — serving over plain HTTP.")
        print("[Dashboard] For HTTPS run:  pip install cryptography")
        return False

    try:
        certs.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        who = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Dashboard"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARVIS"),
        ])

        alt = [x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan = _local_ip()
            if not lan.startswith("127."):
                alt.append(x509.IPAddress(ipaddress.IPv4Address(lan)))
        except Exception:
            pass

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(who)
            .issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        key_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        try:
            import os as _os
            _os.chmod(key_p, 0o600)
        except Exception:
            pass

        print(f"[Dashboard] Generated a self-signed certificate for this machine: {certs}")
        return True
    except Exception as e:
        print(f"[Dashboard] Certificate generation failed ({e}) — serving over plain HTTP.")
        return False

def _read(name: str) -> str:
    path = STATIC_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[Dashboard] missing static file: {path} ({e})")
        return f"<h2>Missing {name}</h2><p>STATIC_DIR={STATIC_DIR}</p>"

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}
        self._aes_cache:  dict[str, bytes]= {}
        self._clients: set[WebSocket]     = set()
        self._phone_devices: dict[WebSocket, dict] = {}
        self._phone_event_callback = None
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}
        self._last_screen_frame = None
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._shared_files: dict[str, tuple[Path, str, float]] = {}   # token -> (path, name, expiry)
        self.last_call: dict               = {}
        self._uploads_dir                 = UPLOADS_DIR
        self._jarvis_app_html             = _read("jarvis_app.html")
        self.app                          = self._build_app()
        global _ACTIVE_DASHBOARD
        _ACTIVE_DASHBOARD = self

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _ssl_enabled() -> bool:
        """HTTPS is on by default; JARVIS_TLS=0 turns it off (plain HTTP, trusted LAN only)."""
        return os.environ.get('JARVIS_TLS', '1').strip().lower() not in ('0', 'false', 'no', 'off')

    def get_url(self) -> str:
        active = getattr(self, '_tls_active', None)
        scheme = 'https' if (self._ssl_enabled() if active is None else active) else 'http'
        host = _bind_host()
        advertised = self._ip if host in ('0.0.0.0', '::') else host
        if ':' in advertised and not advertised.startswith('['):
            advertised = '[' + advertised + ']'
        return f'{scheme}://{advertised}:{PORT}'

    def fingerprint(self) -> str:
        return cert_fingerprint() if getattr(self, '_tls_active', False) else ""

    def share_file(self, path, ttl: int = 900) -> tuple[str, str]:
        """Let a paired phone download one local file through a short-lived, single-purpose link.

        Returns (url_path, filename). The link works only for this file, expires after
        `ttl` seconds, and is not a login token — it cannot call any other endpoint.
        """
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        now = time.time()
        self._shared_files = {k: v for k, v in self._shared_files.items() if v[2] > now}
        token = secrets.token_urlsafe(24)
        self._shared_files[token] = (p, p.name, now + ttl)
        return f"/api/share/{token}", p.name

    def get_manual_url(self) -> str:
        """Include scheme to avoid browser protocol/port guesses."""
        return self.get_url()

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    async def _handle_phone_event(self, event: dict) -> None:
        """Calls and ring events from the phone: show them on the PC and let Jarvis say them."""
        name = event["event"]
        if name in ("incoming_call", "call_active", "call_ended", "missed_call"):
            self.last_call = dict(event, at=time.time())
        callback = self._phone_event_callback
        if callback:
            try:
                callback({"type": "phone_call", **event})
            except Exception:
                pass
        who = event.get("name") or event.get("number") or "an unknown number"
        text = ""
        if name == "incoming_call":
            text = (f"[PHONE_EVENT] The user's phone is ringing: incoming call from {who}. Say in one short sentence "
                    "who is calling and ask whether to answer or reject. If they say answer, call phone_control with "
                    "action=answer; if reject, action=reject.")
        elif name == "missed_call":
            text = f"[PHONE_EVENT] The user missed a call from {who}. Mention it in one short sentence."
        if text:
            await self._command_queue.put(text)
            if self._wake_callback:
                try:
                    self._wake_callback()
                except Exception:
                    pass

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn


    def set_screen_frame_callback(self, fn) -> None:
        self._screen_frame_callback = fn

    def set_phone_event_callback(self, fn) -> None:
        self._phone_event_callback = fn

    def _emit_phone_devices(self) -> None:
        callback = self._phone_event_callback
        if callback:
            try:
                callback({"type": "phone_devices", "devices": [dict(item) for item in self._phone_devices.values()]})
            except Exception:
                pass

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    def phone_linked(self) -> bool:
        """True when at least one dashboard/Jarvis App client is connected."""
        return len(self._clients) > 0

    def phone_count(self) -> int:
        return len(self._clients)

    async def send_to_phones(self, msg: dict) -> int:
        """Push a command/message to all connected phone/dashboard clients."""
        if not self._clients:
            return 0
        dead: set[WebSocket] = set()
        n = 0
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
                n += 1
            except Exception:
                dead.add(ws)
        self._clients -= dead
        return n

    def send_to_phones_sync(self, msg: dict, timeout: float = 5.0) -> int:
        """Thread-safe push from action tools (Gemini tool thread)."""
        try:
            loop = getattr(self, "_loop", None)
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.get_event_loop()
            if loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(self.send_to_phones(msg), loop)
                return int(fut.result(timeout=timeout) or 0)
            return int(loop.run_until_complete(self.send_to_phones(msg)) or 0)
        except Exception as e:
            print(f"[Dashboard] send_to_phones_sync failed: {e}")
            return 0

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._jarvis_app_html or "<h1>Jarvis App missing</h1>")

        @app.get("/jarvis-app", response_class=HTMLResponse)
        @app.get("/app", response_class=HTMLResponse)
        async def jarvis_mobile_app():
            """Phone companion — authenticated WebSocket link to the desktop."""
            return HTMLResponse(self._jarvis_app_html or "<h1>Jarvis App missing</h1>")

        @app.get("/", response_class=HTMLResponse)
        async def index():
            return HTMLResponse(self._jarvis_app_html or "<h1>Jarvis App missing</h1>")

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin") or body.get("key") or "").strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in JARVIS to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            def _js(v: str) -> str:
                # JSON literal, safe inside an inline <script> block
                return (json.dumps(str(v))
                        .replace("<", "\\u003c").replace(">", "\\u003e")
                        .replace("&", "\\u0026"))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token',{_js(tok)});
  sessionStorage.setItem('jarvis_key',{_js(key)});
  localStorage.setItem('jarvis_device_token',{_js(dev_tok)});
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to JARVIS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                if dest.resolve().parent != self._uploads_dir.resolve():
                    return JSONResponse({"error": "Invalid filename"}, status_code=400)

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": "Upload failed"}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/api/share/{token}")
        async def shared_file(token: str):
            entry = self._shared_files.get(token)
            if not entry or entry[2] < time.time() or not entry[0].is_file():
                return JSONResponse({"error": "Link expired"}, status_code=404)
            return FileResponse(str(entry[0]), filename=entry[1])

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = _safe_filename(filename)
            base = self._uploads_dir.resolve()
            path = (base / safe).resolve()
            if path.parent != base or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=path.name)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = (token or "").strip()
            if tok and tok not in self._tokens:
                pin = tok.upper()
                now = time.time()
                if pin in self._pending_keys and self._pending_keys[pin] > now:
                    del self._pending_keys[pin]
                    session = secrets.token_urlsafe(32)
                    self._tokens.add(session)
                    self._token_keys[session] = pin
                    tok = session
                    asyncio.create_task(self.broadcast(
                        {"type": "sys", "text": "Phone connected via Jarvis App."}
                    ))
                else:
                    await websocket.close(code=4001)
                    return
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            client_ip = None
            try:
                if websocket.client:
                    client_ip = websocket.client.host
            except Exception:
                client_ip = None
            # Show every authenticated client (phone app OR web page) as connected in Jarvis,
            # even before/without a "phone_status" message.
            try:
                ua = (websocket.headers.get("user-agent") or "").lower()
            except Exception:
                ua = ""
            if "jarvis" in ua or "okhttp" in ua or "dart" in ua:
                kind = "Jarvis App"
            elif "mobile" in ua or "android" in ua or "iphone" in ua:
                kind = "Phone browser"
            else:
                kind = "Web browser"
            label = f"{kind} ({client_ip})" if client_ip else kind
            self._phone_devices[websocket] = {
                "type": "phone_status", "device_name": label[:80],
                "battery_percent": None, "charging": False, "placeholder": True,
            }
            self._emit_phone_devices()
            if self._connect_callback:
                try:
                    self._connect_callback(client_ip)
                except TypeError:
                    try:
                        self._connect_callback()
                    except Exception:
                        pass
                except Exception:
                    pass
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": f"Remote client online ({len(self._clients)})."}
            ))
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
                    elif data.get("type") == "hello":
                        asyncio.create_task(self.broadcast(
                            {"type": "sys", "text": "Jarvis App linked and ready."}
                        ))
                    elif data.get("type") == "home":
                        # Local-first smart home: the PC is the hub, the phone just sends commands over this socket.
                        from actions.smart_home import run_command
                        req = {k: v for k, v in data.items() if k != "type"}
                        out = await asyncio.get_running_loop().run_in_executor(None, run_command, req)
                        await websocket.send_json({"type": "home", "id": data.get("id"), "text": out})
                    elif data.get("type") == "screen_frame":
                        self._last_screen_frame = data
                        cb = getattr(self, "_screen_frame_callback", None)
                        if cb and data.get("data"):
                            try:
                                cb(data.get("data"))
                            except Exception:
                                pass
                        asyncio.create_task(self.broadcast({
                            "type": "phone_screen",
                            "width": data.get("width"),
                            "height": data.get("height"),
                            "data": data.get("data"),
                        }))
                    elif data.get("type") == "phone_status":
                        status = _sanitize_phone_status(data)
                        if status:
                            self._phone_devices.pop(websocket, None)
                            self._phone_devices[websocket] = status   # real status replaces placeholder
                            self._emit_phone_devices()
                    elif data.get("type") == "phone_event":
                        event = _sanitize_phone_event(data)
                        if event:
                            await self._handle_phone_event(event)
                    elif (data.get("type") == "phone_notification"
                          and websocket in self._phone_devices
                          and not self._phone_devices[websocket].get("placeholder")):
                        notification = _sanitize_phone_notification(data)
                        if notification and self._phone_event_callback:
                            try:
                                self._phone_event_callback(notification)
                            except Exception:
                                pass
            except WebSocketDisconnect:
                pass
            finally:
                if self._phone_devices.pop(websocket, None) is not None:
                    self._emit_phone_devices()
                self._clients.discard(websocket)
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": f"Remote client offline ({len(self._clients)} left)."}
                ))

        @app.get("/plugin-store")
        async def plugin_store_page():
            path = STATIC_DIR / "plugin_store.html"
            if path.exists():
                return FileResponse(str(path), media_type="text/html")
            return HTMLResponse("<h3>plugin_store.html missing</h3>", status_code=404)

        @app.get("/api/plugins")
        async def api_plugins_list(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.plugin_store import list_plugins
                return JSONResponse({"plugins": list_plugins()})
            except Exception as e:
                return JSONResponse({"plugins": [], "error": "Could not list plugins"})

        @app.post("/api/plugins/enable")
        async def api_plugins_enable(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            name = (body.get("name") or "").strip()
            try:
                from core.plugin_store import run as ps_run
                msg = ps_run(action="enable", value=name)
                return JSONResponse({"ok": True, "message": msg})
            except Exception as e:
                return JSONResponse({"ok": False, "error": "Plugin operation failed"})

        @app.post("/api/plugins/disable")
        async def api_plugins_disable(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            name = (body.get("name") or "").strip()
            try:
                from core.plugin_store import run as ps_run
                msg = ps_run(action="disable", value=name)
                return JSONResponse({"ok": True, "message": msg})
            except Exception as e:
                return JSONResponse({"ok": False, "error": "Plugin operation failed"})

        @app.post("/api/plugins/install")
        async def api_plugins_install(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            url = (body.get("url") or "").strip()
            try:
                from core.plugin_store import install_from_url
                msg = install_from_url(url)
                ok = msg.startswith("Installed")
                name = msg.split(":")[-1].strip() if ok else ""
                return JSONResponse({"ok": ok, "name": name, "error": None if ok else msg, "message": msg})
            except Exception as e:
                return JSONResponse({"ok": False, "error": "Plugin operation failed"})

        @app.get("/api/phone_screen")
        async def api_phone_screen(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            fr = getattr(self, "_last_screen_frame", None)
            if not fr:
                return JSONResponse({"ok": False, "error": "no frame"})
            return JSONResponse({"ok": True, "frame": fr})

        return app

    async def _serve_alias(self) -> None:
        """Compatibility no-op: one explicitly configured listener is used."""
        return None

    async def serve(self) -> None:
        """Start one listener. TLS errors never silently downgrade to HTTP."""
        if not _DEPS_OK:
            print("[Dashboard] Install fastapi uvicorn cryptography python-multipart")
            return
        self._loop = asyncio.get_running_loop()
        global _ACTIVE_DASHBOARD
        _ACTIVE_DASHBOARD = self
        host = _bind_host()
        tls = self._ssl_enabled()
        options = {}
        if tls and not _ensure_certs():
            print('[Dashboard] HTTPS certificate unavailable (pip install cryptography) — falling back to plain HTTP.')
            tls = False
        self._tls_active = tls
        if tls:
            options = dict(ssl_keyfile=str(BASE_DIR / 'config/certs/jarvis.key'),
                           ssl_certfile=str(BASE_DIR / 'config/certs/jarvis.crt'))
            print('[Dashboard] HTTPS on. Certificate fingerprint (SHA-256): ' + cert_fingerprint())
        elif host not in ('127.0.0.1', 'localhost', '::1'):
            print('[Dashboard] WARNING: LAN HTTP is unencrypted. Use only a trusted LAN.')
        _quiet_shutdown_noise()
        cfg = uvicorn.Config(self.app, host=host, port=PORT, log_level='warning', **options)
        self._server = uvicorn.Server(cfg)
        print('[Dashboard] ' + self.get_url())
        try:
            await self._server.serve()
        finally:
            if _ACTIVE_DASHBOARD is self:
                _ACTIVE_DASHBOARD = None

    async def stop(self) -> None:
        """Ask uvicorn to drain connections before the owning event loop exits."""
        server = getattr(self, '_server', None)
        if server is not None:
            server.should_exit = True

#by ASDcuber
