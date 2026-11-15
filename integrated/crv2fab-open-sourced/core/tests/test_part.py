"""Spec v6 section 3: intent kind `part`, the designer's own geometry (gnj_nudge/part.py).

Fitted and checked with the technical member's logic (vendor/sc_glulam, through fabrication.py),
never altered. The agent may change only the layer option and the number of pieces.
"""
import functools
import json
import math
import threading
import time
import urllib.request
from dataclasses import replace

import numpy as np
import pytest

from gnj_nudge import fabrication as fb
from gnj_nudge import pieces as pc
from gnj_nudge import vectors_part as vp
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.part import NEVER_MOVED, PartIntent, solve_part
from gnj_nudge.record import make_entry

pytestmark = pytest.mark.slow  # every test here is a billet fit or several
CARDS = load_cards()
V6 = vp.v6_settings()
BIG = (2500.0, 450.0)  # an opening every test part fits through in one billet


@pytest.fixture(scope="module", autouse=True)
def pool():
    pc.enable_pool()
    yield
    pc.enable_pool(False)


@functools.lru_cache(maxsize=None)
def part(name, **kw):
    pts, vol = getattr(vp, name)(**dict(kw))
    return PartIntent.build("P1", pts, vol)


@functools.lru_cache(maxsize=None)
def solved(name, holds=(), opening=vp.V6_OPENING, target=None):
    return solve_part(part(name), frozenset(holds), vp.v6_settings(opening), max_waste_pct=target)  # less_waste: not a Holds name yet


# ---- the analyzer drop's reference, through the seam ---------------------------------------------------

def test_the_analyzer_drops_reference_arc_beam(monkeypatch):
    """R 6000, 400 deep, 200 wide, 60 degrees, 40 mm layers (incoming/dalalaaryan/tests/test_core.js).
    The 40 mm layer goes in through the seam, pieces.current_settings, as the integrator will."""
    real = pc.current_settings
    monkeypatch.setattr(pc, "current_settings", lambda: replace(real(), lams=(40.0,)))
    pts, vol = vp.arc_beam()
    r = solve_part(PartIntent.build("REF", pts, vol), Holds())
    assert r.status == "proposed" and r.form.n_pieces == 1
    piece = r.form.as_dict()["pieces"][0]
    assert abs(piece["billet"]["radius_mm"] - 6000) <= 5
    assert piece["billet"]["depth_mm"] == pytest.approx(400, abs=0.5)
    assert piece["billet"]["width_mm"] == pytest.approx(200, abs=0.5)
    assert piece["n_lamellas"] == 10 and piece["lamella_mm"] == 40
    assert r.sentence == "Buildable as modelled. Pressed in one curve from 10 layers, then milled to shape."


# ---- never altered --------------------------------------------------------------------------------------

def _inside(fit, chk, points, tol=1e-6):
    P2, W = fb.gm.project_to_frame(np.asarray(points, float), fit.origin, fit.u, fit.v, fit.n)
    s, d = fit.spine.project(P2)
    e = chk["ext"]
    return bool((s >= e["sLow"] - tol).all() and (s <= e["sHigh"] + tol).all() and (d >= e["dLow"] - tol).all()
                and (d <= e["dHigh"] + tol).all() and (W >= e["wLow"] - tol).all() and (W <= e["wHigh"] + tol).all())


