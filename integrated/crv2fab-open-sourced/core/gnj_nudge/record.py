"""Append-only JSONL decision record. One line per accept or reject; lines are never rewritten."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .agent import NudgeResult
from .intent import HOLD_NAMES, Holds, Intent
from .limits import Form, LimitCard, governing_face
from .solver import jround, m, n1
from .taste import trade_of
from .surface import SurfaceIntent
from .surface_solver import passes_text, thickest_lam

SPECIES = "softwood"


def _count(n: int, word: str, size: float) -> str:
    return f"{n} {word}{'' if n == 1 else 's'} of {n1(size)} mm"


def _makeup(f: Form) -> str:
    counts = f"{_count(f.n_lamellas, 'lamella', f.lamella_mm)} by {_count(f.n_strips, 'strip', f.strip_mm)}"
    return f"solid section, {counts}" if f.solid else f"glue-laminated, {counts}"


def _governing_text(card_id: str, cards: dict[str, LimitCard], face: str) -> str:
    c = cards[card_id]
    piece = "lamella thickness" if face == "thickness" else "strip width"
    if card_id == "bend_ratio":
        return f"{piece} / radius no greater than 1/{c.value:g}"
    if card_id == "min_lamella":
        return f"{piece} no less than {c.value:g} mm"
    return f"{c.quantity} {c.value:g} {c.unit}"


def _chosen_over(solid: bool, dev: float, drawn_r: float) -> str:
    moved = dev > 0.5
    if not solid and moved:
        return f"a solid section and the drawn {m(drawn_r)} radius, both of which fail the limits"
    if not solid:
        return "a solid section, which fails the bend limit at this radius"
    if moved:
        return f"the drawn {m(drawn_r)} radius, which fails the bend limit in solid stock"
    return "nothing, the gesture was buildable as drawn"


def formal_sentence(intent: Intent, result: NudgeResult, cards: dict[str, LimitCard]) -> str:
    f = result.form
    depth = cards["stock_thickness"].value
    width = cards["stock_width"].value
    length = cards["length"].value
    face = governing_face(f)
    gov = "; ".join(_governing_text(g, cards, face) for g in result.governing)
    return (
        f"Member {intent.member_id}, {SPECIES} {depth:g} x {width:g} mm, length {m(length)}. "
        f"Single curvature, radius {m(f.radius_mm)}, bend direction {n1(f.bend_angle_deg)} degrees, {_makeup(f)}. "
        f"Governing limit: {gov}. "
        f"Deviation from intent {jround(result.deviation_mm)} mm at mid-span. "
        f"Chosen over {_chosen_over(f.solid, result.deviation_mm, intent.radius_mm)}."
        + (" " + volumes_text(*volumes(result)) if volumes(result) else "")
    )


def volumes(result) -> tuple[float, float, float] | None:
    """(billet m3, part m3, waste %) for a proposal, or None when it could not be computed."""
    form = result.form
    if form is None:
        return None
    check = getattr(form, "check", None)
    if isinstance(check, dict):  # surface member: from its billet check
        return check["billet_mm3"] / 1e9, check["part_mm3"] / 1e9, check["waste_pct"]
    w = getattr(result, "waste", None)
    if w:  # bend: the billet around the bent member
        return w["billet_mm3"] / 1e9, w["part_mm3"] / 1e9, w["waste_pct"]
    return None


def volumes_text(billet_m3: float, part_m3: float, waste_pct: float) -> str:
    waste = round(waste_pct, 1) + 0.0  # + 0.0: float noise on a perfect fit must not print "-0.0"
    return f"Billet {billet_m3:.4f} m3, part {part_m3:.4f} m3, waste {waste:.1f}% of the billet."


def make_entry(verdict: str, intent: Intent, holds: Holds, result: NudgeResult,
               cards: dict[str, LimitCard], hold: str | None = None, episode: dict | None = None,
               settings: dict | None = None) -> dict:
    """episode: {"id", "first_offer_trade"} of the gesture this verdict belongs to (taste)."""
    if verdict not in ("accepted", "rejected"):
        raise ValueError("verdict must be 'accepted' or 'rejected'")
    if hold is not None and verdict != "rejected":
        raise ValueError("a hold can only come with a reject")
    if result.form is None:
        raise ValueError("there is no proposed form to judge")
    surface = isinstance(intent, SurfaceIntent)
    part = getattr(intent, "kind", None) == "part"  # spec v6 section 3
    plate = getattr(intent, "kind", None) == "plate"  # spec v9 slice 1
    if plate:
        from .plate import formal_sentence as formal_plate_sentence
        formal = formal_plate_sentence(intent, result)
    elif part:
        from .part import formal_sentence as formal_part_sentence
        formal = formal_part_sentence(intent, result)
    elif surface and getattr(result.form, "plan", None) is not None:  # spec v6 section 4: in pieces
        from .pieces import formal_surface_pieces
        formal = formal_surface_pieces(intent, result, cards)
    else:
        formal = formal_surface_sentence(intent, result, cards) if surface else formal_sentence(intent, result, cards)
    if verdict == "rejected":
        formal = "Proposal declined. " + formal + (
            f" Designer holds: {HOLD_NAMES[hold]}." if hold else " No reason given yet.")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "member_id": intent.member_id,
        "formal": formal,
        "holds_added": [hold] if hold else [],
        "holds_active": sorted(holds),
        # A surface member's stations stay out of the record; the summary carries the numbers.
        "form": result.form.summary() if surface or part or plate else result.as_dict(intent)["form"],
        "deviation_mm": round(result.deviation_mm, 1),
        "source": result.source,
        "intent": intent.summary() if surface or part or plate else intent.as_dict(),
        "limits_source": sorted({c.source for c in cards.values()}),
    }
    if surface:
        entry["trimmed"] = result.trimmed
    episode = episode or {}
    entry |= {
        "kind": "plate" if plate else "part" if part else "surface_stroke" if surface else "bend",
        "episode_id": episode.get("id"),
        "first_offer_trade": episode.get("first_offer_trade", trade_of(result)),
        "accepted_trade": trade_of(result) if verdict == "accepted" else None,
        "taste_led": bool(getattr(result, "taste", None)),
    }
    if settings is not None:  # the user's settings this decision was solved with (spec v6, section 2)
        entry["settings"] = settings
    if hasattr(result.form, "joints"):  # spec v6 section 4: every joint, for the engineer
        entry["joints"] = result.form.joints()
    v = volumes(result)
    if v:  # absent, never invented, when the billet could not be fitted
        entry |= {"billet_m3": round(v[0], 6), "part_m3": round(v[1], 6), "waste_pct": round(v[2], 1) + 0.0}
    return entry


def formal_surface_sentence(intent: SurfaceIntent, result, cards: dict[str, LimitCard]) -> str:
    """v4 (sc_glulam route): one billet pressed from lamellas (or one straight piece), CNC milled."""
    f, c = result.form, result.form.curve
    depth, width = cards["stock_thickness"].value, cards["stock_width"].value
    rn = "straight" if math.isinf(c.r_normal) else m(c.r_normal)
    rs = "straight" if math.isinf(c.r_side) else m(c.r_side)
    b, chk = f.billet(outline=False), f.checks()
    mc, bend = chk["machine"], chk["bend"]
    if f.straight:
        made = "milled from one straight piece, no pressing"
    elif b["mode"] == "straight":
        made = f"glued straight from {_count(f.n_lamellas, 'lamella', f.lamella_mm)}, then milled"
    else:
        made = (f"pressed to a {m(b['radius_mm'])} radius from {_count(f.n_lamellas, 'lamella', f.lamella_mm)}, "
                f"then milled")
    size = f"billet {b['length_mm']:.0f} x {b['width_mm']:.0f} x {b['depth_mm']:.0f} mm, {b['volume_m3']:.3f} m3"
    bend_text = ("bend limit not applicable (no pressing)" if not bend["applies"] else
                 "lamellas do not bend (straight billet)" if bend["tightest_radius_mm"] is None else
                 f"tightest lamella radius {m(bend['tightest_radius_mm'])}, R/t {bend['ratio']:.0f} against {bend['limit']:g}")
    full = f.check["machine"]
    machine = ((f"{full['name']}: " if full.get("name") else "") +
               f"needs {full['need_mm'][0]:.0f} x {full['need_mm'][1]:.0f} mm {full['orientation']}, "
               f"opening {full['opening_mm'][0]:.0f} x {full['opening_mm'][1]:.0f} mm, "
               + ("fits" if full["ok"] else f"too large by {mc['overshoot_mm']:.0f} mm"))
    gov = {"lam_ratio": "lamella bend radius / thickness", "machine": "machine opening"}
    governing = "; ".join(gov.get(g, g) for g in result.governing)
    moved = result.deviation_mm > 0.5
    if f.straight:
        over = "the drawn line, which one straight piece cannot follow on this machine" if moved else             "a pressed billet, not needed for one straight piece"
    else:
        over = ("the drawn line, which fails the limits even at the thinnest lamella" if moved else
                "thicker lamellas, which fail the bend limit on this line"
                if f.lamella_mm < max(f.lam_options or (thickest_lam(),)) else
                "nothing, the line was buildable as drawn with the thickest lamella")
    return (
        f"Member {intent.member_id}, {SPECIES} {depth:g} x {width:g} mm, surface member following the drawn line, "
        f"length {m(c.length_mm)}{', trimmed to the stock length' if result.trimmed else ''}. "
        f"Minimum radius {rn} across the thickness and {rs} across the width; "
        f"twist up to {c.max_twist_deg_per_m:.1f} degrees per metre, milled out. "
        f"{made[0].upper()}{made[1:]}, {passes_text(f.smoothing_passes)}; {size}. "
        f"Bend: {bend_text}. Machine {machine}. {volumes_text(*volumes(result))} Kx {chk['kx']}. "
        f"Governing limit: {governing}. "
        f"Deviation from intent {jround(result.deviation_mm)} mm at most. "
        f"Chosen over {over}."
    )


class Record:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def lines(self) -> list[dict]:
        """Every line, decisions and events (taste resets), oldest first."""
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def live_lines(self) -> list[dict]:
        """Every line, with each accepted decision an `undo` marker names flagged `undone: true` (the
        log itself is never rewritten). The tally, taste and GET /record read these."""
        lines = self.lines()
        gone = {e["undone_line"] for e in lines if e.get("event") == "undo" and isinstance(e.get("undone_line"), int)}
        return [e | {"undone": True} if i in gone else e for i, e in enumerate(lines)]

    def entries(self) -> list[dict]:
        """Decision entries only (what GET /record shows), undone ones marked `undone: true`."""
        return [e for e in self.live_lines() if "event" not in e]

    def undo(self, since_line: int = 0) -> dict | None:
        """Spec v9 slice 3 item 7: append an `undo` marker for the most recent accepted decision that is
        not undone yet, at or after since_line (the session's first line) and after the last tally
        reset. Returns that decision, or None when there is nothing to undo."""
        lines = self.live_lines()
        floor = since_line
        for i, e in enumerate(lines):
            if e.get("event") == "tally_reset":
                floor = max(floor, i + 1)
        for i in range(len(lines) - 1, floor - 1, -1):
            e = lines[i]
            if "event" not in e and e.get("verdict") == "accepted" and not e.get("undone"):
                self.append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": "undo",
                             "undone_timestamp": e.get("timestamp"), "undone_episode_id": e.get("episode_id"),
                             "undone_line": i})
                return e
        return None

    def reset_taste(self) -> dict:
        """Append a marker; taste reads only what follows it. Nothing is deleted or rewritten."""
        return self.append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "event": "taste_reset"})

    def reset_tally(self) -> dict:
        """Append a marker; the tally counts only accepted decisions after it."""
        return self.append({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "event": "tally_reset"})

    def tally(self) -> dict:
        """Accepted decisions since the last tally reset, volume-weighted (spec v4: waste on the panel).
        A taste reset does not clear it. Decisions without volumes are not counted."""
        members, billet, part = 0, 0.0, 0.0
        for e in self.live_lines():
            if e.get("event") == "tally_reset":
                members, billet, part = 0, 0.0, 0.0
            elif e.get("undone"):
                continue  # rewound by POST /undo
            elif e.get("verdict") == "accepted" and e.get("billet_m3") and e.get("part_m3") is not None:
                members, billet, part = members + 1, billet + e["billet_m3"], part + e["part_m3"]
        return {"members": members, "billet_m3": round(billet, 6), "part_m3": round(part, 6),
                "waste_pct": round(100.0 * (billet - part) / billet, 1) + 0.0 if billet > 0 else None}

    def taste_summary(self) -> dict[str, int]:
        """How many times each hold was added. Read as the designer's taste."""
        counts = Counter(h for e in self.entries() for h in e.get("holds_added", []))
        return {h: counts.get(h, 0) for h in HOLD_NAMES}
