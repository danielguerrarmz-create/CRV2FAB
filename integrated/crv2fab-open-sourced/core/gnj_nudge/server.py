"""Stdlib HTTP server for the Rhino plugin. Contract: README.md.

Run:  python -m gnj_nudge.server
Binds 127.0.0.1:8742 only. One designer session: the server remembers the last
proposal so /judge can record it, and forgets it once judged.

Hardening: a browser Origin that is not localhost gets 403 on every method
before anything runs; bodies need a sane Content-Length; every bad input is a
400 JSON error; anything unexpected is a 500 JSON error with no stack trace;
NaN and Infinity are never read or written.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import threading
from pathlib import Path

from . import agent, photo, say, taste
from .settings import Settings
from .intent import Holds, Intent
from .limits import load_cards
from .record import Record, make_entry
from .surface import SurfaceIntent

HOST, PORT = "127.0.0.1", 8742
# v3 raised this from 64 KB: a 21 x 21 surface plus a 400-point stroke at full float
# precision is about 50 KB compact, roughly double that pretty-printed.
MAX_BODY = 1024 * 1024  # spec v6: a part sends up to 6000 points, about 360 KB at full float precision
LOCAL_ORIGIN = re.compile(r"http://(localhost|127\.0\.0\.1)(:\d{1,5})?")

# Sane bounds for a drawn bend on the demo member.
RADIUS_MIN_MM, RADIUS_MAX_MM = 1200, 1_000_000
CHORD_MAX_MM = 2400


class _State:
    def __init__(self, cards, client, record: Record, proposer: bool = False):
        self.cards = cards
        self.client = client  # the model backend: reads words for /say; proposes forms only if proposer
        self.proposer = proposer  # v5: /nudge answers from the rules unless GNJ_PROPOSER=model
        self.record = record
        self.current = None  # (intent, holds) of the last /nudge: what /say talks about
        self.pending_said = []  # words heard when there was no proposal to decline yet
        self.settings = Settings()  # spec v6, section 2: what the user set, for this session
        self.pending_photo = None  # v8: the last photo reading, for the episode's next verdict
        self.last = None  # (intent, holds, NudgeResult) awaiting a verdict
        self.session_floor = len(record.lines())  # POST /undo never reaches a decision from before this session
        self.episode = None  # {"id", "first_offer_trade"}: one gesture from first proposal to Accept
        # Requests run on threads. Session and record state change only under this lock; model and
        # solver work run outside it, so /record, /taste and another /nudge answer meanwhile.
        self.lock = threading.RLock()


class _HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _no_constants(name: str):
    raise ValueError(f"{name} is not a number")


def _finite_number(d: dict, key: str) -> float:
    v = d.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise _HttpError(400, f"intent.{key} must be a number")
    try:
        v = float(v)
    except OverflowError:
        raise _HttpError(400, f"intent.{key} is too large")
    if not math.isfinite(v):
        raise _HttpError(400, f"intent.{key} must be a finite number")
    return v


def parse_intent(d) -> Intent:
    if not isinstance(d, dict):
        raise _HttpError(400, "intent must be an object")
    radius = _finite_number(d, "radius_mm")
    chord = _finite_number(d, "chord_mm")
    if not RADIUS_MIN_MM <= radius <= RADIUS_MAX_MM:
        raise _HttpError(400, f"intent.radius_mm must be between {RADIUS_MIN_MM} and {RADIUS_MAX_MM} mm")
    if not 0 < chord <= CHORD_MAX_MM:
        raise _HttpError(400, f"intent.chord_mm must be above 0 and at most {CHORD_MAX_MM} mm")
    try:
        # bend_angle_deg is optional (v1 clients send direction); when present it must be finite.
        # Intent normalises it into [0, 360).
        angle = _finite_number(d, "bend_angle_deg") if "bend_angle_deg" in d else None
        return Intent(d.get("member_id"), d["chord_mm"], d["radius_mm"], d.get("direction"), angle)
    except ValueError as e:
        raise _HttpError(400, str(e))


def parse_holds(raw) -> Holds:
    if raw is None:
        return Holds()
    if not isinstance(raw, list):
        raise _HttpError(400, "holds must be a list")
    try:
        return Holds(raw)
    except ValueError as e:
        raise _HttpError(400, str(e))


def _handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "gnj-nudge/0.1"
        timeout = 10  # a client that promises more bytes than it sends cannot hold the server

        def log_message(self, fmt, *args):  # quiet unless asked
            if os.environ.get("GNJ_LOG"):
                super().log_message(fmt, *args)

        # ---- plumbing -------------------------------------------------

        def _origin(self) -> str | None:
            return self.headers.get("Origin")

        def _cors(self):
            origin = self._origin()
            if origin and LOCAL_ORIGIN.fullmatch(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send(self, status: int, body: dict | None):
            data = b"" if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            if body is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _run(self, route):
            """Every method goes through here: origin gate first, then the route,
            with every failure turned into a JSON error."""
            self._body_read = False
            try:
                origin = self._origin()
                if origin is not None and not LOCAL_ORIGIN.fullmatch(origin):
                    raise _HttpError(403, "origin not allowed")
                route()
            except _HttpError as e:
                self._discard_unread()
                self._send(e.status, {"error": str(e)})
            except Exception:
                try:
                    self._discard_unread()
                    self._send(500, {"error": "internal error"})
                except Exception:
                    pass

        def _discard_unread(self):
            """Read and drop a request body we refused without reading. Closing a socket
            with unread bytes makes Windows send a reset, and the client never sees our answer."""
            if self._body_read or self.command != "POST":
                return
            self._body_read = True
            try:
                raw = (self.headers.get("Content-Length") or "").strip()
                if raw.isascii() and raw.isdigit() and int(raw) <= MAX_BODY:
                    self.rfile.read(int(raw))
                    return
                # Length missing, bad or over the cap: take what has already arrived, briefly.
                self.connection.settimeout(0.2)
                while self.connection.recv(65536):
                    pass
            except OSError:
                pass
            finally:
                self.connection.settimeout(self.timeout)

        def _body(self, cap: int = MAX_BODY) -> dict:
            raw = self.headers.get("Content-Length")
            if raw is None:
                raise _HttpError(400, "Content-Length is required")
            raw = raw.strip()
            if not (raw.isascii() and raw.isdigit()):
                raise _HttpError(400, "Content-Length must be a whole number of bytes")
            n = int(raw)
            if n > cap:
                raise _HttpError(413, "body too large")
            self._body_read = True
            try:
                body = json.loads(self.rfile.read(n) or b"{}", parse_constant=_no_constants)
            except (ValueError, RecursionError):
                raise _HttpError(400, "body is not valid JSON")
            if not isinstance(body, dict):
                raise _HttpError(400, "body must be a JSON object")
            return body

        # ---- methods --------------------------------------------------

        def do_OPTIONS(self):
            self._run(lambda: self._send(204, None))

        def do_GET(self):
            self._run(self._get)

        def do_POST(self):
            self._run(self._post)

        def _get(self):
            if self.path == "/record":
                with state.lock:
                    body = {"entries": state.record.entries(), "taste_summary": state.record.taste_summary()}
                return self._send(200, body)
            if self.path == "/taste":
                with state.lock:
                    lead, because = taste.lead(state.record.live_lines())
                return self._send(200, {"lead": lead, "because": because})
            if self.path == "/settings":
                return self._send(200, state.settings.public())
            if self.path == "/tally":
                with state.lock:
                    body = state.record.tally()
                return self._send(200, body)
            raise _HttpError(404, "not found")

        def _post(self):
            if self.path not in ("/nudge", "/judge", "/say", "/photo", "/settings", "/taste/reset",
                                 "/tally/reset", "/undo"):
                raise _HttpError(404, "not found")
            body = self._body(photo.MAX_BODY if self.path == "/photo" else MAX_BODY)
            if self.path == "/photo":
                return self._photo(body)
            if self.path == "/nudge":
                return self._nudge(body)
            if self.path == "/say":
                return self._say(body)
            if self.path == "/settings":
                try:
                    state.settings.update(body)
                except ValueError as e:
                    raise _HttpError(400, str(e))
                return self._send(200, state.settings.public())
            if self.path == "/undo":  # spec v9 slice 3 item 7
                if body:
                    raise _HttpError(400, "undo takes an empty body: {}")
                with state.lock:
                    e = state.record.undo(state.session_floor)
                    if e is None:
                        raise _HttpError(409, "nothing to undo since the last tally reset in this session")
                    body = {"undone": {"member_id": e.get("member_id"), "timestamp": e.get("timestamp"),
                                       "kind": e.get("kind", "bend")}, "tally": state.record.tally()}
                return self._send(200, body)
            if self.path == "/tally/reset":
                with state.lock:
                    state.record.reset_tally()
                    body = state.record.tally()
                return self._send(200, body)
            if self.path == "/taste/reset":
                with state.lock:
                    state.record.reset_taste()
                    state.episode = None
                    lead, because = taste.lead(state.record.live_lines())
                return self._send(200, {"lead": lead, "because": because})
            return self._judge(body)

        def _nudge(self, body: dict):
            raw_intent = body.get("intent")
            kind = raw_intent.get("kind", "bend") if isinstance(raw_intent, dict) else "bend"
            if kind == "bend":
                intent = parse_intent(raw_intent)
            elif kind in ("surface_stroke", "part", "plate"):
                from .part import PartIntent
                from .plate import PlateIntent
                cls = {"surface_stroke": SurfaceIntent, "part": PartIntent, "plate": PlateIntent}[kind]
                try:
                    intent = (cls.from_dict(raw_intent, state.settings.snapshot()["thickness_mm"]) if kind == "plate"
                              else cls.from_dict(raw_intent))
                except ValueError as e:
                    raise _HttpError(400, str(e))
            else:
                raise _HttpError(400, "intent.kind must be 'bend', 'surface_stroke', 'part' or 'plate'")
            holds = parse_holds(body.get("holds"))
            self._send(200, self._propose(intent, holds))

        def _propose(self, intent, holds) -> dict:
            """Run the rules (or the model proposer, if switched on) and remember the episode."""
            with state.lock:
                lead, because = taste.lead(state.record.live_lines())
            # Outside the lock: the rules (and a model call, if one is configured) take time.
            proposer = state.client if state.proposer else None
            settings = state.settings.snapshot()
            result = agent.nudge(intent, holds, state.cards, proposer, lead=lead, because=because, settings=settings)
            payload = result.as_dict(intent)
            if os.environ.get("GNJ_LOG") and getattr(result, "model_text", None):
                payload["debug"] = {"model_text": result.model_text}  # never returned unless GNJ_LOG is set
            if os.environ.get("GNJ_LOG") and getattr(result, "rejected_proposals", None):
                # What the model proposed and why the checker refused it: a finding, not noise.
                print(json.dumps({"rejected_proposals": result.rejected_proposals}, default=str), file=sys.stderr,
                      flush=True)
            json.dumps(payload, allow_nan=False)  # refuse to remember a result we cannot send
            with state.lock:
                state.current = (intent, holds)
                state.last = (intent, holds, result) if result.status == "proposed" else None
                state.last_settings = settings
                if result.status == "proposed" and state.episode is None:
                    state.episode = {"id": uuid.uuid4().hex[:12], "first_offer_trade": taste.trade_of(result)}
                payload["tally"] = state.record.tally()  # accepted decisions so far (spec v4)
            return payload

        def _say(self, body: dict):
            """v5: the designer's words become actions from a closed list; nothing the model writes
            is shown. The actions are applied to the holds and the rules answer again."""
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                raise _HttpError(400, "text must be a non-empty string")
            if len(text) > say.MAX_TEXT:
                raise _HttpError(400, f"text must be at most {say.MAX_TEXT} characters")
            text = text.strip()
            with state.lock:
                if state.current is None:
                    raise _HttpError(409, "nothing to talk about yet: POST /nudge first")
                intent, holds = state.current
            kind = getattr(intent, "kind", None) if getattr(intent, "kind", None) in ("part", "sculpt", "plate") else \
                "surface_stroke" if isinstance(intent, SurfaceIntent) else "bend"
            mapping = say.read_words(text, holds, state.client)  # outside the lock: up to 20 s
            if os.environ.get("GNJ_LOG") and mapping.note:
                print(json.dumps({"say": "model reply not used", "why": mapping.note}), file=sys.stderr, flush=True)
            def heard_for(nothing_saved: bool = False) -> str:
                if kind == "part" and ("hold", "shape") in mapping.actions:
                    from .part import NEVER_MOVED
                    return NEVER_MOVED  # spec v6: hold shape means nothing for the designer's own geometry
                return say.heard(mapping.actions, nothing_saved=nothing_saved, kind=kind)

            out = {"understood": mapping.understood, "heard": heard_for(),
                   "actions": [{"op": op, "name": name} for op, name in mapping.actions],
                   "source": mapping.source, "model_ms": mapping.model_ms, "nudge": None}
            if not mapping.understood:
                with state.lock:
                    out["tally"] = state.record.tally()
                return self._send(200, out)
            said = {"said": text, "mapped_to": out["actions"]}
            with state.lock:  # a proposal on screen is declined first, as the hold buttons do
                if state.last is not None:
                    _, held, result = state.last
                    added = next((name for op, name in mapping.actions if op == "hold" and name not in held), None)
                    entry = make_entry("rejected", intent, held, result, state.cards, added, state.episode,
                                       state.last_settings) | said
                    state.record.append(entry)
                    state.last = None
                else:
                    state.pending_said.append(said)
            out["nudge"] = self._propose(intent, Holds(say.apply(holds, mapping.actions)))
            lw = out["nudge"].get("less_waste")
            if ("hold", "less_waste") in mapping.actions and lw is not None:
                out["heard"] = heard_for(nothing_saved=not lw["saved"])
            out["tally"] = out["nudge"]["tally"]  # every /say response carries the tally, as /nudge and /judge do
            self._send(200, out)

        def _photo(self, body: dict):
            """v8: a photo read into bends from a closed list (gnj_nudge/photo.py). Starts a new episode."""
            settings = state.settings.snapshot()
            try:
                out, event, proposal = photo.serve(body, state.client, settings)  # outside the lock: up to 25 s
            except photo.Refused as e:
                raise _HttpError(400, str(e))
            json.dumps(out, allow_nan=False)
            with state.lock:
                state.record.append(event)
                if out["understood"]:
                    state.last, state.episode, state.pending_said = None, None, []
                    state.pending_photo = {k: event[k] for k in ("photo_sha256", "photo_bends")}
                    intent, result = proposal  # spec v9: the photo's plate is the proposal on screen
                    state.current, state.last_settings = (intent, Holds()), settings
                    if result.status == "proposed":
                        state.last = (intent, Holds(), result)
                        state.episode = {"id": event["episode_id"], "first_offer_trade": taste.trade_of(result)}
                out["tally"] = state.record.tally()
            self._send(200, out)

        def _judge(self, body: dict):
            hold = body.get("hold")
            if hold is not None:
                parse_holds([hold])
            with state.lock:  # read the proposal, write the record and clear it as one step
                if state.last is None:
                    raise _HttpError(409, "nothing to judge: POST /nudge first")
                intent, holds, result = state.last
                try:
                    entry = make_entry(body.get("verdict"), intent, holds, result, state.cards, hold, state.episode,
                                       state.last_settings)
                except ValueError as e:
                    raise _HttpError(400, str(e))
                if state.pending_said:  # words heard while nothing was on screen belong to this episode
                    entry |= {"said": " / ".join(x["said"] for x in state.pending_said),
                              "mapped_to": [a for x in state.pending_said for a in x["mapped_to"]]}
                    state.pending_said = []
                if state.pending_photo:  # the photo this episode started from
                    entry |= state.pending_photo
                    state.pending_photo = None
                json.dumps(entry, allow_nan=False)
                state.record.append(entry)
                state.last = None
                if entry["verdict"] == "accepted":
                    state.episode = None  # the gesture is done; the next proposal starts a new episode
                    state.current = None  # holds (less_waste too) belong to one decision: /say needs a new /nudge
                body = entry | {"tally": state.record.tally()}  # the tally rides along; it is not stored
            self._send(200, body)

    return Handler


def make_server(host: str = HOST, port: int = PORT, *, cards=None, client="env",
                record_path: str | Path | None = None, proposer: bool | None = None) -> HTTPServer:
    """client: the model backend ("env": GNJ_BACKEND). proposer: let the model propose forms on
    /nudge (None: GNJ_PROPOSER=model). Off by default: the ghost comes from the rules, at once."""
    from .winpower import keep_full_speed
    keep_full_speed()  # a console-less child of Rhino is otherwise throttled to about a third of its speed
    cards = cards or load_cards()
    if client == "env":
        client = agent.make_client()
    if proposer is None:
        proposer = os.environ.get("GNJ_PROPOSER") == "model"
    record = Record(record_path or os.environ.get("GNJ_RECORD") or "gnj-record.jsonl")
    state = _State(cards, client, record, proposer)
    srv = ThreadingHTTPServer((host, port), _handler(state))
    srv.daemon_threads = True
    srv.gnj_state = state
    return srv


def main() -> None:
    from .pieces import enable_pool
    enable_pool()  # splitting fits its pieces in parallel; safe here, behind the __main__ guard
    srv = make_server()
    st = srv.gnj_state
    words = "keywords" if os.environ.get("GNJ_SAY") == "keywords" or not st.client else getattr(st.client, "source", "model")
    mode = f"forms: {'model ' + agent.model_id() if st.proposer and st.client else 'rules'}; words: {words}"
    print(f"gnj-nudge on http://{HOST}:{PORT}  [{mode}]", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
