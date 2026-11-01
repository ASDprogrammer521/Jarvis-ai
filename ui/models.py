from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import ui.geo as geo
MODELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"
PREFERRED = ("holo", "crystal", "globe", "knot", "helix")

DEFAULTS = {
    "w": 1.5, "a": 1.0, "mix": 0.0, "size": 4.0, "spin": 1.0, "pitchmul": 1.0, "tilt": 0.0, "yaw0": 0.0,
    "roll": 0.0, "scale": 1.0, "amp": 0.0, "ampxz": 0.0, "jit": 0.0, "wob": 0.0, "rad": 1.0,
    "blink": 0.0, "rate": 3.0, "phase": 0.0, "lite": 1.0, "add": 0.0,
    "n": 3.0, "trail": 7.0, "r": 1.38, "speed": 70.0, "spec": 0.0,
}
STR_KEYS = {"scan"}


@dataclass
class Layer:
    kind: str
    verts: np.ndarray
    idx: np.ndarray
    p: dict
    ar: np.ndarray = field(default=None)
    ang: np.ndarray = field(default=None)
    ymid: np.ndarray = field(default=None)


@dataclass
class Model:
    name: str
    layers: list
    meta: dict


def _parse_spec(spec: str) -> tuple[str, dict]:
    kind, _, rest = spec.partition(":")
    p = dict(DEFAULTS)
    p["scan"] = ""
    for part in rest.split(","):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        if k in STR_KEYS:
            p[k] = v.strip()
        elif k == "lite" and v.strip() == "half":
            p[k] = 0.5
        else:
            try:
                p[k] = float(v)
            except ValueError:
                pass
    return kind.strip().lower(), p


def _finish(kind: str, p: dict, verts: np.ndarray, items: list) -> Layer | None:
    if kind == "sparks":
        return Layer(kind, np.zeros((0, 3)), np.zeros((0, 2), dtype=np.int64), p)
    if kind == "pulse":
        return Layer(kind, np.zeros((0, 3)), np.zeros((0, 2), dtype=np.int64), p)
    if not items:
        return None
    arr = np.array(items, dtype=np.int64)
    used = np.unique(arr)
    remap = {int(old): i for i, old in enumerate(used)}
    arr = np.vectorize(remap.get)(arr) if arr.size else arr
    v = verts[used]
    lay = Layer(kind, v, arr.reshape(arr.shape) if kind != "points" else arr.reshape(-1), p)
    lay.ar = np.arange(len(v), dtype=np.float64)
    if len(v):
        lay.ang = np.arctan2(v[:, 2], v[:, 0])
    if kind == "lines" and len(arr):
        lay.ymid = (v[arr[:, 0], 1] + v[arr[:, 1], 1]) / 2.0
    return lay


def load_obj(path: Path) -> Model:
    verts: list = []
    meta: dict = {}
    layers: list = []
    cur_spec, cur_items = None, []

    def flush():
        nonlocal cur_spec, cur_items
        if cur_spec is not None:
            kind, p = _parse_spec(cur_spec)
            lay = _finish(kind, p, np.array(verts, dtype=np.float64) if verts else np.zeros((0, 3)), cur_items)
            if lay is not None:
                layers.append(lay)
        cur_spec, cur_items = None, []

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#@"):
            k, _, v = line[2:].strip().partition(" ")
            meta[k.strip()] = v.strip()
            continue
        if line.startswith("#"):
            continue
        tok = line.split()
        c = tok[0]
        if c == "v":
            verts.append((float(tok[1]), float(tok[2]), float(tok[3])))
        elif c == "g":
            flush()
            cur_spec = tok[1] if len(tok) > 1 else "lines"
        elif c == "l" and cur_spec is not None:
            ids = [int(t.split("/")[0]) - 1 for t in tok[1:]]
            cur_items += [[a, b] for a, b in zip(ids, ids[1:])]
        elif c == "p" and cur_spec is not None:
            cur_items += [int(t.split("/")[0]) - 1 for t in tok[1:]]
        elif c == "f" and cur_spec is not None:
            ids = [int(t.split("/")[0]) - 1 for t in tok[1:]]
            cur_items += [[ids[0], ids[i], ids[i + 1]] for i in range(1, len(ids) - 1)]
    flush()
    if not layers:
        raise ValueError("no drawable groups")
    return Model(path.stem, layers, meta)


def fallback_model() -> Model:
    v, f, e = geo.icosahedron()
    base = {k: v_ for k, v_ in DEFAULTS.items()}
    base.update(w=1.5, a=1.0, mix=0.3, scan="")
    pts = dict(base, size=6.0, mix=0.5)
    lay_l = _finish("lines", dict(base), v, e.tolist())
    lay_p = _finish("points", pts, v, list(range(len(v))))
    return Model("crystal", [x for x in (lay_l, lay_p) if x is not None], {})


_CACHE: dict[str, Model] = {}


def load_all(force: bool = False) -> dict[str, Model]:
    global _CACHE
    if _CACHE and not force:
        return _CACHE
    out: dict[str, Model] = {}
    if MODELS_DIR.exists():
        for f in sorted(MODELS_DIR.glob("*.obj")):
            try:
                out[f.stem.lower()] = load_obj(f)
            except Exception as e:
                print(f"[Models] skipped {f.name}: {e}")
    if not out:
        out["crystal"] = fallback_model()
    _CACHE = out
    return out


def ordered_names(models: dict[str, Model]) -> list[str]:
    first = [n for n in PREFERRED if n in models]
    rest = sorted(n for n in models if n not in first)
    return first + rest

# by ASDcuber521
