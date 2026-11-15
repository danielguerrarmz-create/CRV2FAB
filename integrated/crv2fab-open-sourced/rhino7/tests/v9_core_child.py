# -*- coding: utf-8 -*-
"""The core for the v9 smoke (tests/smoke_v9.py), run as a child process. CPython 3.

    python tests/v9_core_child.py <core_dir> <port> <record_path>

core_dir is a committed export of gnj-nudge-core (never a folder a builder edits); the port is the
smoke's own (never 8742). Words and photos go to the core's own fake Claude Code child
(core_dir/tests/fake_claude_stream.py), so no model is called: a photo always reads as the bends in
FAKE_CLAUDE_PAYLOAD, and typed words fall back to the core's keyword reading.
"""
import os
import sys

core_dir, port, record = sys.argv[1], int(sys.argv[2]), sys.argv[3]
assert port != 8742, "the smoke never uses Daniel's port"
sys.path.insert(0, core_dir)
os.environ.setdefault("FAKE_CLAUDE_MODE", "good")
os.environ.setdefault("FAKE_CLAUDE_PAYLOAD", '{"reads_as": "member", "confident": true, "bends": '
                                             '[{"span": "whole", "direction": "up", "size": "moderate"}]}')
for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SHOW_MACHINE"):
    os.environ.pop(k, None)

from gnj_nudge import server  # noqa: E402
from gnj_nudge.claude_code import ClaudeCodeClient  # noqa: E402
from gnj_nudge.pieces import enable_pool  # noqa: E402

if __name__ == "__main__":
    enable_pool()   # as the core's own main() does
    fake = ClaudeCodeClient([sys.executable, os.path.join(core_dir, "tests", "fake_claude_stream.py")], timeout_s=20)
    srv = server.make_server("127.0.0.1", port, client=fake, record_path=record)
    srv.serve_forever()
