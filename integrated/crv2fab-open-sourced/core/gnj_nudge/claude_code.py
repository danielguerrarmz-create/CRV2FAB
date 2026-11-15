"""Keyless model backend: Claude Code, already signed in on this machine, run headless.

It plugs into the same seam as the SDK client (agent.model_loop calls
client.beta.messages.create(...) and reads .stop_reason / .content), so the checker,
holds, closeness rule, 3 attempts, 45 s budget and solver fallback are unchanged.

The child is inert. Flags read from `claude --help` (Claude Code 2.1.325), not memory:
  -p --output-format json --json-schema <schema>   one structured answer, parsed from JSON
  --tools ""                                        no built-in tools at all
  --strict-mcp-config (and no --mcp-config)         no MCP servers
  --safe-mode                                       CLAUDE.md, skills, plugins, hooks, agents,
                                                    output styles off
  --setting-sources ""                              no user, project or local settings
  --no-session-persistence                          nothing saved to disk
  --permission-prompts none                         anything that would prompt is denied
  --disable-slash-commands, --system-prompt         our system prompt replaces the default one
It runs in a new empty temp directory, with the parent's Claude Code session variables
and any API key stripped from its environment. `--bare` is not used: it ignores the
signed-in session and needs an API key.

Known and not removable by any flag: Claude Code attaches the signed-in account's email
as user context. The agent therefore refuses any answer that contains an email address.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALIAS = "opus"
CALL_TIMEOUT_S = 20
MAX_STDOUT_BYTES = 256 * 1024
MAX_STDERR_BYTES = 64 * 1024

INERT_FLAGS = [
    "-p", "--output-format", "json",
    "--tools", "",
    "--strict-mcp-config",
    "--safe-mode",
    "--setting-sources", "",
    "--no-session-persistence",
    "--permission-prompts", "none",
    "--disable-slash-commands",
]

# Variables the parent Claude Code session exports that would tie the child to it
# (messaging socket and token, session ids), plus keys: this backend is keyless by decision.
_STRIP_PREFIXES = ("CLAUDECODE", "CLAUDE_CODE_")
_STRIP_NAMES = {"CLAUDE_PID", "CLAUDE_EFFORT", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}


class AttemptFailed(Exception):
    """The child failed (timeout, exit code, unreadable or oversized output). One failed attempt."""


class AttemptTimedOut(AttemptFailed):
    """The child ran past its time. The next attempt would too, so the loop stops here."""


def find_claude() -> list[str] | None:
    """The real Claude Code executable as an argument list, never a shell string.
    GNJ_CLAUDE_PATH overrides. On Windows an npm .cmd shim is read for the .exe it calls."""
    override = os.environ.get("GNJ_CLAUDE_PATH")
    if override:
        return [override] if Path(override).is_file() else None
    exe = shutil.which("claude.exe") if os.name == "nt" else None
    if exe:
        return [exe]
    found = shutil.which("claude")
    if not found:
        return None
    if found.lower().endswith((".cmd", ".bat")):
        text = Path(found).read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"%dp0%\\?([^"]+?\.exe)"', text, re.IGNORECASE)
        if not m:
            return None
        target = Path(found).parent / m.group(1).lstrip("\\/")
        return [str(target)] if target.is_file() else None
    return [found]


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_STRIP_PREFIXES) and k not in _STRIP_NAMES}
    return env


class _Job:
    """Windows Job Object with kill-on-close: closing it ends every process the child started,
    even ones still running after the child itself has exited. No-op elsewhere or on failure
    (kill_tree's taskkill /T remains the backstop)."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("R", "W", "O", "RB", "WB", "OB")]

            class EXTENDED(ctypes.Structure):
                _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return
            info = EXTENDED()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(wintypes.HANDLE(job))
                return
            self.k32, self.wt, self.handle = k32, wintypes, job
        except Exception:
            self.handle = None

    def assign(self, proc: subprocess.Popen) -> None:
        if self.handle:
            try:
                self.k32.AssignProcessToJobObject(self.wt.HANDLE(self.handle), self.wt.HANDLE(int(proc._handle)))
            except Exception:
                pass

    def close(self) -> None:
        if self.handle:
            try:
                self.k32.TerminateJobObject(self.wt.HANDLE(self.handle), 1)
                self.k32.CloseHandle(self.wt.HANDLE(self.handle))
            except Exception:
                pass
            self.handle = None


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child and everything it started, then reap it."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
            subprocess.run([taskkill, "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _read_capped(stream, cap: int, sink: list, over: threading.Event, on_over) -> None:
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                over.set()
                on_over()
                break
            sink.append(chunk)
    except Exception:
        pass


def _write_all(stream, data: bytes) -> None:
    """Feed the child's stdin on its own thread, so a child that never reads cannot hold the caller
    past the deadline (a base64 image is larger than the pipe buffer)."""
    try:
        stream.write(data)
        stream.close()
    except (OSError, ValueError):
        pass


def run_child(cmd: list[str], stdin_text: str, timeout_s: float, cwd: str) -> tuple[int, bytes, bytes]:
    """Run one child to completion. Raises AttemptFailed on timeout or oversized output;
    the whole process tree is gone before this returns."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    job = _Job()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=cwd, env=child_env(), shell=False, **kwargs)
    except OSError as e:  # missing, or swapped mid-run (an auto-update): the rules answer instead
        job.close()
        raise AttemptFailed(f"could not start claude ({type(e).__name__})")
    job.assign(proc)
    out, err, over = [], [], threading.Event()
    killer = lambda: kill_tree(proc)  # noqa: E731
    readers = [threading.Thread(target=_read_capped, args=(proc.stdout, MAX_STDOUT_BYTES, out, over, killer), daemon=True),
               threading.Thread(target=_read_capped, args=(proc.stderr, MAX_STDERR_BYTES, err, threading.Event(),
                                                           lambda: None), daemon=True),
               threading.Thread(target=_write_all, args=(proc.stdin, stdin_text.encode("utf-8")), daemon=True)]
    for t in readers:  # the two readers and the stdin writer, all under the one deadline below
        t.start()
    try:
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            raise AttemptTimedOut(f"timed out after {timeout_s:.0f} s")
        if over.is_set():
            raise AttemptFailed("output over the size cap")
    finally:
        kill_tree(proc)
        job.close()  # ends anything the child left running
        for t in readers:
            t.join(timeout=5)
    if over.is_set():
        raise AttemptFailed("output over the size cap")
    return proc.returncode, b"".join(out), b"".join(err)


@dataclass
class _Block:
    type: str
    text: str


@dataclass
class _Response:
    stop_reason: str | None
    content: list


def render_transcript(messages: list[dict]) -> str:
    """One call per attempt, no session: earlier attempts and feedback go into the prompt."""
    parts = []
    for msg in messages:
        content = msg["content"]
        if not isinstance(content, str):
            content = "\n".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")
        label = {"user": "Request" if not parts else "Feedback", "assistant": "Your previous answer"}.get(
            msg["role"], msg["role"])
        parts.append(f"{label}:\n{content}")
    if len(parts) > 1:
        parts.append("Answer again with one corrected JSON object.")
    return "\n\n".join(parts)


class _Messages:
    def __init__(self, owner: "ClaudeCodeClient"):
        self.owner = owner

    def create(self, *, system: str, messages: list[dict], output_config: dict, timeout: float | None = None,
               **_ignored) -> _Response:
        return self.owner.call(system, messages, output_config, timeout)


class ClaudeCodeClient:
    """Duck-types client.beta.messages.create(...) for agent.model_loop."""

    source = "claude-code"
    retries = 0  # no SDK retry layer: each call gets the whole per-call timeout

    def __init__(self, command: list[str], model: str | None = None, timeout_s: float = CALL_TIMEOUT_S):
        self.command = list(command)
        self.model = model or os.environ.get("GNJ_MODEL") or DEFAULT_ALIAS
        self.timeout_s = timeout_s
        self.beta = type("Beta", (), {})()
        self.beta.messages = _Messages(self)

    def argv(self, system: str, schema: dict, effort: str | None) -> list[str]:
        args = self.command + INERT_FLAGS + ["--json-schema", json.dumps(schema), "--model", self.model,
                                            "--system-prompt", system]
        if effort:
            args += ["--effort", effort]
        return args

    def call(self, system: str, messages: list[dict], output_config: dict, timeout: float | None) -> _Response:
        from .claude_code_image import call_with_image, has_image  # v8: an image never reaches render_transcript
        if has_image(messages):
            return call_with_image(self, system, messages, output_config, timeout)
        schema = output_config["format"]["schema"]
        timeout_s = min(self.timeout_s, timeout) if timeout else self.timeout_s
        workdir = tempfile.mkdtemp(prefix="gnj-claude-")
        try:
            code, out, err = run_child(self.argv(system, schema, output_config.get("effort")),
                                       render_transcript(messages), timeout_s, workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # only the directory this call created
        if code != 0:
            raise AttemptFailed(f"claude exited with code {code}")
        try:
            data = json.loads(out.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AttemptFailed("claude printed something that is not JSON")
        if not isinstance(data, dict) or data.get("is_error"):
            raise AttemptFailed("claude reported an error")
        answer = data.get("structured_output")
        text = json.dumps(answer) if isinstance(answer, (dict, list)) else data.get("result")
        if not isinstance(text, str):
            raise AttemptFailed("claude returned no answer")
        stop = data.get("stop_reason")
        return _Response(stop if isinstance(stop, str) else None, [_Block("text", text)])


def make_client() -> ClaudeCodeClient | None:
    cmd = find_claude()
    return ClaudeCodeClient(cmd) if cmd else None


if __name__ == "__main__":  # quick check: python -m gnj_nudge.claude_code
    print(find_claude() or "claude not found", file=sys.stderr)
