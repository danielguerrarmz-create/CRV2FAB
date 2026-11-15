"""Ask Claude for ONE buildable form; the checker decides whether it is one.

Flow:
  1. The solver decides conflicts first. The model is never asked to judge one.
  2. No API key (or no client) -> the solver's form, source "rules".
  3. Otherwise ask the model, up to MAX_ATTEMPTS times. Every proposal goes
     through check() and the hold test; a failure is fed back verbatim.
  4. Three failures, a refusal, or an API error -> the solver's form.

Model output is untrusted: numbers are rebuilt into a Form and re-checked here,
deviation is computed here, and the text is length-capped and de-dashed.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field

import anthropic

from . import solver
from .intent import HOLD_NAMES, Holds, Intent, hold_violations
from .limits import Form, LimitCard, check, deviation_mm, factors, governing, normalise_angle

DEFAULT_MODEL = "claude-opus-5-5"
MAX_ATTEMPTS = 3
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CLIENT_TIMEOUT_S = 20
CLIENT_RETRIES = 1
BUDGET_S = 45  # whole propose loop; past this the solver answers
MIN_CALL_S = 1  # not worth starting a call with less time than this left
CLOSENESS_SLACK_MM = 0.5  # a model form may sit at most this much further from the intent than the solver's
ANGLE_TOLERANCE_DEG = 1e-6  # the model must return the drawn direction


@dataclass
class NudgeResult:
    status: str  # "proposed" | "conflict"
    sentence: str
    steps: list[dict]
    source: str  # "model" (API) | "claude-code" | "rules"
    form: Form | None = None
    deviation_mm: float | None = None
    conflict: tuple[str, str] | None = None
    governing: list[str] = field(default_factory=list)
    rejected_proposals: list[dict] = field(default_factory=list)  # what the model tried and why it failed
    taste: dict | None = None  # {lead, because} when taste chose this answer
    model_text: dict | None = None  # the model's own sentence and steps: debug only, never shown
    less_waste: dict | None = None  # {from_pct, to_pct, saved} when the designer asked for less waste
    waste: dict | None = None  # the billet around the bent member (report only); None if unavailable
    model_ms: int | None = None  # wall time spent in model calls; None when no model was asked

    def as_dict(self, intent: Intent) -> dict:
        form = None
        if self.form is not None:
            form = self.form.as_dict()
            if intent.direction:  # v1 field, kept for bends exactly up (0) or down (180)
                form["direction"] = intent.direction
            if self.waste:  # additive: waste on the panel (spec v4); absent when it cannot be computed
                w = self.waste
                form["checks"] = {"waste_pct": round(w["waste_pct"], 1) + 0.0,
                                  "waste_rounding_pct": round(w["waste_rounding_pct"], 1) + 0.0}
                form["billet"] = {"mode": w["mode"], "length_mm": round(w["length_mm"], 1),
                                  "width_mm": round(w["width_mm"], 1), "depth_mm": round(w["depth_mm"], 1),
                                  "radius_mm": None if w["radius_mm"] is None else round(w["radius_mm"], 1),
                                  "volume_m3": round(w["billet_mm3"] / 1e9, 6)}
                form["part_volume_m3"] = round(w["part_mm3"] / 1e9, 6)
        return {
            "status": self.status,
            "form": form,
            "sentence": self.sentence,
            "steps": self.steps,
            "deviation_mm": None if self.deviation_mm is None else round(self.deviation_mm, 1),
            "source": self.source,
            "conflict": list(self.conflict) if self.conflict else None,
            "governing": self.governing,
            "taste": self.taste,
            "model_ms": self.model_ms,
            **({"less_waste": self.less_waste} if self.less_waste is not None else {}),
        }


BACKENDS = ("claude-code", "api", "solver")


def backend_name() -> str:
    """GNJ_BACKEND = claude-code | api | solver. Default: claude-code when a `claude`
    executable is found, else solver. `api` is never the default and needs a key."""
    from .claude_code import find_claude
    chosen = (os.environ.get("GNJ_BACKEND") or "").strip().lower()
    if chosen and chosen not in BACKENDS:
        raise ValueError(f"GNJ_BACKEND must be one of {', '.join(BACKENDS)}")
    return chosen or ("claude-code" if find_claude() else "solver")


def make_client():
    """The model client for the chosen backend, or None for the solver alone."""
    name = backend_name()
    if name == "claude-code":
        from .claude_code import make_client as make_cc
        return make_cc()
    if name == "api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        return anthropic.Anthropic(timeout=CLIENT_TIMEOUT_S, max_retries=CLIENT_RETRIES)
    return None


def model_id() -> str:
    return os.environ.get("GNJ_MODEL") or DEFAULT_MODEL


def _schema(cards: dict[str, LimitCard]) -> dict:
    return {
        "type": "object",
        "properties": {
            "radius_mm": {"type": "number"},
            "bend_angle_deg": {"type": "number"},
            "n_lamellas": {"type": "integer"},
            "lamella_mm": {"type": "number"},
            "n_strips": {"type": "integer"},
            "strip_mm": {"type": "number"},
            "sentence": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "enum": ["Heard", "Limit", "Decision", "Check"]},
                        "text": {"type": "string"},
                        "limit_id": {"type": "string", "enum": [*cards.keys(), "none"]},
                    },
                    "required": ["tag", "text", "limit_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["radius_mm", "bend_angle_deg", "n_lamellas", "lamella_mm", "n_strips", "strip_mm",
                     "sentence", "steps"],
        "additionalProperties": False,
    }


SYSTEM = """You help a designer bend one straight softwood timber member in single curvature.
The designer drew a curve. You return ONE form: the closest form to that curve that can actually be built.

