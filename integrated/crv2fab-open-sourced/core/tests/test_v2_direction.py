"""Shared spec v2: a bend in any direction. Layers split the 38 mm thickness,
strips split the 89 mm width; the bend ratio and thinnest piece apply to each face."""
import itertools
import math

import pytest

from conftest import FakeClient, intent, reply
from gnj_nudge import agent
from gnj_nudge.intent import Holds, Intent, hold_violations
from gnj_nudge.limits import Form, check, factors
from gnj_nudge.record import formal_sentence
from gnj_nudge.solver import solve
from test_hardening import raw, srv  # noqa: F401  (server fixture and raw request helper)


def sideways(radius, n=1, t=38, k=1, w=89, angle=90):
    return Form(radius, n, t, 2400, k, w, angle)


# ---- intent: the angle, and the v1 direction field ---------------------------

@pytest.mark.parametrize("direction,angle,want_angle,want_dir", [
    ("up", None, 0.0, "up"), ("down", None, 180.0, "down"),
    (None, 90, 90.0, None), (None, -90, 270.0, None), (None, 360, 0.0, "up"),
    (None, 180, 180.0, "down"), (None, -1e-20, 0.0, "up"), (None, 725, 5.0, None),
    ("up", 90, 90.0, None),  # the angle wins over the old field
])
def test_intent_angle_is_derived_and_normalised(direction, angle, want_angle, want_dir):
    i = Intent("M1", 2400, 2450, direction, angle)
    assert i.bend_angle_deg == want_angle
    assert 0 <= i.bend_angle_deg < 360
    assert i.direction == want_dir


@pytest.mark.parametrize("direction,angle", [(None, None), ("sideways", None), (None, float("nan")),
                                             (None, math.inf), (None, True), (None, "90")])
def test_intent_without_a_usable_direction_is_refused(direction, angle):
    with pytest.raises(ValueError):
        Intent("M1", 2400, 2450, direction, angle)


def test_factors_snap_near_zero_to_zero():
    assert factors(0) == (1.0, 0.0)
    assert factors(90) == (0.0, 1.0)
    assert factors(180) == (1.0, 0.0)
    c, s = factors(45)
    assert c == pytest.approx(math.sqrt(0.5)) and s == pytest.approx(math.sqrt(0.5))


# ---- checker on both faces ---------------------------------------------------

def test_sideways_solid_at_exactly_17800_mm_passes(cards):
    assert check(sideways(17800), cards).passed


def test_sideways_solid_at_17799_mm_fails_on_the_width(cards):
    r = check(sideways(17799), cards)
    [fail] = r.failures
    assert (fail.id, fail.face) == ("bend_ratio", "width")
    assert fail.measured == pytest.approx(17799 / 89)
    assert fail.by == pytest.approx(200 - 17799 / 89)


def test_sideways_the_thickness_does_not_bend(cards):
    assert check(sideways(17800), cards).card("bend_ratio", "thickness").passed


def test_a_strip_of_exactly_8_mm_passes_the_thinnest_piece_card(cards):
    r = check(sideways(1600, k=11, w=8), cards)
    assert r.card("min_lamella", "width").passed
    assert [(f.id, f.face) for f in r.failures] == [("stock_width", None)]  # 11 x 8 = 88, not 89


def test_a_strip_just_under_8_mm_fails_the_thinnest_piece_card(cards):
    r = check(sideways(17800, k=12, w=89 / 12), cards)
    assert [(f.id, f.face) for f in r.failures] == [("min_lamella", "width")]


def test_strips_must_fill_the_width(cards):
    r = check(sideways(2450, k=8, w=11), cards)
    assert [f.id for f in r.failures] == ["stock_width"]


# ---- solver: v1 numbers exactly at 0 and 180 ----------------------------------

@pytest.mark.parametrize("radius", [1200, 1500, 1899, 1900, 2450, 3800, 7599, 7600, 20000])
@pytest.mark.parametrize("holds", [[], ["solid"], ["shape"], ["solid", "shape"]])
def test_up_and_down_give_the_same_answer(cards, radius, holds):
    up = solve(intent(radius, angle=0), Holds(holds), cards)
    down = solve(intent(radius, direction="down"), Holds(holds), cards)
    assert (up.status, up.sentence, up.deviation_mm, up.conflict) == \
           (down.status, down.sentence, down.deviation_mm, down.conflict)
    if up.form:
        assert up.form.n_strips == down.form.n_strips == 1
        assert (up.form.radius_mm, up.form.n_lamellas) == (down.form.radius_mm, down.form.n_lamellas)
        assert (up.form.bend_angle_deg, down.form.bend_angle_deg) == (0.0, 180.0)


