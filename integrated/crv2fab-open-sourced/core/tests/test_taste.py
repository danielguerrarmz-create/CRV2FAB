"""Taste: the record is read back (docs/SPEC_V3.md). Limits say what is true; taste says what
this designer likes, and may only choose between forms that already pass the checker."""
import itertools

import pytest

from conftest import FakeClient, intent, reply
from gnj_nudge import agent, taste
from gnj_nudge.intent import Holds
from gnj_nudge.limits import check, load_cards
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.vectors_v4 import CASES
from test_hardening import raw, srv  # noqa: F401

CARDS = load_cards()
BEND = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 0}
SURF = Surface(GRID_N, GRID_N, saddle()["points"])
STROKES = {name: stroke for name, stroke, _ in CASES}
LEAD_SOLID = ("solid", "You kept it solid in 3 of your last 3 decisions.")


def solid_episode(srv, radius=2450):  # noqa: F811
    """One gesture: glued offer, reject holding solid, solid offer, accept."""
    i = BEND | {"radius_mm": radius}
    assert raw(srv, "POST", "/nudge", {"intent": i, "holds": []})[0] == 200
    assert raw(srv, "POST", "/judge", {"verdict": "rejected", "hold": "solid"})[0] == 200
    assert raw(srv, "POST", "/nudge", {"intent": i, "holds": ["solid"]})[0] == 200
    s, e, _ = raw(srv, "POST", "/judge", {"verdict": "accepted"})
    assert s == 200
    return e


def glued_episode(srv):  # noqa: F811
    raw(srv, "POST", "/nudge", {"intent": BEND, "holds": []})
    return raw(srv, "POST", "/judge", {"verdict": "accepted"})[1]


# ---- the lead, from the record ----------------------------------------------------------

def acc(trade, first="makeup"):
    return {"verdict": "accepted", "accepted_trade": trade, "first_offer_trade": first}


def test_three_solid_of_the_last_five_lead_solid_and_two_do_not():
    assert taste.lead([acc("solid")] * 3)[0] == "solid"
    assert taste.lead([acc("solid")] * 2)[0] == "makeup"
    assert taste.lead([acc("solid")] * 3 + [acc("makeup")] * 2)[0] == "solid"
    assert taste.lead([acc("solid")] * 3 + [acc("makeup")] * 3)[0] == "makeup"  # one solid fell out of the 5


def test_episodes_whose_first_offer_was_buildable_as_drawn_do_not_count():
    assert taste.lead([acc("solid")] * 2 + [acc("none", first="none")] * 4 + [acc("solid")])[0] == "solid"
    assert taste.lead([acc("solid", first="none")] * 5)[0] == "makeup"


def test_rejects_and_old_entries_without_trades_do_not_count():
    rejects = [{"verdict": "rejected", "accepted_trade": None, "first_offer_trade": "makeup"}] * 5
    legacy = [{"verdict": "accepted"}] * 5
    assert taste.lead(rejects + legacy + [acc("solid")] * 2)[0] == "makeup"


def test_a_reset_marker_forgets_everything_before_it():
    assert taste.lead([acc("solid")] * 5 + [{"event": "taste_reset"}])[0] == "makeup"
    assert taste.lead([acc("solid")] * 5 + [{"event": "taste_reset"}] + [acc("solid")] * 3)[0] == "solid"


def test_the_constants_are_named():
    assert (taste.WINDOW, taste.SOLID_MIN) == (5, 3)


@pytest.mark.parametrize("sentence,want", [
    ("Kept solid. Curve eased by 40 mm so one piece can bend it.",
     "Kept solid, as you usually do. Curve eased by 40 mm so one piece can bend it."),
    ("Line straightened by 3 mm so it can be built, in one solid piece.",
     "Line straightened by 3 mm so it can be built, in one solid piece, as you usually do."),
    ("Kept solid. Curve eased by 4.5 mm so it bends.", "Kept solid, as you usually do. Curve eased by 4.5 mm so it bends."),
])
def test_taste_words_go_at_the_end_of_the_first_sentence(sentence, want):
    assert taste.with_taste_words(sentence) == want


# ---- the before / after the spec asks for --------------------------------------------------

def test_two_solid_episodes_do_not_move_the_answer(srv):  # noqa: F811
    for _ in range(2):
        solid_episode(srv)
    s, out, _ = raw(srv, "POST", "/nudge", {"intent": BEND, "holds": []})
    assert out["sentence"] == "Your curve holds. Made from 4 glued layers in place of one solid piece."
    assert out["taste"] is None


