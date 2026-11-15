"""Shared test vectors for v4 (surface_stroke on the sc_glulam route), checked by the Rhino script
and the browser mock. Same strokes as v3; the expected answers are now the pressed-billet route.

Regenerate:  python -m gnj_nudge.vectors_v4      (writes tests/vectors_v4.json)
A test fails if the file and the code ever disagree.

Built with the default settings (spec v6, section 2): layer options [38, 17, 11] and the generic
placeholder opening 1200 x 280 mm. No named machine: the private table is never read here.

Each case's request is {"intent": {kind, member_id, surface, stroke_uv}, "holds": [...]} with the
top-level "surface" inserted as intent.surface (kept once to keep the file small).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .intent import Holds
from .surface import GRID_N, Surface, SurfaceIntent, saddle
from .surface_solver import solve_surface

PATH = Path(__file__).resolve().parent.parent / "tests" / "vectors_v4.json"


def wiggle(amplitude: float, waves: float = 1, n: int = 25, u0: float = 0.2, u1: float = 0.8) -> list[list[float]]:
    """A sine wave sideways (in v) along u, rounded to 6 places."""
    return [[round(u0 + (u1 - u0) * i / (n - 1), 6),
             round(0.5 + amplitude * math.sin(2 * math.pi * waves * i / (n - 1)), 6)] for i in range(n)]


CASES = [
    ("x_axis", [[0.15, 0.5], [0.85, 0.5]], []),
    ("diagonal", [[0.25, 0.25], [0.75, 0.75]], []),
    ("gentle_wiggle", wiggle(0.006), []),
    # The browser mock's reference wiggle: 3 waves of 105 mm (0.035) across u 0.2 to 0.8, 120 points.
    ("sharp_wiggle", wiggle(0.035, waves=3, n=120), []),
    ("sharp_wiggle_hold_shape", wiggle(0.035, waves=3, n=120), ["shape"]),
    ("long_x_trimmed", [[0.05, 0.5], [0.95, 0.5]], []),
    ("x_axis_hold_solid", [[0.15, 0.5], [0.85, 0.5]], ["solid"]),
    ("edge_start", [[0.0, 0.3], [0.6, 0.3]], []),  # starts in the edge cell: checks the linear phantoms
    # A long low wave, trimmed to about 1.3 waves: still too sharp at 640 passes, lands on a higher rung.
    ("low_wave_trimmed", wiggle(0.10, waves=1.5, n=61, u0=0.05, u1=0.95), []),
]


def expected(result) -> dict:
    out = {"status": result.status, "sentence": result.sentence, "trimmed": result.trimmed,
           "conflict": list(result.conflict) if result.conflict else None}
    if result.form:
        f = result.form
        r = lambda x: None if math.isinf(x) else round(x)  # noqa: E731  nearest mm
        b, c = f.billet(outline=False), f.checks()
        rr = lambda x: None if x is None else round(x)  # noqa: E731
        out |= {"n_lamellas": f.n_lamellas, "lamella_mm": round(f.lamella_mm, 2), "straight_billet": f.straight,
                "smoothing_passes": f.smoothing_passes, "deviation_mm": round(result.deviation_mm, 1),
                "min_radius_normal_mm": r(f.curve.r_normal), "min_radius_side_mm": r(f.curve.r_side),
                "length_mm": round(f.curve.length_mm, 1),
                "billet": {"mode": b["mode"], "length_mm": rr(b["length_mm"]), "width_mm": rr(b["width_mm"]),
                           "depth_mm": rr(b["depth_mm"]), "radius_mm": rr(b["radius_mm"])},
                "bend_ok": c["bend"]["ok"], "tightest_lam_radius_mm": rr(c["bend"]["tightest_radius_mm"]),
                "machine_ok": c["machine"]["ok"], "machine_overshoot_mm": rr(c["machine"]["overshoot_mm"]),
                "machine_orientation": c["machine"]["orientation"], "waste_pct": round(c["waste_pct"], 1)}
    return out


def build() -> dict:
    s = saddle()
    surf = Surface(GRID_N, GRID_N, s["points"])
    cards = None  # the surface route takes its limits from the settings (defaults here)
    cases = []
    for name, stroke, holds in CASES:
        intent = SurfaceIntent.build("M1", surf, [tuple(q) for q in stroke])
        cases.append({
            "name": name,
            "request": {"intent": {"kind": "surface_stroke", "member_id": "M1", "stroke_uv": stroke},
                        "holds": holds},
            "expected": expected(solve_surface(intent, Holds(holds), cards)),
        })
    return {
        "spec": "docs/SPEC_V4.md (stroke reading as docs/SPEC_V3.md)",
        "note": "Insert the top-level surface as request.intent.surface. Radii and billet sizes are rounded to the "
                "nearest mm (null when straight), deviation_mm, length_mm and waste_pct to 0.1. Fallback solver, "
                "no model, default settings (layers 38, 17, 11 mm; generic opening 1200 x 280 mm). Billet numbers "
                "come from the sc_glulam "
                "optimiser: compare them with a tolerance (a few mm, half a percent of waste).",
        "surface": s,
        "cases": cases,
    }


def dumps(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    PATH.write_text(dumps(build()), encoding="utf-8", newline="\n")
    print(f"wrote {PATH}")