def test_up_2450_is_still_four_layers_of_9_5_and_one_strip(cards):
    r = solve(intent(2450, angle=0), Holds(), cards)
    f = r.form
    assert (f.n_lamellas, f.lamella_mm, f.n_strips, f.strip_mm, r.deviation_mm) == (4, 9.5, 1, 89, 0)
    assert r.sentence == "Your curve holds. Made from 4 glued layers in place of one solid piece."


# ---- solver: sideways and diagonal ---------------------------------------------

def test_sideways_2450_is_one_layer_and_eight_strips(cards):
    r = solve(intent(2450, angle=90), Holds(), cards)
    f = r.form
    assert (f.n_lamellas, f.n_strips, r.deviation_mm) == (1, 8, 0)
    assert f.strip_mm == pytest.approx(11.125)
    assert r.sentence == "Your curve holds. Made from 8 glued strips side by side in place of one solid piece."
    assert any("89 mm width governs" in s["text"] for s in r.steps)


def test_seven_strips_would_not_pass_sideways_at_2450(cards):
    assert not check(sideways(2450, k=7, w=89 / 7), cards).passed


def test_diagonal_2450_is_the_smallest_passing_pair_three_by_six(cards):
    r = solve(intent(2450, angle=45), Holds(), cards)
    f = r.form
    assert (f.n_lamellas, f.n_strips, r.deviation_mm) == (3, 6, 0)
    assert r.sentence == "Your curve holds. Glued both ways, 3 layers of 6 strips."
    # Smallest: one fewer of either fails.
    assert not check(Form(2450, 2, 19, 2400, 6, 89 / 6, 45), cards).passed
    assert not check(Form(2450, 3, 38 / 3, 2400, 5, 89 / 5, 45), cards).passed


def test_sideways_too_tight_for_eleven_strips_eases_the_radius(cards):
    r = solve(intent(1500, angle=90), Holds(), cards)
    f = r.form
    assert (f.n_lamellas, f.n_strips) == (1, 11)
    assert f.radius_mm == pytest.approx(200 * 89 / 11)  # 1618.2 mm
    assert f.bend_angle_deg == 90  # the direction is never changed
    assert r.deviation_mm > 0
    assert r.governing == ["bend_ratio", "min_lamella"]
    assert r.sentence.endswith("in 11 glued strips side by side.")


def test_sideways_too_tight_with_hold_shape_is_a_named_conflict(cards):
    r = solve(intent(1500, angle=90), Holds(["shape"]), cards)
    assert r.status == "conflict"
    assert r.conflict == ("drawn radius 1.50 m", "thinnest strip 8 mm")


def test_sideways_hold_solid_opens_to_17800(cards):
    r = solve(intent(2450, angle=90), Holds(["solid"]), cards)
    assert (r.form.n_lamellas, r.form.n_strips, r.form.radius_mm) == (1, 1, 17800)
    both = solve(intent(2450, angle=90), Holds(["solid", "shape"]), cards)
    assert both.conflict == ("solid section", "drawn radius 2.45 m")


def test_minus_ninety_and_two_seventy_bend_like_ninety(cards):
    a, b, c = (solve(intent(2450, angle=x), Holds(), cards).form for x in (90, 270, -90))
    assert (a.n_lamellas, a.n_strips) == (b.n_lamellas, b.n_strips) == (c.n_lamellas, c.n_strips)
    assert (b.bend_angle_deg, c.bend_angle_deg) == (270, 270)


ANGLES = [0, 10, 30, 45, 60, 89, 90, 120, 135, 180, 225, 270, 300, 359]
RADII = [1200, 1500, 1618, 2000, 2450, 5000, 7600, 12000, 17799, 17800, 30000]


@pytest.mark.parametrize("angle", ANGLES)
def test_every_solver_proposal_passes_keeps_holds_and_direction(cards, angle):
    for radius, holds in itertools.product(RADII, [[], ["solid"], ["shape"], ["solid", "shape"]]):
        i, h = intent(radius, angle=angle), Holds(holds)
        r = solve(i, h, cards)
        if r.status == "proposed":
            assert check(r.form, cards).passed, (angle, radius, holds)
            assert hold_violations(r.form, i, h) == []
            assert r.form.bend_angle_deg == i.bend_angle_deg
            assert r.form.radius_mm >= radius  # only ever opened, never tightened
        else:
            assert r.conflict and len(r.conflict) == 2


# ---- agent ------------------------------------------------------------------------

