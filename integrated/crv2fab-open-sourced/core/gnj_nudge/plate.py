"""Spec v9 slice 1 (docs/SPEC_V9.md): intent kind `plate`, three strokes build a plate.

Request: {kind: "plate", member_id, path, profile_start, profile_end, thickness_mm}, mm, Z up. Each
stroke is a list of [x, y, z] or null; null keeps the current member's own. Slice 1 keeps the
current member simple: it is always the straight 2x4 (path 2400 mm along X from the origin, both
profiles a straight 89 mm line across Y, 38 mm thick).

Building the plate (spec, "Building the plate"):
  1. Path: resampled to 65 stations by arc length, flipped if drawn from the far end, ends pinned to
     the current member's ends (PR #3's pinEnds: a correction blended linearly along the stations),
     resampled again. Frames are rotation minimising (double reflection, Wang et al. 2008, as PR #3's
     rmfNormals): normal starts as world Z square to the first tangent, across = normal x tangent.
  2. Profiles: each projected onto the plane square to the path at its end and read in that end's
     frame as (across, normal), resampled to 15 points by arc length in that plane, centred on the
     mean of the 15 (PR #3's toLocal), ordered so it runs toward +across.
  3. Linear blend point by point between the two ends: the mid-surface, 65 x 15.
  4. Thickened by thickness_mm along the mid-surface normal (half each side): the solid's surface
     samples are the two faces (1950 points). Volume is the closed mesh's (divergence theorem), exact
     for the straight member.
  5. Those points go to the fit every kind uses (pieces.plan, through fabrication's wrappers round
     the vendored sc_glulam).

Easing (slice 2, spec "The nudge" step 3): when the drawn plate fails after layer options and pieces,
one scale at a time is bisected (1 = as drawn, 0 = fully eased), chosen by the check that failed: bend,
the path toward the straight line between its pinned ends; machine or grain, the twist, then the
profiles' curve across the width, then the path's drift out of its best plane through the chord.
Cheap fits steer (the billet's bending plane held at the drawn fit's, fabrication.fit_arc_billet_in_plane,
about 0.03 s); at most 3 full one-billet plans decide each scale.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from dataclasses import replace

from . import pieces as pc
from .part import PartResult

STATIONS = 65
PROFILE_POINTS = 15
MAX_PATH_POINTS, MAX_PROFILE_POINTS = 400, 100
COORD_LIMIT_MM = 1_000_000.0
THICKNESS_MM = 38.0  # spec v9: the default; a setting in slice 3
THICKNESS_RANGE_MM = (1.0, 500.0)
# Stock (Daniel, 2026-11-14): a plate that lies inside one 38 x 89 board, within this tolerance on each
# side of the section and on the length, is one stock 2x4 used as it comes.
STOCK_SECTION_MM = (38.0, 89.0)
STOCK_LENGTH_MM = 2400.0
STOCK_TOLERANCE_MM = 1.0
# The grain card (Daniel, 2026-11-14): a billet's length axis, the way its layers run, lies within this
# many degrees of the path (each piece: the chord of its own run of stations).
GRAIN_CARD = {"id": "grain_deg", "quantity": "billet length axis off the path, maximum", "value": 10.0,
              "unit": "degrees", "source": "placeholder, confirm with the technical member"}
MIN_LENGTH_MM = 1.0  # a stroke shorter than this (after projection, for a profile) is not a stroke

# The current member (slice 1: always the straight 2x4, laid as the bend kind lays it, along X).
STRAIGHT_PATH = ((0.0, 0.0, 0.0), (2400.0, 0.0, 0.0))
STRAIGHT_WIDTH_MM = 89.0
STRAIGHT_PROFILE = ((0.0, -STRAIGHT_WIDTH_MM / 2, 0.0), (0.0, STRAIGHT_WIDTH_MM / 2, 0.0))  # in its end frame
# The current member's end frames (origin, across, normal): where a profile marked "member" was drawn.
MEMBER_ENDS = ((STRAIGHT_PATH[0], (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (STRAIGHT_PATH[1], (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
PROFILE_PLANES = ("member", "path")  # the plane a profile was drawn on: the current member's end, or the drawn path's


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _points(d: dict, key: str, most: int):
    raw = d.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or not 2 <= len(raw) <= most:
        raise ValueError(f"{key} must be null or hold 2 to {most} points")
    for p in raw:
        if not isinstance(p, list) or len(p) != 3 or not all(_finite(c) and abs(c) <= COORD_LIMIT_MM for c in p):
            raise ValueError(f"each point of {key} must be [x, y, z], finite, within {COORD_LIMIT_MM:g} mm")
    return tuple(tuple(float(c) for c in p) for p in raw)


# ---- geometry ------------------------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def resample(pts, n: int) -> np.ndarray:
    """n points evenly spaced by arc length along the polyline; the ends are kept exactly."""
    P = np.asarray(pts, dtype=float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if cum[-1] < MIN_LENGTH_MM:
        raise ValueError("has no length")
    keep = np.concatenate([[True], seg > 0])  # repeated points carry no arc length
    P, cum = P[keep], cum[keep]
    s = np.linspace(0.0, cum[-1], n)
    out = np.stack([np.interp(s, cum, P[:, c]) for c in range(P.shape[1])], axis=1)
    out[0], out[-1] = P[0], P[-1]
    return out


def path_stations(drawn, ends=STRAIGHT_PATH) -> np.ndarray:
    """65 stations: resampled, flipped if drawn from the far end, ends pinned, resampled again."""
    try:
        P = resample(drawn, STATIONS)
    except ValueError:
        raise ValueError("path has no length")
    E0, E1 = np.asarray(ends[0], dtype=float), np.asarray(ends[1], dtype=float)
    as_drawn = np.linalg.norm(P[0] - E0) + np.linalg.norm(P[-1] - E1)
    flipped = np.linalg.norm(P[-1] - E0) + np.linalg.norm(P[0] - E1)
    if flipped < as_drawn:
        P = P[::-1]
    f = np.linspace(0.0, 1.0, STATIONS)[:, None]
    P = P + (1.0 - f) * (E0 - P[0]) + f * (E1 - P[-1])
    try:
        return resample(P, STATIONS)
    except ValueError:
        raise ValueError("path has no length")


def frames(P: np.ndarray):
    """(T, A, N) at every station: unit tangent, across, normal. Rotation minimising by double
    reflection; the first normal is world Z made square to the first tangent (world X when the
    path starts nearly vertical); across = normal x tangent, so the straight member's is +Y."""
    n = len(P)
    T = np.empty_like(P)
    for i in range(n):
        d = P[min(n - 1, i + 1)] - P[max(0, i - 1)]
        if np.linalg.norm(d) < 1e-9:
            raise ValueError("path doubles back on itself")
        T[i] = _unit(d)
    up = np.array([0.0, 0.0, 1.0])
    if abs(up @ T[0]) > 0.95:
        up = np.array([1.0, 0.0, 0.0])
    N = np.empty_like(P)
    N[0] = _unit(up - (up @ T[0]) * T[0])
    for i in range(n - 1):
        v1 = P[i + 1] - P[i]
        c1 = v1 @ v1
        rL = N[i] - (2.0 / c1) * (v1 @ N[i]) * v1
        tL = T[i] - (2.0 / c1) * (v1 @ T[i]) * v1
        v2 = T[i + 1] - tL
        c2 = v2 @ v2
        r = rL - (2.0 / c2) * (v2 @ rL) * v2 if c2 > 1e-18 else rL
        r = r - (r @ T[i + 1]) * T[i + 1]
        N[i + 1] = _unit(r)
    A = np.cross(N, T)
    return T, A / np.linalg.norm(A, axis=1)[:, None], N


