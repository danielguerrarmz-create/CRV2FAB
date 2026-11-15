"""Stands in for Claude Code run with --input-format/--output-format stream-json (v8 photos).
FAKE_CLAUDE_MODE: good | wide | hang | garbage | renamed | no_tools_key | servers_not_a_list. FAKE_CLAUDE_PAYLOAD is the structured answer;
FAKE_CLAUDE_LOG receives what the child saw (argv, cwd and its contents, env names, stdin)."""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "good")
stdin = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "w", encoding="utf-8") as fh:
        json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "cwd_listing": os.listdir(os.getcwd()),
                   "env": sorted(os.environ), "stdin": stdin}, fh)

if mode == "hang":
    time.sleep(120)
elif mode == "garbage":
    print("I would love to help with that photo!")
else:
    tools = ["StructuredOutput", "Read"] if mode == "wide" else ["StructuredOutput"]  # as the real CLI lists
    init = {"type": "system", "subtype": "init", "tools": tools, "mcp_servers": [], "model": "fake"}
    if mode == "renamed":  # a future CLI renaming a key must fail closed
        init["mcpServers"] = init.pop("mcp_servers")
    elif mode == "no_tools_key":
        del init["tools"]
    elif mode == "servers_not_a_list":
        init["mcp_servers"] = {}
    print(json.dumps(init))
    payload = json.loads(os.environ["FAKE_CLAUDE_PAYLOAD"])
    print(json.dumps({"type": "assistant", "message": {"content": []}}))
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn",
                      "result": "", "structured_output": payload}))
