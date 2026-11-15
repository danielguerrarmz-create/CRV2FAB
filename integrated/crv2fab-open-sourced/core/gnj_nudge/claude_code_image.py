"""v8: an image to the keyless backend (Claude Code run headless), without widening the child.

`claude -p` takes an image only as a content block on stdin, with `--input-format stream-json`
(documented in the Agent SDK "Streaming Input" page; the CLI refuses that input format unless
the output is `--output-format stream-json`, which in turn requires `--verbose`). So the image
travels as base64 inside one JSON line on the child's stdin: it is never written to disk, and the
child gets no file tool, no path and no directory to read. Every other inert flag of claude_code.py
is unchanged.

The child reports what it was started with in its first event (`system`/`init`): its tools and
MCP servers. A child that reports any tool or server is refused as a failed attempt, so a future
CLI that widened the defaults could not slip through.
"""
from __future__ import annotations

import json
import shutil
import tempfile

from .claude_code import INERT_FLAGS, AttemptFailed, _Block, _Response, run_child

# INERT_FLAGS with the one output switch changed; all the others kept verbatim.
_i = INERT_FLAGS.index("--output-format")
IMAGE_FLAGS = INERT_FLAGS[:_i] + ["--output-format", "stream-json", "--input-format", "stream-json", "--verbose"] \
    + INERT_FLAGS[_i + 2:]
del _i

# The one tool a structured-output run lists: `--json-schema` returns its answer through a
# StructuredOutput tool call (seen live in the init event, 2026-11-14, Claude Code 2.1.325). It takes
# only the schema'd answer; it reads and writes nothing. /say's child has it too, with the same flags.
ALLOWED_CHILD_TOOLS: frozenset[str] = frozenset({"StructuredOutput"})


def has_image(messages: list[dict]) -> bool:
    return any(isinstance(m.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "image"
                                                          for b in m["content"]) for m in messages)


def stdin_line(messages: list[dict]) -> str:
    """One user message, image and text blocks only, as one stream-json line."""
    if len(messages) != 1 or messages[0].get("role") != "user":
        raise AttemptFailed("an image call takes one user message")
    blocks = []
    for b in messages[0]["content"]:
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            blocks.append({"type": "text", "text": b["text"]})
        elif b.get("type") == "image" and b.get("source", {}).get("type") == "base64":
            s = b["source"]
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": s["media_type"],
                                                       "data": s["data"]}})
        else:
            raise AttemptFailed("only base64 image and text blocks are sent")
    return json.dumps({"type": "user", "message": {"role": "user", "content": blocks},
                       "parent_tool_use_id": None}) + "\n"


def argv(client, system: str, schema: dict, effort: str | None) -> list[str]:
    args = client.command + IMAGE_FLAGS + ["--json-schema", json.dumps(schema), "--model", client.model,
                                           "--system-prompt", system]
    if effort:
        args += ["--effort", effort]
    return args


def parse_stream(out: bytes) -> tuple[dict, dict]:
    """(init event, result event) from the child's stream-json output. Raises AttemptFailed."""
    init = result = None
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        raise AttemptFailed("claude printed something that is not UTF-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            raise AttemptFailed("claude printed something that is not JSON")
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init" and init is None:
            init = ev
        elif ev.get("type") == "result":
            result = ev
    if init is None or result is None:
        raise AttemptFailed("claude did not report its start and its result")
    # Fail closed: a missing or renamed key, or any other shape, is refused like a wide child.
    tools, servers = init.get("tools"), init.get("mcp_servers")
    if (not isinstance(tools, list) or not isinstance(servers, list) or servers
            or not all(isinstance(t, str) for t in tools) or set(tools) - ALLOWED_CHILD_TOOLS):
        raise AttemptFailed("the child was not inert")
    return init, result


def call_with_image(client, system: str, messages: list[dict], output_config: dict,
                    timeout: float | None) -> _Response:
    schema = output_config["format"]["schema"]
    timeout_s = timeout or client.timeout_s
    workdir = tempfile.mkdtemp(prefix="gnj-claude-")
    try:
        code, out, _err = run_child(argv(client, system, schema, output_config.get("effort")),
                                    stdin_line(messages), timeout_s, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)  # only the directory this call created
    if code != 0:
        raise AttemptFailed(f"claude exited with code {code}")
    _init, data = parse_stream(out)
    if data.get("is_error"):
        raise AttemptFailed("claude reported an error")
    answer = data.get("structured_output")
    if not isinstance(answer, (dict, list)):
        raise AttemptFailed("claude returned no structured answer")
    stop = data.get("stop_reason")
    return _Response(stop if isinstance(stop, str) else None, [_Block("text", json.dumps(answer))])