def profile_local(prof, origin: np.ndarray, a: np.ndarray, n: np.ndarray, name: str) -> np.ndarray:
    """A 3D profile on (or near) an end plane -> 15 (across, normal) points in that end's frame:
    projected onto the plane square to the path, resampled by arc length in the plane, centred on
    the mean of the 15, running toward +across."""
    D = np.asarray(prof, dtype=float) - origin
    L = np.stack([D @ a, D @ n], axis=1)  # the projection onto the plane square to t, in its frame
    try:
        L = resample(L, PROFILE_POINTS)
    except ValueError:
        raise ValueError(f"{name} has no width across the path: draw it across the member, on the end's plane")
    L = L - L.mean(axis=0)
    if (L[0, 0], L[0, 1]) > (L[-1, 0], L[-1, 1]):
        L = L[::-1]
    return L


def chord_deg(L: np.ndarray) -> float:
    d = L[-1] - L[0]
    return math.degrees(math.atan2(d[1], d[0]))


def developed_width(L: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(L, axis=0), axis=1).sum())


def grid_normals(G: np.ndarray, N: np.ndarray) -> np.ndarray:
    """Unit normals of the mid-surface (along x across), turned to agree with the path's normal."""
    du = np.gradient(G, axis=0)
    dv = np.gradient(G, axis=1)
    Nm = np.cross(du, dv)
    norm = np.linalg.norm(Nm, axis=2)
    if np.any(norm < 1e-12):
        raise ValueError("the plate folds onto itself: a profile or the path doubles back")
    Nm = Nm / norm[..., None]
    flip = np.einsum("ijk,ik->ij", Nm, N) < 0
    Nm[flip] *= -1.0
    return Nm


def closed_volume(top: np.ndarray, bottom: np.ndarray) -> float:
    """Volume enclosed by the two faces (rows along the path, columns across) and the four sides
    joining them, by the divergence theorem over a triangulation. Exact for planar quads."""
    def quads(a, b, c, d):  # a b / d c, every quad as two triangles: sum of a . (b x c) / 6
        return (np.einsum("...k,...k", a, np.cross(b, c)) + np.einsum("...k,...k", a, np.cross(c, d))).sum() / 6.0

    vol = quads(top[:-1, :-1], top[1:, :-1], top[1:, 1:], top[:-1, 1:])
    vol -= quads(bottom[:-1, :-1], bottom[1:, :-1], bottom[1:, 1:], bottom[:-1, 1:])
    # sides: across edges at both ends of the path, along edges at both sides
    for side, sign in ((0, 1.0), (-1, -1.0)):  # j = 0 and j = last, along the path
        t, b = top[:, side], bottom[:, side]
        vol += sign * quads(b[:-1], b[1:], t[1:], t[:-1])
    for end, sign in ((0, -1.0), (-1, 1.0)):  # i = 0 and i = last, across the path
        t, b = top[end], bottom[end]
        vol += sign * quads(b[:-1], b[1:], t[1:], t[:-1])
    return float(abs(vol))


@dataclass(frozen=True)
class Plate:
    stations: np.ndarray  # (65, 3)
    T: np.ndarray
    A: np.ndarray
    N: np.ndarray
    start: np.ndarray  # (15, 2) local (across, normal)
    end: np.ndarray
    grid: np.ndarray  # (65, 15, 3) mid-surface
    normals: np.ndarray  # (65, 15, 3)
    top: np.ndarray
    bottom: np.ndarray
    thickness_mm: float
    volume_mm3: float
    twist_deg: float
    cum: np.ndarray  # arc length at each station

    @property
    def length_mm(self) -> float:
        return float(self.cum[-1])


