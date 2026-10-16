from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ui.geo as geo

OUT = ROOT / "assets" / "models"


class Obj:

    def __init__(self, title: str, **meta):
        self.v: list = []
        self.out: list = [f"o {title}"]
        for k, val in meta.items():
            self.out.append(f"#@{k} {val}")

    def verts(self, arr) -> int:
        base = len(self.v)
        self.v += [tuple(float(x) for x in r) for r in np.asarray(arr)]
        return base

    def group(self, spec: str):
        self.out.append(f"g {spec}")

    def chain(self, base: int, n: int, closed: bool = False):
        ids = [base + i + 1 for i in range(n)]
        if closed:
            ids.append(ids[0])
        self.out.append("l " + " ".join(map(str, ids)))

    def segments(self, base: int, pairs):
        for a, b in pairs:
            self.out.append(f"l {base + int(a) + 1} {base + int(b) + 1}")

    def points(self, base: int, ids):
        ids = [base + int(i) + 1 for i in ids]
        for i in range(0, len(ids), 24):
            self.out.append("p " + " ".join(map(str, ids[i:i + 24])))

    def faces(self, base: int, tris):
        for a, b, c in tris:
            self.out.append(f"f {base + int(a) + 1} {base + int(b) + 1} {base + int(c) + 1}")

    def save(self, name: str):
        OUT.mkdir(parents=True, exist_ok=True)
        head = [f"v {x:.5f} {y:.5f} {z:.5f}" for x, y, z in self.v]
        (OUT / f"{name}.obj").write_text("\n".join([self.out[0]] + [l for l in self.out[1:] if l.startswith("#@")] + head +
                                                   [l for l in self.out[1:] if not l.startswith("#@")]) + "\n", encoding="utf-8")
        print(f"{name}.obj: {len(self.v)} vertices")


def crystal():
    o = Obj("crystal", hud=1, glow=1, particles=1)
    v, f, e = geo.icosahedron()
    b = o.verts(v)
    o.group("faces:amp=.16,spec=1")
    o.faces(b, f)
    o.group("lines:w=5.5,a=.16,mix=.3,amp=.16,lite=0")
    o.segments(b, e)
    o.group("lines:w=1.5,a=1,mix=.3,amp=.16")
    o.segments(b, e)
    o.group("points:size=13,a=.18,mix=.5,amp=.16,lite=0")
    o.points(b, range(len(v)))
    o.group("points:size=6,a=1,mix=.5,amp=.16")
    o.points(b, range(len(v)))
    o.group("lines:w=1.1,a=.8,mix=.9,scale=.52,amp=.16,spin=-1.7,pitchmul=-.8,tilt=.4,lite=0")
    o.segments(b, e)
    o.group("points:size=3.6,a=.9,mix=1,scale=.52,amp=.16,spin=-1.7,pitchmul=-.8,tilt=.4,lite=0")
    o.points(b, range(len(v)))
    for k in range(2):
        c = geo.circle(90, [0.0, 1.05][k], [0.0, 0.6][k])
        cb = o.verts(c)
        o.group("lines:w=1,a=.45,mix=.6,scale=1.38,spin=.6,tilt=.2,lite=0")
        o.chain(cb, 90, closed=True)
    o.group("sparks:n=3,trail=7,r=1.38,lite=0")
    o.save("crystal")


def globe():
    o = Obj("globe", hud=1, glow=1, particles=1, rim=1)
    g = geo.fib_sphere(300)
    b = o.verts(g)
    north = [i for i in range(len(g)) if g[i, 1] > 0]
    south = [i for i in range(len(g)) if g[i, 1] <= 0]
    o.group("points:size=3.2,a=1,mix=0,jit=.18,scan=lon")
    o.points(b, north)
    o.group("points:size=3.2,a=1,mix=.85,jit=.18,scan=lon")
    o.points(b, south)
    for k in range(3):
        c = geo.circle(90, [0.0, 1.05, -0.9][k], [0.0, 0.6, -0.5][k])
        cb = o.verts(c)
        o.group(f"lines:w=1.2,a=.8,mix={0.7 + k * 0.1:.1f},scale=1.12,spin={1.2 + k * 0.4:.1f},tilt={k * 0.5:.1f},lite=0")
        o.chain(cb, 90, closed=True)
    for ly in (-0.5, 0.0, 0.5):
        c = geo.circle(70) * math.sqrt(1 - ly * ly)
        c[:, 1] = ly
        cb = o.verts(c)
        o.group("lines:w=.8,a=.35,mix=.2,lite=0")
        o.chain(cb, 70, closed=True)
    o.group("sparks:n=2,trail=7,r=1.3,lite=0")
    o.save("globe")