Geometry: the member runs along X. Its thickness is in Z and its width in Y. The bend direction bend_angle_deg is measured in the YZ plane from +Z (0, up) toward +Y (90); 180 is down. A bend of radius R at angle a curves the thickness with radius R / |cos a| and the width with radius R / |sin a|.

How to choose:
- Keep the drawn curve, radius and direction, if at all possible. Change how the member is made first: split the thickness into equal glued layers (n_lamellas of lamella_mm) and the width into equal glued strips (n_strips of strip_mm), using the fewest pieces that pass. Layers must fill the stock thickness and strips the stock width.
- Move the curve (open the radius) only when no allowed piece size can bend to it, and then move it as little as the limits allow. Never change the direction: return the drawn bend_angle_deg.
- Holds override that order. "solid" means one piece: one layer and one strip. "shape" means the drawn radius must not change.

The fabrication limits are given as limit cards. A separate checker tests your numbers against them; if it fails you will be told why and asked again.

Write "sentence" as ONE plain sentence a designer understands at a glance: no jargon, no numbers beyond what helps, no dashes.
Write "steps" as a short reasoning trail (2 to 4 steps), each tagged Heard, Limit, Decision or Check, with the id of the limit card it rests on, or "none"."""


def _user_message(intent: Intent, holds: Holds, cards: dict[str, LimitCard]) -> str:
    card_rows = [{"id": c.id, "quantity": c.quantity, "value": c.value, "unit": c.unit} for c in cards.values()]
    hold_rows = sorted(HOLD_NAMES[h] for h in holds) or ["none"]
    return (
        f"Member {intent.member_id}. Drawn: span {intent.chord_mm:g} mm, radius {intent.radius_mm:g} mm, "
        f"bend_angle_deg {intent.bend_angle_deg:g}.\n"
        f"Holds: {', '.join(hold_rows)}.\n"
        f"Limit cards: {json.dumps(card_rows)}"
    )


_DASH = re.compile(r"\s*[\u2013\u2014]\s*")


# A real address shape: a local part, a domain, and an alphabetic top-level domain. "4@9.5 mm"
# (four at 9.5) is not an address.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")


def _clean(text: str, limit: int) -> str:
    """Model text for a designer: no dashes, capped, and never an email address (Claude Code
    attaches the signed-in account's email as context; an answer that repeats it is refused)."""
    text = str(text)
    if _EMAIL.search(text):
        raise ValueError("model text contains an email address")
    return _DASH.sub(", ", text).strip()[:limit]


def _parse(payload, intent: Intent, cards: dict[str, LimitCard]) -> tuple[Form, str, list[dict]]:
    if not isinstance(payload, dict):
        raise ValueError("reply is not an object")
    # The model's angle is only compared (in _judge_reply); the form always carries the drawn one.
    form = Form(payload["radius_mm"], payload["n_lamellas"], payload["lamella_mm"], intent.chord_mm,
                payload["n_strips"], payload["strip_mm"], intent.bend_angle_deg)
    if not isinstance(payload["sentence"], str):
        raise ValueError("sentence is not text")
    sentence = _clean(payload["sentence"], 240)
    if not sentence:
        raise ValueError("sentence is empty")
    return form, sentence, parse_steps(payload, cards)


def parse_steps(payload: dict, cards: dict[str, LimitCard]) -> list[dict]:
    raw_steps = payload.get("steps") or []
    if not isinstance(raw_steps, list) or not all(isinstance(s, dict) for s in raw_steps):
        raise ValueError("steps is not a list of objects")
    steps = []
    for s in raw_steps[:6]:
        lid = s.get("limit_id")
        if not all(isinstance(s.get(k, ""), str) for k in ("tag", "text")) or not isinstance(lid, (str, type(None))):
            raise ValueError("a step has a field of the wrong type")
        steps.append({"tag": _clean(s.get("tag", ""), 24), "text": _clean(s.get("text", ""), 300),
                      "limit_id": lid if isinstance(lid, str) and lid in cards else None})
    return steps


def _judge_reply(resp, intent: Intent, holds: Holds, cards: dict[str, LimitCard], max_dev: float):
    """Turn one model reply into (accepted form or None, reasons it failed).
    Any surprise in the reply is a failed attempt, never a crash."""
    try:
        text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
        payload = json.loads(text)
        form, sentence, steps = _parse(payload, intent, cards)
        result = check(form, cards)
        reasons = [c.detail for c in result.failures] + hold_violations(form, intent, holds)
        turned = _angle_gap(payload["bend_angle_deg"], intent.bend_angle_deg)
        if turned > ANGLE_TOLERANCE_DEG:
            reasons.append(f"The bend direction must stay at {intent.bend_angle_deg:g} degrees; "
                           f"this form turns it by {turned:g} degrees.")
        dev = deviation_mm(intent.radius_mm, form.radius_mm, intent.chord_mm)
    except Exception as e:  # untrusted output: every failure mode is just a failed attempt
        return None, None, [f"The reply could not be read as a form ({type(e).__name__})."]
    if not reasons and dev > max_dev:
        reasons = [f"This form is buildable but sits {dev:.0f} mm from the drawn curve; "
                   f"a form within {max_dev:.0f} mm exists. Stay closer to the drawn curve."]
    if reasons:
        return None, form, reasons
    return (form, sentence, steps, dev), form, []


def _angle_gap(a, b: float) -> float:
    """Smallest turn between two directions, in degrees. Raises on a non-number."""
    if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a):
        raise ValueError("bend_angle_deg is not a finite number")
    d = abs(normalise_angle(a) - normalise_angle(b))
    return min(d, 360.0 - d)