def drawn_parts(path, profile_start, profile_end, start_on: str = "member", end_on: str = "member"):
    """(stations, start profile, end profile): the path's 65 stations and each profile's local shape,
    read in the frame of the plane it was drawn on (spec v9 Contract): "member", the current member's
    end plane, or "path", the drawn path's end plane. Either way the local shape is then placed at the
    plate's end in the plate's own frame, so a profile drawn before the path was redrawn moves with its
    end and keeps its shape."""
    P = path_stations(path) if path is not None else resample(STRAIGHT_PATH, STATIONS)
    T, A, N = frames(P)
    straight = resample(np.array([[-STRAIGHT_WIDTH_MM / 2, 0.0], [STRAIGHT_WIDTH_MM / 2, 0.0]]), PROFILE_POINTS)
    out = []
    for prof, on, i, member_end, name in ((profile_start, start_on, 0, MEMBER_ENDS[0], "profile_start"),
                                          (profile_end, end_on, -1, MEMBER_ENDS[1], "profile_end")):
        if prof is None:
            out.append(straight)
        elif on == "path":
            out.append(profile_local(prof, P[i], A[i], N[i], name))
        else:
            o, a, n = (np.asarray(v, dtype=float) for v in member_end)
            out.append(profile_local(prof, o, a, n, name))
    return P, out[0], out[1]


def build_plate(path, profile_start, profile_end, thickness_mm: float, start_on: str = "member",
                end_on: str = "member") -> Plate:
    return assemble(*drawn_parts(path, profile_start, profile_end, start_on, end_on), thickness_mm)


def assemble(P: np.ndarray, ps: np.ndarray, pe: np.ndarray, thickness_mm: float) -> Plate:
    """The plate from its stations and its two local profiles: blend, thicken, measure."""
    T, A, N = frames(P)
    f = np.linspace(0.0, 1.0, STATIONS)[:, None, None]
    L = (1.0 - f) * ps[None] + f * pe[None]  # (65, 15, 2)
    G = P[:, None, :] + L[..., :1] * A[:, None, :] + L[..., 1:] * N[:, None, :]
    Nm = grid_normals(G, N)
    h = thickness_mm / 2.0
    top, bottom = G + h * Nm, G - h * Nm
    twist = chord_deg(pe) - chord_deg(ps)
    twist = (twist + 180.0) % 360.0 - 180.0
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return Plate(P, T, A, N, ps, pe, G, Nm, top, bottom, float(thickness_mm), closed_volume(top, bottom),
                 float(twist), cum)


# ---- the intent --------------------------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)  # eq=False: hashed by identity, so the fit cache lives on this object
class PlateIntent:
    member_id: str
    path: tuple | None
    profile_start: tuple | None
    profile_end: tuple | None
    thickness_mm: float
    plate: Plate = field(repr=False)
    profile_start_on: str = "member"
    profile_end_on: str = "member"
    thickness_from: str = "request"  # "request" or "setting": which one set thickness_mm
    kind = "plate"

    @classmethod
    def from_dict(cls, d, default_thickness_mm: float = THICKNESS_MM) -> "PlateIntent":
        """default_thickness_mm: the session's thickness setting, used when the request sends none."""
        from .intent import MEMBER_ID
        if not isinstance(d, dict):
            raise ValueError("intent must be an object")
        mid = d.get("member_id")
        if not isinstance(mid, str) or not MEMBER_ID.fullmatch(mid):
            raise ValueError("member_id must be 1 to 32 letters, digits, underscores or hyphens")
        path = _points(d, "path", MAX_PATH_POINTS)
        start = _points(d, "profile_start", MAX_PROFILE_POINTS)
        end = _points(d, "profile_end", MAX_PROFILE_POINTS)
        sent = "thickness_mm" in d
        t = d["thickness_mm"] if sent else default_thickness_mm
        lo, hi = THICKNESS_RANGE_MM
        if not _finite(t) or not lo <= t <= hi:
            raise ValueError(f"thickness_mm must be a number from {lo:g} to {hi:g}")
        on = []
        for key in ("profile_start_on", "profile_end_on"):
            v = d.get(key, "member")
            if v not in PROFILE_PLANES:
                raise ValueError(f"{key} must be 'member' or 'path'")
            on.append(v)
        return replace(cls.build(mid, path, start, end, float(t), *on), thickness_from="request" if sent else "setting")

    @classmethod
    def build(cls, member_id: str, path=None, profile_start=None, profile_end=None,
              thickness_mm: float = THICKNESS_MM, profile_start_on: str = "member",
              profile_end_on: str = "member") -> "PlateIntent":
        tup = lambda s: None if s is None else tuple(tuple(float(c) for c in p) for p in s)  # noqa: E731
        path, profile_start, profile_end = tup(path), tup(profile_start), tup(profile_end)
        return cls(member_id, path, profile_start, profile_end, float(thickness_mm),
                   build_plate(path, profile_start, profile_end, float(thickness_mm), profile_start_on, profile_end_on),
                   profile_start_on, profile_end_on)

    def drawn(self) -> list[str]:
        return [w for w, s in (("path", self.path), ("start profile", self.profile_start),
                               ("end profile", self.profile_end)) if s is not None]

    def summary(self) -> dict:
        """For the record: what was drawn and the plate's numbers, never the strokes' points."""
        p = self.plate
        return {"member_id": self.member_id, "kind": "plate", "drawn": self.drawn(),
                "profile_start_on": self.profile_start_on, "profile_end_on": self.profile_end_on,
                "thickness_from": self.thickness_from,
                "thickness_mm": self.thickness_mm, "length_mm": round(p.length_mm, 1),
                "width_start_mm": round(developed_width(p.start), 1), "width_end_mm": round(developed_width(p.end), 1),
                "twist_deg": round(p.twist_deg, 1), "volume_mm3": round(p.volume_mm3, 1)}


