"""v4: surface members on the teammate's route (docs/SPEC_V4.md): one singly curved billet pressed
from lamellas, then CNC milled. Their maths is vendor/sc_glulam/glulam_math.py, unmodified."""
import functools
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import FakeClient
from gnj_nudge import agent
from gnj_nudge import fabrication as fb
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.record import make_entry
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.surface_agent import nudge_surface, user_message
from gnj_nudge.surface_solver import FabSetup, Ladder, evaluate, solve_surface
from gnj_nudge.vectors_v4 import CASES

ROOT = Path(__file__).resolve().parent.parent
CARDS = load_cards()
SURF = Surface(GRID_N, GRID_N, saddle()["points"])
STROKES = {name: stroke for name, stroke, _ in CASES}
DEFAULT = FabSetup.default()


@pytest.fixture(autouse=True)
def one_billet(monkeypatch):
    """This module pins the v4 route: one billet per member. Spec v6 puts pieces before straightening
    (a small opening is now cut, not straightened); that is tested in test_pieces.py."""
    from dataclasses import replace
    from gnj_nudge import pieces
    real = pieces.current_settings
    monkeypatch.setattr(pieces, "current_settings", lambda: replace(real(), max_pieces=1))


def opening(w, h, ratio=125.0):
    return FabSetup(ratio, (38.0, 17.0, 11.0), {"name": None, "openingWidth": float(w),
                                                 "openingHeight": float(h), "lengthMax": None})


@functools.lru_cache(maxsize=None)
def intent_of(name):
    return SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES[name]])


@functools.lru_cache(maxsize=None)
def solved(name, holds=(), wh=None):
    """wh: a custom machine opening (width, height) in mm; None for the default machine."""
    return solve_surface(intent_of(name), Holds(holds), None, setup=opening(*wh) if wh else DEFAULT)


FLAT = Surface(GRID_N, GRID_N, [[-1500 + 150 * i, -1500 + 150 * j, 800.0] for i in range(21) for j in range(21)])
ARC = [(round(0.5 + 0.30 * math.cos(a), 6), round(0.2 + 0.30 * math.sin(a), 6))
       for a in [math.radians(30 + 120 * k / 40) for k in range(41)]]  # in-plane radius about 900 mm


@functools.lru_cache(maxsize=None)
def flat_arc(holds=()):
    return solve_surface(SurfaceIntent.build("M1", FLAT, ARC), Holds(holds), None, setup=DEFAULT)


# ---- their code, vendored unmodified, and their own tests ------------------------------------

def test_vendored_files_are_unmodified():
    notice = (ROOT / "vendor" / "sc_glulam" / "NOTICE.md").read_text(encoding="utf-8")
    for name in ("glulam_math.py", "test_glulam_math.py"):
        digest = hashlib.sha256((ROOT / "vendor" / "sc_glulam" / name).read_bytes()).hexdigest()
        assert digest in notice, name


