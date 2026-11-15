# -*- coding: utf-8 -*-
"""SPEC_V9_CARD_SLOTS: the words in the card's fixed slots, mapped from what the core sent.

Echo (1), Verdict (2), Reason (3), Facts (4). Pure: no Rhino, no network, IronPython 2.7 and CPython.
The core's sentences are matched against its own templates; a sentence this table does not know
falls back to the core's words in the Reason slot and says so (mapped False, unmapped set), so a new
core sentence is visible, never silently wrong. A number is never made here: every figure is read
from the sentence or the fields the core sent.
"""
import math
import re

AS_DRAWN = "Buildable as drawn."
EASED = "Buildable, eased."
NOT_BUILDABLE = "Not buildable."
AS_MODELLED = "Buildable as modelled."
NO_ANSWER = "No answer yet."
NO_ANSWER_REASON = "The helper is not running."
TRIMMED_ECHO = "Kept to the timber length."
LIMITS = {"echo": 34, "verdict": 28, "reason": 68, "facts": 42}

_PREFIX = r"(?:Your (?:shape|line) holds|Buildable as (?:drawn|modelled))"
_KEPT = (
    (re.compile(r"^" + _PREFIX + r"\. Pressed in one curve from (\d+) layers, then milled to shape\.$"),
     "pressed", "Pressed in one curve, then milled."),
    (re.compile(r"^" + _PREFIX + r"\. Glued straight from (\d+) layers, then milled to shape\.$"),
     "glued", "Glued straight from layers, then milled."),
    (re.compile(r"^" + _PREFIX + r"\. Milled from one straight piece, no bending\.$"),
     "straight", "Milled from one straight piece."),
    (re.compile(r"^" + _PREFIX + r", in (\d+) pieces joined end to end\. Each pressed from layers, then milled\.$"),
     "pieces", "Made in pieces joined end to end."),
    (re.compile(r"^" + _PREFIX + r"\. (?:One stock 2x4|One piece as it comes), no pressing\.$"),
     "stock", "One piece as it comes, no pressing."),
)
_NAME = r"[A-Za-z]+(?: drift)?"
_EASED_PLATE = re.compile(r"^(" + _NAME + r"(?:(?:, | and )" + _NAME + r")*) (eased|straightened) so the "
                          r"(layers can bend|billet fits the machine|billet runs along the grain), "
                          r"moving the (?:plate|member) at most (\d+) mm\.$")
_EASED_CAUSE = {"layers can bend": "the layers can bend", "billet fits the machine": "it fits the machine",
                "billet runs along the grain": "it runs along the grain"}
_EASED_LINE = re.compile(r"^Line straightened by (\d+) mm so (it mills from one straight piece|"
                         r"the layers can bend, \d+ layers, then milled|the billet fits the machine)\.$")
_OVER = re.compile(r"\s+Waste (\d+)%, over your [\d.]+% target\.\s*$")
_TRIM = re.compile(r"\s+Kept to the 2\.4 m stock length\.\s*$")
_PART_MACHINE = re.compile(r"^This part will not fit through the machine(, even in \d+ pieces)?\.$")

_CONFLICTS = {   # core sentence: (Reason, action)
    "This bends too tightly for the thinnest layer.": ("It bends too tightly for the thinnest layer.", "redraw"),
    "This billet will not fit through the machine.": ("The billet is too big for the machine.", "redraw"),
    "The billet cannot run along the grain at this width.": ("The billet cannot run along the grain at this width.", "redraw"),
    "This will not mill from one straight piece on this machine.": ("One straight piece will not fit the machine.", "release"),
    "This shape could not be fitted with a billet.": ("No billet fits this shape.", "redraw"),
}
_PART_CONFLICTS = {
    "This part bends too tightly for the thinnest layer.": "Your part bends too tightly for the thinnest layer.",
    "This part will not mill from one straight piece on this machine.": "Your part will not mill from one straight piece.",
    "This part could not be fitted with a billet.": "No billet fits your part.",
}

