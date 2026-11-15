"""v4 fabrication route for surface members (spec: docs/SPEC_V4.md). The teammate's method:
press ONE singly curved glulam billet from lamellas, then CNC mill it to the doubly curved member.

Their maths is used unmodified from vendor/sc_glulam/glulam_math.py (loaded from that file).
glulam_billet.py needs Rhino and is never imported; the Rhino-free pieces we need are
re-expressed here, each citing the function it mirrors line for line.

numpy is needed only here: the bend kind never imports this module.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .surface import Curve, cross, scale, sub, unit

ROOT = Path(__file__).resolve().parent.parent
_GM_PATH = ROOT / "vendor" / "sc_glulam" / "glulam_math.py"
_spec = importlib.util.spec_from_file_location("sc_glulam_math", _GM_PATH)
gm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gm)

SECTION_DEPTH_MM = 38.0  # along the surface normal
SECTION_WIDTH_MM = 89.0  # in the surface
OUTLINE_SAMPLES = 200  # our argument (glulam_billet.cnc_envelope uses 800): on these arcs the hull of 200
                       # samples is within a few thousandths of a mm of 800, and four times cheaper
OUTLINE_DRAW_SAMPLES = 33  # response outline polylines: points per face


# ---- 1. the member as points ----------------------------------------------------------------

def member_points(curve: Curve) -> np.ndarray:
    """The 38 x 89 section swept along the stations: the 4 corner curves at all 65 stations.
    38 mm along the surface normal, 89 mm in the surface across the line."""
    pts, normals = curve.pts, curve.normals
    n = len(pts)
    out = []
    for i in range(n):
        a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
        t = unit(sub(b, a))
        nrm = normals[i]
        side = unit(cross(nrm, t))
        for dn in (-SECTION_DEPTH_MM / 2, SECTION_DEPTH_MM / 2):
            for ds in (-SECTION_WIDTH_MM / 2, SECTION_WIDTH_MM / 2):
                p = pts[i]
                out.append((p[0] + nrm[0] * dn + side[0] * ds, p[1] + nrm[1] * dn + side[1] * ds,
                            p[2] + nrm[2] * dn + side[2] * ds))
    return np.array(out, dtype=float)


def member_volume_mm3(curve: Curve) -> float:
    return SECTION_DEPTH_MM * SECTION_WIDTH_MM * curve.length_mm


# ---- 2. the billet fit (once per line; does not depend on lamella thickness) ---------------------

@dataclass
class Fit:
    mode: str  # "arc" or "straight"
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    n: np.ndarray
    spine: object
    P2: np.ndarray
    W: np.ndarray


STRAIGHT_ABOVE_MM = 1_000_000.0  # their fit can return an "arc" of R ~ 1.4e9 mm for a near-straight
                                 # member; in OUR output any radius above this is straight (radius null).


def mode_of(spine) -> str:
    """"arc" only for an arc a panel can state; their spine object is used unchanged for the maths."""
    if spine.kind != "arc":
        return "straight"
    r = float(spine.radius)
    return "arc" if math.isfinite(r) and r <= STRAIGHT_ABOVE_MM else "straight"


def fit_arc_billet(points: np.ndarray, allowance: float = 0.0, max_eval: int = 60, max_count: int = 1000) -> Fit:
    """Mirrors glulam_billet.fit_billet (constant radius, no bendPlane): fit_bending_plane, then
    project, then fit_arc_2d on gm.subset(P2, FIT_SAMPLE_COUNT=4000). max_count is their
    fit_bending_plane argument (the quick sample; their re-score uses 4 x max_count)."""
    origin, u, v, n = gm.fit_bending_plane(points, allowance, maxCount=max_count, maxEval=max_eval)
    P2, W = gm.project_to_frame(points, origin, u, v, n)
    spine, _, _ = gm.fit_arc_2d(gm.subset(P2, 4000), allowance)
    return Fit(mode_of(spine), origin, u, v, n, spine, P2, W)


def fit_arc_billet_in_plane(points: np.ndarray, normal: np.ndarray, allowance: float = 0.0) -> Fit:
    """Mirrors glulam_billet.fit_billet with bendPlane given: pca_axes for the origin and length
    axis, plane_frame(normal, axes[0]), then fit_arc_2d. Used for straightened rungs, which reuse
    the drawn line's bending plane instead of refitting it (the plane fit is 90 % of the time)."""
    origin, axes = gm.pca_axes(points)
    u, v, n = gm.plane_frame(np.asarray(normal, dtype=float), axes[0])
    P2, W = gm.project_to_frame(points, origin, u, v, n)
    spine, _, _ = gm.fit_arc_2d(gm.subset(P2, 4000), allowance)
    return Fit(mode_of(spine), origin, u, v, n, spine, P2, W)


