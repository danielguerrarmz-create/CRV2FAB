"""The keyless backend: Claude Code run headless as a child process. A fake child stands in
for the real executable; the live check is run by hand (see the commit report)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

from conftest import intent, reply
from gnj_nudge import agent
from gnj_nudge.claude_code import (INERT_FLAGS, MAX_STDOUT_BYTES, AttemptFailed, ClaudeCodeClient, child_env,
                                   find_claude, render_transcript, run_child)
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.server import make_server
from test_hardening import raw  # noqa: F401

CARDS = load_cards()
FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@pytest.fixture
def fake(monkeypatch, tmp_path):
    log = tmp_path / "child.json"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))

    def configure(mode="good", payload=None):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        monkeypatch.setenv("FAKE_CLAUDE_PAYLOAD", json.dumps(payload or reply(2450, 4, 9.5)))
        return lambda: json.loads(log.read_text(encoding="utf-8"))
    return configure


def cc(timeout_s=10):
    return ClaudeCodeClient(FAKE, timeout_s=timeout_s)


# ---- good answer, and what the child is allowed to see ---------------------------------------

def test_a_good_answer_is_used_and_tagged_claude_code(fake):
    seen = fake("good")
    r = agent.nudge(intent(2450), Holds(), CARDS, cc())
    assert r.source == "claude-code"
    assert (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert isinstance(r.model_ms, int) and r.model_ms >= 0
    assert r.as_dict(intent(2450))["model_ms"] == r.model_ms
    assert "Member M1" in seen()["stdin"]


def test_the_child_is_launched_inert(fake, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "parent-session-secret")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    monkeypatch.delenv("GNJ_MODEL", raising=False)
    seen = fake("good")
    agent.nudge(intent(2450), Holds(), CARDS, cc())
    s = seen()
    argv = s["argv"]
    assert argv[:len(INERT_FLAGS)] == INERT_FLAGS
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    for flag in ("--strict-mcp-config", "--safe-mode", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--model") + 1] == "opus"
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"][0] == "radius_mm"
    assert "--system-prompt" in argv
    for forbidden in ("--mcp-config", "--add-dir", "--dangerously-skip-permissions", "--allowedTools",
                      "--allow-dangerously-skip-permissions", "--continue", "--resume"):
        assert forbidden not in argv
    # A fresh empty directory, not this repo, and gone afterwards.
    assert s["cwd_listing"] == []
    assert Path(s["cwd"]).name.startswith("gnj-claude-")
    assert not Path(s["cwd"]).exists()
    assert Path.cwd().resolve() != Path(s["cwd"]).resolve()
    # The parent's session variables and any key are not passed on.
    for name in ("CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDECODE", "ANTHROPIC_API_KEY"):
        assert name not in s["env"]


def test_gnj_model_overrides_the_opus_alias(fake, monkeypatch):
    monkeypatch.setenv("GNJ_MODEL", "sonnet")
    seen = fake("good")
    agent.nudge(intent(2450), Holds(), CARDS, cc())
    argv = seen()["argv"]
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_child_env_strips_session_variables(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "x")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "keep-me")
    env = child_env()
    assert "CLAUDE_CODE_SESSION_ID" not in env and env["CLAUDE_CONFIG_DIR"] == "keep-me"


# ---- failures are failed attempts, then the solver ---------------------------------------------

@pytest.mark.parametrize("mode", ["garbage", "exit", "is_error"])
def test_a_bad_child_is_a_failed_attempt_and_ends_in_the_solver(fake, mode):
    fake(mode)
    r = agent.nudge(intent(2450), Holds(), CARDS, cc())
    assert r.source == "rules" and (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert len(r.rejected_proposals) == 3
    assert all("error" in t for t in r.rejected_proposals)
    assert r.model_ms is not None


def test_an_unbuildable_answer_is_judged_like_the_sdk_path(fake):
    seen = fake("good", reply(2450, 1, 38))
    r = agent.nudge(intent(2450), Holds(), CARDS, cc())
    assert r.source == "rules" and len(r.rejected_proposals) == 3
    stdin = seen()["stdin"]  # the third call carried the earlier answers and the checker's words
    assert "Your previous answer" in stdin and "needs a radius of 7600 mm" in stdin


def test_an_answer_that_repeats_an_email_address_is_refused(fake):
    fake("good", reply(2450, 4, 9.5, sentence="Glued for someone@example.com, four layers."))
    r = agent.nudge(intent(2450), Holds(), CARDS, cc())
    assert r.source == "rules"
    assert "email" not in json.dumps(r.as_dict(intent(2450))).lower()


# ---- hang past the timeout: the whole process tree is gone ---------------------------------------

def test_a_hang_is_killed_with_its_whole_process_tree(fake, tmp_path):
    seen = fake("hang")
    t = time.perf_counter()
    with pytest.raises(AttemptFailed, match="timed out"):
        run_child(FAKE, "hello", 2.0, str(tmp_path))
    assert time.perf_counter() - t < 15
    s = seen()
    time.sleep(0.5)
    assert not alive(s["pid"]), "child still running"
    assert not alive(s["grandchild_pid"]), "grandchild still running"


def test_a_timeout_stops_the_loop_after_one_attempt(fake):
    # Gojo 2: offline used to cost three timeouts of dead air; a timeout means the next one will too.
    seen = fake("hang")
    t = time.perf_counter()
    r = agent.nudge(intent(2450), Holds(), CARDS, cc(timeout_s=1.5))
    elapsed = time.perf_counter() - t
    assert r.source == "rules" and len(r.rejected_proposals) == 1
    assert "timed out" in r.rejected_proposals[0]["error"]
    assert elapsed < 6 and r.model_ms >= 1400
    time.sleep(0.5)
    assert not alive(seen()["grandchild_pid"])


def test_a_missing_executable_is_a_failed_attempt_not_a_crash(tmp_path):
    # Gojo 1: an OSError from Popen (missing, or swapped mid-run by an auto-update) used to escape
    # model_loop and become an HTTP 500.
    gone = ClaudeCodeClient([str(tmp_path / "no-such-claude.exe")])
    r = agent.nudge(intent(2450), Holds(), CARDS, gone)
    assert r.source == "rules" and (r.form.n_lamellas, r.form.lamella_mm) == (4, 9.5)
    assert all("could not start claude" in x["error"] for x in r.rejected_proposals)


def test_the_email_guard_needs_a_real_address_shape():
    # Gojo 4: "4@9.5 mm" (four at 9.5) is not an address and must not refuse an answer.
    from gnj_nudge.agent import _EMAIL, _clean
    assert _clean("Pressed from 4@9.5 mm layers.", 240) == "Pressed from 4@9.5 mm layers."
    for text in ("4@9.5 mm", "3@12.67", "x@y", "38 x 89 mm"):
        assert not _EMAIL.search(text), text
    for text in ("someone@example.com", "first.last+tag@mail.utexas.edu"):
        assert _EMAIL.search(text), text
        with pytest.raises(ValueError):
            _clean(f"Made for {text}.", 240)


def test_oversized_output_is_cut_off_and_the_child_killed(fake, tmp_path):
    seen = fake("huge")
    t = time.perf_counter()
    with pytest.raises(AttemptFailed, match="size cap"):
        run_child(FAKE, "hello", 20.0, str(tmp_path))
    assert time.perf_counter() - t < 15  # cut off long before the child's own 30 s sleep
    time.sleep(0.5)
    assert not alive(seen()["pid"])
    assert MAX_STDOUT_BYTES < 2 * 1024 * 1024


# ---- surfaces go through the same backend ---------------------------------------------------------

def test_a_surface_choice_from_claude_code(fake):
    from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
    fake("good", {"smoothing_passes": 0, "lam_mm": 17, "straight_billet": False,  # v4 schema, v6 layers
                  "sentence": "Pressed from glued layers, then milled to shape.",
                  "steps": [{"tag": "Decision", "text": "Layers.", "limit_id": "bend_ratio"}]})
    i = SurfaceIntent.build("M1", Surface(GRID_N, GRID_N, saddle()["points"]), [(0.15, 0.5), (0.85, 0.5)])
    r = agent.nudge(i, Holds(), CARDS, cc())
    assert r.source == "claude-code" and r.form.n_lamellas == 3 and r.as_dict()["model_ms"] is not None


# ---- choosing the backend -----------------------------------------------------------------------

def test_backend_selection(monkeypatch, tmp_path):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("GNJ_CLAUDE_PATH", str(exe))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GNJ_BACKEND", raising=False)
    assert isinstance(agent.make_client(), ClaudeCodeClient)  # default when claude is found
    monkeypatch.setenv("GNJ_BACKEND", "solver")
    assert agent.make_client() is None
    monkeypatch.setenv("GNJ_BACKEND", "api")
    assert agent.make_client() is None  # never without a key
    monkeypatch.setenv("GNJ_BACKEND", "carrier-pigeon")
    with pytest.raises(ValueError):
        agent.make_client()
    monkeypatch.delenv("GNJ_BACKEND")
    monkeypatch.setenv("GNJ_CLAUDE_PATH", str(tmp_path / "missing.exe"))
    assert agent.make_client() is None  # no claude: solver


def test_an_npm_cmd_shim_is_resolved_to_the_real_exe(monkeypatch, tmp_path):
    real = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"")
    shim = tmp_path / "claude.cmd"
    shim.write_text('@ECHO off\nGOTO start\n:start\n"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\n',
                    encoding="utf-8")
    monkeypatch.delenv("GNJ_CLAUDE_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: str(shim) if name == "claude" else None)
    assert find_claude() == [str(real)]


def test_the_transcript_carries_earlier_attempts():
    from types import SimpleNamespace
    t = render_transcript([{"role": "user", "content": "Bend M1."},
                           {"role": "assistant", "content": [SimpleNamespace(type="text", text='{"radius_mm": 1}')]},
                           {"role": "user", "content": "That form fails: too tight."}])
    assert t.index("Request:") < t.index("Your previous answer:") < t.index("Feedback:")
    assert t.endswith("Answer again with one corrected JSON object.")


# ---- the server shows source and model_ms ----------------------------------------------------------

def test_server_reports_claude_code_source_and_model_ms(fake, tmp_path):
    import threading
    fake("good")
    srv = make_server("127.0.0.1", 0, cards=CARDS, client=cc(), record_path=tmp_path / "r.jsonl",
                      proposer=True)  # v5: the model proposes forms only when switched on
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        from types import SimpleNamespace
        s = SimpleNamespace(port=srv.server_address[1])
        status, out, _ = raw(s, "POST", "/nudge", {"intent": {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450,
                                                              "direction": "up"}, "holds": []})
        assert status == 200 and out["source"] == "claude-code" and isinstance(out["model_ms"], int)
    finally:
        srv.shutdown()
        srv.server_close()


def test_solver_only_answers_say_no_model_time(tmp_path):
    r = agent.nudge(intent(2450), Holds(), CARDS, None)
    assert r.model_ms is None and r.as_dict(intent(2450))["model_ms"] is None


# ---- Gojo 3: model prose is never shown, even on the model-proposes path ---------------------------

def test_model_words_are_kept_for_debug_only_and_rule_text_is_shown(fake, monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    fake("good", reply(2450, 4, 9.5, sentence="Totally unchecked model prose, 2113 mm long.",
                       steps=[{"tag": "Invented", "text": "Free text.", "limit_id": "bend_ratio"}]))
    srv = make_server("127.0.0.1", 0, cards=CARDS, client=cc(), record_path=tmp_path / "r.jsonl",
                      proposer=True)  # v5: the model proposes forms only when switched on
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    body = {"intent": {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "direction": "up"}, "holds": []}
    try:
        s = SimpleNamespace(port=srv.server_address[1])
        monkeypatch.delenv("GNJ_LOG", raising=False)
        _, out, _ = raw(s, "POST", "/nudge", body)
        assert out["source"] == "claude-code"
        assert out["sentence"] == "Your curve holds. Made from 4 glued layers in place of one solid piece."
        assert "unchecked" not in json.dumps(out) and "Invented" not in json.dumps(out) and "debug" not in out
        monkeypatch.setenv("GNJ_LOG", "1")
        _, out, _ = raw(s, "POST", "/nudge", body)
        assert out["debug"]["model_text"]["sentence"].startswith("Totally unchecked")
        assert out["sentence"].startswith("Your curve holds.")
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_surface_model_answer_shows_the_rule_sentence(fake):
    from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
    fake("good", {"smoothing_passes": 0, "lam_mm": 17, "straight_billet": False, "sentence": "Model words here.",
                  "steps": [{"tag": "Decision", "text": "Layers.", "limit_id": "lam_ratio"}]})
    i = SurfaceIntent.build("M1", Surface(GRID_N, GRID_N, saddle()["points"]), [(0.15, 0.5), (0.85, 0.5)])
    r = agent.nudge(i, Holds(), CARDS, cc())
    assert r.source == "claude-code"
    assert r.sentence == "Your line holds. Pressed in one curve from 3 layers, then milled to shape."
    assert r.model_text["sentence"] == "Model words here."


# ---- Gojo 2: threads, so the server answers while a model call is in flight ------------------------

def test_the_server_answers_other_requests_while_a_model_call_is_in_flight(fake, monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "2.5")
    fake("good")
    srv = make_server("127.0.0.1", 0, cards=CARDS, client=cc(), record_path=tmp_path / "r.jsonl",
                      proposer=True)  # v5: the model proposes forms only when switched on
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s = SimpleNamespace(port=srv.server_address[1])
    body = {"intent": {"member_id": "M1", "chord_mm": 2400, "radius_mm": 2450, "direction": "up"}, "holds": []}
    done = []
    try:
        t0 = time.perf_counter()
        workers = [threading.Thread(target=lambda: done.append(raw(s, "POST", "/nudge", body)[0])) for _ in range(2)]
        for w in workers:
            w.start()
        time.sleep(0.5)
        t = time.perf_counter()
        assert raw(s, "GET", "/record")[0] == 200 and raw(s, "GET", "/taste")[0] == 200
        assert time.perf_counter() - t < 1.0  # not queued behind the model call
        for w in workers:
            w.join(timeout=20)
        assert done == [200, 200]
        assert time.perf_counter() - t0 < 4.8  # two 2.5 s calls ran side by side, not one after the other
    finally:
        srv.shutdown()
        srv.server_close()