_SAY = {
    ("hold", "solid"): "Keeping it as one piece.",
    ("hold", "shape"): "Keeping your {word} as drawn.",
    ("release", "solid"): "Glue is fine again.",
    ("release", "shape"): "Your {word} may move again.",
    ("hold", "less_waste"): "Thinner layers, less waste.",
    ("release", "less_waste"): "Back to the thickest layers.",
    ("hold", "split_ok"): "Shorter pieces are fine.",
    ("release", "split_ok"): "Keeping it in one length.",
}
_DIRECTION = {"up": "up", "down": "down", "toward_viewer": "toward you", "away_from_viewer": "away from you"}


def _round(x):
    return int(math.floor(x + 0.5))


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _cut(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _layers(n):
    return "%d layer%s" % (n, "" if n == 1 else "s")


def _needs(how, sentence_n, form):
    """'Needs N layers' or 'Needs N pieces', from the sentence's own number, else the sent form."""
    if how in ("straight", "stock"):
        return "Needs 1 piece"
    if how in ("pressed", "glued") and sentence_n:
        return "Needs " + _layers(sentence_n)
    if how == "pieces" and sentence_n:
        return "Needs %d pieces" % sentence_n
    pieces = [p for p in (form.get("pieces") or []) if isinstance(p, dict)] if isinstance(form, dict) else []
    if len(pieces) > 1:
        return "Needs %d pieces" % len(pieces)
    if not isinstance(form, dict):
        return ""
    b = form.get("billet") if isinstance(form.get("billet"), dict) else {}
    if form.get("straight_billet") or b.get("mode") == "stock":
        return "Needs 1 piece"
    n = _num(form.get("n_lamellas"))
    if n is None and pieces:
        n = _num(pieces[0].get("n_lamellas"))
    return ("Needs " + _layers(int(n))) if n else ""


def _facts(result, how, sentence_n, over):
    parts = []
    w = _num((result or {}).get("waste_pct"))
    if w is None:
        w = over
    if w is not None:
        parts.append("Waste %d%%%s" % (_round(w), ", over target" if over is not None else ""))
    dev = _num((result or {}).get("deviation_mm"))
    if dev is not None and _round(dev) > 0:
        parts.append("Moved %d mm" % _round(dev))
    sent = (result or {}).get("sent") or {}
    form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
    need = _needs(how, sentence_n, form)
    if need:
        parts.append(need)
    return "  ".join(parts)


def map_proposal(result, kind, word, holds):
    """The slots for a proposal or a conflict. kind: plate, surface, part or bend (the offline solver).
    Returns verdict, reason, facts, echo (the trim note), action (conflicts: release, redraw or
    other_part), mapped, unmapped (the core sentence this table did not know, else None)."""
    sentence = ((result or {}).get("sentence") or "").strip()
    status = (result or {}).get("status")
    over, trimmed, body = None, False, sentence
    while True:   # the target and trim notes may come in either order
        m = _OVER.search(body)
        if m:
            over, body = float(m.group(1)), body[:m.start()]
            continue
        m = _TRIM.search(body)
        if m:
            trimmed, body = True, body[:m.start()]
            continue
        break
    out = {"verdict": "", "reason": "", "facts": "", "echo": TRIMMED_ECHO if trimmed else "", "action": None,
           "mapped": True, "unmapped": None}
    held = list(holds or [])
    if status == "conflict":
        out["verdict"] = NOT_BUILDABLE
        reason, action = None, None
        if kind == "part":
            if body in _PART_CONFLICTS:
                reason, action = _PART_CONFLICTS[body], "other_part"
            else:
                m = _PART_MACHINE.match(body)
                if m:
                    reason = ("Even in pieces your part is too big for the machine." if m.group(1)
                              else "Your part is too big for the machine.")
                    action = "other_part"
        elif kind in ("plate", "surface") and body in _CONFLICTS:
            reason, action = _CONFLICTS[body]
            if "shape" in held:
                action = "release"   # easing was blocked by the hold: letting it go is the one next step
        if reason is None:
            out["mapped"], out["unmapped"] = False, sentence
            reason = _cut(sentence, LIMITS["reason"])
            action = "other_part" if kind == "part" else ("release" if "shape" in held else "redraw")
        out["reason"], out["action"] = reason, action
        return out
    dev = _num((result or {}).get("deviation_mm"))
    how, n, reason, eased = None, None, None, False
    for pat, tag, text in _KEPT:
        m = pat.match(body)
        if m:
            how, reason = tag, text
            n = int(m.group(1)) if m.groups() else None
            break
    if reason is None:
        m = _EASED_PLATE.match(body)
        if m:
            what = m.group(1)
            what = what[0].upper() + what[1:]
            reason, eased = "%s %s so %s." % (what, m.group(2), _EASED_CAUSE[m.group(3)]), True
            how = "eased"
    if reason is None:
        m = _EASED_LINE.match(body)
        if m:
            cause = m.group(2)
            cause = "the layers can bend" if cause.startswith("the layers") else cause
            reason, eased = "Line straightened so %s." % cause, True
            how = "straight" if "straight piece" in cause else "eased"
    if reason is None:
        out["mapped"], out["unmapped"] = False, sentence
        reason = _cut(sentence, LIMITS["reason"])
        eased = dev is not None and _round(dev) > 0
    if kind == "part":
        out["verdict"] = AS_MODELLED
    else:
        out["verdict"] = EASED if eased else AS_DRAWN
    out["reason"] = reason
    out["facts"] = _facts(result, how, n, over)
    return out


def echo(src, raw, word, kind):
    """Slot 1 from the reply's own actions or bends, never from its text, so the core keeps its longer
    lines for the command line. src: ("say", actions), ("photo", bends), ("photo_no", None) or None."""
    raw = raw or ""
    if not src:
        return _cut(raw, LIMITS["echo"])
    what = src[0]
    if what == "photo_no":
        return "Photo not read."
    if what == "photo":
        bends = src[1] or []
        if not bends:
            return "Photo read: no bends."
        if len(bends) > 1:
            return "Photo read: %d bends." % len(bends)
        b = bends[0]
        way = _DIRECTION.get(b.get("direction"))
        if way is None:
            return "Photo read: a bend."
        line = "Photo read: %s bend %s." % (b.get("size") or "a", way)
        return line if len(line) <= LIMITS["echo"] else "Photo read: a bend %s." % way
    actions = list(src[1] or [])
    if not actions:
        return "I did not catch a change."
    lines = []
    for op, name in actions:
        if raw.startswith("Already as little waste"):
            line = "Already the least waste."
        elif kind == "part" and (op, name) == ("hold", "shape"):
            line = "Your geometry is never moved."
        elif (op, name) in _SAY:
            line = _SAY[(op, name)].format(word=word)
        else:
            return _cut(raw, LIMITS["echo"])
        lines.append(line)
    out = lines[0]
    for line in lines[1:]:
        if len(out) + 1 + len(line) <= LIMITS["echo"] and line not in out:
            out += " " + line
    return out


_WORDS = (
    (re.compile(r"\bYour (?:shape|line) holds\b"), "Buildable as drawn"),
    (re.compile(r"\bOne stock 2x4\b"), "One piece as it comes"),
    (re.compile(r"\bplate\b"), "member"),
    (re.compile(r"\bPlate\b"), "Member"),
    (re.compile(r"\blamellas\b"), "layers"),
    (re.compile(r"\blamella\b"), "layer"),
)


def words(text):
    """The glossary on a Why? line: member, piece, billet, layer. Plate, lamella and stock are retired."""
    for pat, repl in _WORDS:
        text = pat.sub(repl, text or "")
    return text