def fit_straight_billet(points: np.ndarray, allowance: float = 0.0) -> Fit:
    """Their zero-curvature case (fit_arc_2d with kHat = 0, strip_area): the smallest straight
    band, for each of the two principal-axis planes fit_bending_plane starts from; keep the
    smaller volume. Re-expressed because their fit only reaches it when it is optimal."""
    origin, axes = gm.pca_axes(points)
    best = None
    for n0 in (axes[2], axes[1]):
        u, v, n = gm.plane_frame(n0, axes[0])
        P2, W = gm.project_to_frame(points, origin, u, v, n)
        centroid = P2.mean(axis=0)
        _, axes2d = np.linalg.eigh(np.cov((P2 - centroid).T))
        psi0 = math.atan2(axes2d[1, 0], axes2d[0, 0])
        direction = lambda psi: np.array([math.cos(psi), math.sin(psi)])  # noqa: E731
        x, area = gm.nelder_mead(lambda x: gm.strip_area(P2, direction(x[0]), allowance), [psi0], [0.25], maxEval=200)
        volume = (np.ptp(W) + 2 * allowance) * area
        if best is None or volume < best[0]:
            spine = gm.LineSpine(centroid, gm._rot90(direction(x[0]))[0])
            best = (volume, Fit("straight", origin, u, v, n, spine, P2, W))
    return best[1]


# ---- 3 to 7. one lamella thickness on a fitted billet --------------------------------------------

