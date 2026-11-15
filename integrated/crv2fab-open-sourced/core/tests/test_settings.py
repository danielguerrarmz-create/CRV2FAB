"""Spec v6, section 2: settings the user sets, and sees. GET /settings, POST /settings (partial),
kept for the session and written into every record entry. The waste target is a check like any
other once the user sets it; it never moves the designer's line."""
import json
import threading
from types import SimpleNamespace

import pytest

from conftest import FakeClient, intent
from gnj_nudge import agent
from gnj_nudge import settings as gs
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.server import make_server
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.surface_solver import FabSetup
from gnj_nudge.vectors_v4 import CASES
from test_hardening import raw

CARDS = load_cards()
SURF = Surface(GRID_N, GRID_N, saddle()["points"])
X_AXIS = dict((n, s) for n, s, _ in CASES)["x_axis"]
SURFACE = {"kind": "surface_stroke", "member_id": "M1", "surface": saddle(), "stroke_uv": X_AXIS}
STAND_IN = {"machines": [{"name": "Stand-in Mill KX-9", "openingWidth": 1234.0, "openingHeight": 321.0,
                          "lengthMax": 17777.0, "source": "stand-in", "note": ""}]}


def x_axis(holds=(), **setting):
    i = SurfaceIntent.build("M1", SURF, [tuple(q) for q in X_AXIS])
    return agent.nudge(i, Holds(holds), CARDS, None, settings=dict(gs.DEFAULTS, **setting))


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.delenv("GNJ_SAY", raising=False)
    made = []

    def start():
        srv = make_server("127.0.0.1", 0, cards=CARDS, client=FakeClient([]),
                          record_path=tmp_path / f"r{len(made)}.jsonl")
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        made.append(srv)
        return SimpleNamespace(port=srv.server_address[1])

    yield start
    for srv in made:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def no_private(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "PRIVATE_MACHINES", tmp_path / "absent.json")


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    path = tmp_path / "machines.json"
    path.write_text(json.dumps(STAND_IN), encoding="utf-8")
    monkeypatch.setattr(gs, "PRIVATE_MACHINES", path)


# ---- the defaults carry no company data ----------------------------------------------------------

def test_the_defaults_are_the_spec_table():
    assert gs.DEFAULTS == {"lam_options_mm": [38.0, 17.0, 11.0], "lam_ratio": 125.0, "allowance_mm": 0.0,
                           "max_waste_pct": None, "opening_mm": [1200.0, 280.0], "max_length_mm": 18000.0,
                           "max_pieces": 4, "machine": None, "thickness_mm": 38.0}
    setup = FabSetup.default()
    assert (setup.lams, setup.ratio, setup.allowance, setup.max_waste_pct) == ((38.0, 17.0, 11.0), 125.0, 0.0, None)
    assert setup.machine == {"name": None, "openingWidth": 1200.0, "openingHeight": 280.0, "lengthMax": 18000.0}


# ---- round trip, validation, and the record ------------------------------------------------------

def test_settings_round_trip_as_a_partial_update(server, no_private):
    s = server()
    status, out, _ = raw(s, "GET", "/settings")
    assert status == 200 and out["settings"] == gs.DEFAULTS and out["machines"] == []
    status, out, _ = raw(s, "POST", "/settings", {"max_waste_pct": 40, "allowance_mm": 2})
    assert status == 200 and out["settings"]["max_waste_pct"] == 40.0 and out["settings"]["allowance_mm"] == 2.0
    assert out["settings"]["lam_options_mm"] == [38.0, 17.0, 11.0]  # untouched by a partial update
    assert raw(s, "GET", "/settings")[1]["settings"] == out["settings"]
    status, out, _ = raw(s, "POST", "/settings", {"max_waste_pct": None})  # the target can be turned off again
    assert status == 200 and out["settings"]["max_waste_pct"] is None


@pytest.mark.parametrize("bad", [{"lam_ratio": "big"}, {"lam_ratio": 0}, {"allowance_mm": -1},
                                 {"max_waste_pct": 101}, {"opening_mm": [1200]}, {"opening_mm": [1200, True]},
                                 {"lam_options_mm": []}, {"lam_options_mm": [38, "x"]}, {"max_pieces": 2.5},
                                 {"machine": "Nope"}, {"colour": "blue"}, [1, 2]])
def test_bad_settings_are_refused_and_change_nothing(server, no_private, bad):
    s = server()
    status, out, _ = raw(s, "POST", "/settings", bad)
    assert status == 400 and "error" in out
    assert raw(s, "GET", "/settings")[1]["settings"] == gs.DEFAULTS


def test_layer_options_are_kept_thickest_first_without_duplicates():
    assert gs.validate({"lam_options_mm": [11, 38, 17, 17]})["lam_options_mm"] == [38.0, 17.0, 11.0]


