"""Shared test vectors for intent kind `plate` (spec v9 slice 1), for the Rhino client.

Regenerate:  python -m gnj_nudge.vectors_plate      (writes tests/vectors_plate.json)
A test fails if the file and the code ever disagree.

The strokes here are also the unit tests' strokes (tests/test_plate.py). Every case is solved with
the shipped defaults (layers 38/17/11, ratio 125, opening 1200 x 280, up to 4 pieces), the values a
fresh server answers with. The straight member is the 2x4 along X from the origin, 2400 mm.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .vectors_part import V6_LAMS, V6_MAX_PIECES, V6_OPENING, V6_RATIO, dumps, v6_settings

PATH = Path(__file__).resolve().parent.parent / "tests" / "vectors_plate.json"
LENGTH = 2400.0


def arc_path(sag=150.0, n=41):
    """The straight member's span drawn as a circular arc rising sag mm at mid-span (in XZ)."""
    r = (LENGTH ** 2 / 4 + sag ** 2) / (2 * sag)
    half = math.asin(LENGTH / 2 / r)
    out = []
    for k in range(n):
        th = -half + 2 * half * k / (n - 1)
        out.append([LENGTH / 2 + r * math.sin(th), 0.0, r * math.cos(th) - r * math.cos(half)])
    return out


def line_profile(x, width, angle_deg=0.0, n=2):
    """A straight profile on the end plane at x, width mm long, turned angle_deg from +Y toward +Z."""
    a = math.radians(angle_deg)
    return [[x, (-width / 2 + width * k / (n - 1)) * math.cos(a), (-width / 2 + width * k / (n - 1)) * math.sin(a)]
            for k in range(n)]


def u_profile(x, width=300.0, depth=40.0, n=21, turn_deg=0.0):
    """A U across the width: a parabola depth mm deep over width mm, the tips up, turned turn_deg about
    the member's axis (from +Y toward +Z)."""
    a = math.radians(turn_deg)
    out = []
    for k in range(n):
        y, z = -width / 2 + width * k / (n - 1), depth * ((-1 + 2 * k / (n - 1)) ** 2)
        out.append([x, y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)])
    return out


def r1(pts):
    return None if pts is None else [[round(c, 1) + 0.0 for c in p] for p in pts]


CASES = [
    # name, path, profile_start, profile_end, holds
    ("no_strokes", None, None, None, []),
    ("path_arc_up", arc_path(150.0), None, None, []),
    ("profiles_twist_30", None, line_profile(0.0, 300.0, -15.0), line_profile(LENGTH, 300.0, 15.0), []),
    ("profiles_u_across", None, u_profile(0.0), u_profile(LENGTH), []),
    ("path_arc_up_hold_solid", arc_path(150.0), None, None, ["solid"]),
    ("too_wide_for_opening", None, line_profile(0.0, 1400.0), line_profile(LENGTH, 1400.0), []),
    ("too_wide_hold_solid", None, line_profile(0.0, 1400.0), line_profile(LENGTH, 1400.0), ["solid"]),
    ("path_too_tight", arc_path(1000.0), None, None, []),  # radius 1220 mm: under 125 x 11 mm: path eased
    # slice 2, easing: 1000 mm wide, 90 degrees of twist: too deep for the 280 mm opening even in 4 pieces
    ("twist_too_large", None, line_profile(0.0, 1000.0, -45.0), line_profile(LENGTH, 1000.0, 45.0), []),
    ("twist_too_large_hold_shape", None, line_profile(0.0, 1000.0, -45.0), line_profile(LENGTH, 1000.0, 45.0),
     ["shape"]),
    # a 300 mm deep U, 1000 mm across, twisted 40 degrees: untwisted it is still too deep, so the U flattens
    # 600 mm wide, 50 degrees of twist: too deep for the opening in one billet, fits in 2 pieces
    ("twist_50_splits", None, line_profile(0.0, 600.0, -25.0), line_profile(LENGTH, 600.0, 25.0), []),
    ("deep_u_twisted", None, u_profile(0.0, 1000.0, 300.0, turn_deg=-20.0), u_profile(LENGTH, 1000.0, 300.0, turn_deg=20.0),
     []),
]


def request(name: str) -> dict:
    for n, path, ps, pe, holds in CASES:
        if n == name:
            return {"intent": {"kind": "plate", "member_id": "M1", "path": r1(path), "profile_start": r1(ps),
                               "profile_end": r1(pe), "thickness_mm": 38,
                               "profile_start_on": "member", "profile_end_on": "member"},
                    "holds": holds}
    raise KeyError(name)


def expected(result) -> dict:
    out = {"status": result.status, "sentence": result.sentence,
           "conflict": list(result.conflict) if result.conflict else None}
    if result.form is not None:
        d = result.form.summary()
        bills = [p["billet"] for p in d["pieces"]] if "pieces" in d else [d["billet"]]
        out |= {"n_pieces": d.get("n_pieces", 1), "n_lamellas": d["n_lamellas"], "lamella_mm": d["lamella_mm"],
                "twist_deg": d["twist_deg"], "part_volume_m3": d["part_volume_m3"],
                "waste_pct": d["checks"]["waste_pct"],
                "billets_mm": [[round(b[k]) for k in ("length_mm", "width_mm", "depth_mm")] for b in bills],
                "checks": {"bend": d["checks"]["bend"]["ok"], "machine": d["checks"]["machine"]["ok"],
                           "grain": d["checks"]["grain"]["ok"], "grain_angle_deg": d["checks"]["grain"]["angle_deg"]},
                "deviation_mm": round(result.deviation_mm, 1),
                "eased": {k: round(v, 3) for k, v in d["eased"].items()}}
    return out


def build() -> dict:
    from .intent import Holds
    from .plate import PlateIntent, solve_plate
    cases = []
    for name, *_ in CASES:
        req = request(name)
        it = req["intent"]
        intent = PlateIntent.build("M1", it["path"], it["profile_start"], it["profile_end"], it["thickness_mm"],
                                   it["profile_start_on"], it["profile_end_on"])
        result = solve_plate(intent, Holds(req["holds"]), v6_settings())
        cases.append({"name": name, "request": req, "expected": expected(result)})
    return {
        "spec": "docs/SPEC_V9.md slice 1 (intent kind plate: strokes to plate, fit, checks, no easing)",
        "settings": {"lam_options_mm": list(V6_LAMS), "lam_ratio": V6_RATIO, "opening_mm": list(V6_OPENING),
                     "max_pieces": V6_MAX_PIECES, "max_waste_pct": None, "allowance_mm": 0},
        "note": "Solved by the rules with the settings above. The straight member is the 2x4 from (0, 0, 0) to "
                "(2400, 0, 0), profiles a straight 89 mm line across Y, 38 mm thick. Billet sizes are rounded to "
                "the nearest mm, waste to 0.1 %; they come from the sc_glulam optimiser, so compare with a "
                "tolerance (a few mm, half a percent of waste). Stroke points are rounded to 0.1 mm.",
        "cases": cases,
    }


if __name__ == "__main__":
    from .pieces import enable_pool
    from .winpower import keep_full_speed
    keep_full_speed()
    enable_pool()
    PATH.write_text(dumps(build()), encoding="utf-8", newline="\n")
    print(f"wrote {PATH}")