def check_billet(fit: Fit, lam_mm: float | None, machine: dict, ratio_limit: float, member_mm3: float,
                 allowance: float = 0.0, stop_at_bend: bool = False) -> dict:
    """All the numbers for one thickness. lam_mm None: one straight piece, no pressing (the
    bend check does not apply; depth is what the part needs)."""
    pressing = lam_mm is not None
    ext0 = gm.billet_extents(fit.spine, fit.P2, fit.W, allowance, 1.0)
    t = lam_mm if pressing else ext0["depthNeeded"]
    ext = gm.billet_extents(fit.spine, fit.P2, fit.W, allowance, t)  # depth rounded up to whole lams

    # Bend: mirrors glulam_billet.slice_lams (FACES, offset_radii, LAM_RADII, LAM_OK, Kx).
    bend = {"ok": True, "tightest_radius_mm": None, "ratio": None, "limit": ratio_limit, "applies": pressing}
    kx = 1.0
    if pressing:
        faces = [ext["dLow"] + i * t for i in range(ext["lamCount"] + 1)]
        try:
            face_radii = gm.offset_radii(fit.spine, ext["sLow"], ext["sHigh"], faces)
            lam_radii = [min(face_radii[i], face_radii[i + 1]) for i in range(ext["lamCount"])]
            tightest = min(lam_radii)
            ok = all(r / t >= ratio_limit for r in lam_radii)
        except ValueError:  # a face passes its centre of curvature: far too tight
            tightest, ok = 0.0, False
        bend.update(ok=bool(ok), tightest_radius_mm=None if math.isinf(tightest) else float(tightest),
                    ratio=None if math.isinf(tightest) else float(tightest / t))
        kx = gm.curvature_factor_kx(t, tightest) if tightest > 0 else -math.inf

    if stop_at_bend and not bend["ok"]:  # the caller only needs to know this thickness fails
        return {"lam_mm": float(t), "lam_count": int(ext["lamCount"]), "ext": ext, "bend": bend, "machine": None,
                "ok": False}

    # Machine: mirrors glulam_billet.cnc_envelope + check_machine.
    s = np.linspace(ext["sLow"], ext["sHigh"], OUTLINE_SAMPLES)
    outline = np.vstack([fit.spine.point(s, ext["dLow"]), fit.spine.point(s, ext["dHigh"])])
    box = gm.min_width_box(outline)
    in_plane, width = box["width"], ext["wHigh"] - ext["wLow"]
    W_, H_ = machine["openingWidth"], machine["openingHeight"]
    results = []
    for label, across, height in (("flat", in_plane, width), ("on edge", width, in_plane)):
        margin = min(W_ - across, H_ - height)
        results.append({"label": label, "fits": margin >= 0.0, "margin": margin, "across": across, "height": height})
    fitting = [r for r in results if r["fits"]]
    best = max(fitting, key=lambda r: r["margin"]) if fitting else max(results, key=lambda r: r["margin"])
    length_ok = machine.get("lengthMax") is None or box["length"] <= machine["lengthMax"]
    mach = {"ok": bool(fitting), "name": machine["name"],
            "need_mm": [round(float(best["across"]), 1), round(float(best["height"]), 1)],
            "opening_mm": [float(W_), float(H_)], "orientation": best["label"],
            "margin_mm": round(float(best["margin"]), 1), "feed_length_mm": round(float(box["length"]), 1),
            "length_ok": bool(length_ok)}

    # Waste: mirrors glulam_billet.wastage (billet volume = Billet.band_volume, the Brep volume).
    billet_mm3, waste_pct, rounding_pct = waste_figures(fit, ext, member_mm3)

    return {"lam_mm": float(t), "lam_count": int(ext["lamCount"]), "ext": ext, "bend": bend, "machine": mach,
            "waste_pct": float(waste_pct), "waste_rounding_pct": float(rounding_pct), "kx": float(kx),
            "billet_mm3": float(billet_mm3), "part_mm3": float(member_mm3),
            "ok": bool(bend["ok"] and mach["ok"])}


def waste_figures(fit: Fit, ext: dict, member_mm3: float) -> tuple[float, float, float]:
    """(billet mm3, waste %, share of the billet caused by rounding up to whole lamellas %).
    Mirrors glulam_billet.wastage: billet volume minus part volume over billet volume, and the
    rounding share as the billet minus the band at the unrounded depth (pad split equally)."""
    width = ext["wHigh"] - ext["wLow"]
    billet = width * gm.band_area(fit.spine, ext["sLow"], ext["sHigh"], ext["dLow"], ext["dHigh"])
    pad = 0.5 * ((ext["dHigh"] - ext["dLow"]) - ext["depthNeeded"])
    unrounded = width * gm.band_area(fit.spine, ext["sLow"], ext["sHigh"], ext["dLow"] + pad, ext["dHigh"] - pad)
    return billet, 100.0 * (billet - member_mm3) / billet, 100.0 * (billet - unrounded) / billet


# ---- waste for the bend kind (report only; the bend kind's own rules are unchanged) ------------------