def test_their_offline_tests_pass_against_the_vendored_copy():
    # -P: neither the cwd nor the script folder goes on sys.path implicitly; we add only vendor/.
    code = ("import sys, runpy; sys.path.insert(0, r'%s'); "
            "runpy.run_path(r'%s', run_name='__main__')" % (ROOT / "vendor" / "sc_glulam",
                                                          ROOT / "vendor" / "sc_glulam" / "test_glulam_math.py"))
    r = subprocess.run([sys.executable, "-P", "-E", "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    line = next(x for x in r.stdout.splitlines() if "checks passed" in x)
    passed, total = (int(v) for v in line.split("checks")[0].split("/"))
    assert passed == total and total >= 12, line
    assert "FAIL" not in r.stdout


def test_glulam_billet_is_never_imported():
    import re
    pattern = re.compile(r"^\s*(import\s+\S*glulam_billet|from\s+\S*glulam_billet\s+import)", re.MULTILINE)
    for path in list((ROOT / "gnj_nudge").glob("*.py")) + list((ROOT / "tests").glob("*.py")):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name
    assert not (ROOT / "vendor" / "sc_glulam" / "glulam_billet.py").exists()


# ---- the sample saddle on the default machine ---------------------------------------------

def test_x_axis_holds_at_rung_0_pressed_from_three_17_mm_layers():
    r = solved("x_axis")
    f = r.form
    assert (r.status, f.smoothing_passes, r.deviation_mm, f.n_lamellas, f.lamella_mm) == ("proposed", 0, 0, 3, 17.0)
    assert f.fit.mode == "arc" and f.check["bend"]["ok"] and f.check["machine"]["ok"]
    assert r.sentence == "Your line holds. Pressed in one curve from 3 layers, then milled to shape."
    d = r.as_dict()["form"]
    assert "n_strips" not in d and "strip_mm" not in d
    assert d["billet"]["mode"] == "arc" and d["billet"]["radius_mm"] == pytest.approx(3091, abs=5)
    assert d["checks"]["bend"]["limit"] == 125 and d["checks"]["waste_pct"] == pytest.approx(25.5, abs=0.5)
    assert len(d["billet"]["outline"]) == 2 and d["billet"]["outline"][0][0] == d["billet"]["outline"][0][-1]
    json.dumps(r.as_dict(), allow_nan=False)


def test_the_thickest_lam_fails_the_bend_and_a_thinner_one_passes():
    lad = Ladder(intent_of("x_axis"))
    fit = lad.fit(0, False)
    member = fb.member_volume_mm3(lad.get(0))
    thick = {t: fb.check_billet(fit, t, DEFAULT.machine, 125, member) for t in (38, 25, 19, 17)}
    assert not thick[38]["bend"]["ok"] and not thick[25]["bend"]["ok"] and thick[19]["bend"]["ok"]
    assert thick[25]["bend"]["ratio"] < 125 <= thick[19]["bend"]["ratio"]
    assert DEFAULT.lams == (38.0, 17.0, 11.0)  # spec v6: 2x stock as is, ripped in two, ripped in three
    assert evaluate(lad, 0, False, DEFAULT)[0]["lam_mm"] == 17


def test_the_diagonal_is_a_straight_billet_glued_from_the_thickest_layers():
    r = solved("diagonal")
    assert r.form.fit.mode == "straight" and r.form.lamella_mm == 38
    assert r.sentence == "Your line holds. Glued straight from 3 layers, then milled to shape."


def test_the_wiggle_is_milled_out_not_glued_both_ways():
    r = solved("sharp_wiggle")
    assert (r.status, r.form.smoothing_passes) == ("proposed", 0)
    assert "both ways" not in r.sentence and "strip" not in r.sentence


# ---- straightening: for the machine, for the bend; hold shape is then a conflict ------------------

def test_a_small_opening_straightens_the_line_until_the_billet_fits():
    setup = opening(1300, 150)
    r = solved("sharp_wiggle", (), (1300, 150))
    assert r.form.smoothing_passes > 0 and r.form.check["machine"]["ok"]
    assert r.sentence == f"Line straightened by {round(r.deviation_mm)} mm so the billet fits the machine."
    assert r.governing == ["machine"]
    lad = Ladder(intent_of("sharp_wiggle"))
    assert evaluate(lad, 0, False, setup)[0] is None  # nothing passes as drawn


def test_the_same_small_opening_with_hold_shape_is_a_machine_conflict():
    r = solved("sharp_wiggle", ("shape",), (1300, 150))
    assert r.status == "conflict" and r.sentence == "This billet will not fit through the machine."
    assert r.conflict == ("drawn line", "machine opening 1300 x 150 mm")  # v6: the user's own opening, shown


def test_a_tight_sideways_arc_straightens_so_the_layers_can_bend():
    r = flat_arc()
    assert r.form.smoothing_passes > 0 and r.form.check["bend"]["ok"]
    assert r.sentence.startswith(f"Line straightened by {round(r.deviation_mm)} mm so the layers can bend, ")
    assert r.sentence.endswith("layers, then milled.")
    assert r.governing == ["lam_ratio"]


def test_the_same_arc_with_hold_shape_is_a_bend_conflict():
    r = flat_arc(("shape",))
    assert r.status == "conflict" and r.sentence == "This bends too tightly for the thinnest layer."
    assert r.conflict == ("drawn line", "thinnest lamella 11 mm at R/t 125")


def test_straightened_rungs_reuse_the_drawn_lines_bending_plane(monkeypatch):
    # The speed fix (profile: 90 % of the time was fit_bending_plane, once per rung): one full plane
    # fit per solve, for the drawn line; every straightened rung reuses its plane (their bendPlane path).
    calls = []
    real = fb.gm.fit_bending_plane
    monkeypatch.setattr(fb.gm, "fit_bending_plane", lambda *a, **k: calls.append(1) or real(*a, **k))
    lad = Ladder(intent_of("sharp_wiggle"))
    r = solve_surface(intent_of("sharp_wiggle"), Holds(), None, ladder=lad, setup=opening(1300, 150))
    assert r.form.smoothing_passes > 0 and len(calls) == 1
    drawn = lad.fit(0, False)
    for (passes, straight), fit in lad._fits.items():
        if passes != 0 and not straight and fit is not None:
            assert np.allclose(fit.n, drawn.n)


def test_nothing_fits_a_tiny_opening_even_fully_straightened():
    r = solved("x_axis", (), (150, 80))
    assert r.status == "conflict" and r.sentence == "This billet will not fit through the machine."


# ---- hold solid: one straight piece, milled; or its conflict ---------------------------------------

def test_hold_solid_mills_from_one_straight_piece():
    r = solved("x_axis", ("solid",))
    f = r.form
    assert f.straight and f.fit.mode == "straight" and f.n_lamellas == 1
    assert not f.check["bend"]["applies"] and f.check["machine"]["ok"]
    assert r.sentence == "Your line holds. Milled from one straight piece, no bending."
    assert r.as_dict()["form"]["billet"]["radius_mm"] is None


def test_hold_solid_on_a_tiny_opening_is_its_own_conflict():
    r = solved("x_axis", ("solid",), (150, 80))
    assert r.status == "conflict"
    assert r.sentence == "This will not mill from one straight piece on this machine."


@pytest.mark.parametrize("name", ["x_axis", "diagonal", "sharp_wiggle", "long_x_trimmed"])
def test_every_answer_passes_both_checks_and_keeps_its_holds(name):
    for holds in ((), ("shape",), ("solid",)):
        r = solved(name, holds)
        if r.form:
            assert r.form.check["ok"]
            if "shape" in holds:
                assert r.form.smoothing_passes == 0
            if "solid" in holds:
                assert r.form.straight


# ---- boundaries: R/t exactly 125, opening exactly the need ---------------------------------------

def synthetic_arc_fit():
    """An arc billet whose inner lamella face sits at radius exactly 1000 with 8 mm lamellas:
    spine radius 1024 (a power of two keeps the arithmetic exact), part between radii 1000 and 1096."""
    spine = fb.gm.ArcSpine(np.array([0.0, 0.0]), 1024.0, 0.0, 0.6)
    angles = np.linspace(0.05, 0.55, 40)
    P2 = np.vstack([np.column_stack([r * np.cos(angles), r * np.sin(angles)]) for r in (1000.0, 1096.0)])
    W = np.concatenate([np.zeros(40), np.full(40, 89.0)])
    return fb.Fit("arc", np.zeros(3), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]), spine, P2, W)