def _safe_form_dict(form: Form | None) -> dict | None:
    try:
        return form.as_dict() if form else None
    except Exception:
        return None


def _fallback(base: solver.SolveResult, tried: list[dict], model_ms: int | None = None) -> NudgeResult:
    return NudgeResult(base.status, base.sentence, base.steps, "rules", base.form, base.deviation_mm,
                       base.conflict, base.governing, tried, model_ms=model_ms)


def nudge(intent, holds: Holds, cards: dict[str, LimitCard], client=None,
          model: str | None = None, clock=time.monotonic, lead: str = "makeup", because: str = "",
          settings: dict | None = None):
    """Dispatch on the intent kind: a bend (v1, v2) or a surface stroke (v3).

    Taste (docs/SPEC_V3.md): with lead "solid" and no designer hold of solid, try the answer
    as if "solid" were held. If that is a conflict, fall back to the default order without
    comment. Closeness for the model is then measured against the solid-led solver answer."""
    from . import taste
    from .surface import SurfaceIntent
    if getattr(intent, "kind", None) == "part":  # spec v6: the designer's own geometry, rules only
        from .part import solve_part
        from .pieces import from_settings
        return solve_part(intent, holds, from_settings(settings) if settings is not None else None)
    if getattr(intent, "kind", None) == "plate":  # spec v9 slice 1: three strokes build a plate, rules only
        from .plate import solve_plate
        from .pieces import from_settings
        return solve_plate(intent, holds, from_settings(settings) if settings is not None else None)
    if isinstance(intent, SurfaceIntent):
        from .settings import fab_setup
        from .surface_agent import nudge_surface
        from .surface_solver import solve_surface
        setup = fab_setup(settings)
        run = lambda i, h, c, cl, mo, ck: nudge_surface(i, h, c, cl, mo, ck, setup=setup)  # noqa: E731
        solve_only = lambda i, h, c: solve_surface(i, h, c, setup=setup)  # noqa: E731
        finish = lambda r: r  # noqa: E731  surface waste comes with its billet check
    else:
        run, solve_only = nudge_bend, solver.solve
        finish = lambda r: bend_waste_target(  # noqa: E731
            bend_less_waste(with_bend_waste(r, settings), intent, holds, cards, settings), intent, cards, settings)

    # Taste leads only on the bend kind (Daniel, 2026-11-14): on a surface a solid lead would offer a
    # straight block with about 80 % waste, which must never be offered unasked. A solid hold still works.
    if lead == "solid" and "solid" not in holds and not isinstance(intent, SurfaceIntent):
        default = solve_only(intent, holds, cards)
        already_solid = default.status == "proposed" and default.form.solid
        if not already_solid:
            led = run(intent, Holds(holds | {"solid"}), cards, client, model, clock)
            if led.status == "proposed":
                return finish(taste.apply(led, because))
    return finish(run(intent, holds, cards, client, model, clock))