def test_the_geometry_is_never_altered():
    pts, vol = vp.doubly_curved()
    intent = PartIntent.build("P1", pts, vol)
    given = [list(p) for p in intent.points]
    r = solve_part(intent, Holds(), V6)
    assert r.form.n_pieces == 2  # the split path, where geometry is handled the most
    assert [list(p) for p in intent.points] == given  # the request is untouched
    member = r.form.member
    assert np.array_equal(member.P_all, np.array(given))  # the fit read exactly the points sent
    covered = np.zeros(len(given), bool)
    for piece, chk in zip(r.plan.count.pieces, r.plan.checks):
        mine = {tuple(q) for q in member.points(2, piece.index).tolist()}
        mask = np.array([tuple(p) in mine for p in given])
        covered |= mask
        assert _inside(piece.fit, chk, np.array(given)[mask])  # every sent point inside its own billet
    assert covered.all()  # and every point belongs to some piece
    one = solve_part(PartIntent.build("P1", pts, vol), Holds(), vp.v6_settings(BIG))  # the one-billet path
    assert one.form.n_pieces == 1 and _inside(one.plan.count.pieces[0].fit, one.plan.checks[0], np.array(given))
    d = r.as_dict()
    assert d["deviation_mm"] == 0.0 and r.deviation_mm == 0.0
    assert not {"points", "stations", "normals"} & set(d["form"])  # no ghost of a changed shape


def test_hold_shape_is_ignored_with_the_reply():
    plain, held = solved("arc_beam"), solved("arc_beam", ("shape",))
    assert held.sentence == plain.sentence and held.form.check == plain.form.check
    assert {"tag": "Heard", "text": NEVER_MOVED, "limit_id": None} in held.steps


# ---- the three outcomes ---------------------------------------------------------------------------------

def test_a_doubly_curved_part_that_needs_two_pieces_to_fit_the_opening():
    r = solved("doubly_curved")
    one = r.plan.counts[1]
    assert one.reason() == "machine"  # one billet is too big for 1200 x 280
    assert r.status == "proposed" and r.form.n_pieces == 2 and r.plan.split_reason == "machine"
    assert all(c["machine"]["ok"] and c["bend"]["ok"] for c in r.plan.checks)
    assert r.sentence == "Buildable as modelled, in 2 pieces joined end to end. Each pressed from layers, then milled."
    d = r.form.as_dict()
    assert len(d["cuts"]) == 1 and d["cuts"][0]["note"] == "joint to be designed by the engineer"
    assert d["cuts"][0]["at_mm"] == pytest.approx(d["axis"]["length_mm"] / 2, abs=0.2)
    assert len(d["cuts"][0]["line"]) == 2 and len(d["billet"]["outline"]) == 4
    assert [s for s in r.steps if s["tag"] == "Joint"]


def test_a_part_too_tight_for_11_mm_layers_is_a_finding_not_a_ghost():
    r = solved("tight_arc")
    assert r.status == "conflict" and r.form is None and r.as_dict()["form"] is None
    assert r.sentence == "This part bends too tightly for the thinnest layer."
    assert r.conflict == ("your part", "thinnest layer 11 mm at R/t 125")
    assert any("Its tightest layer bends to" in s["text"] and "11 mm" in s["text"] for s in r.steps)
    assert r.plan.P == 1 and r.plan.fits_run == 1  # a bend failure is not a reason to cut


def test_a_part_too_big_even_in_four_pieces_names_the_pieces():
    r = solved("arc_beam", (), (1200.0, 150.0))  # 200 wide: no orientation fits
    assert r.status == "conflict" and r.form is None
    assert r.sentence == "This part will not fit through the machine, even in 4 pieces."
    assert any("too large by" in s["text"] for s in r.steps)


def test_hold_solid_is_one_straight_piece():
    ok = solved("straight_beam", ("solid",))
    assert ok.sentence == "Buildable as modelled. Milled from one straight piece, no bending."
    assert ok.form.solid and ok.form.n_pieces == 1
    no = solved("doubly_curved", ("solid",))
    assert no.status == "conflict" and no.sentence == "This part will not mill from one straight piece on this machine."
    assert no.plan.P == 1  # one piece is one piece: never cut


# ---- split only when allowed; less waste when asked -------------------------------------------------------

def test_a_part_that_fits_is_not_split_to_save_waste():
    pts, vol = vp.doubly_curved()
    r = solve_part(PartIntent.build("P1", pts, vol), Holds(), vp.v6_settings(BIG))  # fresh: nothing cached
    assert r.form.n_pieces == 1 and r.plan.fits_run == 1 and set(r.plan.counts) == {1}  # pieces never fitted