def test_a_lamella_at_exactly_r_over_t_125_passes_and_a_hair_tighter_fails():
    fit = synthetic_arc_fit()
    big = {"name": "big", "openingWidth": 1e6, "openingHeight": 1e6}
    at = fb.check_billet(fit, 8.0, big, 125.0, 1.0)
    assert at["bend"]["tightest_radius_mm"] == 1000.0 and at["bend"]["ratio"] == 125.0
    assert at["bend"]["ok"]
    assert not fb.check_billet(fit, 8.0, big, 125.0 + 1e-9, 1.0)["bend"]["ok"]


def test_an_opening_exactly_the_need_fits_and_a_hundredth_less_does_not():
    lad = Ladder(intent_of("x_axis"))
    fit, member = lad.fit(0, False), fb.member_volume_mm3(lad.get(0))
    probe = fb.check_billet(fit, 19.0, {"name": "p", "openingWidth": 1e6, "openingHeight": 1e6}, 125, member)
    s = np.linspace(probe["ext"]["sLow"], probe["ext"]["sHigh"], fb.OUTLINE_SAMPLES)
    box = fb.gm.min_width_box(np.vstack([fit.spine.point(s, probe["ext"]["dLow"]), fit.spine.point(s, probe["ext"]["dHigh"])]))
    in_plane, width = box["width"], probe["ext"]["wHigh"] - probe["ext"]["wLow"]
    exact = {"name": "exact", "openingWidth": in_plane, "openingHeight": width}  # flat, margin exactly 0
    assert fb.check_billet(fit, 19.0, exact, 125, member)["machine"]["ok"]
    under = {"name": "under", "openingWidth": in_plane - 0.01, "openingHeight": width - 0.01}
    assert not fb.check_billet(fit, 19.0, under, 125, member)["machine"]["ok"]