def bend_less_waste(result: "NudgeResult", intent: Intent, holds: Holds, cards, settings=None) -> "NudgeResult":
    """less_waste on a bend (spec v5): among the layer and strip counts that pass the bend's own rules at
    the same radius, the least waste; ties to fewer pieces. Never moves the line; asked for in words only."""
    if "less_waste" not in holds or result.form is None or result.waste is None:
        return result
    f, before = result.form, result.waste["waste_pct"]
    best = (round(before, 1), f.n_lamellas + f.n_strips, f)
    if not f.solid:
        T, W = cards["stock_thickness"].value, cards["stock_width"].value
        for n in range(f.n_lamellas, 5):
            for k in range(f.n_strips, 12):
                cand = Form(f.radius_mm, n, T / n, f.chord_mm, k, W / k, f.bend_angle_deg)
                if not check(cand, cards).passed:
                    continue
                trial = with_bend_waste(NudgeResult("proposed", "", [], "rules", cand, result.deviation_mm), settings)
                if trial.waste is not None:
                    key = (round(trial.waste["waste_pct"], 1), n + k, cand)
                    if key[:2] < best[:2]:
                        best = key
    chosen = best[2]
    saved = best[0] < round(before, 1)
    if saved:
        base = solver.solve(intent, holds, cards)
        result.form = chosen
        result.sentence, result.steps = solver.describe(intent, chosen, cards, base)
        with_bend_waste(result, settings)
    result.less_waste = {"from_pct": round(before, 1) + 0.0, "to_pct": round(result.waste["waste_pct"], 1) + 0.0,
                         "saved": saved}
    result.steps = list(result.steps) + [{"tag": "Decision", "limit_id": None, "text": (
        f"You asked for less waste: this make-up wastes {result.less_waste['to_pct']:.0f}% instead of "
        f"{result.less_waste['from_pct']:.0f}%, the least of the make-ups that pass." if saved else
        "You asked for less waste: this is already the least waste this curve allows.")}]
    return result


def bend_waste_target(result: "NudgeResult", intent: Intent, cards, settings=None) -> "NudgeResult":
    """The waste target on a bend (spec v6): over it, the fewest-piece make-up that passes the bend's own
    rules at the same radius and meets it; else the over-target sentence and the best reachable."""
    target = (settings or {}).get("max_waste_pct")
    if target is None or result.form is None or result.waste is None or result.waste["waste_pct"] <= target:
        return result
    f, before = result.form, result.waste["waste_pct"]
    T, W = cards["stock_thickness"].value, cards["stock_width"].value
    options = []
    if not f.solid:
        for n in range(f.n_lamellas, 5):
            for k in range(f.n_strips, 12):
                cand = Form(f.radius_mm, n, T / n, f.chord_mm, k, W / k, f.bend_angle_deg)
                if check(cand, cards).passed:
                    trial = with_bend_waste(NudgeResult("proposed", "", [], "rules", cand, result.deviation_mm), settings)
                    if trial.waste is not None:
                        options.append((trial.waste["waste_pct"], n + k, cand))
    meets = sorted((o for o in options if o[0] <= target), key=lambda o: (o[1], o[0]))
    if meets:
        cand = meets[0][2]
        result.sentence, result.steps = solver.describe(intent, cand, cards, solver.solve(intent, Holds(), cards))
        result.form = cand
        with_bend_waste(result, settings)
        result.steps = list(result.steps) + [{"tag": "Decision", "limit_id": "max_waste_pct", "text": (
            f"Your waste target is {target:g}%: the usual make-up would waste {before:.0f}%, this one "
            f"{result.waste['waste_pct']:.0f}%.")}]
        return result
    best = min(options, key=lambda o: (o[0], o[1]))[0] if options else before
    how = (f"other layer and strip counts would reach {best:.0f}%" if best < before - 0.05 else
           "no other make-up brings it lower")
    result.sentence += f" Waste {round(before):.0f}%, over your {target:g}% target."
    result.steps = list(result.steps) + [{"tag": "Check", "limit_id": "max_waste_pct", "text": (
        f"Waste {before:.0f}% is over your {target:g}% target; the best reachable without moving your curve: {how}.")}]
    return result


