"""Spec v9 slice 3 item 7 (Daniel, 2026-11-14): POST /undo rewinds the most recent accepted decision of
this session. The record stays append-only: an `undo` marker is appended; the tally, taste and GET
/record read through it. Plates with no strokes are one stock 2x4 each, so no billet fit runs here."""
import json
import threading

import pytest

from gnj_nudge import taste
from gnj_nudge.record import Record
from gnj_nudge.server import make_server
from test_hardening import raw

STOCK = {"intent": {"kind": "plate", "member_id": "M1", "path": None, "profile_start": None, "profile_end": None},
         "holds": []}


def start(path):
    s = make_server("127.0.0.1", 0, client=None, record_path=path)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    return s


@pytest.fixture
def srv(tmp_path):
    s = start(tmp_path / "r.jsonl")
    s.path = tmp_path / "r.jsonl"
    yield s
    s.shutdown()
    s.server_close()


def accept(srv, member_id="M1", thickness=38):
    req = json.loads(json.dumps(STOCK))
    req["intent"] |= {"member_id": member_id, "thickness_mm": thickness}
    assert raw(srv, "POST", "/nudge", req)[1]["status"] == "proposed"
    return raw(srv, "POST", "/judge", {"verdict": "accepted"})[1]


def test_undo_walks_back_one_accept_at_a_time(srv):
    a = accept(srv, "A1", 38)
    b = accept(srv, "B1", 19)
    assert raw(srv, "GET", "/tally")[1]["members"] == 2
    status, out, _ = raw(srv, "POST", "/undo", {})
    assert status == 200
    assert out["undone"] == {"member_id": "B1", "timestamp": b["timestamp"], "kind": "plate"}
    assert out["tally"] == {"members": 1, "billet_m3": a["billet_m3"], "part_m3": a["part_m3"], "waste_pct": 0.0}
    assert raw(srv, "GET", "/tally")[1] == out["tally"]
    out = raw(srv, "POST", "/undo", {})[1]
    assert out["undone"]["member_id"] == "A1" and out["tally"]["members"] == 0
    status, out, _ = raw(srv, "POST", "/undo", {})
    assert status == 409 and "nothing to undo" in out["error"]


def test_the_record_keeps_every_line_and_marks_what_was_undone(srv):
    accept(srv, "A1")
    b = accept(srv, "B1")
    raw(srv, "POST", "/undo", {})
    entries = raw(srv, "GET", "/record")[1]["entries"]
    assert [(e["member_id"], e.get("undone", False)) for e in entries] == [("A1", False), ("B1", True)]
    lines = [json.loads(x) for x in srv.path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3 and lines[1] == {k: v for k, v in entries[1].items() if k != "undone"}  # never rewritten
    marker = lines[2]
    assert marker["event"] == "undo" and marker["undone_timestamp"] == b["timestamp"]
    assert marker["undone_episode_id"] == b["episode_id"]
    # the next answer's tally ignores the undone accept too
    assert raw(srv, "POST", "/nudge", STOCK)[1]["tally"]["members"] == 1


def test_a_tally_reset_stops_undo_from_crossing_it(srv):
    accept(srv, "A1")
    raw(srv, "POST", "/tally/reset", {})
    accept(srv, "B1")
    assert raw(srv, "POST", "/undo", {})[1]["undone"]["member_id"] == "B1"
    assert raw(srv, "POST", "/undo", {})[0] == 409


def test_undo_never_reaches_a_decision_from_before_this_session(tmp_path):
    path = tmp_path / "r.jsonl"
    first = start(path)
    try:
        accept(first, "A1")
    finally:
        first.shutdown()
        first.server_close()
    second = start(path)
    try:
        assert raw(second, "POST", "/undo", {})[0] == 409
        assert raw(second, "GET", "/tally")[1]["members"] == 1
    finally:
        second.shutdown()
        second.server_close()


@pytest.mark.parametrize("body", [{"member_id": "A1"}, [], "x"])
def test_undo_takes_an_empty_body(srv, body):
    accept(srv)
    status, out, _ = raw(srv, "POST", "/undo", body)
    assert status == 400
    assert raw(srv, "GET", "/tally")[1]["members"] == 1


def test_taste_ignores_an_undone_accept(tmp_path):
    rec = Record(tmp_path / "r.jsonl")
    for i in range(3):
        rec.append({"timestamp": f"2026-11-14T00:00:0{i}+00:00", "verdict": "accepted", "member_id": "M1",
                    "kind": "bend", "episode_id": f"e{i}", "first_offer_trade": "makeup", "accepted_trade": "solid"})
    assert taste.lead(rec.live_lines())[0] == "solid"
    assert rec.undo()["episode_id"] == "e2"
    assert taste.lead(rec.live_lines())[0] == "makeup"
    assert taste.lead(rec.lines())[0] == "solid"  # the raw log still holds the line; only the reading changes