# ---- splitting: pieces are equal runs of stations ----------------------------------------------------------

class PlateMember(pc.Member):
    """The stations are evenly spaced along the path, so equal runs of stations are equal lengths."""

    def __init__(self, intent: PlateIntent, plate: Plate | None = None, owner=None):
        self.owner = owner if owner is not None else intent  # the fit cache lives on the owner
        self.plate = plate if plate is not None else intent.plate
        self.n = STATIONS
        self.total_mm3 = self.plate.volume_mm3

    def bounds(self, P: int, k: int) -> tuple[int, int]:
        last = self.n - 1
        return round(last * k / P), round(last * (k + 1) / P)

    def points(self, P, k):
        a, b = self.bounds(P, k)
        p = self.plate
        return np.concatenate([p.top[a:b + 1].reshape(-1, 3), p.bottom[a:b + 1].reshape(-1, 3)])

    def span(self, P, k):
        a, b = self.bounds(P, k)
        return float(self.plate.cum[a]), float(self.plate.cum[b])

    def grain(self, P, k):
        """The grain follows the path: piece k's axis is the chord of its own stations. The normals
        offered for a fit constrained to the grain are the piece's mean across and mean normal."""
        a, b = self.bounds(P, k)
        p = self.plate
        axis = p.stations[b] - p.stations[a]
        axis = axis / np.linalg.norm(axis)
        return axis, (p.A[a:b + 1].mean(axis=0), p.N[a:b + 1].mean(axis=0))

    def volume(self, P, k):
        if P == 1:
            return self.total_mm3
        a, b = self.bounds(P, k)
        return closed_volume(self.plate.top[a:b + 1], self.plate.bottom[a:b + 1])

    def cut(self, P, j):
        i = self.bounds(P, j)[0]
        p = self.plate
        r = lambda v, nd: [round(float(c), nd) + 0.0 for c in v]  # noqa: E731
        return {"station": i, "origin": r(p.stations[i], 1), "normal": r(p.T[i], 6),
                "line": [r(p.grid[i, 0], 1), r(p.grid[i, -1], 1)]}


# ---- stock: one 2x4 as it comes ----------------------------------------------------------------------------

def stock_fit(plate: Plate) -> dict | None:
    """The board a plate fits inside, or None. The plate's two faces are measured in the frame of its
    path chord and its start frame (across and normal made square to the chord); the section may lie
    either way round. A bend, a twist or a curved profile shows up as a larger extent."""
    pts = np.concatenate([plate.top.reshape(-1, 3), plate.bottom.reshape(-1, 3)])
    x = plate.stations[-1] - plate.stations[0]
    x = x / np.linalg.norm(x)
    a = plate.A[0] - (plate.A[0] @ x) * x
    a = a / np.linalg.norm(a)
    n = np.cross(x, a)
    ext = [float(np.ptp(pts @ e)) for e in (x, a, n)]
    small, large = sorted(ext[1:])
    tol = STOCK_TOLERANCE_MM
    if small <= STOCK_SECTION_MM[0] + tol and large <= STOCK_SECTION_MM[1] + tol and ext[0] <= STOCK_LENGTH_MM + tol:
        board = STOCK_SECTION_MM[0] * STOCK_SECTION_MM[1] * min(ext[0], STOCK_LENGTH_MM)
        part = plate.volume_mm3
        return {"length_mm": min(ext[0], STOCK_LENGTH_MM), "billet_mm3": board, "part_mm3": part,
                "waste_pct": max(0.0, 100.0 * (board - part) / board), "extents_mm": ext}
    return None


# ---- the answer ------------------------------------------------------------------------------------------

def _vec(a: np.ndarray, nd: int) -> list:
    return np.round(a, nd).tolist()


