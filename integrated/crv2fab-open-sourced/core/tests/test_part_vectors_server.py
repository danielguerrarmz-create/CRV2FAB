"""tests/vectors_part.json through the server, as the Rhino client sends it.

Regression (2026-11-14, found by the Rhino builder): the vectors were solved with the v6 settings
passed in directly, while /nudge read the seam, which still returned main's old constants; the
split_ok case answered one piece of 42 layers instead of 2 pieces. The server now solves with its
session settings, whose defaults the vectors are built from, and every case is posted here."""
import json
import threading
from pathlib import Path

import pytest

from gnj_nudge.server import make_server
from test_hardening import raw

pytestmark = pytest.mark.slow  # billet fits, split parts

VECTORS = json.loads((Path(__file__).resolve().parent / "vectors_part.json").read_text(encoding="utf-8"))
CASES = {c["name"]: c for c in VECTORS["cases"]}


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    s = make_server("127.0.0.1", 0, client=None, record_path=tmp_path_factory.mktemp("r") / "r.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    yield s
    s.shutdown()
    s.server_close()


def test_the_vectors_were_built_with_the_server_defaults(srv):
    shipped = raw(srv, "GET", "/settings")[1]["settings"]
    for key, value in VECTORS["settings"].items():
        assert shipped[key] == value, key


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_vector_answers_the_same_through_the_server(srv, name):
    case = CASES[name]
    status, out, _ = raw(srv, "POST", "/nudge", case["request"])
    assert status == 200
    e = case["expected"]
    assert (out["status"], out["sentence"], out["conflict"]) == (e["status"], e["sentence"], e["conflict"])
    if out["form"] is None:
        return
    f = out["form"]
    assert f["n_pieces"] == e["n_pieces"]
    assert f["checks"]["waste_pct"] == pytest.approx(e["waste_pct"], abs=0.5)
    assert [c["at_mm"] for c in f["cuts"]] == pytest.approx(e["cuts_at_mm"], abs=3)
    assert [(p["n_lamellas"], p["lamella_mm"]) for p in f["pieces"]] == \
        [(p["n_lamellas"], p["lamella_mm"]) for p in e["pieces"]]


def test_a_part_is_solved_with_the_session_settings(tmp_path):
    s = make_server("127.0.0.1", 0, client=None, record_path=tmp_path / "r.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    try:
        request = CASES["straight_beam"]["request"]
        assert raw(s, "POST", "/nudge", request)[1]["status"] == "proposed"
        raw(s, "POST", "/settings", {"opening_mm": [60, 40], "max_pieces": 1})
        out = raw(s, "POST", "/nudge", request)[1]
        assert out["status"] == "conflict" and out["conflict"] == ["your part", "machine opening 60 x 40 mm"]
    finally:
        s.shutdown()
        s.server_close()
