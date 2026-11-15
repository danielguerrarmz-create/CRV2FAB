"""The core keeps full speed on Windows and its pool workers die with it (2026-11-14, timing a split
part started the way the Rhino client starts the core). See gnj_nudge/winpower.py."""
import subprocess
import sys
import time

import pytest

from gnj_nudge import winpower

win_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")


@win_only
def test_windows_accepts_the_throttling_opt_out():
    assert winpower.keep_full_speed() is True


def test_the_server_opts_out_when_it_is_made(monkeypatch, tmp_path):
    from gnj_nudge import server
    calls = []
    monkeypatch.setattr(winpower, "keep_full_speed", lambda: calls.append(1) or True)
    srv = server.make_server("127.0.0.1", 0, client=None, record_path=tmp_path / "r.jsonl")
    srv.server_close()
    assert calls == [1]


def test_pool_workers_start_with_the_worker_init():
    from gnj_nudge import pieces
    src = open(pieces.__file__, encoding="utf-8").read()
    assert "ProcessPoolExecutor(max_workers=_workers(), initializer=worker_init)" in src


@win_only
def test_a_worker_exits_when_its_parent_is_killed():
    # A parent python starts a grandchild that runs exit_with_parent and then sleeps; killing the
    # parent must end the grandchild within a few seconds.
    child_code = ("import sys, time; sys.path.insert(0, %r); from gnj_nudge import winpower; "
                  "assert winpower.exit_with_parent(); print('ready', flush=True); time.sleep(60)")
    parent_code = ("import subprocess, sys, time; "
                   "p = subprocess.Popen([sys.executable, '-c', %r], stdout=subprocess.PIPE, text=True); "
                   "print(p.pid, flush=True); print(p.stdout.readline().strip(), flush=True); time.sleep(60)")
    import gnj_nudge
    from pathlib import Path
    root = str(Path(gnj_nudge.__file__).resolve().parent.parent)
    parent = subprocess.Popen([sys.executable, "-c", parent_code % (child_code % root)], stdout=subprocess.PIPE,
                              text=True)
    try:
        pid = int(parent.stdout.readline())
        assert parent.stdout.readline().strip() == "ready"
        parent.kill()
        parent.wait()
        end = time.time() + 10
        while time.time() < end and _alive(pid):
            time.sleep(0.2)
        assert not _alive(pid)
    finally:
        if parent.poll() is None:
            parent.kill()


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out
