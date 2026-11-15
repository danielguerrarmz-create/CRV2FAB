"""Spec v6 section 4: splitting a member into shorter billets (gnj_nudge/pieces.py).

The selection rules are tested on synthetic checks (fast, exact); the fits themselves on real
surface strokes and parts (slow: each piece is a billet fit with the vendored sc_glulam maths).
"""
import functools
import time

import pytest

from gnj_nudge import pieces as pc
from gnj_nudge import say
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.record import make_entry
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.surface_solver import FabSetup, solve_surface
from gnj_nudge.vectors_v4 import CASES as STROKE_CASES

CARDS = load_cards()


@pytest.fixture(scope="module", autouse=True)
def pool():
    pc.enable_pool()
    yield
    pc.enable_pool(False)


# ---- synthetic: the selection rules, exactly --------------------------------------------------------------

def chk(t, billet, part, bend=True, mach=True, margin=10.0, rounding=0.0):
    return {"lam_mm": float(t), "lam_count": int(round(100 / t)), "ok": bend and mach,
            "bend": {"ok": bend}, "machine": {"ok": mach, "margin_mm": margin if mach else -abs(margin)},
            "billet_mm3": float(billet), "part_mm3": float(part), "waste_pct": 100.0 * (billet - part) / billet,
            "waste_rounding_pct": rounding}


class FakeMember(pc.Member):
    owner = None
    total_mm3 = 100.0

    def points(self, P, k):
        return []  # too few to fit: nothing is ever sent to the pool

    def volume(self, P, k):
        return self.total_mm3 / P

    def span(self, P, k):
        return (1000.0 * k / P, 1000.0 * (k + 1) / P)

    def cut(self, P, j):
        return {}


SETTINGS = pc.PieceSettings((38.0, 17.0, 11.0), 125.0, {"name": "x", "openingWidth": 1.0, "openingHeight": 1.0,
                                                        "lengthMax": None}, 0.0, 4, None)


@pytest.fixture
def counts(monkeypatch):
    """Replace the fits with given per-count checks; record which counts were evaluated."""
    table, asked = {}, []

    def fake(member, P, settings, straight, cache, max_eval):
        asked.append(P)
        return pc.Count(P, [pc.Piece(k, object(), opts, member.volume(P, k), member.span(P, k))
                            for k, opts in enumerate(table[P])])
    monkeypatch.setattr(pc, "evaluate_count", fake)
    return table, asked


def run(table_asked, table, **kw):
    t, asked = table_asked
    t.update(table)
    return pc.plan(FakeMember(), SETTINGS, max_eval=1, **kw), asked


ONE_PIECE_PASSES = {1: [[chk(38, 250, 100), chk(17, 240, 100), chk(11, 230, 100)]],
                    2: [[chk(38, 60, 50)], [chk(38, 60, 50)]]}


def test_one_passing_piece_is_never_split_to_shave_waste(counts):
    p, asked = run(counts, ONE_PIECE_PASSES)
    assert p.P == 1 and p.status == "proposed" and asked == [1]  # P = 2 is never even fitted
    assert p.checks[0]["lam_mm"] == 38  # the thickest that passes: waste is only reported


def test_less_waste_alone_does_not_split(counts):
    p, asked = run(counts, ONE_PIECE_PASSES, less_waste=True)
    assert p.P == 1 and asked == [1] and p.checks[0]["lam_mm"] == 11  # the thinner layer, not pieces


def test_split_ok_alone_takes_the_fewest_pieces_that_pass(counts):
    p, asked = run(counts, ONE_PIECE_PASSES, split_ok=True)
    assert p.P == 1 and asked == [1]


def test_split_ok_with_less_waste_takes_the_count_with_the_least_waste(counts):
    table = dict(ONE_PIECE_PASSES)
    table[3] = [[chk(38, 38, 100 / 3)]] * 3  # 114 against 100: 12%, the least
    table[4] = [[chk(38, 30, 25)], [chk(38, 30, 25)], [chk(38, 90, 25)], [chk(38, 30, 25)]]  # 44%
    p, _ = run(counts, table, split_ok=True, less_waste=True)
    assert p.P == 3 and p.split_reason == "split_ok"


def test_a_bend_failure_alone_is_not_a_reason_to_cut(counts):
    p, asked = run(counts, {1: [[chk(38, 200, 100, bend=False), chk(11, 200, 100, bend=False)]],
                            2: [[chk(38, 60, 50)], [chk(38, 60, 50)]]})
    assert p.status == "conflict" and p.reason == "bend" and asked == [1]


def test_a_machine_failure_tries_counts_in_order_and_stops_at_the_first_that_passes(counts):
    p, asked = run(counts, {1: [[chk(38, 200, 100, mach=False)]],
                            2: [[chk(38, 60, 50, mach=False)], [chk(38, 60, 50)]],
                            3: [[chk(38, 40, 100 / 3)]] * 3,
                            4: [[chk(38, 26, 25)]] * 4})
    assert p.P == 3 and p.split_reason == "machine"
    assert asked == [1, 2, 3]  # 4 had less waste and was not chosen, nor evaluated