def bend_member_points(radius_mm: float, chord_mm: float, angle_deg: float, stations: int = 65):
    """The 38 x 89 section swept along the bent member, 4 corner curves. The bend lies in the plane
    of X and d = (0, sin a, cos a); the section turns with the tangent. Returns (points, plane normal,
    centreline length)."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    X = np.array([1.0, 0.0, 0.0])
    d = np.array([0.0, s, c])
    e = np.cross(X, d)  # out of the bending plane
    half = math.asin(min(1.0, chord_mm / (2.0 * radius_mm)))
    pts = []
    for th in np.linspace(-half, half, stations):
        p = radius_mm * math.sin(th) * X + (radius_mm * math.cos(th) - radius_mm * math.cos(half)) * d
        out = math.sin(th) * X + math.cos(th) * d
        thick, wide = c * out + s * e, s * out - c * e  # the unbent Z and Y, carried round the bend
        for dz in (-SECTION_DEPTH_MM / 2, SECTION_DEPTH_MM / 2):
            for dy in (-SECTION_WIDTH_MM / 2, SECTION_WIDTH_MM / 2):
                pts.append(p + dz * thick + dy * wide)
    return np.array(pts), e, radius_mm * 2.0 * half


@functools.lru_cache(maxsize=256)
def bend_waste(radius_mm: float, chord_mm: float, angle_deg: float, lam_mm: float, allowance: float = 0.0) -> dict:
    """The billet around a bent member, the teammate's way, with the bending plane given (their
    fit_billet bendPlane mode: the plane of a bend is known exactly, and it keeps this instant)."""
    points, normal, length = bend_member_points(radius_mm, chord_mm, angle_deg)
    origin, axes = gm.pca_axes(points)
    u, v, n = gm.plane_frame(normal, axes[0])
    P2, W = gm.project_to_frame(points, origin, u, v, n)
    spine, _, _ = gm.fit_arc_2d(gm.subset(P2, 4000), allowance)
    fit = Fit(mode_of(spine), origin, u, v, n, spine, P2, W)
    ext = gm.billet_extents(spine, P2, W, allowance, lam_mm)
    part = SECTION_DEPTH_MM * SECTION_WIDTH_MM * length  # a bent prism: section area x centreline length
    billet, waste, rounding = waste_figures(fit, ext, part)
    return {"billet_mm3": float(billet), "part_mm3": float(part), "waste_pct": float(waste),
            "waste_rounding_pct": float(rounding), "mode": fit.mode, "lam_count": int(ext["lamCount"]),
            "length_mm": float(ext["sHigh"] - ext["sLow"]), "width_mm": float(ext["wHigh"] - ext["wLow"]),
            "depth_mm": float(ext["dHigh"] - ext["dLow"]),
            "radius_mm": float(spine.radius) if fit.mode == "arc" else None}


def billet_axis(fit: Fit, ext: dict) -> np.ndarray:
    """The billet's length axis in world space (the way its layers, and so its grain, run): the chord
    of the spine from sLow to sHigh, unit."""
    a, b = fit.spine.point(np.array([ext["sLow"], ext["sHigh"]]), 0.0)
    d = (b - a)[0] * fit.u + (b - a)[1] * fit.v
    return d / np.linalg.norm(d)


def grain_angle_deg(fit: Fit, ext: dict, axis) -> float:
    """Angle between the billet's length axis and a reference axis (sign-free), degrees."""
    c = abs(float(billet_axis(fit, ext) @ np.asarray(axis, dtype=float)))
    return math.degrees(math.acos(min(1.0, c)))


def outline_polylines(fit: Fit, ext: dict) -> list[list[list[float]]]:
    """Two closed polylines, the billet's in-plane outline at each width face, world mm."""
    s = np.linspace(ext["sLow"], ext["sHigh"], OUTLINE_DRAW_SAMPLES)
    loop2 = np.vstack([fit.spine.point(s, ext["dLow"]), fit.spine.point(s[::-1], ext["dHigh"])])
    loop2 = np.vstack([loop2, loop2[:1]])
    out = []
    for w in (ext["wLow"], ext["wHigh"]):
        pts = fit.origin + loop2[:, :1] * fit.u + loop2[:, 1:2] * fit.v + w * fit.n
        out.append([[round(float(c), 1) + 0.0 for c in p] for p in pts])
    return out
