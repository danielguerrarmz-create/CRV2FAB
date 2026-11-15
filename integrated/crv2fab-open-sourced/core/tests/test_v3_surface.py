"""v3 stroke reading, kept unchanged in v4 (docs/SPEC_V3.md, docs/SPEC_V4.md): the surface, the
cleaned line, the smoothing ladder, nearest-point deviation, twist, and server validation.
The fabrication route itself (the v4 billet) is tested in test_v4_fabrication.py."""
import functools
import json
import math
import time

import pytest

from gnj_nudge.intent import Holds
from gnj_nudge.surface import (GRID_N, LADDER, STATIONS, STRAIGHT, Curve, Surface, SurfaceIntent, deviation, dist,
                               norm, saddle)
from gnj_nudge.surface_solver import Ladder, solve_surface
from gnj_nudge.vectors_v4 import PATH, CASES, build, dumps
from test_hardening import raw, srv  # noqa: F401

SURF = Surface(GRID_N, GRID_N, saddle()["points"])
STROKES = {name: stroke for name, stroke, _ in CASES}


@functools.lru_cache(maxsize=None)
def build_intent(name):
    return SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES[name]])


# ---- the surface -------------------------------------------------------------------

def test_the_surface_reproduces_the_saddle_inside_and_its_normal():
    for u, v in [(0.5, 0.5), (0.3, 0.7), (0.33, 0.61), (0.11, 0.89)]:
        p = SURF.point(u, v)
        assert p[2] == pytest.approx(800 + (p[0] ** 2 - p[1] ** 2) / 6000, abs=1e-9)
        n = SURF.normal(u, v)
        want = (-p[0] / 3000, p[1] / 3000, 1)
        assert sum(a * b for a, b in zip(n, want)) / norm(want) == pytest.approx(1)


def test_the_edge_cell_uses_linear_phantoms():
    # On grid line v = 0.5 (y = 0) the v weights pick one row, so z is a 1D Catmull-Rom in u
    # through P[-1] = 2 P[0] - P[1], P[0], P[1], P[2].
    z = [800 + (x * x) / 6000 for x in (-1500, -1350, -1200)]
    p = [2 * z[0] - z[1], z[0], z[1], z[2]]
    t = 0.4  # u = 0.02 -> cell 0
    want = 0.5 * (2 * p[1] + (-p[0] + p[2]) * t + (2 * p[0] - 5 * p[1] + 4 * p[2] - p[3]) * t * t
                  + (-p[0] + 3 * p[1] - 3 * p[2] + p[3]) * t ** 3)
    assert SURF.point(0.02, 0.5)[2] == pytest.approx(want, abs=1e-9)
    assert SURF.point(0.02, 0.5)[2] != pytest.approx(800 + (-1440.0 ** 2) / 6000, abs=0.01)  # not the true saddle


def test_the_surface_passes_through_its_grid():
    pts = saddle()["points"]
    for i in (0, 7, 20):
        for j in (0, 13, 20):
            assert SURF.point(i / 20, j / 20) == pytest.approx(tuple(pts[i * 21 + j]), abs=1e-9)


# ---- reading the line ---------------------------------------------------------------

def test_the_x_axis_line_follows_the_saddle_at_3000_mm_and_does_not_turn():
    c = build_intent("x_axis").intent
    assert c.r_normal == pytest.approx(3000, abs=1) and math.isinf(c.r_side)
    assert c.length_mm == pytest.approx(2142.1, abs=0.05)


def test_the_diagonal_has_no_normal_curvature_and_twists():
    c = build_intent("diagonal").intent
    assert c.max_kn < 1e-9
    assert c.max_twist_deg_per_m == pytest.approx(19.1, abs=0.05)  # a saddle twists along its diagonal


def test_a_stroke_longer_than_the_stock_is_trimmed():
    i = build_intent("long_x_trimmed")
    assert i.trimmed and i.intent.length_mm == pytest.approx(2400, abs=0.5) and i.intent.length_mm <= 2400
    assert not build_intent("x_axis").trimmed


def test_stations_are_evenly_spaced():
    c = build_intent("sharp_wiggle").intent
    gaps = [dist(c.pts[i], c.pts[i + 1]) for i in range(STATIONS - 1)]
    assert max(gaps) - min(gaps) < 0.05 * (sum(gaps) / len(gaps))


@pytest.mark.parametrize("name", list(STROKES))
def test_every_station_lies_on_the_surface(name):
    i = build_intent(name)
    lad = Ladder(i)
    for curve in (i.intent, lad.get(160), lad.get(STRAIGHT)):
        assert len(curve.pts) == STATIONS
        for (u, v), p, nrm in zip(curve.uv, curve.pts, curve.normals):
            assert 0 <= u <= 1 and 0 <= v <= 1
            assert dist(SURF.point(u, v), p) < 1e-9
            assert norm(nrm) == pytest.approx(1)


