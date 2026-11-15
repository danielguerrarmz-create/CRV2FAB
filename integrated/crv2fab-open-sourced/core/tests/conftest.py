import json
from types import SimpleNamespace

import pytest

from gnj_nudge.winpower import keep_full_speed

keep_full_speed()  # the suite times solves: keep Windows from throttling it mid-run

from gnj_nudge.intent import Intent
from gnj_nudge.limits import load_cards


@pytest.fixture
def cards():
    return load_cards()


def intent(radius_mm, chord_mm=2400, direction="up", angle=None):
    return Intent("M1", chord_mm, radius_mm, None if angle is not None else direction, angle)


class FakeClient:
    """Stands in for anthropic.Anthropic. Each reply is a dict (sent as the JSON
    text block), an Exception (raised), or "refusal"."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        if not self.replies:
            raise AssertionError("model called more times than the test allowed")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if r == "refusal":
            return SimpleNamespace(stop_reason="refusal", content=[])
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(r))])


def reply(radius_mm, n, t, sentence="Made from glued layers so it can bend.", steps=None,
          k=1, w=89, angle=0):
    return {"radius_mm": radius_mm, "bend_angle_deg": angle, "n_lamellas": n, "lamella_mm": t,
            "n_strips": k, "strip_mm": w, "sentence": sentence,
            "steps": steps if steps is not None else [{"tag": "Decision", "text": "Laminated.", "limit_id": "bend_ratio"}]}


# ---- a quick subset: python -m pytest -m "not slow" ---------------------------------------------
# Slow = billet fits (the sc_glulam route), real child processes, deliberate waits. Measured with
# --durations on 2026-11-14: these take 0.4 s or more each.
SLOW_FILES = {"test_v4_fabrication.py", "test_claude_code.py"}  # billet fits; real child processes
SLOW_TESTS = {
    "test_vectors_file_matches_the_code", "test_a_hang_is_killed_with_its_whole_process_tree",
    "test_a_pretty_printed_400_point_request_fits_and_answers_inside_the_budget",
    "test_the_server_answers_other_requests_while_a_model_call_is_in_flight",
    "test_a_timeout_stops_the_loop_after_one_attempt", "test_without_numpy_the_waste_fields_are_absent_not_invented",
    "test_the_surface_proposer_prompts_carry_no_machine_data_even_after_a_machine_failure",
    "test_a_solid_lead_on_a_surface_never_fails_the_checker",
    "test_on_a_surface_a_solid_lead_falls_back_without_comment_when_one_piece_cannot_be_milled",
    "test_server_conflict_keeps_the_v1_shape", "test_oversized_output_is_cut_off_and_the_child_killed",
    "test_a_surface_choice_from_claude_code", "test_a_surface_model_answer_shows_the_rule_sentence",
    "test_the_tally_after_two_accepts_is_volume_weighted", "test_the_record_states_volumes_and_waste",
    "test_server_surface_nudge_then_judge", "test_returned_stations_lie_on_the_surface_after_rounding",
    "test_surface_forms_carry_volumes_and_the_rounding_share",
    "test_rejecting_a_taste_answer_and_holding_shape_moves_taste_back",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.path.name in SLOW_FILES or item.originalname in SLOW_TESTS:
            item.add_marker(pytest.mark.slow)