def knot():
    o = Obj("knot", hud=1, glow=1, particles=1)
    n = 360
    k = geo.torus_knot(n)
    strands = ((1.0, 0, 0.0), (1.07, 17, 0.5), (0.93, 34, 1.0))
    for i, (sc, shift, mx) in enumerate(strands):
        pts = np.roll(k, shift, axis=0) * sc
        b = o.verts(pts)
        if i == 0:
            o.group("lines:w=7,a=.12,mix=0,wob=.04,roll=.2,rad=1.25,amp=.12,lite=0")
            o.chain(b, n, closed=True)
        w = 2.4 - i * 0.5
        a = 1.0 - i * 0.2
        lite = "lite=0," if i else ""
        o.group(f"lines:w={w:.1f},a={a:.1f},mix={mx},wob=.04,phase={i},roll=.2,rad=1.25,amp=.12,{lite[:-1] if lite else 'lite=1'}")
        o.chain(b, n, closed=True)
    o.group("pulse:n=5,speed=70,size=6,mix=.8")
    o.save("knot")


def helix():
    o = Obj("helix", hud=1, glow=1, particles=1)
    n = 120
    s1, s2 = geo.helix(n)
    b1, b2 = o.verts(s1), o.verts(s2)
    rung = list(range(0, n, 5))
    o.group("lines:w=7,a=.12,mix=0,rad=1.15,ampxz=.35,lite=0")
    o.chain(b1, n)
    o.group("lines:w=7,a=.12,mix=1,rad=1.15,ampxz=.35,lite=0")
    o.chain(b2, n)
    o.group("lines:w=2.6,a=1,mix=0,rad=1.15,ampxz=.35")
    o.chain(b1, n)
    o.group("lines:w=2.6,a=1,mix=1,rad=1.15,ampxz=.35")
    o.chain(b2, n)
    rb = o.verts(np.concatenate([s1[rung], s2[rung]]))
    m = len(rung)
    o.group("lines:w=1.2,a=.6,mix=.5,rad=1.15,ampxz=.35,scan=y")
    o.segments(rb, [(i, i + m) for i in range(m)])
    o.group("points:size=6,a=1,mix=.5,rad=1.15,ampxz=.35")
    o.points(rb, range(2 * m))
    o.save("helix")


def _unit(rng, n):
    v = rng.normal(size=(n, 3))
    return v / np.linalg.norm(v, axis=1)[:, None]


def _fragments(rng, n, r_lo, r_hi, l_lo, l_hi):
    d = _unit(rng, n)
    r = rng.uniform(r_lo, r_hi, n)
    c = d * r[:, None]
    up = np.array([0.0, 1.0, 0.0])
    phi = np.cross(up, d)
    phi /= (np.linalg.norm(phi, axis=1)[:, None] + 1e-9)
    theta = np.cross(phi, d)
    theta /= (np.linalg.norm(theta, axis=1)[:, None] + 1e-9)
    pick = rng.random(n)
    rnd = rng.normal(size=(n, 3))
    rnd -= d * (rnd * d).sum(1)[:, None]
    rnd /= (np.linalg.norm(rnd, axis=1)[:, None] + 1e-9)
    t = np.where((pick < 0.38)[:, None], phi, np.where((pick < 0.76)[:, None], theta, rnd))
    ln = rng.uniform(l_lo, l_hi, n) * np.where(rng.random(n) < 0.18, 2.6, 1.0)
    a = c - t * (ln / 2)[:, None]
    b = c + t * (ln / 2)[:, None]
    return np.concatenate([a, b]), n


def _arc(rng, r, sweep, steps=26):
    ax = _unit(rng, 1)[0]
    u = np.cross(ax, _unit(rng, 1)[0])
    u /= np.linalg.norm(u) + 1e-9
    w = np.cross(ax, u)
    start = rng.uniform(0, 2 * math.pi)
    th = start + np.linspace(0, sweep, steps)
    return r * (np.cos(th)[:, None] * u + np.sin(th)[:, None] * w)


def _belt(rng, r, n, jitter_r=0.028, jitter_y=0.05):
    th = np.arange(n) * (2 * math.pi / n) + rng.uniform(-0.01, 0.01, n)
    d = rng.uniform(0.018, 0.075, n) * np.where(rng.random(n) < 0.15, 2.4, 1.0)
    rr = r + rng.uniform(-jitter_r, jitter_r, n)
    yy = rng.uniform(-jitter_y, jitter_y, n)
    a = np.stack([rr * np.cos(th), yy, rr * np.sin(th)], 1)
    b = np.stack([rr * np.cos(th + d), yy + rng.uniform(-0.01, 0.01, n), rr * np.sin(th + d)], 1)
    return np.concatenate([a, b]), n


def _dashed_arc(rng, r, sweep, dashes):
    ax = _unit(rng, 1)[0]
    u = np.cross(ax, _unit(rng, 1)[0])
    u /= np.linalg.norm(u) + 1e-9
    w = np.cross(ax, u)
    start = rng.uniform(0, 2 * math.pi)
    seg = sweep / dashes
    chains = []
    for i in range(dashes):
        th = start + i * seg + np.linspace(0, seg * rng.uniform(0.45, 0.85), 10)
        chains.append(r * (np.cos(th)[:, None] * u + np.sin(th)[:, None] * w))
    return chains