@dataclass(frozen=True)
class PlateForm:
    intent: PlateIntent
    member: PlateMember
    plan: pc.Plan | None  # None for one stock 2x4
    straight: bool
    stock: dict | None = None
    scales: dict | None = None  # the eased scales (None: as drawn)

    @property
    def solid(self) -> bool:  # taste reads this: one piece, no pressing
        return self.straight or self.stock is not None

    @property
    def n_pieces(self) -> int:
        return 1 if self.stock else self.plan.P

    @property
    def n_lamellas(self) -> int:
        return 1 if self.stock else max(c["lam_count"] for c in self.plan.checks)

    @property
    def lamella_mm(self) -> float:
        return STOCK_SECTION_MM[0] if self.stock else min(c["lam_mm"] for c in self.plan.checks)

    @property
    def check(self) -> dict:  # what record.volumes reads: the volume-weighted totals
        t = self.stock or self.plan.totals
        return {"billet_mm3": t["billet_mm3"], "part_mm3": t["part_mm3"], "waste_pct": t["waste_pct"]}

    def joints(self) -> list[dict]:
        return [] if self.stock else pc.joints(self.member, self.plan)

    def _stock_dict(self) -> dict:
        st, (d, w) = self.stock, STOCK_SECTION_MM
        return {"billet": {"mode": "stock", "length_mm": pc._f(st["length_mm"]), "width_mm": w, "depth_mm": d,
                           "radius_mm": None, "volume_m3": round(st["billet_mm3"] / 1e9, 6)},
                "checks": {"bend": {"ok": True, "applies": False}, "machine": {"ok": True, "applies": False},
                           "grain": {"ok": True, "angle_deg": 0.0, "limit": GRAIN_CARD["value"]},
                           "waste_pct": pc._f(st["waste_pct"]), "waste_rounding_pct": 0.0,
                           "max_waste_pct": st["target"],
                           "waste_ok": None if st["target"] is None else st["waste_pct"] <= st["target"] + 1e-9}}

    def as_dict(self, geometry: bool = True) -> dict:
        p = self.member.plate  # the plate as built (eased, or as drawn)
        t = self.stock or self.plan.totals
        out = {"kind": "plate_member"}
        if geometry:
            grid = _vec(p.grid, 2)
            out["end_frames"] = {name: {"origin": _vec(p.stations[i], 2), "tangent": _vec(p.T[i], 6),
                                        "across": _vec(p.A[i], 6), "normal": _vec(p.N[i], 6)}
                                 for name, i in (("start", 0), ("end", -1))}
            out |= {"stations": _vec(p.stations, 2), "grid": grid, "normals": _vec(p.normals, 6),
                    "intent_grid": grid if self.scales is None else _vec(self.intent.plate.grid, 2)}
        eased = {k: round(float(v), 4) for k, v in (self.scales or dict.fromkeys(SCALES, 1.0)).items()}
        out |= {"thickness_mm": p.thickness_mm, "eased": eased,
                "twist_deg": round(p.twist_deg, 1) + 0.0, "length_mm": round(p.length_mm, 1),
                "width_start_mm": round(developed_width(p.start), 1), "width_end_mm": round(developed_width(p.end), 1),
                "n_lamellas": self.n_lamellas, "lamella_mm": pc._f(self.lamella_mm, 2),
                "straight_billet": self.straight, "part_volume_m3": round(t["part_mm3"] / 1e9, 6)}
        if self.stock:
            return out | {"stock": True} | self._stock_dict()
        pcs = [pc.piece_dict(pi, c, self.straight, geometry) for pi, c in zip(self.plan.count.pieces, self.plan.checks)]
        if self.plan.P == 1:
            out["billet"] = pcs[0]["billet"]
            out["checks"] = pcs[0]["checks"] | {k: v for k, v in pc.summary_checks(self.plan).items()
                                                if k not in ("bend", "machine")}
        else:
            billet = {"mode": "pieces", "volume_m3": round(t["billet_mm3"] / 1e9, 6)}
            if geometry:
                billet["outline"] = [loop for q in pcs for loop in q["billet"]["outline"]]
            out |= {"billet": billet, "checks": pc.summary_checks(self.plan), "n_pieces": self.plan.P,
                    "pieces": pcs, "cuts": self.joints()}
        return out

    def summary(self) -> dict:
        return self.as_dict(geometry=False)


@dataclass
class PlateResult(PartResult):
    def as_dict(self, intent=None) -> dict:
        return {"status": self.status, "form": self.form.as_dict() if self.form else None,
                "sentence": self.sentence, "steps": self.steps, "deviation_mm": round(self.deviation_mm, 1),
                "source": self.source, "conflict": list(self.conflict) if self.conflict else None,
                "governing": self.governing, "taste": None, "model_ms": None}


def _sentence(plan: pc.Plan, straight: bool) -> str:
    if plan.P > 1:
        s = f"Your shape holds, in {plan.P} pieces joined end to end. Each pressed from layers, then milled."
    elif straight:
        s = "Your shape holds. Milled from one straight piece, no bending."
    else:
        piece, chk = plan.count.pieces[0], plan.checks[0]
        how = "Glued straight" if pc.fit_of(piece, chk).mode == "straight" else "Pressed in one curve"
        s = f"Your shape holds. {how} from {chk['lam_count']} layers, then milled to shape."
    return s + pc.target_suffix(plan)


PIECES_MET = {"grain": "a billet would fit only across the grain, and the grain must follow the path.",
              "machine": "each piece's billet is still too large for the opening.",
              "bend": "a piece still bends too tightly for the thinnest layer.",
              "fit": "a piece could not be fitted with a billet."}

CONFLICT_SENTENCES = {"straight": "This will not mill from one straight piece on this machine.",
                      "bend": "This bends too tightly for the thinnest layer.",
                      "machine": "This billet will not fit through the machine.",
                      "grain": "The billet cannot run along the grain at this width.",
                      "fit": "This shape could not be fitted with a billet."}


def heard_text(intent: PlateIntent) -> str:
    p = intent.plate
    drawn = intent.drawn()
    strokes = ("your " + (" and ".join(drawn) if len(drawn) < 3 else "path, start profile and end profile")
               if drawn else "no strokes")
    kept = "" if len(drawn) == 3 else " The rest is the straight member's."
    w0, w1 = developed_width(p.start), developed_width(p.end)
    width = f"{w0:.0f} mm wide" if abs(w0 - w1) < 0.5 else f"{w0:.0f} mm wide at the start and {w1:.0f} mm at the end"
    twist = f", twisting {abs(p.twist_deg):.0f} degrees" if abs(p.twist_deg) >= 0.5 else ""
    return (f"A plate from {strokes}, {pc.m_text(p.length_mm)} along its path, {width}{twist}, "
            f"{p.thickness_mm:g} mm thick.{kept}")