def test_the_settings_go_into_the_record_entry(server, no_private):
    s = server()
    raw(s, "POST", "/settings", {"max_waste_pct": 70})
    raw(s, "POST", "/nudge", {"intent": {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 0}, "holds": []})
    status, entry, _ = raw(s, "POST", "/judge", {"verdict": "accepted"})
    assert status == 200 and entry["settings"]["max_waste_pct"] == 70.0
    assert raw(s, "GET", "/record")[1]["entries"][-1]["settings"] == entry["settings"]


def test_a_settings_change_after_the_nudge_does_not_rewrite_that_decision(server, no_private):
    # The record keeps the settings the decision was solved with, not the ones set afterwards.
    s = server()
    raw(s, "POST", "/nudge", {"intent": {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 0}, "holds": []})
    raw(s, "POST", "/settings", {"max_waste_pct": 5})
    entry = raw(s, "POST", "/judge", {"verdict": "accepted"})[1]
    assert entry["settings"]["max_waste_pct"] is None


# ---- machines: the user's opening shown plainly; a private machine only where its file is ---------

def test_without_the_private_file_no_machine_is_offered(server, no_private):
    assert raw(server(), "GET", "/settings")[1]["machines"] == []


def test_a_private_machine_is_offered_by_name_and_selected(server, stand_in):
    s = server()
    out = raw(s, "GET", "/settings")[1]
    assert out["machines"] == [{"name": "Stand-in Mill KX-9", "opening_mm": [1234.0, 321.0]}]
    out = raw(s, "POST", "/settings", {"machine": "Stand-in Mill KX-9"})[1]
    assert out["settings"]["machine"] == "Stand-in Mill KX-9"
    assert gs.machine_of(out["settings"]) == {"name": "Stand-in Mill KX-9", "openingWidth": 1234.0,
                                              "openingHeight": 321.0, "lengthMax": 17777.0}
    out = raw(s, "POST", "/settings", {"opening_mm": [1000, 200]})[1]  # a typed opening replaces the machine
    assert out["settings"]["machine"] is None and gs.machine_of(out["settings"])["openingWidth"] == 1000.0


@pytest.mark.slow
def test_the_opening_setting_reaches_the_solver_and_is_shown_plainly():
    r = x_axis()
    assert r.form.checks()["machine"]["opening_mm"] == [1200.0, 280.0]
    assert any("the opening is 1200 x 280 mm, so it fits" in s["text"] for s in r.steps)
    tiny = x_axis(opening_mm=[150.0, 80.0], max_pieces=1)  # one billet: pieces would fit it (spec v6 section 4)
    assert tiny.status == "conflict" and tiny.conflict[1] == "machine opening 150 x 80 mm"


@pytest.mark.slow
def test_a_setting_posted_to_the_server_reaches_the_next_nudge(server, no_private):
    s = server()
    assert raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})[1]["form"]["lamella_mm"] == 17.0
    raw(s, "POST", "/settings", {"lam_options_mm": [19]})
    assert raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})[1]["form"]["lamella_mm"] == 19.0
    raw(s, "POST", "/settings", {"opening_mm": [150, 80]})
    out = raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})[1]
    assert out["status"] == "proposed" and out["form"]["n_pieces"] > 1  # pieces before straightening
    raw(s, "POST", "/settings", {"max_pieces": 1})
    out = raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})[1]
    assert out["status"] == "conflict" and out["conflict"] == ["drawn line", "machine opening 150 x 80 mm"]


@pytest.mark.slow
def test_a_selected_private_machine_is_named_in_the_why_steps(stand_in):
    r = x_axis(machine="Stand-in Mill KX-9")
    assert any("the Stand-in Mill KX-9 takes 1234 x 321 mm" in s["text"] for s in r.steps)


# ---- layer options, ratio and allowance reach their functions -------------------------------------

@pytest.mark.slow
def test_the_layer_options_and_ratio_are_the_users():
    assert (x_axis().form.n_lamellas, x_axis().form.lamella_mm) == (3, 17.0)
    only_19 = x_axis(lam_options_mm=[19.0])
    assert (only_19.form.n_lamellas, only_19.form.lamella_mm) == (3, 19.0)
    loose = x_axis(lam_ratio=60.0)  # a looser bend limit lets the 38 mm stock bend as is
    assert loose.form.lamella_mm == 38.0


@pytest.mark.slow
def test_the_allowance_is_passed_to_their_billet_fit():
    plain, allowed = x_axis().form.billet(False), x_axis(allowance_mm=5.0).form.billet(False)
    assert allowed["width_mm"] == pytest.approx(plain["width_mm"] + 10, abs=0.2)  # 5 mm per face
    assert allowed["length_mm"] == pytest.approx(plain["length_mm"] + 10, abs=0.2)
    assert allowed["volume_m3"] > plain["volume_m3"]