def test_three_solid_episodes_answer_solid_with_the_taste_wording(srv):  # noqa: F811
    for _ in range(3):
        e = solid_episode(srv)
    assert (e["first_offer_trade"], e["accepted_trade"], e["kind"]) == ("makeup", "solid", "bend")
    s, out, _ = raw(srv, "POST", "/nudge", {"intent": BEND, "holds": []})
    assert (out["form"]["n_lamellas"], out["form"]["n_strips"], out["form"]["radius_mm"]) == (1, 1, 7600)
    assert out["sentence"].startswith("Kept solid, as you usually do. Curve eased by ")
    assert out["steps"][-1] == {"tag": "Taste", "text": "You kept it solid in 3 of your last 3 decisions.",
                                "limit_id": None}
    assert out["taste"] == {"lead": "solid", "because": "You kept it solid in 3 of your last 3 decisions."}
    assert raw(srv, "GET", "/taste")[1]["lead"] == "solid"


def test_rejecting_a_taste_answer_and_holding_shape_moves_taste_back(srv):  # noqa: F811
    for _ in range(3):
        solid_episode(srv)
    leads = []
    for _ in range(3):
        offer = raw(srv, "POST", "/nudge", {"intent": BEND, "holds": []})[1]
        assert offer["taste"] is not None  # the lead is still solid
        raw(srv, "POST", "/judge", {"verdict": "rejected", "hold": "shape"})
        s, out, _ = raw(srv, "POST", "/nudge", {"intent": BEND, "holds": ["shape"]})
        assert out["taste"] is None and out["form"]["n_lamellas"] == 4  # solid cannot keep the shape: no comment
        e = raw(srv, "POST", "/judge", {"verdict": "accepted"})[1]
        assert (e["first_offer_trade"], e["accepted_trade"]) == ("solid", "makeup")
        leads.append(raw(srv, "GET", "/taste")[1]["lead"])
    # Last 5 after each: 3 of 4 solid, 3 of 5 solid, then 2 of 5: taste has moved back by itself.
    assert leads == ["solid", "solid", "makeup"]


def test_a_plain_accept_of_a_taste_answer_keeps_the_lead(srv):  # noqa: F811
    for _ in range(3):
        solid_episode(srv)
    e = glued_episode(srv)  # the offer is taste-led solid; accepting it records solid
    assert (e["first_offer_trade"], e["accepted_trade"], e["taste_led"]) == ("solid", "solid", True)
    assert raw(srv, "GET", "/taste")[1]["lead"] == "solid"


def test_reset_returns_the_default(srv):  # noqa: F811
    for _ in range(3):
        solid_episode(srv)
    s, out, _ = raw(srv, "POST", "/taste/reset", {})
    assert s == 200 and out["lead"] == "makeup"
    assert raw(srv, "POST", "/nudge", {"intent": BEND, "holds": []})[1]["taste"] is None
    assert len(raw(srv, "GET", "/record")[1]["entries"]) == 6  # nothing deleted; the marker is not an entry


def test_one_episode_spans_rejects_and_ends_at_accept(srv):  # noqa: F811
    a = solid_episode(srv)
    b = solid_episode(srv)
    entries = raw(srv, "GET", "/record")[1]["entries"]
    assert [e["episode_id"] for e in entries] == [a["episode_id"]] * 2 + [b["episode_id"]] * 2
    assert a["episode_id"] != b["episode_id"]
    assert [e["accepted_trade"] for e in entries] == [None, "solid", None, "solid"]


def test_taste_routes_refuse_a_foreign_origin(srv):  # noqa: F811
    assert raw(srv, "GET", "/taste", headers={"Origin": "http://evil.example"})[0] == 403
    assert raw(srv, "POST", "/taste/reset", {}, headers={"Origin": "http://evil.example"})[0] == 403


# ---- taste never breaks a limit or a hold --------------------------------------------------

@pytest.mark.parametrize("angle", [0, 45, 90, 180])
def test_a_solid_lead_never_yields_a_form_the_checker_fails(angle):
    for radius, holds in itertools.product([1200, 1500, 2450, 5000, 7599, 7600, 17800, 30000],
                                           [[], ["shape"], ["solid"], ["solid", "shape"]]):
        r = agent.nudge(intent(radius, angle=angle), Holds(holds), CARDS, None, lead=LEAD_SOLID[0],
                        because=LEAD_SOLID[1])
        if r.form:
            assert check(r.form, CARDS).passed
            if "shape" in holds:
                assert r.deviation_mm <= 0.5  # the designer's hold outranks the lead
            if r.taste:
                assert r.form.n_lamellas == r.form.n_strips == 1


