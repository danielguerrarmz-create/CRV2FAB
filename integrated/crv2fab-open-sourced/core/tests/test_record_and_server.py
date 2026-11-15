import json
import threading
import urllib.error
import urllib.request

import pytest

from conftest import intent
from gnj_nudge import agent
from gnj_nudge.intent import Holds
from gnj_nudge.record import Record, make_entry
from gnj_nudge.server import make_server


def test_accept_writes_the_formal_sentence(cards, tmp_path):
    i = intent(2450)
    res = agent.nudge(i, Holds(), cards, None)
    e = Record(tmp_path / "r.jsonl").append(make_entry("accepted", i, Holds(), res, cards))
    assert e["formal"] == (
        "Member M1, softwood 38 x 89 mm, length 2.40 m. Single curvature, radius 2.45 m, bend direction 0 degrees, "
        "glue-laminated, 4 lamellas of 9.5 mm by 1 strip of 89 mm. "
        "Governing limit: lamella thickness / radius no greater than 1/200. "
        "Deviation from intent 0 mm at mid-span. Chosen over a solid section, which fails the bend limit at this radius."
        " Billet 0.0085 m3, part 0.0085 m3, waste 0.0% of the billet."  # v4: waste on the panel
    )
    assert "\u2014" not in e["formal"] and "\u2013" not in e["formal"]


def test_record_is_append_only_and_counts_holds(cards, tmp_path):
    rec = Record(tmp_path / "r.jsonl")
    i = intent(2450)
    res = agent.nudge(i, Holds(), cards, None)
    rec.append(make_entry("rejected", i, Holds(), res, cards, hold="solid"))
    first = (tmp_path / "r.jsonl").read_text(encoding="utf-8")
    rec.append(make_entry("rejected", i, Holds(), res, cards, hold="solid"))
    rec.append(make_entry("rejected", i, Holds(), res, cards, hold="shape"))
    assert (tmp_path / "r.jsonl").read_text(encoding="utf-8").startswith(first)
    assert len(rec.entries()) == 3
    assert rec.taste_summary() == {"solid": 2, "shape": 1, "less_waste": 0, "split_ok": 0}
    assert rec.entries()[0]["formal"].endswith("Designer holds: solid section.")


def test_a_hold_only_comes_with_a_reject(cards):
    i = intent(2450)
    res = agent.nudge(i, Holds(), cards, None)
    with pytest.raises(ValueError):
        make_entry("accepted", i, Holds(), res, cards, hold="solid")


@pytest.fixture
def server(cards, tmp_path):
    srv = make_server("127.0.0.1", 0, cards=cards, client=None, record_path=tmp_path / "rec.jsonl")
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(url, body=None, origin=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), e.headers


INTENT = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "direction": "up"}


def test_nudge_then_judge_then_record(server):
    s, body, _ = call(server + "/nudge", {"intent": INTENT, "holds": []})
    assert s == 200
    assert body["status"] == "proposed" and body["source"] == "rules"
    v1 = {"radius_mm": 2450, "n_lamellas": 4, "lamella_mm": 9.5, "chord_mm": 2400, "direction": "up"}
    v2 = {"n_strips": 1, "strip_mm": 89, "bend_angle_deg": 0}
    v4 = {"checks", "billet", "part_volume_m3"}  # v4 adds waste on the panel (absent without numpy)
    assert {k: v for k, v in body["form"].items() if k not in v4} == v1 | v2  # v1 fields unchanged
    assert body["form"]["checks"]["waste_pct"] == 0.0 and body["form"]["part_volume_m3"] > 0
    assert body["deviation_mm"] == 0

    s, entry, _ = call(server + "/judge", {"verdict": "rejected", "hold": "solid"})
    assert s == 200 and entry["holds_added"] == ["solid"]

    s, _, _ = call(server + "/judge", {"verdict": "accepted"})
    assert s == 409  # already judged; never guesses again by itself

    s, rec, _ = call(server + "/record")
    assert len(rec["entries"]) == 1 and rec["taste_summary"] == {"solid": 1, "shape": 0, "less_waste": 0,
                                                                  "split_ok": 0}


def test_conflict_cannot_be_judged(server):
    s, body, _ = call(server + "/nudge", {"intent": INTENT, "holds": ["solid", "shape"]})
    assert body["status"] == "conflict" and body["form"] is None
    assert body["conflict"] == ["solid section", "drawn radius 2.45 m"]
    s, _, _ = call(server + "/judge", {"verdict": "accepted"})
    assert s == 409


@pytest.mark.parametrize("payload", [
    {"intent": {**INTENT, "radius_mm": -1}},
    {"intent": {**INTENT, "direction": "sideways"}},
    {"intent": INTENT, "holds": ["glitter"]},
    {"intent": INTENT, "holds": "solid"},
    {},
])
def test_bad_input_is_a_400(server, payload):
    s, body, _ = call(server + "/nudge", payload)
    assert s == 400 and "error" in body


def test_cors_answers_localhost_only(server):
    _, _, h = call(server + "/record", origin="http://localhost:5173")
    assert h["Access-Control-Allow-Origin"] == "http://localhost:5173"
    _, _, h = call(server + "/record", origin="https://evil.example")
    assert h.get("Access-Control-Allow-Origin") is None