def test_returned_stations_lie_on_the_surface_after_rounding():
    r = solve_surface(build_intent("sharp_wiggle"), Holds())
    d = r.form.as_dict()
    for (u, v), p in zip(d["uv"], d["stations"]):
        assert dist(SURF.point(u, v), p) < 0.02


# ---- the shared vectors file -------------------------------------------------------

def test_vectors_file_matches_the_code():
    assert PATH.read_text(encoding="utf-8") == dumps(build()), "run: python -m gnj_nudge.vectors_v4"


def test_vectors_file_covers_six_to_nine_cases():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    assert 6 <= len(data["cases"]) <= 9
    assert {"x_axis", "diagonal", "sharp_wiggle", "long_x_trimmed"} <= {c["name"] for c in data["cases"]}
    assert all("n_strips" not in c["expected"] for c in data["cases"])


# ---- the ladder and deviation ------------------------------------------------------------

def test_the_ladder_ends_with_the_straight_rung():
    assert LADDER[-1] == STRAIGHT == -1
    assert LADDER[:12] == (0, 5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120)


def test_the_straight_rung_is_the_even_uv_segment_between_the_ends():
    i = build_intent("sharp_wiggle")
    c = Ladder(i).get(STRAIGHT)
    (u0, v0), (u1, v1) = i.intent_uv[0], i.intent_uv[-1]
    for u, v in c.uv:
        # On the (u, v) segment between the fixed ends: the cross product is zero.
        assert abs((u - u0) * (v1 - v0) - (v - v0) * (u1 - u0)) < 1e-12
    assert c.uv[0] == pytest.approx((u0, v0)) and c.uv[-1] == pytest.approx((u1, v1))
    gaps = [dist(c.pts[k], c.pts[k + 1]) for k in range(STATIONS - 1)]
    assert max(gaps) - min(gaps) < 0.02 * (sum(gaps) / len(gaps))


def test_incremental_smoothing_matches_smoothing_from_scratch():
    from gnj_nudge.surface import build_curve, ladder_uv
    i = build_intent("sharp_wiggle")
    lad = Ladder(i)
    for p in (5, 10, 320, 640, 5120):
        assert lad.get(p).pts == build_curve(SURF, ladder_uv(SURF, i.intent_uv, p)).pts


def test_deviation_is_distance_to_the_drawn_line_not_to_the_same_index():
    drawn = build_intent("x_axis").intent
    # The same line, stations slid half a step along it: the ghost sits on the drawn line.
    slid = [tuple((a + b) / 2 for a, b in zip(p, q)) for p, q in zip(drawn.pts, drawn.pts[1:])] + [drawn.pts[-1]]
    built = Curve((), tuple(slid), (), 0.0, 0.0, 0.0, 0.0)
    same_index = max(dist(p, q) for p, q in zip(built.pts, drawn.pts))
    assert same_index > 15  # half of a ~33 mm station spacing
    assert deviation(built, drawn) < 0.05  # chord sag of the curved drawn line only


def front_wiggle():
    """Five tight waves in the first 35 % of the line, straight after: straightening shortens the
    front, so every later station slides along the line without moving off it."""
    out = []
    for k in range(200):
        t = k / 199
        v = 0.5 + (0.03 * math.sin(2 * math.pi * 5 * t / 0.35) if t < 0.35 else 0.0)
        out.append((round(0.15 + 0.7 * t, 6), round(v, 6)))
    return out


def test_deviation_pins_the_nearest_point_distance_not_the_sliding_same_index_one():
    i = SurfaceIntent.build("M1", SURF, front_wiggle())
    lad = Ladder(i)
    c = lad.get(40)
    same_index = max(dist(p, q) for p, q in zip(c.pts, i.intent.pts))
    assert same_index >= 2 * lad.deviation(40)
    assert lad.deviation(40) == pytest.approx(14.2, abs=0.05)
    assert same_index == pytest.approx(33.9, abs=0.05)


def test_twist_uses_the_segment_tangent():
    # Agreed with the browser mock: the diagonal of the saddle reads 19.1 degrees per metre.
    assert build_intent("diagonal").intent.max_twist_deg_per_m == pytest.approx(19.1, abs=0.05)
    # The two tangent choices differ by at most a few hundredths; edge_start shows it (central would be 1.8413).
    assert build_intent("edge_start").intent.max_twist_deg_per_m == pytest.approx(1.8183, abs=1e-4)


# ---- server ------------------------------------------------------------------------------