def test_pieces_waste_less_than_one_billet_on_a_twisting_member():
    one = solved("doubly_curved", (), BIG)
    many = solved("doubly_curved", ("split_ok", "less_waste"), BIG)
    assert many.form.n_pieces > 1
    assert many.form.check["waste_pct"] < one.form.check["waste_pct"] - 10


def test_split_ok_alone_keeps_the_fewest_pieces():
    assert solved("doubly_curved", ("split_ok",), BIG).form.n_pieces == 1


def test_the_part_total_is_volume_weighted():
    intent = part("doubly_curved", length=6000.0, drift=180.0)  # three pieces of unequal waste
    r = solve_part(intent, Holds(), V6)
    checks = r.plan.checks
    assert r.form.n_pieces == 3
    billet = sum(c["billet_mm3"] for c in checks)
    assert r.form.check["part_mm3"] == pytest.approx(intent.volume_mm3)
    assert r.form.check["waste_pct"] == pytest.approx(100 * (billet - intent.volume_mm3) / billet)
    mean = sum(c["waste_pct"] for c in checks) / len(checks)
    assert abs(r.form.check["waste_pct"] - mean) > 0.2  # the pieces differ, so a plain mean is wrong


# ---- the waste target, passed in directly ------------------------------------------------------------------

def test_waste_target_met_only_by_splitting():
    one = solved("doubly_curved", (), BIG).form.check["waste_pct"]
    r = solved("doubly_curved", (), BIG, target=round(one - 8))
    assert r.form.n_pieces > 1 and r.plan.split_reason == "waste" and not r.plan.over_target
    assert r.form.check["waste_pct"] <= round(one - 8)
    assert not r.sentence.endswith("target.")


def test_an_unreachable_waste_target_still_shows_the_part():
    r = solved("doubly_curved", (), BIG, target=1.0)
    assert r.status == "proposed" and r.form.n_pieces == 1  # no ghost withheld: the fewest pieces
    assert r.sentence.endswith(f"Waste {r.form.check['waste_pct']:.0f}%, over your 1% target.")
    best = [s for s in r.steps if s["limit_id"] == "max_waste_pct"][0]["text"]
    assert best.startswith("Your waste target is 1%. ") and "pieces would reach" in best
    assert r.deviation_mm == 0.0


def test_waste_target_met_by_a_thinner_layer_on_a_straight_part():
    thick = solved("straight_beam")
    assert thick.plan.checks[0]["lam_mm"] == 38  # 6 x 38 = 228 for a 200 deep part
    r = solved("straight_beam", (), target=5.0)
    assert r.form.n_pieces == 1 and r.plan.checks[0]["lam_mm"] < 38 and r.form.check["waste_pct"] <= 5.0


# ---- the record, the server, the cache, the clock ---------------------------------------------------------

def test_the_record_keeps_joints_and_volumes_for_a_part():
    r = solved("doubly_curved")
    e = make_entry("accepted", part("doubly_curved"), Holds(), r, CARDS)
    assert e["kind"] == "part" and e["intent"]["points"] == len(part("doubly_curved").points)
    assert e["joints"][0]["note"] == "joint to be designed by the engineer"
    assert "Geometry not altered" in e["formal"] and "joint to be designed by the engineer" in e["formal"]
    assert e["waste_pct"] == round(r.form.check["waste_pct"], 1) and e["deviation_mm"] == 0.0
    assert "outline" not in e["form"]["billet"] and e["form"]["kind"] == "part_plan"


def test_asking_again_about_the_same_part_refits_nothing():
    intent = part("doubly_curved", drift=110.0)
    first = solve_part(intent, Holds(), V6)
    again = solve_part(intent, Holds(("shape",)), V6)
    assert first.plan.fits_run > 1 and again.plan.fits_run == 0
    assert again.form.check == first.form.check


