"""Stands in for the Claude Code executable in tests. Behaviour from FAKE_CLAUDE_MODE:
good | garbage | exit | hang | huge | is_error. FAKE_CLAUDE_PAYLOAD is the structured answer;
FAKE_CLAUDE_LOG receives what the child saw (argv, cwd and its contents, env names, stdin)."""
import json
import os
import subprocess
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "good")
stdin = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
record = {"argv": sys.argv[1:], "cwd": os.getcwd(), "cwd_listing": os.listdir(os.getcwd()),
          "env": sorted(os.environ), "stdin": stdin, "pid": os.getpid()}

if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    record["grandchild_pid"] = child.pid
if log:
    with open(log, "w", encoding="utf-8") as fh:
        json.dump(record, fh)

if mode == "good":
    time.sleep(float(os.environ.get("FAKE_CLAUDE_DELAY", "0")))
    payload = json.loads(os.environ["FAKE_CLAUDE_PAYLOAD"])
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn",
                      "result": json.dumps(payload), "structured_output": payload}))
elif mode == "garbage":
    print("I would love to help with that timber!")
elif mode == "exit":
    print("auth expired", file=sys.stderr)
    sys.exit(3)
elif mode == "is_error":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}))
elif mode == "huge":
    sys.stdout.write("x" * (2 * 1024 * 1024))
    sys.stdout.flush()
    time.sleep(30)
elif mode == "hang":
    time.sleep(120)