def body(stroke, holds=(), **over):
    intent = {"kind": "surface_stroke", "member_id": "M1", "surface": saddle(), "stroke_uv": stroke} | over
    return {"intent": intent, "holds": list(holds)}


def test_server_surface_nudge_then_judge(srv):  # noqa: F811
    s, out, _ = raw(srv, "POST", "/nudge", body(STROKES["x_axis"]))
    assert s == 200 and out["status"] == "proposed" and out["trimmed"] is False
    f = out["form"]
    assert f["kind"] == "surface_member"
    assert all(len(f[k]) == 65 for k in ("stations", "normals", "uv", "intent_stations"))
    assert (f["n_lamellas"], f["lamella_mm"], f["smoothing_passes"]) == (3, 17.0, 0)
    assert {"billet", "checks"} <= set(f) and "n_strips" not in f
    s, entry, _ = raw(srv, "POST", "/judge", {"verdict": "accepted"})
    assert s == 200 and entry["kind"] == "surface_stroke" and "outline" not in entry["form"]["billet"]


def test_server_conflict_keeps_the_v1_shape(srv):  # noqa: F811
    flat = {"nu": 21, "nv": 21, "points": [[-1500 + 150 * i, -1500 + 150 * j, 800.0] for i in range(21) for j in range(21)]}
    arc = [[round(0.5 + 0.30 * math.cos(a), 6), round(0.2 + 0.30 * math.sin(a), 6)]
           for a in [math.radians(30 + 120 * k / 40) for k in range(41)]]
    s, out, _ = raw(srv, "POST", "/nudge", body(arc, ["shape"], surface=flat))
    assert s == 200 and out["status"] == "conflict" and out["form"] is None
    assert out["conflict"] == ["drawn line", "thinnest lamella 11 mm at R/t 125"]


def test_explicit_kind_bend_is_v2(srv):  # noqa: F811
    i = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 90}
    a = raw(srv, "POST", "/nudge", {"intent": i, "holds": []})[1]
    b = raw(srv, "POST", "/nudge", {"intent": i | {"kind": "bend"}, "holds": []})[1]
    assert a == b and a["form"]["n_strips"] == 8


def grid(n=21):
    return saddle(n)


@pytest.mark.parametrize("over", [
    {"kind": "sculpture"},
    {"surface": grid(11)},
    {"surface": {**grid(), "nu": True}},
    {"surface": {**grid(), "nu": 441, "nv": 1}},  # right point count, wrong grid
    {"surface": {**grid(), "points": grid()["points"][:-1]}},
    {"surface": {**grid(), "points": [[0, 0]] + grid()["points"][1:]}},
    {"surface": {**grid(), "points": [[1e7, 0, 0]] + grid()["points"][1:]}},
    {"surface": {**grid(), "points": [["1", 0, 0]] + grid()["points"][1:]}},
    {"surface": {"nu": 21, "nv": 21, "points": [[0, 0, 0]] * 441}},  # degenerate
    {"stroke_uv": [[0.5, 0.5]]},
    {"stroke_uv": [[0.5, 0.5]] * 401},
    {"stroke_uv": [[0.5, 0.5], [0.5, 0.5]]},  # zero length
    {"stroke_uv": [[0.1, 0.5], [1.01, 0.5]]},
    {"stroke_uv": [[0.1, 0.5], [-0.01, 0.5]]},
    {"stroke_uv": [[0.1, 0.5], [0.2]]},
    {"stroke_uv": "line"},
    {"member_id": "M 1"},
], ids=lambda o: next(iter(o)))
def test_server_refuses_bad_surface_intents(srv, over):  # noqa: F811
    s, out, _ = raw(srv, "POST", "/nudge", body(STROKES["x_axis"], **over))
    assert s == 400 and "error" in out


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity"])
def test_server_refuses_non_finite_surface_numbers(srv, literal):  # noqa: F811
    text = json.dumps(body(STROKES["x_axis"])).replace("0.15", literal.decode(), 1).encode()
    s, out, _ = raw(srv, "POST", "/nudge", text)
    assert s == 400


def test_a_pretty_printed_400_point_request_fits_and_answers_inside_the_budget(srv):  # noqa: F811
    stroke = [[0.2 + 0.6 * i / 399, 0.5 + 0.03 * math.sin(2 * math.pi * i / 399)] for i in range(400)]
    text = json.dumps(body(stroke), indent=4).encode()  # about 93 KB: over the old 64 KB cap
    assert 64 * 1024 < len(text) < 256 * 1024
    t = time.perf_counter()
    s, out, _ = raw(srv, "POST", "/nudge", text)
    assert s == 200 and out["status"] == "proposed"
    assert time.perf_counter() - t < 5.0  # v4 target: fallback under 5 s worst case
