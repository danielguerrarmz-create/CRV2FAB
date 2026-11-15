"""Shared test vectors for intent kind `part` (spec v6 sections 3 and 4), for the Rhino client.

Regenerate:  python -m gnj_nudge.vectors_part      (writes tests/vectors_part.json)
A test fails if the file and the code ever disagree.

The geometry generators here are also the test parts (tests/test_part.py, tests/test_pieces.py).
Every case is solved with the spec v6 defaults passed explicitly (layers 38/17/11, ratio 125,
opening 1200 x 280, up to 4 pieces), so the file holds whatever settings main ships with today.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "tests" / "vectors_part.json"
V6_LAMS = (38.0, 17.0, 11.0)
V6_RATIO = 125.0
V6_OPENING = (1200.0, 280.0)
V6_MAX_PIECES = 4


def arc_beam(radius=6000.0, depth=400.0, width=200.0, angle_deg=60.0, steps=60):
    """The analyzer drop's own reference (incoming/dalalaaryan/tests/test_core.js): a pure arc beam,
    3 x 3 points across the section at every one of 61 stations. Returns (points, volume_mm3)."""
    pts = []
    for k in range(steps + 1):
        th = k / steps * math.radians(angle_deg)
        for d in (-depth / 2, 0.0, depth / 2):
            for w in (-width / 2, 0.0, width / 2):
                pts.append([(radius - d) * math.cos(th), (radius - d) * math.sin(th), w])
    return pts, depth * width * radius * math.radians(angle_deg)


def swept(spine, length, depth, width, twist_deg=0.0, stations=60, per_edge=4, cap=3):
    """Surface samples of a rectangular section swept along spine(s) for s in [0, length]: the
    perimeter at every station plus a cap grid at both ends. Returns (points, volume_mm3) with the
    volume as section area x spine length (exact for a section that stays square to the spine)."""
    def frame(s):
        h = 1.0
        a, b = spine(max(s - h, 0.0)), spine(min(s + h, length))
        t = [b[i] - a[i] for i in range(3)]
        n = math.sqrt(sum(c * c for c in t))
        t = [c / n for c in t]
        side = [-t[1], t[0], 0.0]  # Z up: sideways is horizontal
        n = math.sqrt(sum(c * c for c in side))
        side = [c / n for c in side]
        up = [t[1] * side[2] - t[2] * side[1], t[2] * side[0] - t[0] * side[2], t[0] * side[1] - t[1] * side[0]]
        a = math.radians(twist_deg) * (s / length - 0.5)
        c, sn = math.cos(a), math.sin(a)
        e1 = [c * up[i] + sn * side[i] for i in range(3)]
        e2 = [-sn * up[i] + c * side[i] for i in range(3)]
        return e1, e2

    def at(s, dn, dw):
        p, (e1, e2) = spine(s), frame(s)
        return [round(p[i] + dn * e1[i] + dw * e2[i], 3) for i in range(3)]

    ring = []
    corners = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
    for e in range(4):
        a0, a1 = corners[e], corners[(e + 1) % 4]
        for q in range(per_edge):
            f = q / per_edge
            ring.append(((a0[0] + (a1[0] - a0[0]) * f) * depth, (a0[1] + (a1[1] - a0[1]) * f) * width))
    pts = []
    for i in range(stations + 1):
        s = length * i / stations
        pts += [at(s, dn, dw) for dn, dw in ring]
    for s in (0.0, length):
        for i in range(1, cap + 1):
            for j in range(1, cap + 1):
                pts.append(at(s, (i / (cap + 1) - 0.5) * depth, (j / (cap + 1) - 0.5) * width))
    run = 0.0
    prev = spine(0.0)
    for i in range(1, 2001):
        p = spine(length * i / 2000)
        run += math.dist(p, prev)
        prev = p
    return pts, depth * width * run


def straight_beam(length=4000.0, depth=200.0, width=120.0):
    return swept(lambda s: (s, 0.0, 0.0), length, depth, width, stations=20)


def doubly_curved(length=5000.0, rise_radius=9000.0, drift=100.0, depth=120.0, width=200.0, twist_deg=30.0,
                  stations=60):
    """Curved up (radius about rise_radius), drifting sideways in an S, twisting: one singly curved
    billet around all of it is wide and deep."""
    def spine(s):
        x = s - length / 2
        return (s, drift * math.sin(2 * math.pi * s / length),
                rise_radius - math.sqrt(rise_radius ** 2 - x * x))
    return swept(spine, length, depth, width, twist_deg, stations=stations)


def tight_arc(radius=1000.0, angle_deg=80.0, depth=100.0, width=100.0):
    """Bent in one plane to a radius no 11 mm layer can take at ratio 125 (needs 1375 mm)."""
    def spine(s):
        th = s / radius
        return (radius * math.sin(th), 0.0, radius - radius * math.cos(th))
    return swept(spine, radius * math.radians(angle_deg), depth, width, stations=40)


def v_part(leg=1500.0, angle_deg=70.0, depth=100.0, width=100.0):
    """Two straight legs meeting at a kink (turning angle_deg in the vertical plane): one billet must
    bend tightly round the kink; cut at the kink, each leg is straight."""
    a = math.radians(angle_deg / 2)

    def spine(s):
        if s <= leg:
            return ((s - leg) * math.cos(a), 0.0, (leg - s) * math.sin(a))
        return ((s - leg) * math.cos(a), 0.0, (s - leg) * math.sin(a))
    return swept(spine, 2 * leg, depth, width, stations=40)


def v6_settings(opening=V6_OPENING):
    """The shipped defaults (gnj_nudge.settings.DEFAULTS), with another opening if asked: the same
    values a server answers with, so a vector posted to /nudge must get its expected answer."""
    import copy
    from .pieces import from_settings
    from .settings import DEFAULTS
    s = copy.deepcopy(DEFAULTS)
    assert (tuple(s["lam_options_mm"]), s["lam_ratio"], tuple(s["opening_mm"]), s["max_pieces"]) == \
        (V6_LAMS, V6_RATIO, V6_OPENING, V6_MAX_PIECES), "vectors_part constants drifted from settings.DEFAULTS"
    s["opening_mm"] = [float(opening[0]), float(opening[1])]
    return from_settings(s)


CASES = [
    ("arc_beam_reference", arc_beam, [], None),
    ("straight_beam", straight_beam, [], None),
    ("doubly_curved", doubly_curved, [], None),
    ("doubly_curved_hold_solid", doubly_curved, ["solid"], None),
    ("tight_arc", tight_arc, [], None),
    ("v_part_split_ok", v_part, ["split_ok"], None),
]


def expected(result) -> dict:
    out = {"status": result.status, "sentence": result.sentence,
           "conflict": list(result.conflict) if result.conflict else None}
    if result.form is not None:
        d = result.form.summary()
        out |= {"n_pieces": d["n_pieces"], "waste_pct": d["checks"]["waste_pct"],
                "pieces": [{"n_lamellas": p["n_lamellas"], "lamella_mm": p["lamella_mm"],
                            "billet_mm": [round(p["billet"][k]) for k in ("length_mm", "width_mm", "depth_mm")],
                            "radius_mm": None if p["billet"]["radius_mm"] is None else round(p["billet"]["radius_mm"]),
                            "waste_pct": p["waste_pct"]} for p in d["pieces"]],
                "cuts_at_mm": [c["at_mm"] for c in d["cuts"]]}
    return out


def build() -> dict:
    from .intent import Holds
    from .part import PartIntent, solve_part
    cases = []
    for name, make, holds, _ in CASES:
        pts, vol = make()
        pts = [[round(c, 1) for c in p] for p in pts]
        vol = round(vol, 1)
        result = solve_part(PartIntent.build("P1", pts, vol), Holds(holds), v6_settings())
        cases.append({"name": name,
                      "request": {"intent": {"kind": "part", "member_id": "P1", "points": pts, "volume_mm3": vol},
                                  "holds": holds},
                      "expected": expected(result)})
    return {
        "spec": "gnj-spec-v6.md sections 3 and 4 (intent kind part, splitting)",
        "settings": {"lam_options_mm": list(V6_LAMS), "lam_ratio": V6_RATIO, "opening_mm": list(V6_OPENING),
                     "max_pieces": V6_MAX_PIECES, "max_waste_pct": None, "allowance_mm": 0},
        "note": "Solved by the rules with the settings above (the spec v6 defaults). Billet sizes and radii are "
                "rounded to the nearest mm, waste to 0.1 %. Billet numbers come from the sc_glulam optimiser: "
                "compare with a tolerance (a few mm, half a percent of waste). Points are rounded to 0.1 mm.",
        "cases": cases,
    }


def dumps(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"


if __name__ == "__main__":
    from .pieces import enable_pool
    enable_pool()
    PATH.write_text(dumps(build()), encoding="utf-8", newline="\n")
    print(f"wrote {PATH}")
