"""Waste on the panel (spec v4, "Waste is on the panel"): every proposed form of both kinds carries
the teammate's waste figure, and every response carries a running tally of accepted decisions."""
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import intent
from gnj_nudge import agent
from gnj_nudge import fabrication as fb
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.server import make_server
from gnj_nudge.surface import saddle
from test_hardening import raw

ROOT = Path(__file__).resolve().parent.parent
CARDS = load_cards()
X_AXIS = [[0.15, 0.5], [0.85, 0.5]]


def bend_form(radius, holds=(), angle=0):
    i = intent(radius, angle=angle)
    return agent.nudge(i, Holds(holds), CARDS, None).as_dict(i)["form"]


# ---- the bend kind: waste is reported, its rules are unchanged -----------------------------------

def test_a_straight_box_member_wastes_nothing_beyond_lam_rounding():
    f = bend_form(1_000_000)  # the straightest bend the server takes: the 2x4 as drawn
    assert f["n_lamellas"] == 1 and f["checks"]["waste_pct"] == pytest.approx(0.0, abs=0.5)
    assert f["checks"]["waste_rounding_pct"] == pytest.approx(0.0, abs=0.5)
    assert f["billet"]["volume_m3"] == pytest.approx(f["part_volume_m3"], rel=5e-3)
    assert f["part_volume_m3"] == pytest.approx(0.038 * 0.089 * 2.4, rel=1e-3)


@pytest.mark.parametrize("holds", [(), ("solid",)])
def test_a_bent_2x4_is_its_own_billet(holds):
    f = bend_form(2450, holds)
    assert f["checks"]["waste_pct"] == pytest.approx(0.0, abs=0.1)
    assert f["billet"]["mode"] == "arc"


def test_a_diagonal_bend_is_milled_from_a_bigger_billet():
    f = bend_form(2450, angle=45)
    assert f["checks"]["waste_pct"] > 30 and f["checks"]["waste_rounding_pct"] > 0
    assert (f["n_lamellas"], f["n_strips"]) == (3, 6)  # the bend kind's own answer is unchanged


def test_bend_waste_is_instant():
    fb.bend_waste.cache_clear()
    t = time.perf_counter()
    bend_form(3333)
    assert time.perf_counter() - t < 0.5


def test_waste_matches_its_definition():
    f = bend_form(2450, angle=45)
    b, p = f["billet"]["volume_m3"], f["part_volume_m3"]
    assert f["checks"]["waste_pct"] == pytest.approx(100 * (b - p) / b, abs=0.05)


# ---- the surface kind -------------------------------------------------------------------------

def test_surface_forms_carry_volumes_and_the_rounding_share():
    from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent
    i = SurfaceIntent.build("M1", Surface(GRID_N, GRID_N, saddle()["points"]), [tuple(q) for q in X_AXIS])
    f = agent.nudge(i, Holds(), CARDS, None).as_dict()["form"]
    b, p = f["billet"]["volume_m3"], f["part_volume_m3"]
    assert f["checks"]["waste_pct"] == pytest.approx(100 * (b - p) / b, abs=0.05)
    assert 0 <= f["checks"]["waste_rounding_pct"] < f["checks"]["waste_pct"]


# ---- the tally ----------------------------------------------------------------------------------

@pytest.fixture
def server(tmp_path):
    srv = make_server("127.0.0.1", 0, cards=CARDS, client=None, record_path=tmp_path / "rec.jsonl")
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield SimpleNamespace(port=srv.server_address[1])
    srv.shutdown()
    srv.server_close()


BEND45 = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "bend_angle_deg": 45}
SURF_X = {"kind": "surface_stroke", "member_id": "M2", "surface": saddle(), "stroke_uv": X_AXIS}


def accept(server, intent_body):
    s, offer, _ = raw(server, "POST", "/nudge", {"intent": intent_body, "holds": []})
    assert s == 200 and "tally" in offer
    s, entry, _ = raw(server, "POST", "/judge", {"verdict": "accepted"})
    assert s == 200 and "tally" in entry
    return offer, entry