@pytest.mark.parametrize("bad, words", [
    ({"points": [[0, 0, 0]] * 10, "volume_mm3": 1}, "300 to 6000"),
    ({"volume_mm3": -1}, "positive"),
    ({"volume_mm3": float("inf")}, "positive"),
    ({"volume_mm3": 1e15}, "larger than the box"),
    ({"points": [[i, 0, 0] for i in range(400)], "volume_mm3": 1}, "flat or a line"),
])
def test_bad_part_requests_are_refused(bad, words):
    pts, vol = vp.straight_beam()
    req = {"kind": "part", "member_id": "P1", "points": pts, "volume_mm3": vol} | bad
    with pytest.raises(ValueError, match=words):
        PartIntent.from_dict(req)


def _post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def test_server_part_nudge_then_split_ok_by_words_then_judge(tmp_path, monkeypatch):
    from gnj_nudge.server import make_server
    monkeypatch.setenv("GNJ_SAY", "keywords")
    monkeypatch.setattr(pc, "current_settings", lambda: V6)
    srv = make_server("127.0.0.1", 0, client=None, record_path=tmp_path / "r.jsonl")
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        pts, vol = vp.v_part()
        r = _post(port, "/nudge", {"intent": {"kind": "part", "member_id": "V1", "points": pts, "volume_mm3": vol}})
        assert r["status"] == "conflict" and r["sentence"] == "This part bends too tightly for the thinnest layer."
        s = _post(port, "/say", {"text": "split it, joints are fine"})
        assert s["actions"] == [{"op": "hold", "name": "split_ok"}]
        n = s["nudge"]
        assert n["status"] == "proposed" and n["form"]["kind"] == "part_plan" and n["form"]["n_pieces"] == 2
        assert n["sentence"].startswith("Buildable as modelled, in 2 pieces")
        shape = _post(port, "/say", {"text": "keep my shape"})
        assert shape["heard"] == NEVER_MOVED and shape["nudge"]["form"]["n_pieces"] == 2
        j = _post(port, "/judge", {"verdict": "accepted"})
        assert j["kind"] == "part" and j["joints"] and j["holds_active"] == ["shape", "split_ok"]
        assert j["tally"]["members"] == 1 and j["tally"]["waste_pct"] == pytest.approx(j["waste_pct"], abs=0.15)
    finally:
        srv.shutdown()
        srv.server_close()


def test_timings_typical_and_worst():
    """Measured and printed for the report. Fresh intents, so nothing is cached; workers warm."""
    pc.warm_pool()
    rows = []
    for name, settings, holds in (("arc_beam", V6, ()), ("straight_beam", V6, ()),
                                  ("doubly_curved", V6, ()), ("doubly_curved", vp.v6_settings(BIG), ("split_ok", "less_waste")),
                                  ("arc_beam", vp.v6_settings((1200.0, 150.0)), ())):
        pts, vol = getattr(vp, name)()
        t0 = time.perf_counter()
        r = solve_part(PartIntent.build("T", pts, vol), frozenset(holds), settings)
        rows.append((name, holds, len(pts), r.plan.P, r.plan.fits_run, time.perf_counter() - t0))
    print()
    for row in rows:
        print("part timing: %-14s %-26s %5d points, %d pieces, %2d fits, %.2f s" % row)
    assert max(r[-1] for r in rows) < 10.0


def test_vectors_file_matches_the_code():
    """tests/vectors_part.json is what the Rhino client checks against. Regenerate with
    python -m gnj_nudge.vectors_part after any intended change."""
    on_disk = json.loads(vp.PATH.read_text(encoding="utf-8"))
    assert on_disk == json.loads(vp.dumps(vp.build()))
    assert 4 <= len(on_disk["cases"]) <= 6
    assert all(len(c["request"]["intent"]["points"]) <= 1000 for c in on_disk["cases"])