# ---- the machine table never reaches the model: tests/test_privacy.py (every prompt, a named
# machine selected) and its scan of every tracked file (spec v6) ------------------------------


# ---- the model's part --------------------------------------------------------------------------

def mchoice(p=0, t=17, straight=False, sentence="Your line holds. Pressed in one curve, then milled."):
    return {"smoothing_passes": p, "lam_mm": t, "straight_billet": straight, "sentence": sentence,
            "steps": [{"tag": "Decision", "text": "Layers.", "limit_id": "lam_ratio"}]}


def test_a_matching_model_choice_is_built_and_used():
    r = nudge_surface(intent_of("x_axis"), Holds(), None, FakeClient([mchoice()]), setup=DEFAULT)
    assert r.source == "model" and r.form.lamella_mm == 17 and r.form.check["ok"]
    assert any(s["tag"] == "Decision" and "billet" in s["text"] for s in r.steps)  # the core's steps


@pytest.mark.parametrize("bad", [mchoice(t=25), mchoice(t=13), mchoice(p=7), mchoice(straight="yes"),
                                 mchoice(t=True), {**mchoice(), "lam_mm": None}])
def test_unbuildable_or_malformed_model_choices_end_in_the_solver(bad):
    fake = FakeClient([bad] * 3)
    r = nudge_surface(intent_of("x_axis"), Holds(), None, fake, setup=DEFAULT)
    assert r.source == "rules" and r.form.lamella_mm == 17 and len(fake.calls) == 3


def test_a_buildable_choice_further_than_the_solver_is_refused():
    setup = opening(1300, 150)
    base = solved("sharp_wiggle", (), (1300, 150))
    lad = Ladder(intent_of("sharp_wiggle"))
    assert lad.deviation(-1) > base.deviation_mm + 0.5
    far = mchoice(p=-1, t=17, sentence="Fully straightened, then milled.")
    fake = FakeClient([far] * 3)
    r = nudge_surface(intent_of("sharp_wiggle"), Holds(), None, fake, setup=setup)
    assert r.source == "rules" and r.form.smoothing_passes == base.form.smoothing_passes
    assert "Straighten less" in fake.calls[1]["messages"][-1]["content"]


def test_model_holds_are_enforced():
    fake = FakeClient([mchoice()] * 3)  # pressed, but solid is held
    r = nudge_surface(intent_of("x_axis"), Holds(["solid"]), None, fake, setup=DEFAULT)
    assert r.source == "rules" and r.form.straight
    ok = nudge_surface(intent_of("x_axis"), Holds(["solid"]), None, FakeClient([mchoice(straight=True)]),
                       setup=DEFAULT)
    assert ok.source == "model" and ok.form.straight


def test_the_schema_offers_the_ladder_and_the_lam_stock():
    fake = FakeClient([mchoice()])
    nudge_surface(intent_of("x_axis"), Holds(), None, fake, setup=DEFAULT)
    props = fake.calls[0]["output_config"]["format"]["schema"]["properties"]
    assert props["lam_mm"]["enum"] == [38.0, 17.0, 11.0]
    assert -1 in props["smoothing_passes"]["enum"] and props["straight_billet"]["type"] == "boolean"


# ---- record, taste, timing, and the bend kind without numpy ----------------------------------------

