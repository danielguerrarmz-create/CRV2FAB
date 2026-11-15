"""Regression tests for Gojo's review of 04c454c. One section per finding."""
import http.client
import itertools
import json
import threading
from types import SimpleNamespace

import pytest

from conftest import FakeClient, intent, reply
from gnj_nudge import agent
from gnj_nudge.intent import Holds, Intent
from gnj_nudge.server import MAX_BODY, make_server

INTENT = {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "direction": "up"}


@pytest.fixture
def srv(cards, tmp_path):
    s = make_server("127.0.0.1", 0, cards=cards, client=None, record_path=tmp_path / "rec.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield SimpleNamespace(port=s.server_address[1], state=s.gnj_state, record=tmp_path / "rec.jsonl")
    s.shutdown()
    s.server_close()


def raw(srv, method, path, body=None, headers=None, length="auto"):
    """Full control of the request line and headers. Returns (status, parsed body or None)."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.putrequest(method, path, skip_accept_encoding=True)
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    if length == "auto" and data is not None:
        length = str(len(data))
    if length not in (None, "auto"):
        conn.putheader("Content-Length", length)
    for k, v in (headers or {}).items():
        conn.putheader(k, v)
    conn.endheaders(data)
    r = conn.getresponse()
    text = r.read()
    conn.close()
    return r.status, (json.loads(text) if text else None), r


# ---- 1. client timeout, one retry, and a wall-clock budget ------------------

def test_client_is_built_with_a_short_timeout_and_one_retry(monkeypatch):
    monkeypatch.setenv("GNJ_BACKEND", "api")  # opt-in since the keyless decision
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    c = agent.make_client()
    assert c.timeout == 20
    assert c.max_retries == 1


def test_the_propose_loop_hands_over_to_the_solver_when_the_budget_is_spent(cards):
    ticks = itertools.count(0, 30)  # every clock read is 30 s later
    bad = reply(2450, 1, 38)
    fake = FakeClient([bad, bad, bad])
    r = agent.nudge(intent(2450), Holds(), cards, fake, clock=lambda: next(ticks))
    assert r.source == "rules"
    assert len(fake.calls) == 1  # 30 s in, 15 s left: one call; 60 s in: budget gone
    # The one call may not outlive the budget, even with its retry: 15 s left / 2 tries.
    assert fake.calls[0]["timeout"] <= 7.5


# ---- 2. any surprise in a model reply is a failed attempt, never a crash ----

GARBAGE = [
    {**reply(2450, 4, 9.5), "steps": "not a list"},
    {**reply(2450, 4, 9.5), "steps": [1, 2]},
    {**reply(2450, 4, 9.5), "steps": [{"tag": "Check", "text": "x", "limit_id": ["bend_ratio"]}]},
    reply(2450, 10**400, 9.5),
    reply(2450, "4", 9.5),
    reply(float("nan"), 4, 9.5),
    reply(-2450, 4, 9.5),
    reply(2450, 0, 9.5),
    reply(2450, 4, -9.5),
    reply(2450, 4, 9.0),  # 4 x 9 = 36, not the 38 mm stock
    {**reply(2450, 4, 9.5), "sentence": 5},
    [1, 2, 3],
    "just text",
]


@pytest.mark.parametrize("bad", GARBAGE, ids=range(len(GARBAGE)))
def test_garbage_replies_end_in_the_solver(cards, bad):
    fake = FakeClient([bad, bad, bad])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "rules"
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert len(fake.calls) == 3


# ---- 3. buildable but far is wrong: closeness to the intent ------------------

def test_a_buildable_form_further_than_the_solvers_is_refused(cards):
    far = reply(7600, 1, 38)  # solid at 7600 passes every card, but 2450 can be kept exactly
    fake = FakeClient([far, far, far])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "rules"
    assert r.deviation_mm == 0
    assert "Stay closer" in fake.calls[1]["messages"][-1]["content"]


def test_with_a_hold_the_model_must_still_match_the_solvers_closeness(cards):
    wider = reply(8000, 1, 38)  # solid, buildable, but further than the solver's 7600
    fake = FakeClient([wider, wider, wider])
    r = agent.nudge(intent(2450), Holds(["solid"]), cards, fake)
    assert r.source == "rules"
    assert r.form.radius_mm == 7600


def test_a_model_form_as_close_as_the_solvers_is_accepted(cards):
    fake = FakeClient([reply(1900, 4, 9.5)])
    r = agent.nudge(intent(1500), Holds(), cards, fake)
    assert r.source == "model"


def test_a_model_form_half_a_millimetre_further_is_on_the_line(cards):
    from gnj_nudge.limits import deviation_mm
    base = deviation_mm(1500, 1900, 2400)
    # Find the radius whose deviation is base + 0.5 and base + 0.6 (deviation grows with radius here).
    def radius_for(extra):
        lo, hi = 1900.0, 3000.0
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if deviation_mm(1500, mid, 2400) < base + extra else (lo, mid)
        return lo
    on = agent.nudge(intent(1500), Holds(), cards, FakeClient([reply(radius_for(0.5), 4, 9.5)]))
    assert on.source == "model"
    past = reply(radius_for(0.6), 4, 9.5)
    over = agent.nudge(intent(1500), Holds(), cards, FakeClient([past, past, past]))
    assert over.source == "rules"


# ---- 4. no NaN or Infinity, and sane intent bounds ----------------------------

@pytest.mark.parametrize("field,value,ok", [
    ("radius_mm", 1200, True), ("radius_mm", 1199.9, False),
    ("radius_mm", 1_000_000, True), ("radius_mm", 1_000_001, False),
    ("chord_mm", 2400, True), ("chord_mm", 2400.1, False),
    ("chord_mm", 0, False), ("chord_mm", -5, False),
    ("radius_mm", True, False), ("radius_mm", "2450", False), ("radius_mm", 10**400, False),
])
def test_intent_numbers_are_bounded(srv, field, value, ok):
    s, body, _ = raw(srv, "POST", "/nudge", {"intent": {**INTENT, field: value}, "holds": []})
    assert (s == 200) if ok else (s == 400 and "error" in body)


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity", b"1e400"])
def test_non_finite_numbers_in_the_body_are_a_400(srv, literal):
    body = b'{"intent":{"member_id":"M1","chord_mm":2400,"radius_mm":' + literal + b',"direction":"up"},"holds":[]}'
    s, out, _ = raw(srv, "POST", "/nudge", body)
    assert s == 400 and "error" in out


def test_a_nan_in_a_result_is_never_sent(srv, monkeypatch, cards):
    real_nudge = agent.nudge

    def nan_nudge(i, h, c, client, **kw):
        r = real_nudge(i, h, c, None)
        r.deviation_mm = float("nan")
        return r
    monkeypatch.setattr(agent, "nudge", nan_nudge)
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request("POST", "/nudge", json.dumps({"intent": INTENT, "holds": []}), {"Content-Type": "application/json"})
    r = conn.getresponse()
    text = r.read().decode()
    assert r.status == 500 and "NaN" not in text
    assert srv.state.last is None  # nothing half-remembered for /judge


# ---- 5. bad bodies are 400 JSON; surprises are 500 JSON without a trace -------

@pytest.mark.parametrize("body", [
    {"intent": INTENT, "holds": [["solid"]]},
    {"intent": INTENT, "holds": [{"a": 1}]},
    {"intent": INTENT, "holds": [1]},
    {"intent": INTENT, "holds": "solid"},
    {"intent": [INTENT]},
    {"intent": {**INTENT, "member_id": 7}},
    b"[" * 30000 + b"]" * 30000,
    b"\xff\xfe not utf8",
    [1, 2],
], ids=["hold-list", "hold-object", "hold-int", "holds-string", "intent-list", "member-int",
        "nested-30000", "not-utf8", "body-list"])
def test_bad_bodies_are_a_400_json_error(srv, body):
    s, out, _ = raw(srv, "POST", "/nudge", body)
    assert s == 400 and isinstance(out.get("error"), str)


@pytest.mark.parametrize("body", [{"verdict": 5}, {"verdict": "rejected", "hold": ["solid"]},
                                  {"verdict": "rejected", "hold": {"x": 1}}, {"verdict": "maybe"}])
def test_bad_judge_bodies_are_a_400_and_keep_the_proposal(srv, body):
    raw(srv, "POST", "/nudge", {"intent": INTENT, "holds": []})
    s, out, _ = raw(srv, "POST", "/judge", body)
    assert s == 400 and "error" in out
    assert srv.state.last is not None


def test_an_unexpected_exception_is_a_500_json_body_with_no_trace(srv, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(agent, "nudge", boom)
    s, out, _ = raw(srv, "POST", "/nudge", {"intent": INTENT, "holds": []})
    assert s == 500 and out == {"error": "internal error"}


# ---- 6. Content-Length is checked before reading -----------------------------

@pytest.mark.parametrize("length,status", [(None, 400), ("-1", 400), ("abc", 400), ("\u00b2", 400),
                                           (str(MAX_BODY + 1), 413)])
def test_content_length_is_checked_before_reading(srv, length, status):
    s, out, _ = raw(srv, "POST", "/nudge", b'{"intent":{}}', length=length)
    assert s == status and "error" in out


def test_a_missing_content_length_is_named(srv):
    s, out, _ = raw(srv, "POST", "/judge", None, length=None)
    assert s == 400 and "Content-Length" in out["error"]


# ---- 7. a foreign Origin gets 403 on every method, before anything runs -------

@pytest.mark.parametrize("origin", ["http://evil.example", "null", "https://localhost",
                                    "http://localhost.evil.example", "http://127.0.0.1.evil.example:80"])
@pytest.mark.parametrize("method,path", [("GET", "/record"), ("POST", "/nudge"), ("POST", "/judge"),
                                         ("OPTIONS", "/nudge")])
def test_a_foreign_origin_is_refused(srv, origin, method, path):
    body = {"intent": INTENT, "holds": []} if method == "POST" else None
    s, _, r = raw(srv, method, path, body, headers={"Origin": origin})
    assert s == 403
    assert r.getheader("Access-Control-Allow-Origin") is None


def test_a_foreign_judge_writes_nothing_and_leaves_the_proposal(srv):
    raw(srv, "POST", "/nudge", {"intent": INTENT, "holds": []})
    s, _, _ = raw(srv, "POST", "/judge", {"verdict": "accepted"}, headers={"Origin": "http://evil.example"})
    assert s == 403
    assert not srv.record.exists()
    assert srv.state.last is not None
    s, _, _ = raw(srv, "POST", "/judge", {"verdict": "accepted"})  # no Origin: the Rhino script
    assert s == 200


@pytest.mark.parametrize("origin", ["http://localhost", "http://localhost:5173", "http://127.0.0.1:8080"])
def test_a_local_origin_is_allowed(srv, origin):
    s, _, r = raw(srv, "GET", "/record", headers={"Origin": origin})
    assert s == 200 and r.getheader("Access-Control-Allow-Origin") == origin


# ---- 8. member_id is a short plain identifier ----------------------------------

@pytest.mark.parametrize("member_id,ok", [
    ("M1", True), ("beam_02-A", True), ("a" * 32, True),
    ("a" * 33, False), ("", False), ("M 1", False), ("M1;rm", False), ("M1\n", False),
    ("Mé", False), ("../M1", False),
])
def test_member_id_is_letters_digits_underscore_hyphen(srv, member_id, ok):
    s, _, _ = raw(srv, "POST", "/nudge", {"intent": {**INTENT, "member_id": member_id}, "holds": []})
    assert s == (200 if ok else 400)
    if not ok:
        with pytest.raises(ValueError):
            Intent(member_id, 2400, 2450, "up")
