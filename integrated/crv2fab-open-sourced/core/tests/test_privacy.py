"""No machine data of any kind enters any prompt (spec v4, "Using their code", tightened after
Gojo's review; kept by spec v6): the keyless model path runs under Daniel's personal subscription
with his account attached. This builds every prompt the code can send, with a named machine selected,
and checks that no machine name, number or source string appears.

Spec v6: the named table lives only in the git-ignored private/machines.json. This file names no
company: it reads the private table when this computer has it, and otherwise uses a stand-in with
the same fields, so the guard runs everywhere. A last test scans every tracked file for the names."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import FakeClient, intent, reply
from gnj_nudge import agent
from gnj_nudge import settings as gs
from gnj_nudge.intent import Holds
from gnj_nudge.limits import load_cards
from gnj_nudge.surface import GRID_N, Surface, SurfaceIntent, saddle
from gnj_nudge.surface_agent import nudge_surface
from gnj_nudge.surface_solver import FabSetup

CARDS = load_cards()
ROOT = Path(__file__).resolve().parent.parent
STAND_IN = {"name": "Stand-in Mill KX-9", "openingWidth": 1234.0, "openingHeight": 321.0, "lengthMax": 17777.0,
            "source": "stand-in source string", "note": "stand-in note"}
MACHINES = gs.private_machines() or [STAND_IN]


def name_words(machines) -> set[str]:
    """Each name, and each distinctive word in it (a company or maker name on its own is a leak too)."""
    common = {"robot", "drive", "industrie", "side", "modified", "cnc"}
    out = set()
    for m in machines:
        out.add(m["name"])
        out |= {w for w in re.split(r"[\s,()/-]+", m["name"]) if len(w) > 3 and w.lower() not in common}
    return out


def forbidden_in(text: str) -> list[str]:
    """Every machine fact found in text: names, sources, notes, opening and length numbers."""
    found = []
    # Ladder rungs are pass counts, not machine data (1280 is both a rung and one machine's opening
    # width): drop exactly those fields before looking for numbers.
    numbers_text = re.sub(r'\\?"smoothing_passes\\?": -?\d+|\\?"enum\\?": \[[-\d, .]+\]', "", text)
    for m in MACHINES:
        for field in ("name", "source", "note"):
            if m.get(field) and m[field] in text:
                found.append(f"{field}: {m[field]}")
        for field in ("openingWidth", "openingHeight", "lengthMax"):
            value = m.get(field)
            if value is not None and re.search(r"(?<![\d.])%d(?:\.0)?(?![\d.])" % int(value), numbers_text):
                found.append(f"{field}: {int(value)}")
    for word in sorted(name_words(MACHINES)) + ["Knowledge Base", "KB ", ".csv", "Notion", "openingWidth",
                                                "openingHeight", "lengthMax"]:
        if word in text:
            found.append(word)
    return found


def every_text(fake: FakeClient) -> str:
    return "\n".join(c["system"] + json.dumps(c["messages"], default=str) + json.dumps(c["output_config"])
                     for c in fake.calls)


def test_the_bend_proposer_prompts_carry_no_machine_data():
    fake = FakeClient([reply(2450, 1, 38)] * 3)  # fails, so feedback prompts are sent too
    agent.nudge(intent(2450), Holds(), CARDS, fake)
    assert len(fake.calls) == 3
    assert forbidden_in(every_text(fake)) == []


def test_the_surface_proposer_prompts_carry_no_machine_data_even_after_a_machine_failure():
    # A named machine first (its own name and opening would show if anything leaked), then a small
    # opening where the rules straighten the wiggle and the model's unstraightened choice fails the
    # machine check, so a feedback prompt is sent too.
    from gnj_nudge.vectors_v4 import CASES
    surf = Surface(GRID_N, GRID_N, saddle()["points"])
    choice = {"smoothing_passes": 0, "lam_mm": 17, "straight_billet": False, "sentence": "Layers.",
              "steps": [{"tag": "Decision", "text": "Layers.", "limit_id": "lam_ratio"}]}
    straight = SurfaceIntent.build("M1", surf, [(0.15, 0.5), (0.85, 0.5)])
    fake = FakeClient([choice] * 3)
    named = FabSetup(125.0, (38.0, 17.0, 11.0), dict(MACHINES[0], openingWidth=float(MACHINES[0]["openingWidth"]),
                                                    openingHeight=float(MACHINES[0]["openingHeight"])))
    nudge_surface(straight, Holds(), None, fake, setup=named)
    wiggle = SurfaceIntent.build("M1", surf, [tuple(q) for q in dict((n, s) for n, s, _ in CASES)["sharp_wiggle"]])
    small = FabSetup(125.0, (38.0, 17.0, 11.0), dict(MACHINES[0], openingWidth=1300.0, openingHeight=150.0))
    fake_small = FakeClient([choice] * 3)
    nudge_surface(wiggle, Holds(), None, fake_small, setup=small)
    text = every_text(fake) + every_text(fake_small)
    assert len(fake_small.calls) == 3 and "does not pass the machine opening check" in text
    assert forbidden_in(text) == []


def test_the_check_itself_can_find_machine_data():
    # The guard is only meaningful if it can go red.
    m = MACHINES[0]
    leak = f"Machine: {m['name']}, opening {int(m['openingWidth'])} x {int(m['openingHeight'])} mm."
    assert len(forbidden_in(leak)) >= 3
    assert forbidden_in("radius 3000 mm, 19 mm layers, 1300.5 mm away") == []


def test_the_say_prompt_carries_no_machine_data():
    from gnj_nudge import say
    fake = FakeClient([{"actions": [{"op": "hold", "name": "solid"}], "confident": True}])
    say.read_words("no glue lines please, keep it under the machine opening", Holds(["shape"]), fake)
    assert len(fake.calls) == 1
    assert forbidden_in(every_text(fake)) == []


# ---- spec v6: no tracked file names a private machine ----------------------------------------------

def tracked_text() -> dict[str, str]:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    out = {}
    for f in filter(None, files.split("\0")):
        try:
            out[f] = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return out


@pytest.mark.skipif(not gs.private_machines(), reason="no private/machines.json on this computer")
def test_no_tracked_file_names_a_private_machine():
    words = name_words(gs.private_machines())
    leaks = {f: sorted(w for w in words if w in t) for f, t in tracked_text().items()}
    assert {f: w for f, w in leaks.items() if w} == {}


def test_the_private_table_is_ignored_by_git():
    ignored = subprocess.run(["git", "check-ignore", "-q", "private/machines.json"], cwd=ROOT).returncode
    assert ignored == 0
    assert "private/machines.json" not in tracked_text()


def test_the_tree_scan_can_find_a_name():
    # The guard is only meaningful if it can go red: a stand-in name planted in tracked text is found.
    text = tracked_text()["README.md"] + " installed on the Stand-in Mill KX-9 "
    assert {w for w in name_words([STAND_IN]) if w in text}


# ---- spec v9: the plate kind never asks a model -----------------------------------------------------

@pytest.mark.slow
def test_a_plate_never_reaches_a_model_even_with_the_proposer_on(tmp_path):
    """Slice 1 has no prompt path for a plate: its strokes, its billet and the opening stay here,
    even when the server is told to let the model propose forms."""
    import threading
    from gnj_nudge.server import make_server
    from gnj_nudge.vectors_plate import request
    from test_hardening import raw
    fake = FakeClient([])  # any call raises: the test allows none
    s = make_server("127.0.0.1", 0, client=fake, record_path=tmp_path / "r.jsonl", proposer=True)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    try:
        for name in ("path_arc_up", "too_wide_hold_solid"):  # a proposal and a conflict
            status, out, _ = raw(s, "POST", "/nudge", request(name))
            assert status == 200 and out["source"] == "rules"
    finally:
        s.shutdown()
        s.server_close()
    assert fake.calls == []


def test_say_on_a_plate_episode_sends_only_the_words_holds_and_list(tmp_path):
    """Spec v9 slice 3: /say on a plate builds the same prompt as on any kind: the designer's words,
    the holds and the closed list. No stroke, plate number, setting or machine fact reaches it."""
    import threading
    from gnj_nudge import say
    from gnj_nudge.server import make_server
    from test_hardening import raw
    fake = FakeClient([{"actions": [{"op": "hold", "name": "shape"}], "confident": True}])
    s = make_server("127.0.0.1", 0, client=fake, record_path=tmp_path / "r.jsonl")
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    s.port = s.server_address[1]
    try:
        raw(s, "POST", "/settings", {"thickness_mm": 30})
        req = {"intent": {"kind": "plate", "member_id": "M1", "path": None, "profile_start": None,
                          "profile_end": [[2400.0, -44.5, 0.0], [2400.0, 44.5, 0.0]]}, "holds": []}
        assert raw(s, "POST", "/nudge", req)[1]["status"] == "proposed"
        out = raw(s, "POST", "/say", {"text": "keep my shape exactly"})[1]
        assert out["heard"] == "Keeping your shape as drawn."
    finally:
        s.shutdown()
        s.server_close()
    assert len(fake.calls) == 1
    text = every_text(fake)
    assert fake.calls[0]["messages"][0]["content"] == say.prompt("keep my shape exactly", frozenset())
    assert forbidden_in(text) == []
    for leak in ("2400", "44.5", "thickness", "plate", "30"):
        assert leak not in fake.calls[0]["messages"][0]["content"], leak
