"""less_waste (spec v5, Daniel 2026-11-14): "It directs intent. It is not a material optimisation
system, it simply reports the material waste to the user. However, through chat, the user can ask
for material optimisation." Never by itself, never moves the line, only through /say."""
import functools
import threading
from types import SimpleNamespace

import pytest

from conftest import FakeClient, intent
from gnj_nudge import agent, say
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.server import make_server
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.vectors_v4 import CASES
from test_hardening import raw

pytestmark = pytest.mark.slow  # billet fits

CARDS = load_cards()
SURF = Surface(GRID_N, GRID_N, saddle()["points"])
X_AXIS = dict((n, s) for n, s, _ in CASES)["x_axis"]


@functools.lru_cache(maxsize=None)
def x_axis(holds=()):
    i = SurfaceIntent.build("M1", SURF, [tuple(q) for q in X_AXIS])
    return agent.nudge(i, Holds(holds), CARDS, None)


def test_the_default_does_not_optimise_material():
    r = x_axis()
    assert (r.form.n_lamellas, r.form.lamella_mm, round(r.form.check["waste_pct"], 1)) == (3, 17.0, 25.5)
    assert r.less_waste is None and "less_waste" not in r.as_dict()


def test_asked_for_less_waste_the_saddle_line_takes_the_least_waste_passing_thickness():
    r = x_axis(("less_waste",))
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 11.0)
    assert round(r.form.check["waste_pct"], 1) == 13.7
    assert r.less_waste == {"from_pct": 25.5, "to_pct": 13.7, "saved": True}
    assert r.form.check["ok"]
    assert "You asked for less waste" in r.steps[-1]["text"]


def test_less_waste_never_moves_the_line():
    a, b = x_axis(), x_axis(("less_waste",))
    assert a.form.curve.pts == b.form.curve.pts and a.form.smoothing_passes == b.form.smoothing_passes == 0
    assert a.deviation_mm == b.deviation_mm == 0


def test_less_waste_with_solid_keeps_the_straight_piece_and_says_nothing_can_be_saved():
    r = x_axis(("less_waste", "solid"))
    assert r.form.straight and r.less_waste["saved"] is False
    assert r.less_waste["from_pct"] == r.less_waste["to_pct"] == round(x_axis(("solid",)).form.check["waste_pct"], 1)


def test_less_waste_with_shape_keeps_the_line_and_still_saves():
    r = x_axis(("less_waste", "shape"))
    assert r.form.smoothing_passes == 0 and (r.form.n_lamellas, r.form.lamella_mm) == (4, 11.0)


def test_on_the_2450_mm_bend_there_is_nothing_to_save():
    i = intent(2450)
    plain = agent.nudge(i, Holds(), CARDS, None)
    lw = agent.nudge(i, Holds(["less_waste"]), CARDS, None)
    assert lw.less_waste == {"from_pct": 0.0, "to_pct": 0.0, "saved": False}
    assert (lw.form.n_lamellas, lw.form.n_strips) == (plain.form.n_lamellas, plain.form.n_strips) == (4, 1)
    assert "already the least waste" in lw.steps[-1]["text"]


def test_a_diagonal_bend_can_save_some_and_keeps_its_radius():
    i = intent(2450, angle=45)
    plain = agent.nudge(i, Holds(), CARDS, None)
    lw = agent.nudge(i, Holds(["less_waste"]), CARDS, None)
    assert lw.less_waste["saved"] and lw.less_waste["to_pct"] < lw.less_waste["from_pct"]
    assert lw.form.radius_mm == plain.form.radius_mm and lw.deviation_mm == plain.deviation_mm
    assert agent.check(lw.form, CARDS).passed


# ---- only through /say ---------------------------------------------------------------------

@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.delenv("GNJ_SAY", raising=False)
    made = []

    def start(replies):
        fake = FakeClient(replies)
        srv = make_server("127.0.0.1", 0, cards=CARDS, client=fake, record_path=tmp_path / f"r{len(made)}.jsonl")
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        made.append(srv)
        return SimpleNamespace(port=srv.server_address[1])

    yield start
    for srv in made:
        srv.shutdown()
        srv.server_close()


LW = {"actions": [{"op": "hold", "name": "less_waste"}], "confident": True}
SURFACE = {"kind": "surface_stroke", "member_id": "M1", "surface": saddle(), "stroke_uv": X_AXIS}
BEND = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 0}


def test_saying_it_on_a_surface_saves_and_says_so(server):
    s = server([LW])
    raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})
    out = raw(s, "POST", "/say", {"text": "can you use less wood"})[1]
    assert out["actions"] == [{"op": "hold", "name": "less_waste"}]
    assert out["heard"] == "Using thinner layers to waste less."
    assert out["nudge"]["form"]["lamella_mm"] == 11.0 and out["nudge"]["less_waste"]["saved"]


def test_saying_it_on_the_bend_says_nothing_can_be_saved(server):
    s = server([LW])
    raw(s, "POST", "/nudge", {"intent": BEND, "holds": []})
    out = raw(s, "POST", "/say", {"text": "optimise the material"})[1]
    assert out["heard"] == "Already as little waste as this curve allows."  # a bend: the designer drew a curve


def test_it_clears_on_accept_and_the_record_keeps_the_words(server):
    s = server([LW])
    raw(s, "POST", "/nudge", {"intent": SURFACE, "holds": []})
    raw(s, "POST", "/say", {"text": "that's a lot of waste"})
    raw(s, "POST", "/judge", {"verdict": "accepted"})
    assert raw(s, "POST", "/say", {"text": "less waste"})[0] == 409  # a new decision starts from a new /nudge
    declined, accepted = raw(s, "GET", "/record")[1]["entries"]
    assert declined["holds_added"] == ["less_waste"] and declined["said"] == "that's a lot of waste"
    assert declined["formal"].endswith("Designer holds: less waste.")
    assert accepted["form"]["lamella_mm"] == 11.0


def test_the_schema_and_the_list_carry_it():
    assert "less_waste" in say.schema()["properties"]["actions"]["items"]["properties"]["name"]["enum"]
    assert ("hold", "less_waste") in say.ACTIONS and ("release", "less_waste") in say.ACTIONS


@pytest.mark.parametrize("text,actions", [
    ("can you use less wood", [("hold", "less_waste")]),
    ("optimise the material", [("hold", "less_waste")]),
    ("optimize it", [("hold", "less_waste")]),
    ("that's a lot of waste", [("hold", "less_waste")]),
    ("make it more efficient", [("hold", "less_waste")]),
    ("make it cheaper", []),  # left to the model: cost is not waste
    ("the waste is fine", [("release", "less_waste")]),
    ("don't worry about the material", [("release", "less_waste")]),
])
def test_keywords(text, actions):
    assert say.keywords(text) == actions