def with_bend_waste(result: "NudgeResult", settings: dict | None = None) -> "NudgeResult":
    """Waste on the panel for the bend kind (spec v4): the billet the teammate's way around the bent
    member, reported only. Without numpy, or if the fit fails, the fields stay absent: never a
    made-up number."""
    if result.form is None:
        return result
    try:
        from . import fabrication as fb
        f = result.form
        c, s = factors(f.bend_angle_deg)
        # Rounding is in the bending direction: layers when it bends through the thickness, strips
        # when through the width, the thinner piece when both.
        lam = f.lamella_mm if s == 0 else f.strip_mm if c == 0 else min(f.lamella_mm, f.strip_mm)
        allowance = float((settings or {}).get("allowance_mm") or 0.0)
        result.waste = fb.bend_waste(float(f.radius_mm), float(f.chord_mm), float(f.bend_angle_deg), float(lam),
                                     allowance)
    except Exception:
        result.waste = None
    return result


def nudge_bend(intent: Intent, holds: Holds, cards: dict[str, LimitCard], client=None,
               model: str | None = None, clock=time.monotonic) -> NudgeResult:
    base = solver.solve(intent, holds, cards)
    if base.status == "proposed":
        # The fallback must itself pass the checker: the solver never gets to call a form buildable.
        if not check(base.form, cards).passed or hold_violations(base.form, intent, holds):
            raise RuntimeError("solver produced a form the checker or the holds reject")
    if base.status == "conflict" or client is None:
        return _fallback(base, [])

    max_dev = base.deviation_mm + CLOSENESS_SLACK_MM

    def judge(resp):
        accepted, form, reasons = _judge_reply(resp, intent, holds, cards, max_dev)
        return accepted, _safe_form_dict(form), reasons

    accepted, tried, ms = model_loop(client, model, clock, SYSTEM, _user_message(intent, holds, cards),
                                 _schema(cards), judge)
    if accepted:
        form, sentence, steps, dev = accepted
        # What is shown is the rule templates built from the checked form; the model's own words are
        # kept only for debugging (the server returns them only when GNJ_LOG is set).
        shown_sentence, shown_steps = solver.describe(intent, form, cards, base)
        return NudgeResult("proposed", shown_sentence, shown_steps, getattr(client, "source", "model"), form, dev,
                           None, governing(form, cards, dev), tried, model_ms=ms,
                           model_text={"sentence": sentence, "steps": steps})
    return _fallback(base, tried, ms)


def model_loop(client, model, clock, system: str, first_message: str, schema: dict, judge):
    """Ask, check, feed the failure back; at most MAX_ATTEMPTS calls inside BUDGET_S.
    judge(resp) -> (accepted or None, form summary for the log, reasons).
    Returns (accepted or None, tried, model_ms): model_ms is the wall time spent in model calls."""
    from .claude_code import AttemptFailed, AttemptTimedOut
    messages: list[dict] = [{"role": "user", "content": first_message}]
    tried: list[dict] = []
    start = clock()
    model_s = 0.0
    retries = getattr(client, "retries", CLIENT_RETRIES)
    for _ in range(MAX_ATTEMPTS):
        remaining = BUDGET_S - (clock() - start)
        if remaining < MIN_CALL_S:
            tried.append({"error": "time budget spent"})
            break
        t0 = time.perf_counter()
        try:
            resp = client.beta.messages.create(
                # A call may be retried by its client, so split what is left between the tries.
                timeout=min(CLIENT_TIMEOUT_S, remaining / (retries + 1)),
                model=model or model_id(),
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=system,
                messages=messages,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError as e:
            model_s += time.perf_counter() - t0
            tried.append({"error": type(e).__name__})
            break
        except AttemptFailed as e:  # the Claude Code child timed out, crashed or printed junk
            model_s += time.perf_counter() - t0
            tried.append({"error": str(e)})
            if isinstance(e, AttemptTimedOut):
                break  # offline or stuck: a second attempt would only add another 20 s of dead air
            continue
        model_s += time.perf_counter() - t0
        if getattr(resp, "stop_reason", None) == "refusal":
            tried.append({"error": "refusal"})
            break

        accepted, logged, reasons = judge(resp)
        if accepted:
            return accepted, tried, round(model_s * 1000)

        tried.append({"form": logged, "reasons": reasons})
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": "That form fails:\n- " + "\n- ".join(reasons)
                         + "\nPropose one corrected form."})

    return None, tried, round(model_s * 1000)
