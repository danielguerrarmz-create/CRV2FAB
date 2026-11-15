"""Spec v9 slice 3, wiring: the thickness setting, the record, /say and /photo on a plate, conflict
wording and the one deviation figure people read. Quick tests use the straight member (one stock 2x4,
no billet fit); the rest are marked slow."""
import threading

import pytest

from gnj_nudge.server import make_server
from test_hardening import raw


def plate(**kw):
    return {"intent": {"kind": "plate", "member_id": "M1", "path": None, "profile_start": None,
                       "profile_end": None} | kw, "holds": []}


@pytest.fixture
def srv(tmp_path):
    s = make_server("127.0.0.1", 0, client=None, record_path=tmp_path / "r.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    yield s
    s.shutdown()
    s.server_close()


# ---- 1. thickness_mm is a session setting; the request's own value wins for that request ------------

def test_the_thickness_setting_is_used_when_the_request_sends_none(srv):
    assert raw(srv, "GET", "/settings")[1]["settings"]["thickness_mm"] == 38.0
    assert raw(srv, "POST", "/settings", {"thickness_mm": 19})[0] == 200
    out = raw(srv, "POST", "/nudge", plate())[1]
    assert out["form"]["thickness_mm"] == 19.0
    assert out["form"]["checks"]["waste_pct"] == pytest.approx(50.0)  # still one stock 2x4, half of it waste


def test_a_thickness_in_the_request_wins_for_that_request_only(srv):
    raw(srv, "POST", "/settings", {"thickness_mm": 19})
    assert raw(srv, "POST", "/nudge", plate(thickness_mm=38))[1]["form"]["thickness_mm"] == 38.0
    assert raw(srv, "POST", "/nudge", plate())[1]["form"]["thickness_mm"] == 19.0
    assert raw(srv, "GET", "/settings")[1]["settings"]["thickness_mm"] == 19.0


@pytest.mark.parametrize("bad", [0, 501, "38", True, None, float("nan")])
def test_a_bad_thickness_setting_is_a_400_that_changes_nothing(srv, bad):
    import json
    body = json.dumps({"thickness_mm": bad, "lam_ratio": 150}).replace("NaN", "1e999")
    status, out, _ = raw(srv, "POST", "/settings", body.encode())
    assert status == 400 and "thickness_mm" in out["error"]
    shown = raw(srv, "GET", "/settings")[1]["settings"]
    assert shown["thickness_mm"] == 38.0 and shown["lam_ratio"] == 125.0


def test_record_entries_carry_the_thickness_and_where_it_came_from(srv):
    raw(srv, "POST", "/settings", {"thickness_mm": 30})
    raw(srv, "POST", "/nudge", plate())
    entry = raw(srv, "POST", "/judge", {"verdict": "accepted"})[1]
    assert entry["settings"]["thickness_mm"] == 30.0
    assert entry["intent"]["thickness_mm"] == 30.0 and entry["intent"]["thickness_from"] == "setting"
    raw(srv, "POST", "/nudge", plate(thickness_mm=38))
    entry = raw(srv, "POST", "/judge", {"verdict": "accepted"})[1]
    assert entry["intent"]["thickness_mm"] == 38.0 and entry["intent"]["thickness_from"] == "request"


# ---- 2. the record: a full formal sentence, a summary of the intent, no taste lead -------------------

def _solve(name, holds=()):
    from gnj_nudge import vectors_plate as vp
    from gnj_nudge.intent import Holds
    from gnj_nudge.plate import PlateIntent, solve_plate
    it = vp.request(name)["intent"]
    intent = PlateIntent.build("M1", it["path"], it["profile_start"], it["profile_end"], it["thickness_mm"])
    return intent, solve_plate(intent, Holds(holds), vp.v6_settings())


@pytest.mark.slow
def test_the_formal_sentence_of_an_eased_plate_states_every_number():
    from gnj_nudge.limits import load_cards
    from gnj_nudge.record import make_entry
    intent, r = _solve("twist_too_large")
    f = make_entry("accepted", intent, frozenset(), r, load_cards())["formal"]
    for words in ("Member M1, softwood, a plate 38 mm thick", "2.40 m along its path", "1000 mm wide",
                  "twist 90.0 degrees as drawn, 27.6 as built", "Eased to build: twist scale 0.31",
                  "glued straight from 26 layers of 38 mm", "A straight billet 2404 x 275 x 988 mm",
                  "Grain: the billet runs 0.0 degrees off the path (limit 10).", "waste 86.3% of the billet",
                  "Deviation from intent 269 mm at most."):
        assert words in f, words
    assert "pressed in one curve" not in f


@pytest.mark.slow
def test_a_split_plate_records_its_joints():
    from gnj_nudge.limits import load_cards
    from gnj_nudge.record import make_entry
    intent, r = _solve("twist_50_splits")
    assert r.form.n_pieces == 2
    e = make_entry("accepted", intent, frozenset(), r, load_cards())
    assert f"made in {r.form.n_pieces} pieces joined end to end" in e["formal"]
    assert "Joint 1 at " in e["formal"] and "joint to be designed by the engineer" in e["formal"]
    assert len(e["joints"]) == r.form.n_pieces - 1
    assert "Grain: each billet runs at most " in e["formal"]
    flat = repr(e["intent"])
    assert "[[" not in flat and "((" not in flat  # a summary, never a point list


@pytest.mark.slow
def test_taste_does_not_lead_a_plate():
    from gnj_nudge import agent
    from gnj_nudge import vectors_plate as vp
    from gnj_nudge.intent import Holds
    from gnj_nudge.limits import load_cards
    from gnj_nudge.plate import PlateIntent
    it = vp.request("path_arc_up")["intent"]
    r = agent.nudge(PlateIntent.build("M1", it["path"]), Holds(), load_cards(), None, lead="solid",
                    because="You kept it solid in 5 of your last 5 decisions.")
    assert r.taste is None and not r.form.solid and "as you usually do" not in r.sentence


# ---- 3. /say on a plate speaks of the shape ----------------------------------------------------------

def test_every_say_template_on_a_plate_says_shape():
    from gnj_nudge import say
    assert say.word_for("plate") == "shape"
    for op in ("hold", "release"):
        text = say.heard([(op, "shape")], kind="plate")
        assert "shape" in text and "curve" not in text and "line" not in text
    assert say.heard([("hold", "less_waste")], nothing_saved=True, kind="plate") == \
        "Already as little waste as this shape allows."
    assert "keep your shape" in say.not_understood("plate") and "curve" not in say.not_understood("plate")


def test_keep_my_shape_exactly_holds_the_shape():
    from gnj_nudge import say
    assert say.keywords("keep my shape exactly") == [("hold", "shape")]
    assert "shape" in say.ACTIONS[("hold", "shape")]  # what the model reads for that action names it too


def test_say_on_a_plate_episode_through_the_server(srv):
    raw(srv, "POST", "/nudge", plate())
    out = raw(srv, "POST", "/say", {"text": "keep my shape exactly"})[1]
    assert out["understood"] and out["heard"] == "Keeping your shape as drawn."
    assert out["actions"] == [{"op": "hold", "name": "shape"}] and out["nudge"]["status"] == "proposed"
    out = raw(srv, "POST", "/say", {"text": "make it purple"})[1]
    assert not out["understood"] and "keep your shape" in out["heard"]
    out = raw(srv, "POST", "/say", {"text": "shorter pieces are fine"})[1]
    assert out["heard"] == "Shorter pieces are fine; joints to be designed by the engineer."


# ---- 5. a conflict names the drawn plate's own failure ----------------------------------------------

@pytest.mark.slow
def test_holding_the_twisted_plate_is_the_machine_conflict_not_grain():
    _, r = _solve("twist_too_large_hold_shape", ["shape"])
    assert r.status == "conflict" and r.sentence == "This billet will not fit through the machine."
    assert r.conflict == ("your shape", "machine opening 1200 x 280 mm")
    assert any("across the grain" in s["text"] for s in r.steps)  # what the pieces ran into is still said


@pytest.mark.slow
def test_the_plate_wider_than_the_opening_names_the_machine_and_says_what_pieces_met():
    _, r = _solve("too_wide_for_opening")
    assert r.sentence == "This billet will not fit through the machine."
    assert any(s["text"].startswith("Tried up to 4 pieces: a billet would fit only across the grain")
               for s in r.steps)


# ---- 6. one deviation figure for people: deviation_mm, the largest move anywhere on the plate ---------

@pytest.mark.slow
@pytest.mark.parametrize("name", ["path_too_tight", "twist_too_large", "deep_u_twisted"])
def test_the_only_distance_people_read_for_easing_is_deviation_mm(name):
    import re
    _, r = _solve(name)
    dev = f"{r.deviation_mm:.0f} mm"
    # Daniel, 2026-11-14: words plus ONE number. No per-scale figure (mm, degrees or scale) in text.
    assert re.findall(r"\d+(?:\.\d+)?(?: mm| degrees)?", r.sentence) == [dev], r.sentence
    assert r.sentence.endswith(f", moving the plate at most {dev}.")
    eased_steps = [s["text"] for s in r.steps if s["text"].startswith(("Twist ", "Profiles ", "Path "))]
    assert eased_steps and not any(re.search(r"\d", t) for t in eased_steps), eased_steps
    assert len(eased_steps) == sum(v < 1.0 for v in r.form.scales.values())
    assert f"The plate sits at most {dev} from what you drew." in [s["text"] for s in r.steps]


# ---- the binding check names the easing (Daniel, 2026-11-15) ---------------------------------------

@pytest.mark.slow
def test_an_eased_plate_names_the_check_that_binds_in_the_answer_not_the_first_failure():
    """The drawn plate fails both bend (1.12 m tightest) and machine (318 mm in a 280 mm opening);
    straightening the path for the bend leaves the bend with room (4.08 m against 2.13 m) and the
    machine with 18 mm: the machine binds, so the words name it (the Rhino v9 smoke's upright arch)."""
    import math
    from gnj_nudge.intent import Holds
    from gnj_nudge.plate import PlateIntent, solve_plate
    from gnj_nudge.vectors_plate import v6_settings
    path = [[2400.0 * i / 40, 0.0, 900.0 * math.sin(math.pi * i / 40)] for i in range(41)]
    start = [[0.0, u, u * math.tan(math.radians(20.0))] for u in (-150.0, 0.0, 150.0)]
    r = solve_plate(PlateIntent.build("M1", path, start, None), Holds(), v6_settings())
    assert r.sentence == "Path straightened so the billet fits the machine, moving the plate at most 701 mm."
    why = [s for s in r.steps if s["text"].startswith("Path straightened toward")]
    assert why and why[0]["text"].endswith("so the billet fits the machine.") and why[0]["limit_id"] == "machine"