def test_the_formal_record_sentence_carries_the_route():
    i = intent_of("x_axis")
    r = solved("x_axis")
    f = make_entry("accepted", i, Holds(), r, CARDS)["formal"]
    for part in ("Pressed to a 3.09 m radius from 3 lamellas of 17 mm, then milled", "billet 2142 x 89 x 51 mm",
                 "R/t", "against 125", "fits", "part 0.0072 m3, waste 25.5% of the billet.", "Kx", "twist up to 0.0 degrees per metre, milled out",
                 "Governing limit: lamella bend radius / thickness; machine opening", "Deviation from intent 0 mm"):
        assert part in f, part
    assert "\u2014" not in f and "\u2013" not in f


def test_taste_does_not_lead_on_a_surface_but_a_solid_hold_still_works():
    # Daniel, 2026-11-14: a solid lead on a surface would offer an 82 % waste straight block unasked.
    led = agent.nudge(intent_of("x_axis"), Holds(), CARDS, None, lead="solid", because="You kept it solid.")
    assert led.taste is None and not led.form.straight
    assert led.sentence == "Your line holds. Pressed in one curve from 3 layers, then milled to shape."
    held = agent.nudge(intent_of("x_axis"), Holds(["solid"]), CARDS, None, lead="solid", because="You kept it solid.")
    assert held.taste is None and held.form.straight
    assert held.sentence == "Your line holds. Milled from one straight piece, no bending."


def test_surface_episodes_are_recorded_but_do_not_lead_the_bend_taste():
    from gnj_nudge import taste
    solid_surface = {"verdict": "accepted", "accepted_trade": "solid", "first_offer_trade": "makeup",
                     "kind": "surface_stroke"}
    solid_bend = dict(solid_surface, kind="bend")
    assert taste.lead([solid_surface] * 5)[0] == "makeup"
    assert taste.lead([solid_bend] * 3)[0] == "solid"
    assert taste.lead([{k: v for k, v in solid_bend.items() if k != "kind"}] * 3)[0] == "solid"  # older entries


def test_the_worst_case_fallback_stays_under_five_seconds():
    t = time.perf_counter()
    solve_surface(SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES["sharp_wiggle"]]), Holds(), None,
                  setup=opening(1300, 150))
    assert time.perf_counter() - t < 5.0


PROBE_QUIET_S = 0.28  # the probe below on this machine when quiet (measured 2026-11-14: 0.27 to 0.28 s)


def test_the_worst_case_costs_under_2_5_s_and_a_typical_answer_under_1_s_of_cpu():
    # Targets from the lead: worst under 2.5 s, typical well under 1 s, on this machine at its quiet
    # speed. CPU time alone is not enough: with several builders on the machine the whole CPU slows
    # about threefold for seconds at a time (2026-11-14: the same x-axis solve went 0.6 to 2.7 s of
    # thread time, and a pure-Python loop with no numpy slowed by the same factor at the same moment).
    # So each solve is timed beside a fixed pure-Python workload and scaled back to quiet speed; it is
    # only ever scaled down, never up, and a real slowdown in the solve still fails. Bounds unchanged.
    def probe():
        t = time.thread_time()
        sum(i * i for i in range(6_000_000))
        return time.thread_time() - t

    def cpu(stroke, setup):
        runs = []
        for _ in range(3):
            before = probe()
            t = time.thread_time()
            solve_surface(SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES[stroke]]), Holds(), None, setup=setup)
            spent = time.thread_time() - t
            slowdown = max(1.0, min(before, probe()) / PROBE_QUIET_S)
            runs.append(spent / slowdown)
        return min(runs)

    assert cpu("sharp_wiggle", opening(1300, 150)) < 2.5
    assert cpu("x_axis", DEFAULT) < 1.0


def test_the_bend_kind_works_without_numpy():
    code = ("import sys; sys.modules['numpy'] = None; sys.path.insert(0, r'%s');"
            "from gnj_nudge import server, agent; from gnj_nudge.intent import Intent, Holds;"
            "from gnj_nudge.limits import load_cards;"
            "r = agent.nudge(Intent('M1', 2400, 2450, 'up'), Holds(), load_cards(), None);"
            "print(r.form.n_lamellas, r.sentence)" % ROOT)
    out = subprocess.run([sys.executable, "-P", "-E", "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.startswith("4 Your curve holds.")