def test_a_model_that_turns_the_direction_is_refused(cards):
    turned = reply(2450, 1, 38, k=8, w=89 / 8, angle=90)  # buildable sideways, but the drawing points up
    fake = FakeClient([turned, turned, turned])
    r = agent.nudge(intent(2450, angle=0), Holds(), cards, fake)
    assert r.source == "rules"
    assert r.form.bend_angle_deg == 0
    assert "bend direction must stay" in fake.calls[1]["messages"][-1]["content"]


def test_a_model_angle_of_360_is_the_same_as_0(cards):
    r = agent.nudge(intent(2450, angle=0), Holds(), cards, FakeClient([reply(2450, 4, 9.5, angle=360)]))
    assert r.source == "model"


def test_a_sideways_model_proposal_is_used(cards):
    fake = FakeClient([reply(2450, 1, 38, k=8, w=89 / 8, angle=90)])
    r = agent.nudge(intent(2450, angle=90), Holds(), cards, fake)
    assert r.source == "model"
    assert (r.form.n_strips, r.form.bend_angle_deg) == (8, 90)
    assert fake.calls[0]["output_config"]["format"]["schema"]["required"][:6] == [
        "radius_mm", "bend_angle_deg", "n_lamellas", "lamella_mm", "n_strips", "strip_mm"]


def test_a_model_that_forgets_the_strips_is_refused(cards):
    flat = reply(2450, 1, 38, angle=90)  # solid sideways at 2450 fails the width face
    fake = FakeClient([flat, flat, flat])
    r = agent.nudge(intent(2450, angle=90), Holds(), cards, fake)
    assert r.source == "rules" and r.form.n_strips == 8
    assert "across the width" in fake.calls[1]["messages"][-1]["content"]


def test_a_reply_missing_the_new_fields_is_a_failed_attempt(cards):
    old = reply(2450, 4, 9.5)
    del old["n_strips"], old["bend_angle_deg"]
    fake = FakeClient([old, old, old])
    assert agent.nudge(intent(2450, angle=0), Holds(), cards, fake).source == "rules"


def test_hold_solid_means_one_strip_too(cards):
    fake = FakeClient([reply(17800, 1, 38, k=2, w=44.5, angle=90)] * 3)
    r = agent.nudge(intent(2450, angle=90), Holds(["solid"]), cards, fake)
    assert r.source == "rules" and r.form.solid


# ---- record ----------------------------------------------------------------------

def test_the_formal_sentence_names_the_direction_and_both_counts(cards):
    i = intent(2450, angle=90)
    s = formal_sentence(i, agent.nudge(i, Holds(), cards, None), cards)
    assert "bend direction 90 degrees" in s
    assert "glue-laminated, 1 lamella of 38 mm by 8 strips of 11.1 mm" in s
    assert "Governing limit: strip width / radius no greater than 1/200." in s
    assert "\u2014" not in s and "\u2013" not in s


# ---- server ------------------------------------------------------------------------

BASE = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450}


def test_server_sideways_nudge(srv):  # noqa: F811
    s, body, _ = raw(srv, "POST", "/nudge", {"intent": {**BASE, "bend_angle_deg": 90}, "holds": []})
    assert s == 200
    assert {k: v for k, v in body["form"].items() if k not in ("checks", "billet", "part_volume_m3")} == {"radius_mm": 2450, "n_lamellas": 1, "lamella_mm": 38, "n_strips": 8,
                            "strip_mm": 11.12, "bend_angle_deg": 90, "chord_mm": 2400}
    assert "direction" not in body["form"]


@pytest.mark.parametrize("given,angle,direction", [({"direction": "up"}, 0, "up"),
                                                   ({"direction": "down"}, 180, "down"),
                                                   ({"bend_angle_deg": 180}, 180, "down"),
                                                   ({"bend_angle_deg": -90}, 270, None)])
def test_server_keeps_v1_direction_and_normalises_the_angle(srv, given, angle, direction):  # noqa: F811
    s, body, _ = raw(srv, "POST", "/nudge", {"intent": {**BASE, **given}, "holds": []})
    assert s == 200
    assert body["form"]["bend_angle_deg"] == angle
    assert body["form"].get("direction") == direction


@pytest.mark.parametrize("bad", [b"NaN", b"Infinity", b"1e400", b'"90"', b"true", b"null"])
def test_server_refuses_a_bad_angle(srv, bad):  # noqa: F811
    body = b'{"intent":{"member_id":"M1","chord_mm":2400,"radius_mm":2450,"bend_angle_deg":' + bad + b'}}'
    s, out, _ = raw(srv, "POST", "/nudge", body)
    assert s == 400 and "error" in out