def test_nothing_fits_names_the_machine_at_the_most_pieces(counts):
    bad = [chk(38, 60, 25, mach=False)]
    p, _ = run(counts, {1: [bad], 2: [bad] * 2, 3: [bad] * 3, 4: [bad] * 4})
    assert p.status == "conflict" and p.reason == "machine" and p.P == 4


def test_waste_target_met_at_rung_zero(counts):
    p, asked = run(counts, ONE_PIECE_PASSES, max_waste_pct=70.0)
    assert p.P == 1 and p.checks[0]["lam_mm"] == 38 and not p.over_target and asked == [1]


def test_waste_target_met_by_a_thinner_layer(counts):
    p, asked = run(counts, ONE_PIECE_PASSES, max_waste_pct=58.5)
    assert p.P == 1 and p.checks[0]["lam_mm"] == 17 and not p.over_target and asked == [1]


def test_waste_target_met_only_by_splitting(counts):
    p, _ = run(counts, ONE_PIECE_PASSES, max_waste_pct=20.0)
    assert p.P == 2 and p.split_reason == "waste" and not p.over_target


def test_an_unreachable_target_shows_the_fewest_pieces_and_the_best_reachable(counts):
    table = dict(ONE_PIECE_PASSES)
    table[3] = [[chk(38, 50, 100 / 3)]] * 3
    table[4] = [[chk(38, 40, 25)]] * 4
    p, _ = run(counts, table, max_waste_pct=5.0)
    assert p.status == "proposed" and p.P == 1 and p.over_target
    assert p.best[1] == 2 and round(p.best[0]) == 17 and p.best[2] == "2 pieces would reach"  # 120 against 100
    assert pc.target_suffix(p) == " Waste 60%, over your 5% target."
    steps = pc.waste_steps(p)
    assert steps[-1]["text"] == "Your waste target is 5%. 2 pieces would reach 17%."


def test_the_total_is_weighted_by_volume_not_a_mean_of_pieces():
    a, b = chk(38, 100, 50), chk(38, 300, 50)
    t = pc.totals([a, b])
    assert t["waste_pct"] == pytest.approx(75.0)  # (400 - 100) / 400
    assert t["waste_pct"] != pytest.approx((a["waste_pct"] + b["waste_pct"]) / 2)  # 66.7, the wrong answer
    r = pc.totals([chk(38, 100, 50, rounding=10.0), chk(38, 300, 50, rounding=0.0)])
    assert r["waste_rounding_pct"] == pytest.approx(2.5)  # 10 of 400


# ---- words: split_ok ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["split it", "shorter pieces are fine", "joints are ok", "do it in two pieces"])
def test_split_ok_by_words(text):
    assert say.keywords(text) == [("hold", "split_ok")]
    assert say.validate({"actions": [{"op": "hold", "name": "split_ok"}], "confident": True}) == [("hold", "split_ok")]


def test_no_joints_releases_split_ok():
    assert say.keywords("no joints please") == [("release", "split_ok")]
    assert say.apply({"split_ok"}, [("release", "split_ok")]) == frozenset()
    assert Holds(["split_ok"])  # a known hold


# ---- surface_stroke, real fits -------------------------------------------------------------------------------

SURF = Surface(GRID_N, GRID_N, saddle()["points"])
STROKES = {name: stroke for name, stroke, _ in STROKE_CASES}


def opening(w, h):
    return FabSetup(125.0, (38.0, 17.0, 11.0), {"name": "Test opening", "openingWidth": float(w),
                                               "openingHeight": float(h), "lengthMax": None})


@functools.lru_cache(maxsize=None)
def stroke(name):
    return SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES[name]])


@functools.lru_cache(maxsize=None)
def surface(name, holds=(), wh=(1200, 280)):
    return solve_surface(stroke(name), frozenset(holds), None, setup=opening(*wh))  # less_waste: not a Holds name yet


@pytest.mark.slow
def test_a_surface_member_too_big_for_the_opening_is_cut_before_its_line_moves():
    one = surface("sharp_wiggle")  # 1200 x 280: one billet fits
    r = surface("sharp_wiggle", (), (1200, 180))  # one billet needs 253 x 194: too high by 14 mm
    assert one.form.check["waste_pct"] and not hasattr(one.form, "plan")
    assert r.status == "proposed" and r.form.pieces == 2 and r.deviation_mm == 0.0
    assert r.sentence == "Your line holds, in 2 pieces joined end to end. Each pressed from layers, then milled."
    assert all(c["machine"]["ok"] for c in r.form.plan.checks)
    d = r.form.as_dict()
    assert d["n_pieces"] == 2 and len(d["cuts"]) == 1 and d["cuts"][0]["note"] == pc.JOINT_WORDS
    assert d["stations"] == one.form.as_dict()["stations"]  # the same line, untouched
    joints = [s for s in r.steps if s["tag"] == "Joint"]
    assert len(joints) == 1 and pc.JOINT_WORDS in joints[0]["text"]


