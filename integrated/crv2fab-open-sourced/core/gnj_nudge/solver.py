"""Deterministic fallback solver: a port of solve() in the ghost-nudge.html mock,
extended to a bend in any direction (shared spec v2).

Order of what gets given up: keep the drawn shape (radius AND direction), change
the make-up first (the fewest layers through the 38 mm and strips across the
89 mm that pass), move the radius last. The direction is never changed. Holds
override that order. A bend straight up or down (0 or 180 degrees) reproduces
the v1 numbers and wording exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .intent import Holds, Intent
from .limits import EPS, Form, LimitCard, deviation_mm, face_radii, factors, governing


def m(mm: float) -> str:
    """Metres to two places, as the mock prints them."""
    return f"{mm / 1000:.2f} m"


def n1(x: float) -> str:
    """One decimal, trailing .0 dropped (JS Math.round(x*10)/10 then toString)."""
    r = math.floor(x * 10 + 0.5) / 10
    return str(int(r)) if r == int(r) else str(r)


def jround(x: float) -> int:
    """JS Math.round: half rounds up."""
    return int(math.floor(x + 0.5))


@dataclass
class SolveResult:
    status: str  # "proposed" or "conflict"
    sentence: str
    steps: list[dict] = field(default_factory=list)
    form: Form | None = None
    deviation_mm: float | None = None
    conflict: tuple[str, str] | None = None
    governing: list[str] = field(default_factory=list)


def _step(tag: str, text: str, limit_id: str | None = None) -> dict:
    return {"tag": tag, "text": text, "limit_id": limit_id}


FACE_WORDS = {"thickness": "38 mm thickness", "width": "89 mm width"}


def makeup_phrase(n: int, t: float, k: int, w: float, glued: bool = True) -> str:
    """How the member is made, in plain words. Layers only reads as in v1."""
    g = "glued " if glued else ""
    if k == 1:
        return f"{n} {g}layers of {n1(t)} mm"
    if n == 1:
        return f"{k} {g}strips of {n1(w)} mm side by side"
    return f"{n} layers of {n1(t)} mm and {k} strips of {n1(w)} mm, glued both ways"


def makeup_short(n: int, k: int) -> str:
    if k == 1:
        return f"{n} glued layers"
    if n == 1:
        return f"{k} glued strips side by side"
    return f"{n} layers of {k} strips, glued both ways"


def kept_sentence(n: int, k: int) -> str:
    if k == 1:
        return f"Your curve holds. Made from {n} glued layers in place of one solid piece."
    if n == 1:
        return f"Your curve holds. Made from {k} glued strips side by side in place of one solid piece."
    return f"Your curve holds. Glued both ways, {n} layers of {k} strips."


def describe(intent: Intent, form: Form, cards: dict[str, LimitCard], base: SolveResult) -> tuple[str, list[dict]]:
    """Rule-template sentence and steps for any checked form (used when the model proposed it):
    every fact comes from the form and the cards, never from model text."""
    dev = deviation_mm(intent.radius_mm, form.radius_mm, intent.chord_mm)
    if base.form is not None and (base.form.n_lamellas, base.form.n_strips) == (form.n_lamellas, form.n_strips) \
            and abs(base.form.radius_mm - form.radius_mm) <= 0.5:
        return base.sentence, list(base.steps)
    RATIO = cards["bend_ratio"].value
    c, s = factors(form.bend_angle_deg)
    n, t, k, w = form.n_lamellas, form.lamella_mm, form.n_strips, form.strip_mm
    legacy = s == 0
    heard = f"Bend the full {m(intent.chord_mm)} to a radius of {m(intent.radius_mm)}."
    steps = [_step("Heard", heard if legacy else heard + f" Direction {n1(form.bend_angle_deg)} degrees from up."),
             _step("Limit", f"This make-up bends to {m(max(t * RATIO * c, w * RATIO * s))} or wider in this direction.",
                   "bend_ratio")]
    moved = dev > 0.5
    if form.solid:
        decision = f"Kept one piece and opened the radius to {m(form.radius_mm)}." if moved else "No change needed."
        sentence = (f"Kept solid. Curve eased by {jround(dev)} mm so one piece can bend it." if moved
                    else "Buildable as drawn, in one solid piece.")
    elif moved:
        decision = f"Opened the radius to {m(form.radius_mm)} and made it from {makeup_phrase(n, t, k, w, glued=False)}."
        sentence = f"Curve eased by {jround(dev)} mm so it can be built, in {makeup_short(n, k)}."
    else:
        decision = f"Kept your curve and changed how it is made: {makeup_phrase(n, t, k, w)}."
        sentence = kept_sentence(n, k)
    steps.append(_step("Decision", decision))
    steps.append(_step("Check", f"Passes. The ghost sits {jround(dev)} mm from your curve at mid-span.", "bend_ratio"))
    return sentence, steps


def solve(intent: Intent, holds: Holds, cards: dict[str, LimitCard]) -> SolveResult:
    T = cards["stock_thickness"].value
    W = cards["stock_width"].value
    RATIO = cards["bend_ratio"].value
    MINLAM = cards["min_lamella"].value
    LENGTH = cards["length"].value
    R, C, a = intent.radius_mm, intent.chord_mm, intent.bend_angle_deg
    c, s = factors(a)
    legacy = s == 0  # straight up or down: v1 wording
    nmax, kmax = max(1, math.floor(T / MINLAM)), max(1, math.floor(W / MINLAM))

    def fewest(stock: float, r_face: float, most: int) -> int | None:
        """Fewest equal pieces across `stock` that bend to `r_face`; None if even `most` cannot."""
        for n in range(1, most + 1):
            if r_face / (stock / n) >= RATIO - EPS:
                return n
        return None

    Rsolid = max(T * RATIO * c, W * RATIO * s)
    solid_face = "thickness" if T * c >= W * s else "width"
    in_dir = "" if legacy else " in this direction"
    stock = f"{T:g} mm" if legacy else f"{T:g} x {W:g} mm"
    steps: list[dict] = []

    def conflict(sentence: str, text: str, pair: tuple[str, str], limit_id: str) -> SolveResult:
        steps.append(_step("Cannot resolve", text, limit_id))
        return SolveResult("conflict", sentence, steps, conflict=pair)

    def proposed(sentence: str, radius: float, n: int, k: int) -> SolveResult:
        form = Form(radius, n, T / n, C, k, W / k, a)
        dev = deviation_mm(R, radius, C)
        return SolveResult("proposed", sentence, steps, form, dev, governing=governing(form, cards, dev))

    heard = f"Bend the full {m(C)} to a radius of {m(R)}."
    steps.append(_step("Heard", heard if legacy else heard + f" Direction {n1(a)} degrees from up."))

    # Not in the mock (its span is fixed at 2.4 m): a span longer than the member cannot be bent at all.
    if C > LENGTH:
        return conflict("This span is longer than the timber.",
                        f"The drawn span of {m(C)} is longer than the {m(LENGTH)} member.",
                        (f"drawn span {m(C)}", f"member length {m(LENGTH)}"), "length")

    rz, ry = face_radii(R, a)
    n0, k0 = fewest(T, rz, nmax), fewest(W, ry, kmax)

    if n0 == 1 and k0 == 1:
        steps.append(_step("Limit", f"Solid {stock} bends to {m(Rsolid)} or wider{in_dir}. "
                                    f"Your curve is inside that.", "bend_ratio"))
        steps.append(_step("Decision", "No change needed."))
        return proposed("Buildable as drawn, in one solid piece.", R, 1, 1)

    governs = "" if legacy else f" The {FACE_WORDS[solid_face]} governs."
    steps.append(_step("Limit", f"Solid {stock} bends no tighter than {m(Rsolid)}{in_dir}. "
                                f"Your curve is {n1(Rsolid / R)} times too tight for one piece.{governs}",
                       "bend_ratio"))

    if "solid" in holds:
        if "shape" in holds:
            return conflict("Solid and this curve cannot both be built.",
                            f"Solid and a {m(R)} radius cannot both be true in {stock} stock{in_dir}.",
                            ("solid section", f"drawn radius {m(R)}"), "bend_ratio")
        dev = deviation_mm(R, Rsolid, C)
        steps.append(_step("Decision", f"You are holding solid. Kept one piece and opened the radius to {m(Rsolid)}."))
        steps.append(_step("Check", f"Passes. The ghost sits {jround(dev)} mm from your curve at mid-span.", "bend_ratio"))
        return proposed(f"Kept solid. Curve eased by {jround(dev)} mm so one piece can bend it.", Rsolid, 1, 1)

    if n0 is not None and k0 is not None:
        t, w = T / n0, W / k0
        steps.append(_step("Decision", f"Kept your curve and changed how it is made: {makeup_phrase(n0, t, k0, w)}."))
        if legacy:
            check_text = f"A {n1(t)} mm layer bends to {m(t * RATIO)}. Passes, 0 mm from your curve."
        else:
            tightest = max(t * RATIO * c, w * RATIO * s)
            face = "thickness" if t * RATIO * c >= w * RATIO * s else "width"
            check_text = (f"This make-up bends to {m(tightest)} in this direction; the {FACE_WORDS[face]} governs. "
                          f"Passes, 0 mm from your curve.")
        steps.append(_step("Check", check_text, "bend_ratio"))
        return proposed(kept_sentence(n0, k0), R, n0, k0)

    # Some face would need pieces thinner than the thinnest that can be cut.
    piece, formal = ("layer", "lamella") if n0 is None else ("strip", "strip")
    Rmin = max(RATIO * (T / nmax) * c, RATIO * (W / kmax) * s)
    if "shape" in holds:
        return conflict(f"This curve is too tight for any {piece} we can cut.",
                        f"The thinnest {piece} ({MINLAM:g} mm) bends no tighter than {m(Rmin)}{in_dir}. "
                        f"Your {m(R)} radius cannot be held.",
                        (f"drawn radius {m(R)}", f"thinnest {formal} {MINLAM:g} mm"), "min_lamella")
    rz2, ry2 = face_radii(Rmin, a)
    n2, k2 = fewest(T, rz2, nmax) or nmax, fewest(W, ry2, kmax) or kmax
    dev = deviation_mm(R, Rmin, C)
    steps.append(_step("Decision", f"Too tight even for the thinnest {piece}. Used "
                                   f"{makeup_phrase(n2, T / n2, k2, W / k2, glued=False)} "
                                   f"and opened the radius to {m(Rmin)}.", "min_lamella"))
    steps.append(_step("Check", f"Passes. The ghost sits {jround(dev)} mm from your curve at mid-span.", "bend_ratio"))
    return proposed(f"Curve eased by {jround(dev)} mm, the tightest this timber bends, in {makeup_short(n2, k2)}.",
                    Rmin, n2, k2)
