"""Small pictures of 3D models for the Hand Space cards, drawn once and kept on disk (ui/mesh_cache.py).

The card used to say just "3D" because drawing every model live every frame was too heavy. Now each model is rendered a
single time, off-screen, in a worker thread, with numpy only — no OpenGL, no Qt — and the picture is cached, so the card
shows the model instantly from then on and the GPU stays free for the model you actually opened.

Method: the triangles are thinned to at most MAX_TRIS, projected like the GL view (same turn, same light, perspective),
random points are scattered over each triangle (as many as it covers pixels), a z-buffer keeps the nearest one per pixel,
and the 2× image is averaged down for smooth edges. Shading uses the same formula as the model shader in ui/hs_gpu.py.
"""
from __future__ import annotations

import math

import numpy as np

from ui import mesh_cache

SIDE = mesh_cache.THUMB_SIDE
SS = 2                                      # supersampling: rendered at SS× and averaged down
MAX_TRIS = 150_000                          # more triangles than this add nothing at 192 px
DENSITY = 6.0                               # scattered points per covered (supersampled) pixel: ~0.25 % holes
MAX_POINTS = 900_000
PER_TRIANGLE = 400_000                      # a few huge triangles (a cube) need many points; thin meshes never reach this
DIST = 3.4                                  # same camera distance as the GL shader
MAIN = np.array([0.35, 0.78, 1.00], np.float32)     # accent colours of the holographic look
BASE = np.array([0.66, 0.74, 0.84], np.float32)
LIGHT = np.array([-0.45, 0.60, 0.75], np.float32)
LIGHT /= np.linalg.norm(LIGHT)


def _rot(yaw: float, pitch: float) -> np.ndarray:
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    return rx @ ry


def render_thumb(flat: np.ndarray, meta: tuple, size: int = SIDE, yaw: float = 0.6, pitch: float = 0.35) -> np.ndarray:
    """flat: float32 (3n, 3) triangle corners · meta: (cx, cy, cz, 1/radius) → uint8 (size, size, 4) RGBA, transparent background."""
    tri = flat.reshape(-1, 3, 3)
    n = len(tri)
    if n > MAX_TRIS:
        tri = tri[:: -(-n // MAX_TRIS)]
    cx, cy, cz, inv = meta
    q = (tri - np.array([cx, cy, cz], np.float32)) * np.float32(inv)
    p = q @ _rot(yaw, pitch).T                                   # rotated corners, unit sphere
    a, b, c = p[:, 0], p[:, 1], p[:, 2]

    nrm = np.cross(b - a, c - a)
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-12
    if not ok.any():
        return np.zeros((size, size, 4), np.uint8)
    a, b, c, nrm, ln = a[ok], b[ok], c[ok], nrm[ok], ln[ok]
    nrm = nrm / ln[:, None]
    nrm[nrm[:, 2] < 0] *= -1                                     # the shader's normals always face the viewer
    nl = nrm @ LIGHT
    d = np.maximum(nl, 0) + 0.35 * np.maximum(-nl, 0)
    rim = (1.0 - np.clip(np.abs(nrm[:, 2]), 0, 1)) ** 2.2
    col = np.clip(((BASE * 0.70 + MAIN * 0.30) * (0.20 + 0.85 * d)[:, None]) + MAIN * (rim * 0.55)[:, None], 0.0, 1.0)

    big = size * SS
    r_px = big / 2 * 0.68                                        # keeps the near (perspective-enlarged) side inside the picture

    def project(v):
        f = DIST / (DIST - v[:, 2])
        return v[:, 0] * f * r_px + big / 2, big / 2 - v[:, 1] * f * r_px, v[:, 2]

    xa, ya, za = project(a)
    xb, yb, zb = project(b)
    xc, yc, zc = project(c)
    area = 0.5 * np.abs((xb - xa) * (yc - ya) - (xc - xa) * (yb - ya))
    k = np.clip(np.ceil(area * DENSITY), 1, PER_TRIANGLE)
    tot = float(k.sum())
    if tot > MAX_POINTS:
        k = np.maximum(1.0, np.ceil(k * (MAX_POINTS / tot)))
    k = k.astype(np.int64)

    ti = np.repeat(np.arange(len(k)), k)                         # which triangle each point belongs to
    rng = np.random.default_rng(1)
    r1 = rng.random(len(ti), dtype=np.float32)
    r2 = rng.random(len(ti), dtype=np.float32)
    fold = r1 + r2 > 1.0
    r1[fold], r2[fold] = 1.0 - r1[fold], 1.0 - r2[fold]
    X = xa[ti] + r1 * (xb - xa)[ti] + r2 * (xc - xa)[ti]
    Y = ya[ti] + r1 * (yb - ya)[ti] + r2 * (yc - ya)[ti]
    Z = za[ti] + r1 * (zb - za)[ti] + r2 * (zc - za)[ti]
    xi, yi = X.astype(np.int32), Y.astype(np.int32)
    inside = (X >= 0) & (Y >= 0) & (xi < big) & (yi < big)
    idx = (yi * big + xi)[inside]
    order = np.argsort(Z[inside], kind="stable")                 # far → near: the nearest point is written last and wins
    tid = np.full(big * big, -1, np.int32)
    tid[idx[order]] = ti[inside][order]

    cov = (tid >= 0).reshape(big, big)
    img = np.zeros((big, big, 3), np.float32)
    img[cov] = col[tid.reshape(big, big)[cov]]
    _fill_holes(cov, img)
    cov = cov.reshape(-1)
    img = img.reshape(-1, 3)
    cov4 = cov.reshape(size, SS, size, SS).astype(np.float32)
    cnt = cov4.sum(axis=(1, 3))
    rgb = (img.reshape(size, SS, size, SS, 3) * cov4[..., None]).sum(axis=(1, 3)) / np.maximum(cnt, 1.0)[..., None]
    out = np.empty((size, size, 4), np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(cnt / (SS * SS) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def _fill_holes(cov: np.ndarray, img: np.ndarray) -> None:
    """A pixel nobody landed on, whose neighbours are (almost) all covered, takes their average colour (in place)."""
    cf = cov.astype(np.float32)
    pc = np.pad(cf, 1)
    pi = np.pad(img * cf[..., None], ((1, 1), (1, 1), (0, 0)))
    h, w = cov.shape
    nb = np.zeros_like(cf)
    acc = np.zeros_like(img)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy == 1 and dx == 1:
                continue
            nb += pc[dy:dy + h, dx:dx + w]
            acc += pi[dy:dy + h, dx:dx + w]
    hole = (~cov) & (nb >= 6)
    img[hole] = acc[hole] / nb[hole][:, None]
    cov |= hole


def thumb_for(path: str, loader) -> np.ndarray | None:
    """Worker thread: the cached picture of the model at `path`, drawn (and cached) first if needed.
    `loader(path)` is hs_gpu.load_mesh — it uses the mesh cache too, so the model also opens faster afterwards."""
    key = mesh_cache.key_for(path, f"thumb{SIDE}")
    hit = mesh_cache.get_thumb(key)
    if hit is not None:
        return hit
    flat, _tris, meta = loader(path)
    arr = render_thumb(flat, meta)
    mesh_cache.put_thumb(key, arr)
    return arr


def store_thumb(path: str, flat: np.ndarray, meta: tuple) -> np.ndarray:
    """For a model that was just opened (already in memory): draw its picture without reading the file again."""
    key = mesh_cache.key_for(path, f"thumb{SIDE}")
    arr = render_thumb(flat, meta)
    mesh_cache.put_thumb(key, arr)
    return arr