@pytest.mark.slow
def test_joints_appear_in_the_record():
    r = surface("sharp_wiggle", (), (1200, 180))
    e = make_entry("accepted", stroke("sharp_wiggle"), Holds(), r, CARDS)
    assert e["joints"] and e["joints"][0]["note"] == "joint to be designed by the engineer"
    assert "Joint 1 at" in e["formal"] and "joint to be designed by the engineer" in e["formal"]
    assert e["waste_pct"] == round(r.form.plan.totals["waste_pct"], 1)
    assert e["form"]["n_pieces"] == 2 and "outline" not in e["form"]["billet"]


@pytest.mark.slow
def test_pieces_waste_less_than_one_billet_on_a_twisting_member():
    one = surface("diagonal")
    many = surface("diagonal", ("split_ok", "less_waste"))
    assert not hasattr(one.form, "plan")
    assert many.form.pieces > 1
    assert many.form.check["waste_pct"] < one.form.check["waste_pct"] - 10  # measured 19% against 55%


@pytest.mark.slow
def test_a_passing_surface_line_is_not_split_and_fits_nothing_more(monkeypatch):
    called = []
    monkeypatch.setattr(pc, "plan", lambda *a, **k: called.append(1))
    r = solve_surface(stroke("x_axis"), Holds(()), None, setup=opening(1200, 280))
    assert r.form.n_lamellas and called == []


@pytest.mark.slow
def test_holding_solid_never_splits():
    r = surface("sharp_wiggle", ("solid",), (1200, 180))
    assert not hasattr(r.form, "plan") if r.form is not None else r.status == "conflict"


@pytest.mark.slow
def test_split_surface_timing_is_reported():
    """Spec: speed budgets hold with splitting. Measured, printed, and held to 8 s cold."""
    it = SurfaceIntent.build("M2", SURF, [tuple(q) for q in STROKES["sharp_wiggle"]])
    t0 = time.perf_counter()
    r = solve_surface(it, Holds(()), None, setup=opening(1200, 180))
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    solve_surface(it, Holds(()), None, setup=opening(1200, 180))
    again = time.perf_counter() - t0
    print(f"\nsurface split: cold {cold:.2f} s, same line again {again:.2f} s, pieces {r.form.pieces}")
    assert r.form.pieces == 2 and cold < 8.0


@pytest.mark.slow
def test_a_surface_line_that_fails_only_the_bend_is_straightened_never_cut(monkeypatch):
    import math
    flat = Surface(GRID_N, GRID_N, [[-1500 + 150 * i, -1500 + 150 * j, 800.0] for i in range(21) for j in range(21)])
    arc = [(round(0.5 + 0.30 * math.cos(a), 6), round(0.2 + 0.30 * math.sin(a), 6))
           for a in [math.radians(30 + 120 * k / 40) for k in range(41)]]  # in-plane radius about 900 mm
    called = []
    real = pc.plan
    monkeypatch.setattr(pc, "plan", lambda *a, **k: called.append(1) or real(*a, **k))
    r = solve_surface(SurfaceIntent.build("M1", flat, arc), Holds(()), None,
                      setup=FabSetup(125.0, (38.0, 25.0, 19.0, 12.0, 8.0), opening(1200, 280).machine))
    assert r.form.smoothing_passes > 0 and called == []  # the v4 answer, untouched by pieces


# ---- a near-straight leg: their fit may return an "arc" of R ~ 1e9 mm; we show it as straight ----

def test_a_radius_above_a_million_mm_is_shown_as_straight():
    import math
    from types import SimpleNamespace
    import numpy as np
    from gnj_nudge import fabrication as fb
    import json
    from gnj_nudge import vectors_part as vp
    from gnj_nudge.part import PartIntent, solve_part
    assert fb.mode_of(SimpleNamespace(kind="arc", radius=1.4e9)) == "straight"
    assert fb.mode_of(SimpleNamespace(kind="arc", radius=float("inf"))) == "straight"
    assert fb.mode_of(SimpleNamespace(kind="arc", radius=1_000_000.0)) == "arc"
    assert fb.mode_of(SimpleNamespace(kind="line")) == "straight"
    R = 2e9  # their fit returns an arc of about 1.05e9 mm for this member
    pts, vol = vp.swept(lambda s: (s, 0.0, R - math.sqrt(R * R - (s - 1500) ** 2)), 3000.0, 100.0, 100.0)
    fit = fb.fit_arc_billet(np.asarray(pts, float))
    assert fit.spine.kind == "arc" and fit.spine.radius > 1e8  # their answer, unchanged
    assert fit.mode == "straight"
    r = solve_part(PartIntent.build("P1", [[round(c, 1) for c in p] for p in pts], vol), frozenset())
    billet = r.form.summary()["pieces"][0]["billet"]
    assert billet["mode"] == "straight" and billet["radius_mm"] is None
    assert "1052" not in json.dumps(r.as_dict()) and "e+" not in json.dumps(r.as_dict())