def holo():
    rng = np.random.default_rng(20)
    o = Obj("holo", hud=0, glow=1, particles=0, floor=0, palette="gold")
    shells = (
        (300, 0.94, 1.07, 0.03, 0.13, 0.7, 2.1, 0.0),
        (260, 0.90, 1.09, 0.03, 0.14, -1.0, 2.7, 2.1),
        (220, 0.86, 1.05, 0.04, 0.15, 1.4, 1.7, 4.2),
        (220, 0.60, 0.74, 0.03, 0.11, -1.3, 3.1, 1.0),
        (180, 0.62, 0.76, 0.03, 0.11, 0.9, 2.3, 3.3),
        (130, 0.32, 0.50, 0.03, 0.10, 2.0, 3.6, 5.0),
        (90, 0.10, 0.30, 0.03, 0.09, -2.2, 2.9, 2.5),
    )
    for n, lo, hi, ll, lh, spin, rate, ph in shells:
        arr, m = _fragments(rng, n, lo, hi, ll, lh)
        b = o.verts(arr)
        o.group(f"lines:w=1.7,a=1,mix=.1,spin={spin},rad=1.25,blink=.45,rate={rate},phase={ph},add=1,lite=half")
        o.segments(b, [(i, i + m) for i in range(m)])
    belts = ((0.99, 0.35, 0.7, 130), (0.84, 1.15, -0.9, 110), (0.68, -0.75, 1.2, 90), (1.06, 0.0, -0.5, 140))
    for k, (r, tilt, spin, cnt) in enumerate(belts):
        arr, m = _belt(rng, r, cnt)
        b = o.verts(arr)
        o.group(f"lines:w=2.2,a=1,mix=.25,spin={spin},tilt={tilt},rad=1.25,blink=.3,rate={1.5 + k * 0.4},phase={k},add=1")
        o.segments(b, [(i, i + m) for i in range(m)])
        o.group(f"lines:w=8,a=.07,mix=.3,spin={spin},tilt={tilt},rad=1.25,add=1,lite=0")
        o.segments(b, [(i, i + m) for i in range(0, m, 3)])
    for k, (spin, rate) in enumerate(((0.6, 1.4), (-0.9, 1.9), (1.3, 1.1))):
        chains = []
        for _ in range(3):
            chains += _dashed_arc(rng, rng.uniform(0.5, 1.12), rng.uniform(2.0, 5.4), int(rng.integers(3, 6)))
        counts = [len(c) for c in chains]
        b = o.verts(np.concatenate(chains))
        for tag, spec in (("glow", f"lines:w=9,a=.09,mix=.4,spin={spin},rad=1.25,add=1,lite=0"),
                          ("core", f"lines:w=2.8,a=1,mix=.45,spin={spin},rad=1.25,blink=.3,rate={rate},phase={k},add=1")):
            o.group(spec)
            off = 0
            for c in counts:
                o.chain(b + off, c)
                off += c
    sp = _unit(rng, 70)
    r0 = rng.uniform(0.12, 0.35, 70)
    r1 = rng.uniform(0.7, 1.12, 70)
    arr = np.concatenate([sp * r0[:, None], sp * r1[:, None]])
    b = o.verts(arr)
    o.group("lines:w=1,a=.35,mix=.3,spin=.5,rad=1.25,add=1,lite=0")
    o.segments(b, [(i, i + 70) for i in range(70)])
    th = np.linspace(0, 7 * math.pi, 240)
    rr = np.linspace(0.02, 0.34, 240)
    sw = np.stack([rr * np.cos(th), 0.12 * np.sin(th * 1.5), rr * np.sin(th)], 1)
    b = o.verts(sw)
    o.group("lines:w=3.6,a=1,mix=.7,spin=2.4,pitchmul=0,tilt=.5,rad=1.25,add=1")
    o.chain(b, 240)
    o.group("lines:w=11,a=.12,mix=.7,spin=2.4,pitchmul=0,tilt=.5,rad=1.25,add=1,lite=0")
    o.chain(b, 240)
    for k, (cnt, lo, hi) in enumerate(((260, 0.3, 1.12), (200, 0.05, 0.7))):
        d = _unit(rng, cnt) * rng.uniform(lo, hi, cnt)[:, None]
        b = o.verts(d)
        o.group(f"points:size=3,a=1,mix=.7,spin={0.8 + k * 0.5},rad=1.25,blink=.6,rate={2.0 + k},phase={k * 3},add=1")
        o.points(b, range(cnt))
    o.save("holo")


if __name__ == "__main__":
    for fn in (holo, crystal, globe, knot, helix):
        fn()

# by ASDcuber521
