"""v3 geometry: a stroke drawn on a doubly-curved surface. Pure Python.

Spec: docs/SPEC_V3.md. Everything here works in the surface's normalised (u, v),
so every curve the core produces lies on the surface by construction.

Algorithms, exactly (clients reproduce these to match tests/vectors_v4.json):
- Surface: bicubic uniform Catmull-Rom through an nu x nv grid (row-major, u outer).
  Cell i = min(floor(u * (nu - 1)), nu - 2), t = u * (nu - 1) - i; same in v. Edge
  phantoms by linear extrapolation, P[-1] = 2 P[0] - P[1], P[n] = 2 P[n-1] - P[n-2].
  Normal = normalize(Su x Sv) from the analytic partials of the same basis.
- Twist at segment i: |(N[i+1] - N[i]) . (Ts x N[i])| / h with Ts the segment's unit tangent.
- resample_even: map uv stations to 3D, cumulative chord length along that polyline,
  place `count` targets at L * s / (count - 1), and interpolate (u, v) linearly inside
  the polyline segment that holds each target. With a length cap, L = min(L, cap).
- smooth: Jacobi Laplacian in (u, v), q[i] = p[i] + 0.5 * ((p[i-1] + p[i+1]) / 2 - p[i]),
  endpoints fixed.
- Cleaned intent: resample_even(stroke, 65); smooth 10 passes; resample_even(65);
  if longer than 2400 mm, resample_even(65, cap 2400) and trimmed = true.
- Ladder curve m: m = 0 is the cleaned intent; m = -1 is the straight (u, v) segment between the
  fixed ends: 65 points evenly spaced in (u, v), then resample_even(65); otherwise
  resample_even(smooth(intent, m), 65).
- Deviation: for each built station, the 3D distance to the nearest point on the cleaned-intent
  polyline (point to segment); the largest. m = 0 means 0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

STATIONS = 65
CLEAN_PASSES = 10
LAMBDA = 0.5
# Extra Laplacian passes; -1 is the last rung: the straight (u, v) segment between the fixed ends.
LADDER = (0, 5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120, -1)
STRAIGHT = -1
STOCK_LENGTH_MM = 2400.0
GRID_N = 21
MIN_STROKE_MM = 10.0
COORD_LIMIT_MM = 1_000_000.0
K_ZERO = 1e-9  # curvature below this (radius above 1e9 mm) reads as straight


class DegenerateSurface(ValueError):
    pass


# ---- small vector helpers (tuples of 3 floats) ------------------------------

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-12:
        raise DegenerateSurface("zero-length vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def dist(a, b):
    return norm(sub(a, b))


# ---- surface ----------------------------------------------------------------

def _cr_weights(t: float):
    """Catmull-Rom basis weights for P0..P3 and their derivatives in t."""
    t2, t3 = t * t, t * t * t
    w = (0.5 * (-t3 + 2 * t2 - t), 0.5 * (3 * t3 - 5 * t2 + 2), 0.5 * (-3 * t3 + 4 * t2 + t), 0.5 * (t3 - t2))
    d = (0.5 * (-3 * t2 + 4 * t - 1), 0.5 * (9 * t2 - 10 * t), 0.5 * (-9 * t2 + 8 * t + 1), 0.5 * (3 * t2 - 2 * t))
    return w, d


class Surface:
    def __init__(self, nu: int, nv: int, points):
        self.nu, self.nv = nu, nv
        grid = [[tuple(float(c) for c in points[i * nv + j]) for j in range(nv)] for i in range(nu)]
        # Pad with linear phantoms: rows first, then columns.
        rows = [tuple(2 * a - b for a, b in zip(grid[0][j], grid[1][j])) for j in range(nv)]
        rowe = [tuple(2 * a - b for a, b in zip(grid[-1][j], grid[-2][j])) for j in range(nv)]
        padded = [rows] + grid + [rowe]
        self.g = [[tuple(2 * a - b for a, b in zip(r[0], r[1]))] + list(r) +
                  [tuple(2 * a - b for a, b in zip(r[-1], r[-2]))] for r in padded]

    def _cell(self, x: float, n: int):
        s = min(max(x, 0.0), 1.0) * (n - 1)
        i = min(int(math.floor(s)), n - 2)
        return i, s - i

    def eval(self, u: float, v: float):
        """(point, Su, Sv) at (u, v)."""
        i, tu = self._cell(u, self.nu)
        j, tv = self._cell(v, self.nv)
        wu, du = _cr_weights(tu)
        wv, dv = _cr_weights(tv)
        px = py = pz = ux = uy = uz = vx = vy = vz = 0.0
        g = self.g
        for a in range(4):
            row = g[i + a]  # padded index i + a == grid index i - 1 + a
            wa, da = wu[a], du[a]
            for b in range(4):
                p = row[j + b]
                wb, db = wv[b], dv[b]
                ww, dw, wd = wa * wb, da * wb, wa * db
                px += ww * p[0]; py += ww * p[1]; pz += ww * p[2]
                ux += dw * p[0]; uy += dw * p[1]; uz += dw * p[2]
                vx += wd * p[0]; vy += wd * p[1]; vz += wd * p[2]
        su, sv = self.nu - 1, self.nv - 1
        return (px, py, pz), (ux * su, uy * su, uz * su), (vx * sv, vy * sv, vz * sv)

    def point(self, u: float, v: float):
        return self.eval(u, v)[0]

    def normal(self, u: float, v: float):
        _, a, b = self.eval(u, v)
        return unit(cross(a, b))


def saddle(n: int = GRID_N) -> dict:
    """The demo sample: z = 800 + (x^2 - y^2) / 6000 for x, y in [-1500, 1500] mm, u along x."""
    pts = []
    for i in range(n):
        x = -1500 + 3000 * i / (n - 1)
        for j in range(n):
            y = -1500 + 3000 * j / (n - 1)
            pts.append([x, y, 800 + (x * x - y * y) / 6000])
    return {"nu": n, "nv": n, "points": pts}


# ---- stroke cleaning and the smoothing ladder ----------------------------------

def polyline_length(pts) -> float:
    return sum(dist(pts[i], pts[i - 1]) for i in range(1, len(pts)))


def resample_even(surf: Surface, uv, count: int = STATIONS, cap: float | None = None):
    """Even 3D arc-length stations along the uv polyline. Returns (uv list, trimmed)."""
    pts = [surf.point(u, v) for u, v in uv]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + dist(pts[i], pts[i - 1]))
    total = cum[-1]
    trimmed = cap is not None and total > cap
    length = cap if trimmed else total
    out, j = [], 0
    for s in range(count):
        target = length * s / (count - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        f = 0.0 if seg <= 0 else min(max((target - cum[j]) / seg, 0.0), 1.0)
        (u0, v0), (u1, v1) = uv[j], uv[j + 1]
        out.append((u0 + (u1 - u0) * f, v0 + (v1 - v0) * f))
    return out, trimmed


def smooth(uv, passes: int):
    """Jacobi: every interior point updates from the previous pass, endpoints fixed."""
    us, vs = [q[0] for q in uv], [q[1] for q in uv]
    n = len(us)
    for _ in range(passes):
        us = [us[0]] + [us[i] + LAMBDA * ((us[i - 1] + us[i + 1]) / 2 - us[i]) for i in range(1, n - 1)] + [us[-1]]
        vs = [vs[0]] + [vs[i] + LAMBDA * ((vs[i - 1] + vs[i + 1]) / 2 - vs[i]) for i in range(1, n - 1)] + [vs[-1]]
    return list(zip(us, vs))


def clean_stroke(surf: Surface, stroke_uv):
    """The cleaned intent: (65 uv stations, trimmed)."""
    uv, _ = resample_even(surf, stroke_uv)
    uv, _ = resample_even(surf, smooth(uv, CLEAN_PASSES))
    if polyline_length([surf.point(u, v) for u, v in uv]) > STOCK_LENGTH_MM:
        return resample_even(surf, uv, cap=STOCK_LENGTH_MM)
    return uv, False


def ladder_uv(surf: Surface, intent_uv, m: int):
    if m == 0:
        return list(intent_uv)
    if m == STRAIGHT:
        (u0, v0), (u1, v1) = intent_uv[0], intent_uv[-1]
        n = len(intent_uv) - 1
        segment = [(u0 + (u1 - u0) * s / n, v0 + (v1 - v0) * s / n) for s in range(n + 1)]
        return resample_even(surf, segment)[0]
    return resample_even(surf, smooth(intent_uv, m))[0]


# ---- curve metrics ----------------------------------------------------------------

@dataclass(frozen=True)
class Curve:
    uv: tuple
    pts: tuple
    normals: tuple
    max_kn: float  # per mm, across the thickness (along the surface normal)
    max_kg: float  # per mm, across the width (in the surface)
    max_twist_deg_per_m: float
    length_mm: float

    @property
    def r_normal(self) -> float:
        return 1 / self.max_kn if self.max_kn > K_ZERO else math.inf

    @property
    def r_side(self) -> float:
        return 1 / self.max_kg if self.max_kg > K_ZERO else math.inf


def build_curve(surf: Surface, uv) -> Curve:
    pts = [surf.point(u, v) for u, v in uv]
    normals = [surf.normal(u, v) for u, v in uv]
    n = len(pts)
    max_kn = max_kg = 0.0
    for i in range(1, n - 1):
        h1, h2 = dist(pts[i], pts[i - 1]), dist(pts[i + 1], pts[i])
        if h1 <= 0 or h2 <= 0:
            raise DegenerateSurface("repeated station")
        k = scale(sub(scale(sub(pts[i + 1], pts[i]), 1 / h2), scale(sub(pts[i], pts[i - 1]), 1 / h1)),
                  2 / (h1 + h2))
        t = unit(sub(pts[i + 1], pts[i - 1]))
        max_kn = max(max_kn, abs(dot(k, normals[i])))
        max_kg = max(max_kg, abs(dot(k, cross(normals[i], t))))
    max_twist = 0.0
    for i in range(n - 1):
        # Twist along each segment, with the segment's own tangent (agreed with the browser mock).
        seg = sub(pts[i + 1], pts[i])
        h = norm(seg)
        rate = abs(dot(sub(normals[i + 1], normals[i]), cross(unit(seg), normals[i]))) / h
        max_twist = max(max_twist, rate)
    return Curve(tuple(uv), tuple(pts), tuple(normals), max_kn, max_kg,
                 math.degrees(max_twist) * 1000, polyline_length(pts))


def point_segment_distance(p, a, b) -> float:
    ab = sub(b, a)
    L2 = dot(ab, ab)
    t = 0.0 if L2 <= 0 else min(max(dot(sub(p, a), ab) / L2, 0.0), 1.0)
    return dist(p, add(a, scale(ab, t)))


def deviation(built: Curve, drawn: Curve) -> float:
    """For each station of the built curve, its 3D distance to the nearest point on the drawn
    polyline (point to segment); the largest. How far the ghost sits from the drawn line."""
    segs = list(zip(drawn.pts, drawn.pts[1:]))
    return max(min(point_segment_distance(p, a, b) for a, b in segs) for p in built.pts)


# ---- the intent ----------------------------------------------------------------

def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class SurfaceIntent:
    member_id: str
    surface: Surface
    stroke_uv: tuple
    intent_uv: tuple  # cleaned, 65 stations
    trimmed: bool
    intent: Curve

    @classmethod
    def from_dict(cls, d) -> "SurfaceIntent":
        from .intent import MEMBER_ID
        if not isinstance(d, dict):
            raise ValueError("intent must be an object")
        mid = d.get("member_id")
        if not isinstance(mid, str) or not MEMBER_ID.fullmatch(mid):
            raise ValueError("member_id must be 1 to 32 letters, digits, underscores or hyphens")
        s = d.get("surface")
        if not isinstance(s, dict):
            raise ValueError("surface must be an object")
        if s.get("nu") != GRID_N or s.get("nv") != GRID_N or isinstance(s.get("nu"), bool) \
                or isinstance(s.get("nv"), bool):
            raise ValueError(f"surface grid must be {GRID_N} x {GRID_N} for now")
        pts = s.get("points")
        if not isinstance(pts, list) or len(pts) != GRID_N * GRID_N:
            raise ValueError(f"surface.points must hold {GRID_N * GRID_N} points")
        for p in pts:
            if not isinstance(p, list) or len(p) != 3 or not all(_finite(c) and abs(c) <= COORD_LIMIT_MM for c in p):
                raise ValueError(f"each surface point must be [x, y, z], finite, within {COORD_LIMIT_MM:g} mm")
        st = d.get("stroke_uv")
        if not isinstance(st, list) or not 2 <= len(st) <= 400:
            raise ValueError("stroke_uv must hold 2 to 400 points")
        for q in st:
            if not isinstance(q, list) or len(q) != 2 or not all(_finite(c) and 0 <= c <= 1 for c in q):
                raise ValueError("each stroke_uv point must be [u, v], each between 0 and 1")
        return cls.build(mid, Surface(GRID_N, GRID_N, pts), [tuple(q) for q in st])

    @classmethod
    def build(cls, member_id: str, surf: Surface, stroke_uv) -> "SurfaceIntent":
        try:
            if polyline_length([surf.point(u, v) for u, v in stroke_uv]) < MIN_STROKE_MM:
                raise ValueError(f"the stroke is shorter than {MIN_STROKE_MM:g} mm on the surface")
            uv, trimmed = clean_stroke(surf, stroke_uv)
            curve = build_curve(surf, uv)
        except DegenerateSurface:
            raise ValueError("the surface is degenerate under the stroke")
        return cls(member_id, surf, tuple(stroke_uv), tuple(uv), trimmed, curve)

    def summary(self) -> dict:
        return {"member_id": self.member_id, "kind": "surface_stroke", "stroke_points": len(self.stroke_uv),
                "trimmed": self.trimmed}
