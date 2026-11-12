"""Face recognition (OpenCV YuNet detector + SFace recognizer, all local). Off by default.

Only 128-number face "fingerprints" are stored (memory/faces.json) — never photos — and they never leave the PC.
Models (~37 MB) download once to config/models/ the first time it is switched on.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from core.common_utils import project_root

MODELS = project_root() / "config" / "models"
STORE = project_root() / "memory" / "faces.json"
DET_PATH = MODELS / "face_detection_yunet_2023mar.onnx"
REC_PATH = MODELS / "face_recognition_sface_2021dec.onnx"
_BASE = "https://github.com/opencv/opencv_zoo/raw/main/models/"
DET_URL = _BASE + "face_detection_yunet/face_detection_yunet_2023mar.onnx"
REC_URL = _BASE + "face_recognition_sface/face_recognition_sface_2021dec.onnx"

MATCH_THRESHOLD = 0.42      # cosine similarity; SFace's own "same person" cut-off is 0.363 — a bit stricter here
_LOCK = threading.Lock()


# ── config ─────────────────────────────────────────────────────────────────────
def _cfg() -> dict:
    from memory.config_manager import load_api_keys
    return load_api_keys()


def _set(**kw) -> None:
    from memory.config_manager import _patch_config
    _patch_config(**kw)


def is_enabled() -> bool:
    return bool(_cfg().get("face_enabled", False))


def set_enabled(on: bool) -> None:
    _set(face_enabled=bool(on))


def greet_enabled() -> bool:
    return bool(_cfg().get("face_greet", False))


def set_greet(on: bool) -> None:
    _set(face_greet=bool(on))


def alert_unknown() -> bool:
    return bool(_cfg().get("face_alert_unknown", False))


def set_alert_unknown(on: bool) -> None:
    _set(face_alert_unknown=bool(on))


# ── storage ────────────────────────────────────────────────────────────────────
def _load() -> dict:
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(STORE)


def people() -> dict[str, list]:
    with _LOCK:
        return _load()


def names() -> list[str]:
    return sorted(people())


def add_person(name: str, embeddings: list) -> None:
    name = name.strip()[:40]
    with _LOCK:
        d = _load()
        d.setdefault(name, [])
        d[name] = (d[name] + [list(map(float, e)) for e in embeddings])[-25:]
        _save(d)


def forget(name: str) -> bool:
    with _LOCK:
        d = _load()
        key = next((k for k in d if k.lower() == name.strip().lower()), None)
        if key is None:
            return False
        del d[key]
        _save(d)
        return True


def forget_all() -> None:
    with _LOCK:
        _save({})


# ── models ─────────────────────────────────────────────────────────────────────
def _fetch(url: str, path: Path, min_bytes: int) -> None:
    if path.exists() and path.stat().st_size > min_bytes:
        return
    import requests
    path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    tmp = path.with_suffix(".part")
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 16):
            fh.write(chunk)
    if tmp.stat().st_size <= min_bytes:        # a Git-LFS pointer or an error page, not the model
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download of {path.name} was incomplete")
    tmp.replace(path)


class FaceEngine:
    def __init__(self):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        if not (hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")):
            raise RuntimeError("OpenCV 4.5.4+ is needed for face recognition: pip install -U opencv-python")
        _fetch(DET_URL, DET_PATH, 100_000)
        _fetch(REC_URL, REC_PATH, 10_000_000)
        self.det = cv2.FaceDetectorYN.create(str(DET_PATH), "", (640, 480), 0.85, 0.3, 20)
        self.rec = cv2.FaceRecognizerSF.create(str(REC_PATH), "")
        self._size = (640, 480)
        self._cache: dict | None = None
        self._cache_n = -1

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        if (w, h) != self._size:
            self.det.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self.det.detect(bgr)
        return [] if faces is None else list(faces)

    def embed(self, bgr, face):
        feat = self.rec.feature(self.rec.alignCrop(bgr, face))
        v = self.np.asarray(feat, dtype="float32").reshape(-1)
        n = float(self.np.linalg.norm(v))
        return v / n if n else v

    def identify(self, vec):
        """(name, score) of the best match, or (None, score) when nobody known is similar enough."""
        db = people()
        best, score = None, -1.0
        for name, embs in db.items():
            for e in embs:
                e = self.np.asarray(e, dtype="float32")
                n = float(self.np.linalg.norm(e))
                s = float(self.np.dot(vec, e / n)) if n else -1.0
                if s > score:
                    best, score = name, s
        return (best, score) if best is not None and score >= MATCH_THRESHOLD else (None, score)
