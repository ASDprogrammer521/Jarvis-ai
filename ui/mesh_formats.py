"""3D model readers for Hand Space. Every reader returns triangles as float32 (n, 3, 3) in world space.

Built in (numpy only):   .obj  .stl  .glb  .gltf  .fbx (binary)  .usda / .usdz that contains plain-text USD
Optional libraries:      .usd / .usdc / .usdz (binary USD)  →  pip install usd-core
                         .step / .stp                        →  pip install cadquery
Nothing here touches Qt or OpenGL, so it runs in a worker thread.
"""
from __future__ import annotations

import base64
import json
import os
import re
import struct
import urllib.parse
import zlib

import numpy as np

HEAVY_EXT = {".step", ".stp", ".usd", ".usda", ".usdc", ".usdz"}      # slow to read: only loaded when the card is opened
MODEL_EXT = {".obj", ".stl", ".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz", ".step", ".stp"}


def _tri(a) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float32).reshape(-1, 3, 3)


def _triangulate(P: np.ndarray, counts: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Polygon soup (face vertex counts + vertex indices) → triangles (fan for n-gons)."""
    counts = np.asarray(counts, dtype=np.int64)
    idx = np.asarray(idx, dtype=np.int64)
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    out = []
    for n in np.unique(counts):
        if n < 3:
            continue
        s = starts[counts == n]
        for k in range(1, n - 1):
            out.append(np.stack([idx[s], idx[s + k], idx[s + k + 1]], axis=1))
    if not out:
        raise ValueError("no faces to draw")
    t = np.concatenate(out, axis=0)
    if t.min() < 0 or t.max() >= len(P):
        raise ValueError("broken face indices")
    return P[t]


# ── OBJ / STL ───────────────────────────────────────────────────────────────────────
def read_obj(path: str) -> np.ndarray:
    import time
    verts: list = []
    faces: list = []
    n_lines = 0
    with open(path, "rb") as f:
        for raw in f:
            n_lines += 1
            if n_lines % 50000 == 0:
                time.sleep(0)                                  # let the UI thread breathe while a big file parses
            if raw[:2] == b"v ":
                t = raw.split()
                verts.append((float(t[1]), float(t[2]), float(t[3])))
            elif raw[:2] == b"f ":
                t = raw.split()[1:]
                n = len(verts)
                idx = []
                for x in t:
                    i = int(x.split(b"/")[0])
                    idx.append(i - 1 if i > 0 else n + i)
                for k in range(1, len(idx) - 1):
                    faces.append((idx[0], idx[k], idx[k + 1]))
    if not verts or not faces:
        raise ValueError("this OBJ has no faces to draw")
    v = np.asarray(verts, dtype=np.float32)
    fa = np.asarray(faces, dtype=np.int64)
    if fa.min() < 0 or fa.max() >= len(v):
        raise ValueError("broken face indices")
    return _tri(v[fa])


def read_stl(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) >= 84:
        n = struct.unpack_from("<I", raw, 80)[0]
        if 84 + 50 * n == len(raw) and n > 0:                  # binary STL
            dt = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
            return _tri(np.frombuffer(raw, dtype=dt, count=n, offset=84)["v"])
    vs = []                                                    # ASCII STL
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            t = line.split()
            vs.append((float(t[1]), float(t[2]), float(t[3])))
    if len(vs) < 3:
        raise ValueError("this STL has no triangles")
    a = np.asarray(vs, dtype=np.float32)
    return _tri(a[: len(a) // 3 * 3])


# ── glTF / GLB ──────────────────────────────────────────────────────────────────────
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def _quat_matrix(q) -> np.ndarray:
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w or 1.0
    s = 2.0 / n
    return np.array([[1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
                     [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
                     [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)]])


def read_gltf(path: str) -> np.ndarray:
    ext = os.path.splitext(path)[1].lower()
    binchunk = None
    if ext == ".glb":
        with open(path, "rb") as f:
            raw = f.read()
        if raw[:4] != b"glTF":
            raise ValueError("not a GLB file")
        off, js = 12, None
        while off + 8 <= len(raw):
            clen, ctype = struct.unpack_from("<II", raw, off)
            off += 8
            data = raw[off:off + clen]
            off += clen
            if ctype == 0x4E4F534A:
                js = json.loads(data.decode("utf-8"))
            elif ctype == 0x004E4942 and binchunk is None:
                binchunk = data
        if js is None:
            raise ValueError("GLB has no JSON chunk")
    else:
        with open(path, "r", encoding="utf-8") as f:
            js = json.load(f)
    if any("KHR_draco_mesh_compression" in (m.get("extensions") or {}) for mesh in js.get("meshes", []) for m in mesh.get("primitives", [])):
        raise ValueError("Draco-compressed glTF isn't supported — export without compression")
    base = os.path.dirname(path)
    buffers = []
    for b in js.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            buffers.append(binchunk or b"")
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            with open(os.path.join(base, urllib.parse.unquote(uri)), "rb") as f:
                buffers.append(f.read())

    def acc(i: int) -> np.ndarray:
        a = js["accessors"][i]
        dt = np.dtype(_CT[a["componentType"]])
        n, cnt = _NC[a["type"]], a["count"]
        if "bufferView" not in a:
            return np.zeros((cnt, n), dtype=dt)
        bv = js["bufferViews"][a["bufferView"]]
        buf = buffers[bv["buffer"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        item = dt.itemsize * n
        stride = bv.get("byteStride") or item
        if stride == item:
            arr = np.frombuffer(buf, dtype=dt, count=cnt * n, offset=off).reshape(cnt, n)
        else:
            raw8 = np.frombuffer(buf, dtype=np.uint8, count=(cnt - 1) * stride + item, offset=off)
            arr = np.ascontiguousarray(np.lib.stride_tricks.as_strided(raw8, shape=(cnt, item), strides=(stride, 1))).view(dt).reshape(cnt, n)
        if a.get("normalized") and dt.kind in "iu":
            arr = np.maximum(arr / float(np.iinfo(dt).max), -1.0)
        return arr

    def prim_tris(prim) -> np.ndarray | None:
        mode = prim.get("mode", 4)
        if mode not in (4, 5, 6) or "POSITION" not in prim.get("attributes", {}):
            return None
        P = acc(prim["attributes"]["POSITION"]).astype(np.float32)[:, :3]
        idx = acc(prim["indices"]).reshape(-1).astype(np.int64) if "indices" in prim else np.arange(len(P), dtype=np.int64)
        if mode == 4:
            idx = idx[: len(idx) // 3 * 3].reshape(-1, 3)
        elif mode == 5:                                        # triangle strip
            if len(idx) < 3:
                return None
            k = np.arange(len(idx) - 2)
            t = np.stack([idx[k], idx[k + 1], idx[k + 2]], axis=1)
            t[1::2] = t[1::2][:, [1, 0, 2]]
            idx = t
        else:                                                  # triangle fan
            if len(idx) < 3:
                return None
            k = np.arange(1, len(idx) - 1)
            idx = np.stack([np.full_like(k, idx[0]), idx[k], idx[k + 1]], axis=1)
        if len(idx) == 0 or idx.min() < 0 or idx.max() >= len(P):
            return None
        return P[idx]

    def node_matrix(n) -> np.ndarray:
        if "matrix" in n:
            return np.array(n["matrix"], dtype=np.float64).reshape(4, 4).T
        M = np.eye(4)
        S = np.diag(list(n.get("scale", (1, 1, 1))) + [1.0])
        R = np.eye(4)
        R[:3, :3] = _quat_matrix(n.get("rotation", (0, 0, 0, 1)))
        T = np.eye(4)
        T[:3, 3] = n.get("translation", (0, 0, 0))
        return T @ R @ S @ M

    nodes = js.get("nodes", [])
    meshes = js.get("meshes", [])
    out: list = []

    def emit(mesh_i: int, M: np.ndarray):
        for prim in meshes[mesh_i].get("primitives", []):
            t = prim_tris(prim)
            if t is not None:
                out.append((t.astype(np.float64) @ M[:3, :3].T + M[:3, 3]).astype(np.float32))

    if nodes:
        scenes = js.get("scenes") or []
        if scenes:
            roots = scenes[js.get("scene", 0)].get("nodes", [])
        else:
            kids = {c for n in nodes for c in n.get("children", [])}
            roots = [i for i in range(len(nodes)) if i not in kids]
        stack = [(r, np.eye(4)) for r in roots]
        seen = 0
        while stack and seen < 200000:
            i, parent = stack.pop()
            seen += 1
            n = nodes[i]
            M = parent @ node_matrix(n)
            if "mesh" in n:
                emit(n["mesh"], M)
            stack.extend((c, M) for c in n.get("children", []))
    else:
        for i in range(len(meshes)):
            emit(i, np.eye(4))
    if not out:
        raise ValueError("no triangle meshes in this glTF")
    return _tri(np.concatenate(out, axis=0))


# ── FBX (binary) ────────────────────────────────────────────────────────────────────
_FBX_SCALAR = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}
_FBX_ARRAY = {"f": np.float32, "d": np.float64, "i": np.int32, "l": np.int64, "b": np.bool_}


def _fbx_parse(raw: bytes):
    if raw[:2] == b"; ":
        raise ValueError("ASCII FBX isn't supported — export a binary FBX")
    if raw[:18] != b"Kaydara FBX Binary":
        raise ValueError("not an FBX file")
    ver = struct.unpack_from("<I", raw, 23)[0]
    wide = ver >= 7500

    def node(off: int):
        if wide:
            end, nprops, plen = struct.unpack_from("<QQQ", raw, off)
            off += 24
        else:
            end, nprops, plen = struct.unpack_from("<III", raw, off)
            off += 12
        nl = raw[off]
        off += 1
        if end == 0:
            return None, off + nl
        name = raw[off:off + nl].decode("latin1")
        off += nl
        props = []
        for _ in range(nprops):
            t = chr(raw[off])
            off += 1
            if t in _FBX_SCALAR:
                fmt = _FBX_SCALAR[t]
                props.append(struct.unpack_from(fmt, raw, off)[0])
                off += struct.calcsize(fmt)
            elif t in _FBX_ARRAY:
                length, enc, clen = struct.unpack_from("<III", raw, off)
                off += 12
                data = raw[off:off + clen]
                off += clen
                if enc == 1:
                    data = zlib.decompress(data)
                props.append(np.frombuffer(data, dtype=_FBX_ARRAY[t], count=length))
            elif t in "SR":
                ln = struct.unpack_from("<I", raw, off)[0]
                off += 4
                v = raw[off:off + ln]
                off += ln
                props.append(v.decode("utf-8", "replace") if t == "S" else v)
            else:
                raise ValueError(f"unknown FBX property type {t!r}")
        children = []
        while off < end:
            ch, off = node(off)
            if ch is None:
                break
            children.append(ch)
        return (name, props, children), end

    top = []
    off = 27
    while off + 13 < len(raw):
        n, off = node(off)
        if n is None:
            break
        top.append(n)
    return top


def read_fbx(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        raw = f.read()
    top = _fbx_parse(raw)
    objects = next((n for n in top if n[0] == "Objects"), None)
    conns = next((n for n in top if n[0] == "Connections"), None)
    if objects is None:
        raise ValueError("FBX has no objects")
    geoms: dict = {}
    models: dict = {}
    for name, props, kids in objects[2]:
        if name == "Geometry" and len(props) >= 3 and props[2] == "Mesh":
            v = next((k[1][0] for k in kids if k[0] == "Vertices"), None)
            pv = next((k[1][0] for k in kids if k[0] == "PolygonVertexIndex"), None)
            if v is not None and pv is not None:
                geoms[props[0]] = (np.asarray(v, dtype=np.float64).reshape(-1, 3), np.asarray(pv, dtype=np.int64))
        elif name == "Model":
            P = {}
            for k in kids:
                if k[0] == "Properties70":
                    for p in k[2]:
                        if p[0] == "P" and len(p[1]) >= 7 and isinstance(p[1][0], str):
                            P[p[1][0]] = [float(x) for x in p[1][4:7]]
            models[props[0]] = P
    if not geoms:
        raise ValueError("this FBX has no polygon meshes")
    parent_of: dict = {}
    geom_model: dict = {}
    for _n, props, _k in (conns[2] if conns else []):
        if _n == "C" and len(props) >= 3 and props[0] == "OO":
            child, parent = props[1], props[2]
            if child in geoms and parent in models:
                geom_model[child] = parent
            elif child in models and parent in models:
                parent_of[child] = parent

    def rot(deg) -> np.ndarray:
        x, y, z = np.radians(deg)
        cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        return Rz @ Ry @ Rx

    cache: dict = {}

    def world(mid) -> np.ndarray:
        if mid in cache:
            return cache[mid]
        P = models.get(mid, {})
        M = np.eye(4)
        M[:3, 3] = P.get("Lcl Translation", [0, 0, 0])
        R = np.eye(4)
        R[:3, :3] = rot(P.get("PreRotation", [0, 0, 0])) @ rot(P.get("Lcl Rotation", [0, 0, 0]))
        S = np.diag(list(P.get("Lcl Scaling", [1, 1, 1])) + [1.0])
        L = M @ R @ S
        par = parent_of.get(mid)
        cache[mid] = (world(par) if par is not None and par != mid else np.eye(4)) @ L
        return cache[mid]

    out = []
    for gid, (V, pv) in geoms.items():
        ends = np.nonzero(pv < 0)[0]
        if len(ends) == 0:
            continue
        counts = np.diff(np.concatenate(([-1], ends)))
        idx = np.where(pv < 0, ~pv, pv)[: ends[-1] + 1]
        try:
            t = _triangulate(V, counts, idx)
        except ValueError:
            continue
        M = world(geom_model[gid]) if gid in geom_model else np.eye(4)
        out.append((t.astype(np.float64) @ M[:3, :3].T + M[:3, 3]).astype(np.float32))
    if not out:
        raise ValueError("no usable faces in this FBX")
    return _tri(np.concatenate(out, axis=0))


# ── USD ─────────────────────────────────────────────────────────────────────────────
def _usd_text_meshes(text: str) -> np.ndarray:
    num = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

    def grab(seg: str, key: str):
        m = re.search(key + r"\s*=\s*\[(.*?)\]", seg, re.S)
        return np.array(num.findall(m.group(1)), dtype=np.float64) if m else None
    out = []
    for seg in re.split(r'def\s+Mesh\s+"', text)[1:]:
        P, counts, idx = grab(seg, r"point3f\[\]\s+points"), grab(seg, r"int\[\]\s+faceVertexCounts"), grab(seg, r"int\[\]\s+faceVertexIndices")
        if P is None or counts is None or idx is None:
            continue
        try:
            out.append(_triangulate(P.reshape(-1, 3), counts.astype(np.int64), idx.astype(np.int64)))
        except ValueError:
            continue
    if not out:
        raise ValueError("no meshes found in this USD")
    return _tri(np.concatenate(out, axis=0))


def read_usd(path: str) -> np.ndarray:
    try:
        from pxr import Usd, UsdGeom                           # pip install usd-core
    except ImportError:
        Usd = None
    if Usd is not None:
        stage = Usd.Stage.Open(path)
        if stage is None:
            raise ValueError("USD could not be opened")
        cache = UsdGeom.XformCache()
        out = []
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh):
                continue
            m = UsdGeom.Mesh(prim)
            pts, cnt, idx = m.GetPointsAttr().Get(), m.GetFaceVertexCountsAttr().Get(), m.GetFaceVertexIndicesAttr().Get()
            if not pts or cnt is None or idx is None:
                continue
            P = np.array(pts, dtype=np.float64).reshape(-1, 3)
            Mx = np.array(cache.GetLocalToWorldTransform(prim), dtype=np.float64).reshape(4, 4)
            P = P @ Mx[:3, :3] + Mx[3, :3]                      # USD matrices act on row vectors
            try:
                out.append(_triangulate(P, np.array(cnt), np.array(idx)))
            except ValueError:
                continue
        if not out:
            raise ValueError("no meshes found in this USD")
        return _tri(np.concatenate(out, axis=0))
    # no USD library: plain-text USD only
    ext = os.path.splitext(path)[1].lower()
    if ext == ".usdz":
        import zipfile
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith((".usd", ".usda", ".usdc")):
                    data = z.read(n)
                    if data[:5] == b"#usda":
                        return _usd_text_meshes(data.decode("utf-8", "replace"))
        raise ValueError("binary USD needs: pip install usd-core")
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:5] != b"#usda":
        raise ValueError("binary USD needs: pip install usd-core")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return _usd_text_meshes(f.read())


# ── STEP ────────────────────────────────────────────────────────────────────────────
def read_step(path: str) -> np.ndarray:
    try:
        import cadquery as cq                                   # pip install cadquery
    except ImportError:
        raise ValueError("STEP needs: pip install cadquery") from None
    shape = cq.importers.importStep(path).val()
    diag = float(shape.BoundingBox().DiagonalLength) or 1.0
    verts, faces = shape.tessellate(max(diag / 600.0, 1e-5), 0.3)
    if not faces:
        raise ValueError("this STEP file has no solids to draw")
    V = np.array([v.toTuple() for v in verts], dtype=np.float32)
    return _tri(V[np.asarray(faces, dtype=np.int64)])


READERS = {".obj": read_obj, ".stl": read_stl, ".glb": read_gltf, ".gltf": read_gltf, ".fbx": read_fbx,
           ".usd": read_usd, ".usda": read_usd, ".usdc": read_usd, ".usdz": read_usd, ".step": read_step, ".stp": read_step}


def read_triangles(path: str) -> np.ndarray:
    ext = os.path.splitext(path)[1].lower()
    fn = READERS.get(ext)
    if fn is None:
        raise ValueError(f"{ext or 'this'} format isn't supported")
    return fn(path)