def solve_plate(intent: PlateIntent, holds=frozenset(), settings: pc.PieceSettings | None = None,
                max_waste_pct: float | None = None) -> PlateResult:
    """Fit and check exactly as kind part does. No easing in slice 1: what fails is a conflict."""
    settings = replace(settings or pc.current_settings(), grain_deg=GRAIN_CARD["value"])
    target = settings.max_waste_pct if max_waste_pct is None else max_waste_pct
    straight = "solid" in holds
    member = PlateMember(intent)
    steps = [{"tag": "Heard", "text": heard_text(intent), "limit_id": None}]
    stock = stock_fit(intent.plate)
    if stock is not None:  # one 2x4 as it comes: nothing to press, fit or cut
        d, w = STOCK_SECTION_MM
        steps += [{"tag": "Decision", "text": f"It lies inside one {d:g} x {w:g} mm board, {pc.m_text(stock['length_mm'])} "
                                              f"long, within {STOCK_TOLERANCE_MM:g} mm: one stock 2x4, no pressing.",
                   "limit_id": None},
                  {"tag": "Check", "text": f"It wastes {stock['waste_pct']:.0f}% of the board.", "limit_id": None}]
        form = PlateForm(intent, member, None, straight, stock | {"target": target})
        return PlateResult("proposed", "Your shape holds. One stock 2x4, no pressing.", steps, form=form,
                           governing=[])
    if not straight and settings.max_pieces > 1:
        pc.warm_pool()
    plan = pc.plan(member, settings, straight=straight, split_ok="split_ok" in holds,
                   less_waste="less_waste" in holds, max_waste_pct=target)

    if plan.status == "conflict":
        steps += pc.failure_steps(plan)
        drawn_reason = plan.counts[1].reason()  # the decisive step: the drawn plate in one billet
        cause, pair, lid = pc.conflict_cause(plan, settings, straight, "your shape", drawn_reason)
        tried = f" Tried up to {plan.P} pieces." if plan.P > 1 else ""
        if plan.P > 1 and plan.reason != drawn_reason:  # the pieces met something else: say so, once
            steps.append({"tag": "Limit", "text": f"Tried up to {plan.P} pieces: {PIECES_MET[plan.reason]}",
                          "limit_id": EASE_LIMIT.get(plan.reason)})
            tried = ""
        if "shape" in holds or cause == "fit":
            why = "You are holding the shape" if "shape" in holds else "The shape cannot be fitted"
            steps.append({"tag": "Cannot resolve", "text": f"{why}, so this is a finding, not a change." + tried,
                          "limit_id": lid})
            return PlateResult("conflict", CONFLICT_SENTENCES[cause], steps, conflict=pair, plan=plan)
        eased = ease(intent, plan, settings, straight, holds, target)
        if eased is None:
            done = ", ".join(EASE_WORDS[k][0] for k in EASE_ORDER[plan.counts[1].reason()])
            steps.append({"tag": "Cannot resolve", "text": f"Even with {done} fully eased it does not pass, so this "
                          f"is a finding, not a change." + tried, "limit_id": lid})
            return PlateResult("conflict", CONFLICT_SENTENCES[cause], steps, conflict=pair, plan=plan)
        return eased_result(intent, eased, steps, straight)

    form = PlateForm(intent, member, plan, straight)
    steps += pc.split_why(plan) + pc.piece_steps(plan, straight) + pc.joint_steps(member, plan) + pc.waste_steps(plan)
    governing = ["machine"] if straight else ["lam_ratio", "machine"]
    return PlateResult("proposed", _sentence(plan, straight), steps, form=form, governing=governing, plan=plan)


# ---- easing (slice 2) ---------------------------------------------------------------------------------------

SCALES = ("path", "drift", "twist", "profiles")
EASE_ORDER = {"bend": ("path",), "machine": ("twist", "profiles", "drift"), "grain": ("twist", "profiles", "drift")}
EASE_WHY = {"bend": "so the layers can bend", "machine": "so the billet fits the machine",
            "grain": "so the billet runs along the grain"}
# Slice 3 (one figure for people): the only distance in any sentence or Why step about easing is
# deviation_mm, the largest move anywhere on the plate. The scale phrases carry no distance of their
# own; the twist keeps its angle.
EASE_WORDS = {"path": ("the path's curve", "path"),
              "drift": ("the path's drift", "path drift"),
              "twist": ("the twist", "twist"),
              "profiles": ("the profiles' curve", "profiles")}
# Why step per eased scale, in words only (Daniel, 2026-11-14: the per-scale values stay in `eased`):
# (partly eased, fully eased).
EASE_STEPS = {"twist": ("Twist eased toward none, each end turned back by the same amount",
                        "Twist removed, each end turned back by the same amount"),
              "profiles": ("Profiles flattened toward their chords, their span kept",
                           "Profiles made straight between their ends, their span kept"),
              "path": ("Path straightened toward the line between its ends", "Path made straight between its ends"),
              "drift": ("Path drift eased toward its best plane", "Path drift removed, the path lies in its best plane")}
EASE_LIMIT = {"bend": "lam_ratio", "machine": "machine", "grain": "grain_deg"}
BISECTION_STEPS = 12
FULL_FITS = 3  # full one-billet plans that decide, over all scales (spec "Speed": at most 3 full fits decide)
NOTHING_MM = 0.5  # a scale that moves the plate less than this when fully eased has nothing to ease


def drift_axis(P: np.ndarray):
    """The unit direction out of the path's best plane through its chord (the plane holding the chord
    that is closest to every station, least squares), or None for a straight path."""
    c = P[-1] - P[0]
    c = c / np.linalg.norm(c)
    L = P[0] + np.outer(np.linspace(0.0, 1.0, len(P)), P[-1] - P[0])
    D = P - L
    D = D - np.outer(D @ c, c)
    b1 = np.cross(c, [0.0, 0.0, 1.0])
    if np.linalg.norm(b1) < 1e-6:
        b1 = np.cross(c, [0.0, 1.0, 0.0])
    b1 = b1 / np.linalg.norm(b1)
    b2 = np.cross(c, b1)
    X = np.stack([D @ b1, D @ b2], axis=1)
    if np.abs(X).max() < 1e-9:
        return None
    w, V = np.linalg.eigh(X.T @ X)
    e = V[0, 0] * b1 + V[1, 0] * b2  # the smallest spread: out of the best plane
    return e / np.linalg.norm(e)


