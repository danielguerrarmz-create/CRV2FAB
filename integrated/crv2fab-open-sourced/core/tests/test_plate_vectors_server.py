"""tests/vectors_plate.json through the server, as the Rhino client will send it (spec v9).

Each case is timed from request to answer: the spec's budget is under 10 s per answer. The server runs
as `python -m gnj_nudge.server` runs it, with the piece-fit process pool on (pieces.enable_pool)."""
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from gnj_nudge.server import make_server
from test_hardening import raw

pytestmark = pytest.mark.slow  # billet fits

VECTORS = json.loads((Path(__file__).resolve().parent / "vectors_plate.json").read_text(encoding="utf-8"))
CASES = {c["name"]: c for c in VECTORS["cases"]}
BUDGET_S = 10.0


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    from gnj_nudge import pieces as pc
    pc.enable_pool()  # as server.main() does
    s = make_server("127.0.0.1", 0, client=None, record_path=tmp_path_factory.mktemp("r") / "r.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    yield s
    s.shutdown()
    s.server_close()
    pc.enable_pool(False)


def post(srv, path, body):
    """(status, body, wall seconds). A long timeout: the budget is asserted, not enforced by the socket."""
    data = json.dumps(body).encode()
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=60)
    t0 = time.perf_counter()
    conn.request("POST", path, data, {"Content-Type": "application/json", "Content-Length": str(len(data))})
    r = conn.getresponse()
    out = json.loads(r.read())
    wall = time.perf_counter() - t0
    conn.close()
    return r.status, out, wall


def test_the_vectors_were_built_with_the_server_defaults(srv):
    shipped = raw(srv, "GET", "/settings")[1]["settings"]
    for key, value in VECTORS["settings"].items():
        assert shipped[key] == value, key


@pytest.mark.parametrize("name", list(CASES))
def test_each_vector_answers_the_same_through_the_server_inside_the_budget(srv, name):
    case = CASES[name]
    status, out, wall = post(srv, "/nudge", case["request"])
    print(f"\n/nudge {name}: {wall:.2f} s")
    assert status == 200
    assert wall < BUDGET_S
    e = case["expected"]
    assert (out["status"], out["sentence"], out["conflict"]) == (e["status"], e["sentence"], e["conflict"])
    if out["form"] is None:
        return
    f = out["form"]
    assert f["kind"] == "plate_member"
    assert out["deviation_mm"] == pytest.approx(e["deviation_mm"], abs=1.0)
    assert f["eased"] == pytest.approx(e["eased"], abs=0.01)
    if f["eased"] != dict.fromkeys(f["eased"], 1.0):
        assert out["deviation_mm"] > 0 and f["intent_grid"] != f["grid"]
    assert (f["n_lamellas"], f["lamella_mm"]) == (e["n_lamellas"], e["lamella_mm"])
    assert f.get("n_pieces", 1) == e["n_pieces"]
    assert f["twist_deg"] == pytest.approx(e["twist_deg"], abs=0.1)
    assert f["part_volume_m3"] == pytest.approx(e["part_volume_m3"], rel=1e-4)
    assert f["checks"]["waste_pct"] == pytest.approx(e["waste_pct"], abs=0.5)
    bills = [p["billet"] for p in f["pieces"]] if "pieces" in f else [f["billet"]]
    for got, want in zip(bills, e["billets_mm"]):
        assert [got[k] for k in ("length_mm", "width_mm", "depth_mm")] == pytest.approx(want, abs=3)
    got = {"bend": f["checks"]["bend"]["ok"], "machine": f["checks"]["machine"]["ok"],
           "grain": f["checks"]["grain"]["ok"], "grain_angle_deg": f["checks"]["grain"]["angle_deg"]}
    assert got == pytest.approx(e["checks"] | {"grain_angle_deg": pytest.approx(e["checks"]["grain_angle_deg"], abs=0.5)})


def test_a_plate_is_judged_into_the_record_without_its_strokes(srv):
    status, out, _ = post(srv, "/nudge", CASES["path_arc_up"]["request"])
    assert status == 200 and out["status"] == "proposed"
    status, entry, _ = post(srv, "/judge", {"verdict": "accepted"})
    assert status == 200
    assert entry["kind"] == "plate" and entry["deviation_mm"] == 0.0
    assert entry["formal"].startswith("Member M1, softwood, a plate 38 mm thick (from the request) built from the designer's strokes (path)")
    assert "Deviation from intent 0 mm at most." in entry["formal"]
    assert entry["intent"]["drawn"] == ["path"] and "path" not in entry["intent"]
    assert not {"grid", "stations", "normals", "intent_grid"} & set(entry["form"])
    assert entry["billet_m3"] > entry["part_m3"] > 0


def test_a_bad_plate_is_a_400_with_a_reason(srv):
    req = {"intent": {"kind": "plate", "member_id": "M1", "path": [[0, 0, 0]], "profile_start": None,
                      "profile_end": None, "thickness_mm": 38}, "holds": []}
    status, out, _ = raw(srv, "POST", "/nudge", req)
    assert status == 400 and out["error"] == "path must be null or hold 2 to 400 points"
    status, out, _ = raw(srv, "POST", "/nudge", {"intent": {"kind": "slab", "member_id": "M1"}})
    assert status == 400 and "'plate'" in out["error"]