def test_the_allowance_is_passed_to_their_fit_functions_too(monkeypatch):
    # Their fit_bending_plane and fit_arc_2d take the allowance as well as billet_extents; the width
    # test above only sees the extents, so spy on the fits.
    from gnj_nudge import fabrication as fb
    from gnj_nudge.surface_solver import Ladder
    seen = []
    for name in ("fit_arc_billet", "fit_arc_billet_in_plane", "fit_straight_billet"):
        real = getattr(fb, name)
        monkeypatch.setattr(fb, name, lambda *a, _real=real, _n=name, **k: seen.append((_n, a, k)) or _real(*a, **k))
    lad = Ladder(SurfaceIntent.build("M1", SURF, [tuple(q) for q in X_AXIS]))
    lad.allowance = 3.0
    lad.fit(0, False), lad.fit(5, False), lad.fit(0, True)
    assert [n for n, _, _ in seen] == ["fit_arc_billet", "fit_arc_billet_in_plane", "fit_straight_billet"]
    assert all(any(isinstance(x, float) and x == 3.0 for x in a) for _, a, _ in seen)


def test_the_allowance_reaches_the_bend_waste():
    plain = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=gs.DEFAULTS)
    allowed = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=dict(gs.DEFAULTS, allowance_mm=5.0))
    assert allowed.waste["width_mm"] == pytest.approx(plain.waste["width_mm"] + 10, abs=0.2)
    assert allowed.waste["waste_pct"] > plain.waste["waste_pct"]


# ---- the waste target -----------------------------------------------------------------------------

@pytest.mark.slow
def test_a_target_met_as_proposed_changes_nothing():
    plain, met = x_axis(), x_axis(max_waste_pct=30)
    assert (met.form.lamella_mm, met.sentence, met.steps) == (plain.form.lamella_mm, plain.sentence, plain.steps)


@pytest.mark.slow
def test_a_target_met_by_a_thinner_layer_takes_it_and_says_why():
    r = x_axis(max_waste_pct=20)
    assert (r.form.n_lamellas, r.form.lamella_mm, round(r.form.check["waste_pct"], 1)) == (4, 11.0, 13.7)
    assert r.sentence == "Your line holds. Pressed in one curve from 4 layers, then milled to shape."
    assert r.steps[-1] == {"tag": "Decision", "limit_id": "max_waste_pct", "text": (
        "Your waste target is 20%: 17 mm layers would waste 26%, so 11 mm layers, wasting 14%.")}


@pytest.mark.slow
def test_an_unreachable_target_shows_the_ghost_with_the_over_target_sentence_and_the_best_reachable():
    r = x_axis(max_waste_pct=10)
    assert r.status == "proposed" and r.form is not None  # no ghost is withheld
    assert r.form.lamella_mm == 17.0
    assert r.sentence.endswith("Waste 26%, over your 10% target.")
    assert r.steps[-1]["text"] == ("Waste 26% is over your 10% target; the best reachable without moving your "
                                   "line: 11 mm layers would reach 14%.")


@pytest.mark.slow
def test_the_target_never_moves_the_line():
    for target in (30, 20, 10, 0):
        r = x_axis(max_waste_pct=target)
        assert r.form.smoothing_passes == 0 and r.deviation_mm == 0


@pytest.mark.slow
def test_a_solid_hold_over_the_target_says_there_is_no_thinner_layer():
    r = x_axis(("solid",), max_waste_pct=10)
    assert r.form.straight and r.sentence.endswith("over your 10% target.")
    assert "no thinner layer to try" in r.steps[-1]["text"]


def test_a_bend_target_met_by_another_make_up_at_the_same_radius():
    plain = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=gs.DEFAULTS)
    r = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=dict(gs.DEFAULTS, max_waste_pct=61))
    assert round(plain.waste["waste_pct"], 1) == 62.8 and round(r.waste["waste_pct"], 1) == 60.4
    assert (r.form.n_lamellas, r.form.n_strips) == (4, 6) and r.form.radius_mm == plain.form.radius_mm
    assert agent.check(r.form, CARDS).passed and r.deviation_mm == plain.deviation_mm
    assert r.steps[-1]["text"] == "Your waste target is 61%: the usual make-up would waste 63%, this one 60%."


def test_a_bend_target_out_of_reach_says_so():
    r = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=dict(gs.DEFAULTS, max_waste_pct=10))
    assert r.status == "proposed" and r.sentence.endswith("Waste 63%, over your 10% target.")
    assert r.steps[-1]["text"].endswith("other layer and strip counts would reach 60%.")


def test_with_no_target_nothing_is_done_about_waste():
    a = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None)
    b = agent.nudge(intent(2450, angle=45), Holds(), CARDS, None, settings=gs.DEFAULTS)
    assert (a.form, a.sentence, a.steps) == (b.form, b.sentence, b.steps)
    assert "target" not in a.sentence
