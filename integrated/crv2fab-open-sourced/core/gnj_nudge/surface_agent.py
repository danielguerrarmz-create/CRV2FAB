"""Surface agent, spec v4: the model chooses how much to straighten, the lamella thickness and
whether to mill from one straight piece; the core builds the curve, fits the billet and checks it
with the teammate's route. The model never writes geometry.

No machine data of any kind enters a prompt (no name, no opening, no source): this path runs under
Daniel's personal subscription. The model is told only that a machine check exists, and whether
its proposal failed it, in generic words.
"""
from __future__ import annotations

import json
import math
import time

from .agent import CLOSENESS_SLACK_MM, _clean, model_loop, parse_steps
from .intent import HOLD_NAMES, Holds
from .surface import LADDER, SurfaceIntent
from .surface_solver import TRIM_NOTE, FabSetup, Ladder, SurfaceForm, SurfaceResult, evaluate, finish, solve_surface

SYSTEM = """You help a designer turn a line drawn on a curved surface into one timber member that follows the surface.
The core has already measured the line. You choose ONE way to build it.

How it is made: one billet is pressed in a single curve from equal glued layers (lamellas), then milled by a CNC machine down to the member. Or, with straight_billet true, it is milled from one straight piece with no pressing.
- lam_mm is the layer thickness, one of the listed values. Thicker layers mean fewer glue lines, but each layer must bend to a radius of at least the ratio limit times its thickness.
- The billet must pass a machine opening check; you are told only whether it passed.
- smoothing_passes must be one of the listed values. 0 keeps the drawn line exactly; more straightens it within the surface and moves it further from the drawing; -1 is the fully straightened line between its ends.

How to choose: keep the drawn line if at all possible and change the make-up first: the thickest layer that passes. Straighten only when nothing passes, and then as little as possible. Holds override that order: "solid" means straight_billet true; "shape" means smoothing_passes 0.

A separate checker fits the billet and tests your choice; if it fails you will be told why and asked again.
Write "sentence" as ONE plain sentence a designer understands at a glance: no jargon, no dashes, no numbers except millimetres moved.
Write "steps" as a short reasoning trail (2 to 4 steps), each tagged Heard, Limit, Decision or Check, with the id of the limit card it rests on, or "none"."""

CARD_IDS = ["lam_ratio", "lam_stock", "machine", "length"]


def _schema(setup: FabSetup) -> dict:
    return {
        "type": "object",
        "properties": {
            "smoothing_passes": {"type": "integer", "enum": list(LADDER)},
            "lam_mm": {"type": "number", "enum": [float(t) for t in setup.lams]},
            "straight_billet": {"type": "boolean"},
            "sentence": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "enum": ["Heard", "Limit", "Decision", "Check"]},
                        "text": {"type": "string"},
                        "limit_id": {"type": "string", "enum": [*CARD_IDS, "none"]},
                    },
                    "required": ["tag", "text", "limit_id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["smoothing_passes", "lam_mm", "straight_billet", "sentence", "steps"],
        "additionalProperties": False,
    }


def _radius(r: float) -> str:
    return "straight" if math.isinf(r) else f"{r:.0f} mm"