def _rotate(L: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return L @ R.T


def _flatten(L: np.ndarray, s: float) -> np.ndarray:
    """Toward the profile's own chord: the ends stay, so its span across never shrinks."""
    chord = L[0] + np.outer(np.linspace(0.0, 1.0, len(L)), L[-1] - L[0])
    out = chord + s * (L - chord)
    return out - out.mean(axis=0)


def eased_parts(drawn: Plate, scales: dict):
    """(stations, start profile, end profile) of the drawn plate with each scale applied."""
    P = drawn.stations
    L = P[0] + np.outer(np.linspace(0.0, 1.0, STATIONS), P[-1] - P[0])
    D = P - L
    if scales["drift"] < 1.0:
        e = drift_axis(P)
        if e is not None:
            D = D - (1.0 - scales["drift"]) * np.outer(D @ e, e)
    D = scales["path"] * D
    if scales["path"] < 1.0 or scales["drift"] < 1.0:
        P = resample(L + D, STATIONS) if np.abs(D).max() > 1e-9 else L
    ps, pe = drawn.start, drawn.end
    if scales["profiles"] < 1.0:
        ps, pe = _flatten(ps, scales["profiles"]), _flatten(pe, scales["profiles"])
    if scales["twist"] < 1.0:
        turn = (1.0 - scales["twist"]) * drawn.twist_deg / 2.0
        ps, pe = _rotate(ps, turn), _rotate(pe, -turn)
    return P, ps, pe


def shape_at(drawn: Plate, scales: dict) -> Plate:
    return assemble(*eased_parts(drawn, scales), drawn.thickness_mm)


def deviation(drawn: Plate, built: Plate) -> float:
    """The largest distance between the drawn and the built mid-surface over the 65 x 15 grid."""
    return float(np.linalg.norm(built.grid - drawn.grid, axis=2).max())


class _Owner:
    """A fit-cache owner for one eased shape."""


def _reference(plan: pc.Plan, cause: str):
    """The fit whose bending plane the cheap fits hold: the drawn one-billet fit that came closest
    (for grain, the best fit that runs on grain, if any)."""
    piece = plan.counts[1].pieces[0]
    if cause == "grain":
        on = [c for c in piece.options if c["grain"]["ok"]]
        if on:
            return max(on, key=lambda c: c["machine"]["margin_mm"])["fit"]
    return pc.explaining(piece, cause)["fit"]


def _cheap_ok(intent, plate: Plate, settings, straight: bool, normal) -> bool:
    from . import fabrication as fb
    m = PlateMember(intent, plate, _Owner())
    pts = m.points(1, 0)
    try:
        fit = fb.fit_straight_billet(pts, settings.allowance) if straight else \
            fb.fit_arc_billet_in_plane(pts, normal, settings.allowance)
    except (ValueError, FloatingPointError, IndexError, ZeroDivisionError):
        return False
    return any(c["ok"] for c in pc.options_for([fit], m.volume(1, 0), settings, straight,
                                               pc.grain_of(m, 1, 0, settings)))


def ease(intent: PlateIntent, plan: pc.Plan, settings, straight: bool, holds, target):
    """(plate, scales, plan, cause, member) for the closest buildable plate, or None."""
    cause = plan.counts[1].reason()
    if cause not in EASE_ORDER:
        return None
    drawn = intent.plate
    normal = _reference(plan, cause).n
    one = replace(settings, max_pieces=1)
    scales = dict.fromkeys(SCALES, 1.0)
    full = FULL_FITS
    for k in EASE_ORDER[cause]:
        if deviation(shape_at(drawn, scales), shape_at(drawn, scales | {k: 0.0})) < NOTHING_MM:
            continue  # nothing of this kind to ease
        ok = lambda v: _cheap_ok(intent, shape_at(drawn, scales | {k: v}), settings, straight, normal)  # noqa: E731
        if not ok(0.0):
            scales[k] = 0.0  # fully eased is still not enough: the next scale
            continue
        lo, hi = 0.0, 1.0
        for _ in range(BISECTION_STEPS):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if ok(mid) else (lo, mid)
        for v in dict.fromkeys((lo, 0.5 * lo, 0.0)):
            if full == 0:
                return None
            full -= 1
            trial = scales | {k: v}
            plate = shape_at(drawn, trial)
            member = PlateMember(intent, plate, _Owner())
            p = pc.plan(member, one, straight=straight, less_waste="less_waste" in holds, max_waste_pct=target)
            if p.status == "proposed":
                return plate, trial, p, cause, member, drawn_failures(plan)
        scales[k] = 0.0
    return None


def drawn_failures(plan: pc.Plan) -> list:
    """The checks the drawn plate failed in one billet: those no layer option passed."""
    opts = plan.counts[1].pieces[0].options
    out = []
    for name, ok in (("bend", lambda c: c["bend"]["ok"]), ("machine", lambda c: c["machine"]["ok"]),
                     ("grain", lambda c: c.get("grain", {}).get("ok", True))):
        if opts and not any(ok(c) for c in opts):
            out.append(name)
    return out


def relative_margin(check: str, chk: dict) -> float:
    """How far a passing check is from its limit, as a share of that limit: bend (R/t over the ratio
    limit) - 1; machine, the smaller of the two spare dimensions over its opening; grain, (limit -
    angle) / limit."""
    if check == "bend":
        b = chk["bend"]
        return (b["ratio"] / b["limit"] - 1.0) if b.get("ratio") is not None else float("inf")
    if check == "machine":
        (across, height), (w, h) = chk["machine"]["need_mm"], chk["machine"]["opening_mm"]
        return min((w - across) / w, (h - height) / h)
    g = chk.get("grain") or {}
    return (g["limit"] - g["angle_deg"]) / g["limit"] if g else float("inf")


def binding(cause: str, failures: list, plan: pc.Plan) -> str:
    """SPEC_V9 "binding": among the checks the drawn plate failed, the one with the least relative
    margin in the eased answer. One failure (or none measurable): the easing cause."""
    candidates = [c for c in failures if c in EASE_WHY]
    if len(candidates) < 2:
        return cause
    return min(candidates, key=lambda c: min(relative_margin(c, chk) for chk in plan.checks))


def eased_result(intent: PlateIntent, eased, steps: list, straight: bool) -> PlateResult:
    plate, scales, plan, cause, member, failures = eased
    cause = binding(cause, failures, plan)   # the words name what binds now, not the first failure
    drawn = intent.plate
    names, why_steps = [], []
    for k in ("twist", "profiles", "drift", "path"):  # the order they are eased in
        if scales[k] >= 1.0:
            continue
        names.append(EASE_WORDS[k][1])
        why_steps.append({"tag": "Decision", "text": f"{EASE_STEPS[k][scales[k] <= 0.0]}, {EASE_WHY[cause]}.",
                          "limit_id": EASE_LIMIT[cause]})
    dev = deviation(drawn, plate)
    # Words plus ONE number (Daniel, 2026-11-14): what eased, why, and deviation_mm.
    what = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    verb = "straightened" if names == ["path"] else "eased"
    sentence = f"{what[0].upper()}{what[1:]} {verb} {EASE_WHY[cause]}, moving the plate at most {dev:.0f} mm."
    form = PlateForm(intent, member, plan, straight, None, scales)
    steps = steps + why_steps + [{"tag": "Check", "text": f"The plate sits at most {dev:.0f} mm from what you drew.",
                                  "limit_id": None}]
    steps += pc.piece_steps(plan, straight) + pc.waste_steps(plan)
    governing = ["machine"] if straight else ["lam_ratio", "machine"]
    return PlateResult("proposed", sentence + pc.target_suffix(plan), steps, form=form, deviation_mm=dev,
                       governing=governing, plan=plan)


def formal_sentence(intent: PlateIntent, result: PlateResult) -> str:
    from .record import SPECIES, volumes_text
    f = result.form
    p = intent.plate
    if f.stock:
        st = f.stock
        return (f"Member {intent.member_id}, {SPECIES}, one stock 2x4 ({STOCK_SECTION_MM[0]:g} x {STOCK_SECTION_MM[1]:g} mm), "
                f"{pc.m_text(st['length_mm'])}, used as it comes, no pressing; the designer's strokes "
                f"({', '.join(intent.drawn()) or 'no strokes'}) lie inside it within {STOCK_TOLERANCE_MM:g} mm. "
                + volumes_text(st["billet_mm3"] / 1e9, st["part_mm3"] / 1e9, st["waste_pct"])
                + " Deviation from intent 0 mm.")
    t = f.plan.totals
    built = f.member.plate
    if f.straight:
        how = "milled from one straight piece, no pressing"
    elif f.plan.P > 1:
        how = f"made in {f.plan.P} pieces joined end to end, each glued from layers, then milled"
    elif pc.fit_of(f.plan.count.pieces[0], f.plan.checks[0]).mode == "straight":
        how = f"glued straight from {f.plan.checks[0]['lam_count']} layers of {f.plan.checks[0]['lam_mm']:g} mm, then milled"
    else:
        how = f"pressed in one curve from {f.plan.checks[0]['lam_count']} layers of {f.plan.checks[0]['lam_mm']:g} mm, then milled"
    drawn = ", ".join(intent.drawn()) or "no strokes"
    w0, w1 = developed_width(p.start), developed_width(p.end)
    width = f"{w0:.0f} mm wide" if abs(w0 - w1) < 0.5 else f"{w0:.0f} to {w1:.0f} mm wide"
    twist = f"twist {p.twist_deg:.1f} degrees" + ("" if not f.scales else f" as drawn, {built.twist_deg:.1f} as built")
    if f.scales:
        kept = "Eased to build: " + ", ".join(f"{k} scale {v:.2f}" for k, v in f.scales.items() if v < 1.0)
    else:
        kept = "Shape kept as drawn"
    g = pc.summary_checks(f.plan)["grain"]
    return (f"Member {intent.member_id}, {SPECIES}, a plate {p.thickness_mm:g} mm thick (from the {intent.thickness_from}) "
            f"built from the designer's strokes ({drawn}), {pc.m_text(built.length_mm)} along its path, {width}, {twist}. "
            f"{kept}; {how}. "
            + pc.formal_text(f.plan, f.member, f.straight) + " "
            + volumes_text(t["billet_mm3"] / 1e9, t["part_mm3"] / 1e9, t["waste_pct"])
            + (f" Grain: the billet runs {g['angle_deg']:.1f} degrees off the path (limit {g['limit']:g})." if f.plan.P == 1
               else f" Grain: each billet runs at most {g['angle_deg']:.1f} degrees off its piece's path (limit {g['limit']:g}).")
            + " Governing limit: " + ("machine opening" if f.straight else "lamella bend radius / thickness; machine opening")
            + f". Deviation from intent {result.deviation_mm:.0f} mm at most.")
