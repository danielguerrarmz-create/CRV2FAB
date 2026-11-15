import anthropic
import httpx
import pytest

from conftest import FakeClient, intent, reply
from gnj_nudge import agent
from gnj_nudge.intent import Holds


def test_a_buildable_model_proposal_is_used_and_deviation_is_ours(cards):
    fake = FakeClient([reply(2450, 4, 9.5)])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "model"
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert r.deviation_mm == 0
    assert len(fake.calls) == 1


def test_three_unbuildable_proposals_end_in_the_fallback(cards):
    bad = reply(2450, 1, 38)  # solid at 2450: fails the bend ratio
    fake = FakeClient([bad, bad, bad])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "rules"
    assert len(fake.calls) == agent.MAX_ATTEMPTS == 3
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert len(r.rejected_proposals) == 3
    # The checker's words were fed back on each retry.
    assert "needs a radius of 7600 mm" in fake.calls[1]["messages"][-1]["content"]
    assert len(fake.calls[2]["messages"]) == 5


def test_a_model_that_ignores_a_hold_is_rejected(cards):
    # Buildable (4 x 9.5 at 2450 passes every card) but the designer holds solid.
    ignores = reply(2450, 4, 9.5)
    fake = FakeClient([ignores, ignores, ignores])
    r = agent.nudge(intent(2450), Holds(["solid"]), cards, fake)
    assert r.source == "rules"
    assert (r.form.n_lamellas, r.form.radius_mm) == (1, 7600)
    assert "holding solid" in fake.calls[1]["messages"][-1]["content"]


def test_a_model_that_corrects_itself_after_a_hold_failure_is_used(cards):
    fake = FakeClient([reply(2450, 4, 9.5), reply(7600, 1, 38, "Kept it solid, so the curve opens up.")])
    r = agent.nudge(intent(2450), Holds(["solid"]), cards, fake)
    assert r.source == "model"
    assert (r.form.n_lamellas, r.form.radius_mm) == (1, 7600)
    assert r.deviation_mm > 0


def test_a_model_that_moves_a_held_shape_is_rejected(cards):
    moved = reply(7600, 1, 38)  # buildable, but 2450 was held
    fake = FakeClient([moved, moved, moved])
    r = agent.nudge(intent(2450), Holds(["shape"]), cards, fake)
    assert r.source == "rules"
    assert (r.form.radius_mm, r.deviation_mm) == (2450, 0)


def test_conflicts_are_decided_without_asking_the_model(cards):
    fake = FakeClient([])
    r = agent.nudge(intent(2450), Holds(["solid", "shape"]), cards, fake)
    assert r.status == "conflict"
    assert r.source == "rules"
    assert fake.calls == []


def test_no_client_means_solver_only(cards):
    r = agent.nudge(intent(2450), Holds(), cards, None)
    assert r.source == "rules"
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)


def test_no_api_key_means_no_client(monkeypatch):
    # Since the keyless decision the API backend is opt-in (GNJ_BACKEND=api); without a key it is off.
    monkeypatch.setenv("GNJ_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert agent.make_client() is None


def test_an_api_error_falls_back_at_once(cards):
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    fake = FakeClient([err])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "rules"
    assert len(fake.calls) == 1


def test_a_refusal_falls_back_at_once(cards):
    fake = FakeClient(["refusal"])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "rules"
    assert len(fake.calls) == 1


def test_unreadable_replies_count_as_failed_attempts(cards):
    fake = FakeClient([{"radius_mm": "tight"}, {"nonsense": 1}, reply(2450, 4, 9.5)])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert r.source == "model"
    assert len(fake.calls) == 3


def test_model_text_is_de_dashed_and_capped(cards):
    fake = FakeClient([reply(2450, 4, 9.5, "Your curve holds \u2014 four glued layers." + "x" * 500,
                             steps=[{"tag": "Decision", "text": "a \u2013 b", "limit_id": "invented"}])])
    r = agent.nudge(intent(2450), Holds(), cards, fake)
    assert "\u2014" not in r.sentence and "\u2013" not in r.steps[0]["text"]
    assert len(r.sentence) <= 240
    assert r.steps[0]["limit_id"] is None


def test_request_shape_uses_structured_output_and_the_model_env(cards, monkeypatch):
    monkeypatch.delenv("GNJ_MODEL", raising=False)
    fake = FakeClient([reply(2450, 4, 9.5)])
    agent.nudge(intent(2450), Holds(), cards, fake)
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in kw  # forced tool choice is a 400 on this model
    monkeypatch.setenv("GNJ_MODEL", "claude-sonnet-5-5")
    fake = FakeClient([reply(2450, 4, 9.5)])
    agent.nudge(intent(2450), Holds(), cards, fake)
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"
