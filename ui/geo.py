from __future__ import annotations

import math

import numpy as np


def icosahedron():
    p = (1 + 5 ** 0.5) / 2
    v = np.array([
        (-1, p, 0), (1, p, 0), (-1, -p, 0), (1, -p, 0),
        (0, -1, p), (0, 1, p), (0, -1, -p), (0, 1, -p),
        (p, 0, -1), (p, 0, 1), (-p, 0, -1), (-p, 0, 1),
    ], dtype=np.float64)
    v /= np.linalg.norm(v, axis=1)[:, None]
    f = np.array([
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ], dtype=np.int64)
    e = set()
    for a, b, c in f:
        for i, j in ((a, b), (b, c), (c, a)):
            e.add((min(i, j), max(i, j)))
    return v, f, np.array(sorted(e), dtype=np.int64)


def fib_sphere(n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], 1)


def circle(n: int, tilt: float = 0.0, roll: float = 0.0) -> np.ndarray:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([np.cos(a), np.zeros(n), np.sin(a)], 1)
    return rotate(pts, roll, tilt)


def torus_knot(n: int, p: int = 2, q: int = 3) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    r = np.cos(q * t) + 2.0
    pts = np.stack([r * np.cos(p * t), r * np.sin(p * t), -np.sin(q * t)], 1)
    return pts / 3.1


def helix(n: int, turns: float = 1.6):
    y = np.linspace(-1, 1, n)
    a = y * math.pi * turns
    s1 = np.stack([0.46 * np.cos(a), y, 0.46 * np.sin(a)], 1)
    s2 = np.stack([0.46 * np.cos(a + math.pi), y, 0.46 * np.sin(a + math.pi)], 1)
    return s1, s2


def rotate(pts: np.ndarray, yaw: float, pitch: float, roll: float = 0.0) -> np.ndarray:
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    x = pts[:, 0] * cy + pts[:, 2] * sy
    z = -pts[:, 0] * sy + pts[:, 2] * cy
    y = pts[:, 1]
    y2 = y * cp - z * sp
    z2 = y * sp + z * cp
    if roll:
        cr, sr = math.cos(roll), math.sin(roll)
        x, y2 = x * cr - y2 * sr, x * sr + y2 * cr
    return np.stack([x, y2, z2], 1)


def project(pts: np.ndarray, cx: float, cy: float, radius: float, dist: float = 3.4):
    f = dist / (dist - pts[:, 2])
    return cx + pts[:, 0] * radius * f, cy - pts[:, 1] * radius * f, pts[:, 2], f


def depth_bucket(z: np.ndarray, buckets: int = 4, zr: float = 1.6) -> np.ndarray:
    zn = np.clip((z + zr) / (2 * zr), 0.0, 0.999)
    return (zn * buckets).astype(np.int64)

# by ASDcuber521
