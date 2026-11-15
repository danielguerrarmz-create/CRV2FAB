"""Taste: the record is read back. Spec: docs/SPEC_V3.md, "Taste: the record is read back".

Limits say what is true; taste says what this designer likes. Taste only chooses between
forms that already pass the checker: a solid lead asks the solver for the solid answer first,
exactly as if "solid" were held, and falls back to the default order without comment if that
is a conflict. A hold the designer sets always outranks the lead.
"""
from __future__ import annotations

import re

WINDOW = 5  # look at this many recent accepted episodes...
SOLID_MIN = 3  # ...and lead solid if at least this many of them ended solid
TRADES = ("none", "makeup", "solid")
MOVED_MM = 0.5
TASTE_TAIL = ", as you usually do"


def trade_of(result) -> str:
    """none: buildable as drawn (solid, not moved). solid: kept solid, shape moved. makeup: glued."""
    f = result.form
    solid = f.solid  # bend: one layer and one strip; surface (v4): one straight piece, no pressing
    if not solid:
        return "makeup"
    return "solid" if result.deviation_mm > MOVED_MM else "none"


def considered(entries: list[dict]) -> list[dict]:
    """The last WINDOW accepted bend episodes whose first offer was not `none`, after the last reset.
    Surface episodes are recorded but not read back: taste's trade (solid against glued) is defined
    for the bend kind, and taste does not lead on surfaces. Entries from before `kind` existed are bends."""
    since_reset = []
    for e in entries:
        if e.get("event") == "taste_reset":
            since_reset = []
        elif (e.get("verdict") == "accepted" and not e.get("undone") and e.get("accepted_trade") in TRADES
              and e.get("kind", "bend") == "bend"):
            since_reset.append(e)
    return [e for e in since_reset if e.get("first_offer_trade") not in (None, "none")][-WINDOW:]


def lead(entries: list[dict]) -> tuple[str, str]:
    """(lead, because). lead is "solid" or "makeup" (the default order)."""
    window = considered(entries)
    k = sum(1 for e in window if e["accepted_trade"] == "solid")
    if not window:
        return "makeup", "No decisions recorded yet; the default order stands."
    because = f"You kept it solid in {k} of your last {len(window)} decisions."
    if k >= SOLID_MIN:
        return "solid", because
    return "makeup", because[:-1] + "; the default order stands."


_FIRST_STOP = re.compile(r"\.(\s|$)")


def with_taste_words(sentence: str) -> str:
    """Add the taste words at the end of the first sentence: "Kept solid, as you usually do. ..." """
    m = _FIRST_STOP.search(sentence)
    if not m:
        return sentence + TASTE_TAIL + "."
    return sentence[:m.start()] + TASTE_TAIL + sentence[m.start():]


HELD = "You are holding solid. "
USUAL = "You usually keep it solid. "


def apply(result, because: str):
    """Mark a solver or model result as taste-led: words, one Why step, and the taste field.
    Only called when the designer has NOT held solid, so a Decision step that says they are
    holding solid is reworded: taste chose it, not a hold."""
    result.sentence = with_taste_words(result.sentence)
    steps = [s | {"text": USUAL + s["text"][len(HELD):]}
             if s.get("tag") == "Decision" and str(s.get("text", "")).startswith(HELD) else s
             for s in result.steps]
    result.steps = steps + [{"tag": "Taste", "text": because, "limit_id": None}]
    result.taste = {"lead": "solid", "because": because}
    return result