@pytest.mark.parametrize("name", ["x_axis", "diagonal", "sharp_wiggle"])
def test_a_solid_lead_on_a_surface_never_fails_the_checker(name):
    # v4: the surface checker is the sc_glulam route (bend R/t and machine opening).
    i = SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES[name]])
    for holds in ([], ["shape"]):
        r = agent.nudge(i, Holds(holds), CARDS, None, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
        if r.form:
            assert r.form.check["ok"]
            if r.taste:
                assert r.form.solid


def test_on_a_surface_a_solid_lead_falls_back_without_comment_when_one_piece_cannot_be_milled(monkeypatch):
    # v4 changed this case: on the default machine one straight piece mills the x-axis line, so
    # taste now leads there (test_v4_fabrication). With an opening nothing fits, the solid try is a
    # conflict and the default order answers with no taste words.
    from gnj_nudge.settings import DEFAULTS
    tiny = dict(DEFAULTS, opening_mm=[150.0, 80.0], max_pieces=1)  # spec v6: the opening is a setting; one billet
    i = SurfaceIntent.build("M1", SURF, [tuple(q) for q in STROKES["x_axis"]])
    r = agent.nudge(i, Holds(), CARDS, None, lead=LEAD_SOLID[0], because=LEAD_SOLID[1], settings=tiny)
    assert r.status == "conflict"  # nothing fits a 150 x 80 opening: the setting reached the solver
    assert r.taste is None and "as you usually do" not in r.sentence


def test_a_lead_says_nothing_when_the_default_is_already_solid():
    r = agent.nudge(intent(7600), Holds(), CARDS, None, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
    assert r.taste is None and r.sentence == "Buildable as drawn, in one solid piece."


def test_a_designer_hold_outranks_the_lead():
    r = agent.nudge(intent(2450), Holds(["shape"]), CARDS, None, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
    assert r.taste is None and (r.form.n_lamellas, r.deviation_mm) == (4, 0)


# ---- closeness, corrected: compared with the solver's answer for the same lead ---------------

def test_a_taste_led_model_answer_is_judged_against_the_taste_led_solver():
    # The solid answer sits ~260 mm from a 2450 mm curve. Against the default order (deviation 0)
    # it would be refused; against the solid-led solver it is the same answer and passes.
    fake = FakeClient([reply(7600, 1, 38, "Kept solid so one piece can bend it.")])
    r = agent.nudge(intent(2450), Holds(), CARDS, fake, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
    assert r.source == "model" and r.taste is not None
    # Shown: the rule template for the checked form (Gojo's review). The model's words: debug only.
    assert r.sentence == "Kept solid, as you usually do. Curve eased by 219 mm so one piece can bend it."
    assert r.model_text["sentence"] == "Kept solid so one piece can bend it."


def test_without_a_lead_the_same_model_answer_is_too_far():
    fake = FakeClient([reply(7600, 1, 38)] * 3)
    r = agent.nudge(intent(2450), Holds(), CARDS, fake)
    assert r.source == "rules" and r.form.n_lamellas == 4


def test_under_a_solid_lead_a_glued_model_answer_is_refused():
    fake = FakeClient([reply(2450, 4, 9.5)] * 3)
    r = agent.nudge(intent(2450), Holds(), CARDS, fake, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
    assert r.source == "rules" and r.form.n_lamellas == 1 and r.taste is not None


# ---- wording: a taste-led answer must not say the designer is holding anything ---------------

def decision(r):
    return next(s["text"] for s in r.steps if s["tag"] == "Decision")


def test_taste_led_decision_says_usually_and_a_real_hold_says_holding():
    led = agent.nudge(intent(2450), Holds(), CARDS, None, lead=LEAD_SOLID[0], because=LEAD_SOLID[1])
    held = agent.nudge(intent(2450), Holds(["solid"]), CARDS, None)
    assert decision(led).startswith("You usually keep it solid. Kept one piece and opened the radius to 7.60 m")
    assert decision(held).startswith("You are holding solid. Kept one piece and opened the radius to 7.60 m")
    assert decision(led) != decision(held)
    assert "holding" not in " ".join(s["text"] for s in led.steps)