def test_the_tally_after_two_accepts_is_volume_weighted(server):
    a, _ = accept(server, BEND45)
    b, entry = accept(server, SURF_X)
    billets = a["form"]["billet"]["volume_m3"] + b["form"]["billet"]["volume_m3"]
    parts = a["form"]["part_volume_m3"] + b["form"]["part_volume_m3"]
    by_hand = 100 * (billets - parts) / billets
    tally = raw(server, "GET", "/tally")[1]
    assert tally["members"] == 2
    assert tally["billet_m3"] == pytest.approx(billets, abs=2e-6) and tally["part_m3"] == pytest.approx(parts, abs=2e-6)
    assert tally["waste_pct"] == pytest.approx(by_hand, abs=0.05)
    # Volume-weighted, not the mean of the two percentages.
    mean = (a["form"]["checks"]["waste_pct"] + b["form"]["checks"]["waste_pct"]) / 2
    assert abs(tally["waste_pct"] - mean) > 1
    assert entry["tally"] == tally


def test_rejects_are_not_in_the_tally(server):
    raw(server, "POST", "/nudge", {"intent": BEND45, "holds": []})
    raw(server, "POST", "/judge", {"verdict": "rejected"})
    assert raw(server, "GET", "/tally")[1] == {"members": 0, "billet_m3": 0.0, "part_m3": 0.0, "waste_pct": None}


def test_the_tally_survives_a_taste_reset_and_clears_on_its_own_reset(server):
    accept(server, BEND45)
    assert raw(server, "POST", "/taste/reset", {})[0] == 200
    assert raw(server, "GET", "/tally")[1]["members"] == 1
    s, out, _ = raw(server, "POST", "/tally/reset", {})
    assert s == 200 and out["members"] == 0 and out["waste_pct"] is None
    accept(server, BEND45)
    assert raw(server, "GET", "/tally")[1]["members"] == 1
    assert len(raw(server, "GET", "/record")[1]["entries"]) == 2  # nothing deleted; markers hidden


def test_the_record_states_volumes_and_waste(server):
    _, entry = accept(server, BEND45)
    assert entry["billet_m3"] > entry["part_m3"] > 0 and entry["waste_pct"] > 30
    assert "Billet 0.0228 m3, part 0.0085 m3, waste 62.8% of the billet." in entry["formal"]
    _, entry = accept(server, SURF_X)
    assert "m3, part 0.0072 m3, waste 25.5% of the billet." in entry["formal"]


# ---- no numpy: no number, never a made-up one ------------------------------------------------------

def test_without_numpy_the_waste_fields_are_absent_not_invented(tmp_path):
    code = r"""
import sys, json, threading, http.client
sys.modules['numpy'] = None
sys.path.insert(0, r'%s')
from gnj_nudge.server import make_server
srv = make_server('127.0.0.1', 0, client=None, record_path=r'%s')
threading.Thread(target=srv.serve_forever, daemon=True).start()
def call(method, path, body=None):
    c = http.client.HTTPConnection('127.0.0.1', srv.server_address[1])
    c.request(method, path, None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
    return json.loads(c.getresponse().read())
offer = call('POST', '/nudge', {'intent': {'member_id': 'M1', 'chord_mm': 2400, 'radius_mm': 2450, 'direction': 'up'}, 'holds': []})
entry = call('POST', '/judge', {'verdict': 'accepted'})
print(json.dumps({'form_keys': sorted(offer['form']), 'entry_keys': sorted(entry), 'tally': call('GET', '/tally'),
                  'formal': entry['formal']}))
srv.shutdown()
""" % (ROOT, tmp_path / "rec.jsonl")
    out = subprocess.run([sys.executable, "-P", "-E", "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    import json
    d = json.loads(out.stdout)
    assert not {"checks", "billet", "part_volume_m3"} & set(d["form_keys"])
    assert "billet_m3" not in d["entry_keys"] and "waste" not in d["formal"].lower()
    assert d["tally"] == {"members": 0, "billet_m3": 0.0, "part_m3": 0.0, "waste_pct": None}