def user_message(intent: SurfaceIntent, holds: Holds, ladder: Ladder, setup: FabSetup) -> str:
    """Everything the model sees. No machine data: not the name, not the opening, not a source."""
    c0 = intent.intent
    rows = []
    for p in LADDER:
        c = ladder.get(p)
        if c is None:
            continue
        rows.append({"smoothing_passes": p, "moves_line_mm": round(ladder.deviation(p), 1),
                     "tightest_surface_curve": _radius(c.r_normal), "tightest_sideways_turn": _radius(c.r_side)})
    hold_rows = sorted(HOLD_NAMES[h] for h in holds) or ["none"]
    return (
        f"Member {intent.member_id}, section 38 x 89 mm. Line on the surface: {c0.length_mm:.0f} mm long"
        f"{', trimmed to the stock length' if intent.trimmed else ''}; twist up to {c0.max_twist_deg_per_m:.1f} "
        f"degrees per metre (milled out).\n"
        f"Holds: {', '.join(hold_rows)}.\n"
        f"Layer thicknesses available (mm): {', '.join(f'{t:g}' for t in setup.lams)}. "
        f"Each layer must bend to at least {setup.ratio:g} times its thickness.\n"
        "The billet must also pass a machine opening check; you are told only whether it passed.\n"
        f"Smoothing options: {json.dumps(rows)}"
    )


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def nudge_surface(intent: SurfaceIntent, holds: Holds, cards=None, client=None,
                  model: str | None = None, clock=time.monotonic, setup: FabSetup | None = None) -> SurfaceResult:
    setup = setup or FabSetup.default()
    ladder = Ladder(intent)
    base = solve_surface(intent, holds, cards, ladder, setup)
    if base.status == "conflict" or client is None:
        return base
    max_dev = base.deviation_mm + CLOSENESS_SLACK_MM

    def judge(resp):
        logged = None
        try:
            text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("reply is not an object")
            p, t, straight = payload["smoothing_passes"], payload["lam_mm"], payload["straight_billet"]
            logged = {"smoothing_passes": p, "lam_mm": t, "straight_billet": straight}
            if not _is_int(p) or not isinstance(straight, bool):
                raise ValueError("wrong types")
            if not isinstance(t, (int, float)) or isinstance(t, bool):
                raise ValueError("lam_mm is not a number")
            if not isinstance(payload["sentence"], str):
                raise ValueError("sentence is not text")
            sentence = _clean(payload["sentence"], 240)
            steps = parse_steps(payload, {k: None for k in CARD_IDS})
            if not sentence:
                raise ValueError("sentence is empty")
            if p not in LADDER:
                return None, logged, [f"smoothing_passes must be one of {list(LADDER)}."]
            if not straight and float(t) not in [float(x) for x in setup.lams]:
                return None, logged, [f"lam_mm must be one of {list(setup.lams)}."]
            reasons = []
            if "solid" in holds and not straight:
                reasons.append("You are holding solid, so straight_billet must be true.")
            if "shape" in holds and p != 0:
                reasons.append("You are holding the drawn line, so smoothing_passes must be 0.")
            if not reasons:
                chk, why = evaluate(ladder, p, straight, setup, None if straight else float(t))
                if chk is None:
                    if why is None:
                        return None, logged, ["That much smoothing runs off the usable surface."]
                    if why["bend"]["applies"] and not why["bend"]["ok"]:
                        reasons.append(f"A {why['lam_mm']:g} mm layer bends too tightly here: radius "
                                       f"{why['bend']['tightest_radius_mm'] or 0:.0f} mm is {why['bend']['ratio'] or 0:.0f} "
                                       f"times its thickness, under {setup.ratio:g}.")
                    if not why["machine"]["ok"]:
                        reasons.append("The billet does not pass the machine opening check.")  # generic: no machine data
            dev = ladder.deviation(p)
        except Exception as e:  # untrusted output: every failure mode is just a failed attempt
            return None, logged, [f"The reply could not be read as a choice ({type(e).__name__})."]
        if not reasons and dev > max_dev:
            reasons = [f"This is buildable but moves the line {dev:.0f} mm; a choice within {max_dev:.0f} mm "
                       f"exists. Straighten less."]
        if reasons:
            return None, logged, reasons
        form = SurfaceForm(ladder.get(p), intent.intent, p, straight, ladder.fit(p, straight), chk)
        at_drawn = evaluate(ladder, 0, straight, setup)[1] if p != 0 else None
        cause_bend = at_drawn is not None and not at_drawn["bend"]["ok"]
        heard = [{"tag": "Heard", "text": f"Follow your line on the surface, {intent.intent.length_mm / 1000:.2f} m long."
                  + (" " + TRIM_NOTE if intent.trimmed else ""), "limit_id": "length" if intent.trimmed else None}]
        # Shown: the rule templates for this checked form. The model's words: debug only.
        result = finish(intent, form, dev, heard, getattr(client, "source", "model"), "solid" in holds, cause_bend)
        result.model_text = {"sentence": sentence, "steps": steps}
        return result, logged, []

    accepted, tried, ms = model_loop(client, model, clock, SYSTEM, user_message(intent, holds, ladder, setup),
                                     _schema(setup), judge)
    if accepted:
        accepted.rejected_proposals, accepted.model_ms = tried, ms
        return accepted
    base.rejected_proposals, base.model_ms = tried, ms
    return base
