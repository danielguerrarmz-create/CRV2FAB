"""Surface member solver, spec v4 (docs/SPEC_V4.md): the teammate's fabrication route.

One singly curved glulam billet is pressed from lamellas, then CNC milled to the doubly
curved member. The checks (lamella bend R/t, machine opening, waste) live in fabrication.py.
The stroke reading, the smoothing ladder and the nearest-point deviation are v3's, unchanged.

Order, as always: keep the drawn line, change the make-up first (the thickest lamella that
passes), move the line last (the least straightening found by bisection over the ladder).

numpy is imported only inside functions here (via fabrication), so the bend kind, the server
and the record never need it.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from .intent import Holds
from .solver import jround, m
from .surface import (LADDER, STRAIGHT, Curve, DegenerateSurface, SurfaceIntent, build_curve, deviation, ladder_uv,
                      resample_even, smooth)

TRIM_NOTE = "Kept to the 2.4 m stock length."


def overshoot_mm(mc: dict) -> float:
    """How far the billet is past the opening in its best orientation; 0 when it fits."""
    return max(0.0, -float(mc["margin_mm"]))


FIT_MAX_EVAL = 20  # our argument to glulam_math.fit_bending_plane (their default 60). Measured 2026-11-14 on
                   # the vector strokes: same make-ups as 30, waste within about a point; 12 changed one.


def _f(x, nd=1):
    return None if x is None or (isinstance(x, float) and math.isinf(x)) else round(float(x), nd) + 0.0


@dataclass(frozen=True)
class SurfaceForm:
    curve: Curve
    intent: Curve
    smoothing_passes: int
    straight: bool  # one straight piece, no pressing (hold solid, or taste)
    fit: object  # fabrication.Fit
    check: dict  # fabrication.check_billet result
    lam_options: tuple = ()  # the layer options of the settings it was solved with

    @property
    def n_lamellas(self) -> int:
        return self.check["lam_count"]

    @property
    def lamella_mm(self) -> float:
        return self.check["lam_mm"]

    @property
    def solid(self) -> bool:
        return self.straight

    def billet(self, outline: bool = True) -> dict:
        from . import fabrication as fb
        ext, fit = self.check["ext"], self.fit
        out = {"mode": "straight" if (self.straight or fit.mode == "straight") else "arc",
               "length_mm": _f(ext["sHigh"] - ext["sLow"]), "width_mm": _f(ext["wHigh"] - ext["wLow"]),
               "depth_mm": _f(ext["dHigh"] - ext["dLow"]),
               "radius_mm": _f(getattr(fit.spine, "radius", None)) if fit.mode == "arc" else None,
               "volume_m3": round(self.check["billet_mm3"] / 1e9, 6)}
        if outline:
            out["outline"] = fb.outline_polylines(fit, ext)
        return out

    def checks(self) -> dict:
        c = self.check
        bend = {k: (_f(v) if isinstance(v, float) else v) for k, v in c["bend"].items()}
        full = dict(c["machine"])  # v6: the opening is the user's own setting, shown plainly
        mach = full | {"need_mm": [_f(x) for x in full["need_mm"]], "opening_mm": [_f(x) for x in full["opening_mm"]],
                       "overshoot_mm": _f(overshoot_mm(full))}
        return {"bend": bend, "machine": mach, "waste_pct": _f(c["waste_pct"]),
                "waste_rounding_pct": _f(c["waste_rounding_pct"]),
                "kx": None if not math.isfinite(c["kx"]) else round(float(c["kx"]), 4)}

    def as_dict(self) -> dict:
        cv = self.curve
        vec = lambda pts, nd: [[round(a, nd) + 0.0 for a in p] for p in pts]  # noqa: E731  (+ 0.0 drops -0.0)
        return {
            "kind": "surface_member",
            "stations": vec(cv.pts, 2),
            "normals": vec(cv.normals, 6),
            "uv": vec(cv.uv, 6),
            "intent_stations": vec(self.intent.pts, 2),
            "n_lamellas": self.n_lamellas, "lamella_mm": _f(self.lamella_mm, 2),
            "straight_billet": self.straight,
            "billet": self.billet(),
            "part_volume_m3": round(self.check["part_mm3"] / 1e9, 6),
            "checks": self.checks(),
            "min_radius_normal_mm": _f(cv.r_normal), "min_radius_side_mm": _f(cv.r_side),
            "max_twist_deg_per_m": round(cv.max_twist_deg_per_m, 1),
            "length_mm": round(cv.length_mm, 1),
            "smoothing_passes": self.smoothing_passes,
        }

    def summary(self) -> dict:
        d = self.as_dict()
        for k in ("stations", "normals", "uv", "intent_stations"):
            d.pop(k)
        d["billet"].pop("outline", None)
        return d


@dataclass
class SurfaceResult:
    status: str  # "proposed" | "conflict"
    sentence: str
    steps: list[dict]
    source: str
    form: SurfaceForm | None = None
    deviation_mm: float | None = None
    trimmed: bool = False
    conflict: tuple[str, str] | None = None
    governing: list[str] = field(default_factory=list)
    rejected_proposals: list[dict] = field(default_factory=list)
    taste: dict | None = None  # {lead, because} when taste chose this answer
    model_text: dict | None = None  # the model's own sentence and steps: debug only, never shown
    less_waste: dict | None = None  # {from_pct, to_pct, saved} when the designer asked for less waste
    model_ms: int | None = None  # wall time spent in model calls; None when no model was asked

    def as_dict(self, intent=None) -> dict:
        return {
            "status": self.status,
            "form": self.form.as_dict() if self.form else None,
            "sentence": self.sentence,
            "steps": self.steps,
            "deviation_mm": None if self.deviation_mm is None else round(self.deviation_mm, 1),
            "trimmed": self.trimmed,
            "source": self.source,
            "conflict": list(self.conflict) if self.conflict else None,
            "governing": self.governing,
            "taste": self.taste,
            "model_ms": self.model_ms,
            **({"less_waste": self.less_waste} if self.less_waste is not None else {}),
        }


class Ladder:
    """Curves for each smoothing pass count, built on demand. None if the surface degenerates.
    Also caches each rung's billet fits, which are the expensive part."""

    def __init__(self, intent: SurfaceIntent):
        self.intent = intent
        self._cache: dict[int, Curve | None] = {0: intent.intent}
        # Smoothing is iterative, so rung m continues from the last rung smoothed (identical result,
        # far less work than restarting each rung from the intent).
        self._smoothed = (0, list(intent.intent_uv))
        self._fits: dict[tuple[int, bool, bool], object] = {}
        self.allowance = 0.0  # set by the solver from the settings: passed to their fit and extents

    def _uv(self, passes: int):
        surf = self.intent.surface
        if passes in (0, STRAIGHT):
            return ladder_uv(surf, self.intent.intent_uv, passes)
        done, uv = self._smoothed
        if passes >= done:
            uv = smooth(uv, passes - done)
            self._smoothed = (passes, uv)
        else:
            uv = smooth(self.intent.intent_uv, passes)
        return resample_even(surf, uv)[0]

    def get(self, passes: int) -> Curve | None:
        if passes not in self._cache:
            try:
                self._cache[passes] = build_curve(self.intent.surface, self._uv(passes))
            except DegenerateSurface:
                self._cache[passes] = None
        return self._cache[passes]

    def deviation(self, passes: int) -> float:
        return 0.0 if passes == 0 else deviation(self.get(passes), self.intent.intent)

    def fit(self, passes: int, straight: bool):
        """The billet fit for this rung (arc pressing, or one straight piece). None if no curve.
        Rung 0 gets the full bending-plane fit; straightened rungs reuse its plane (their bendPlane
        path), which keeps a straightening search to a fraction of a second."""
        from . import fabrication as fb
        key = (passes, straight)
        if key not in self._fits:
            curve = self.get(passes)
            if curve is None:
                self._fits[key] = None
            else:
                pts = fb.member_points(curve)
                a = self.allowance
                if straight:
                    self._fits[key] = fb.fit_straight_billet(pts, a)
                elif passes == 0:
                    self._fits[key] = fb.fit_arc_billet(pts, a, max_eval=FIT_MAX_EVAL)
                else:
                    drawn = self.fit(0, False)
                    self._fits[key] = fb.fit_arc_billet_in_plane(pts, drawn.n, a) if drawn is not None else \
                        fb.fit_arc_billet(pts, a, max_eval=FIT_MAX_EVAL)
        return self._fits[key]


@dataclass
class FabSetup:
    """What the route needs besides the line, from the user's settings (spec v6, section 2)."""
    ratio: float
    lams: tuple
    machine: dict  # {name or None, openingWidth, openingHeight, lengthMax}
    allowance: float = 0.0
    max_waste_pct: float | None = None  # the waste target, a check the user set
    max_pieces: int | None = None  # from the session settings; None: pieces.current_settings() decides

    @classmethod
    def default(cls) -> "FabSetup":
        from .settings import fab_setup
        return fab_setup(None)


def evaluate(ladder: Ladder, passes: int, straight: bool, setup: FabSetup, lam_mm: float | None = None):
    """(passing check or None, the check that explains a failure). straight: one piece, machine
    only. Otherwise the thickest lamella in the stock that passes both checks, or lam_mm only."""
    from . import fabrication as fb
    fit = ladder.fit(passes, straight)
    if fit is None:
        return None, None
    member = fb.member_volume_mm3(ladder.get(passes))
    if straight:
        chk = fb.check_billet(fit, None, setup.machine, setup.ratio, member, setup.allowance)
        return (chk if chk["ok"] else None), chk
    stock = [lam_mm] if lam_mm is not None else list(setup.lams)
    for i, t in enumerate(stock):
        thinnest = i == len(stock) - 1  # always fully checked: it explains a conflict
        chk = fb.check_billet(fit, float(t), setup.machine, setup.ratio, member, setup.allowance,
                              stop_at_bend=not thinnest)
        if chk["ok"]:
            return chk, chk
    return None, chk


def thickest_lam() -> float:
    """The thickest default layer option, read without numpy."""
    from .settings import DEFAULTS
    return float(max(DEFAULTS["lam_options_mm"]))


def passes_text(passes: int) -> str:
    return "fully straightened between its ends" if passes == STRAIGHT else f"{passes} smoothing passes"


def _billet_words(form: SurfaceForm) -> str:
    b = form.billet(outline=False)
    size = f"{b['length_mm']:.0f} x {b['width_mm']:.0f} x {b['depth_mm']:.0f} mm (length x width x depth)"
    if form.straight:
        return f"One straight piece {size}, no pressing."
    if b["mode"] == "straight":
        return f"One straight billet {size}, glued from {form.n_lamellas} layers of {form.lamella_mm:g} mm."
    return (f"One billet pressed to a {m(b['radius_mm'])} radius, {size}, from {form.n_lamellas} layers of "
            f"{form.lamella_mm:g} mm.")


def _opening_words(chk: dict) -> str:
    """The conflict's second term: the opening (the user's setting, or a private machine's)."""
    ow, oh = chk["machine"]["opening_mm"]
    return f"machine opening {ow:.0f} x {oh:.0f} mm"


def _bend_words(chk: dict) -> str:
    b = chk["bend"]
    if not b["applies"]:
        return "One straight piece is not bent, so the layer bend limit does not apply."
    if b["tightest_radius_mm"] is None:
        return f"The billet is straight, so its {chk['lam_mm']:g} mm layers do not bend."
    return (f"Its tightest layer bends to {m(b['tightest_radius_mm'])}, {b['ratio']:.0f} times its "
            f"{chk['lam_mm']:g} mm thickness; the limit is {b['limit']:g}.")


def _machine_words(chk: dict) -> str:
    mc = chk["machine"]
    w, h = mc["need_mm"]
    ow, oh = mc["opening_mm"]
    lying = "lying flat" if mc["orientation"] == "flat" else "on edge"
    where = f"the {mc['name']} takes" if mc.get("name") else "the opening is"
    if mc["ok"]:
        return f"It needs {w:.0f} x {h:.0f} mm {lying}; {where} {ow:.0f} x {oh:.0f} mm, so it fits."
    return (f"It needs {w:.0f} x {h:.0f} mm {lying}; {where} {ow:.0f} x {oh:.0f} mm, so it is too large by "
            f"{overshoot_mm(mc):.0f} mm.")


def solve_surface(intent: SurfaceIntent, holds: Holds, cards=None, ladder: Ladder | None = None,
                  setup: FabSetup | None = None) -> SurfaceResult:
    """cards is accepted for the shared call shape and ignored: this route reads its own cards."""
    setup = setup or FabSetup.default()
    ladder = ladder or Ladder(intent)
    ladder.allowance = setup.allowance
    c0 = intent.intent
    solid, shape = "solid" in holds, "shape" in holds
    rungs = (0,) if shape else LADDER

    steps = [{"tag": "Heard", "text": f"Follow your line on the surface, {m(c0.length_mm)} long."
              + (" " + TRIM_NOTE if intent.trimmed else ""), "limit_id": "length" if intent.trimmed else None}]

    results: dict[int, tuple] = {}

    def at(i: int):
        if i not in results:
            results[i] = evaluate(ladder, rungs[i], solid, setup)
        return results[i]

    chosen = 0 if at(0)[0] else None
    from .pieces import try_split_surface  # spec v6 section 4: layer option, then pieces, then the line
    split = try_split_surface(intent, holds, ladder, setup, at(0))
    if split is not None:
        return split
    if chosen is None and len(rungs) > 1 and at(len(rungs) - 1)[0]:
        lo, hi = 0, len(rungs) - 1  # lo fails, hi passes: bisect for the least straightening
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if at(mid)[0] else (mid, hi)
        chosen = hi

    if chosen is None:
        why = at(len(rungs) - 1)[1] or at(0)[1]
        bend_fails = why is not None and not why["bend"]["ok"]
        if solid:
            sentence = "This will not mill from one straight piece on this machine."
            pair, limit_id = ("one straight piece", _opening_words(why)), "machine"
        elif bend_fails:
            sentence = "This bends too tightly for the thinnest layer."
            pair, limit_id = ("drawn line", f"thinnest lamella {setup.lams[-1]:g} mm at R/t {setup.ratio:g}"), "lam_ratio"
        else:
            sentence = "This billet will not fit through the machine."
            pair, limit_id = ("drawn line", _opening_words(why)), "machine"
        if intent.trimmed:
            sentence += " " + TRIM_NOTE
        if why is not None:
            steps.append({"tag": "Limit", "text": _bend_words(why), "limit_id": "lam_ratio"})
            steps.append({"tag": "Limit", "text": _machine_words(why), "limit_id": "machine"})
        steps.append({"tag": "Cannot resolve", "text": ("Even with your line held as drawn, " if shape else
                      "Even straightened as far as it goes, ") + "no make-up passes.", "limit_id": limit_id})
        return SurfaceResult("conflict", sentence, steps, "rules", trimmed=intent.trimmed, conflict=pair)

    passes = rungs[chosen]
    chk = at(chosen)[0]
    saving = None
    if "less_waste" in holds and not solid:  # asked for in words: never by itself, never moves the line
        best = least_waste(ladder, passes, setup)
        saving = {"from_pct": round(chk["waste_pct"], 1) + 0.0, "to_pct": round(best["waste_pct"], 1) + 0.0,
                  "saved": best["waste_pct"] < chk["waste_pct"] - 0.05}
        chk = best
    elif "less_waste" in holds:
        saving = {"from_pct": round(chk["waste_pct"], 1) + 0.0, "to_pct": round(chk["waste_pct"], 1) + 0.0,
                  "saved": False}
    target = waste_target(ladder, passes, solid, setup, chk)
    chk = target["check"]
    form = SurfaceForm(ladder.get(passes), c0, passes, solid, ladder.fit(passes, solid), chk, tuple(setup.lams))
    dev = ladder.deviation(passes)
    cause_bend = passes != 0 and at(0)[1] is not None and not at(0)[1]["bend"]["ok"]
    result = finish(intent, form, dev, steps, "rules", solid, cause_bend)
    if target["step"]:
        result.steps.append(target["step"])
    if target["over"]:
        result.sentence += f" Waste {round(chk['waste_pct']):.0f}%, over your {setup.max_waste_pct:g}% target."
    if saving is not None:
        result.less_waste = saving
        result.steps.append({"tag": "Decision", "limit_id": None, "text": (
            f"You asked for less waste: {form.n_lamellas} layers of {form.lamella_mm:g} mm waste "
            f"{saving['to_pct']:.0f}% instead of {saving['from_pct']:.0f}%, the least of the make-ups that pass."
            if saving["saved"] else "You asked for less waste: this is already the least waste this line allows.")})
    return result


def waste_target(ladder: Ladder, passes: int, solid: bool, setup: FabSetup, chk: dict) -> dict:
    """The waste target the user set (spec v6, section 2): a proposal over it tries a thinner layer
    option; it never moves the line. Seam: splitting into pieces (section 4) is the next remedy,
    built on its own branch. Returns {check, over, step}."""
    target = setup.max_waste_pct
    if target is None or chk["waste_pct"] <= target:
        return {"check": chk, "over": False, "step": None}
    if solid:
        return {"check": chk, "over": True, "step": {"tag": "Check", "limit_id": "max_waste_pct", "text": (
            f"Waste {chk['waste_pct']:.0f}% is over your {target:g}% target; one straight piece has no thinner "
            f"layer to try.")}}
    from . import fabrication as fb
    fit = ladder.fit(passes, False)
    member = fb.member_volume_mm3(ladder.get(passes))
    passing = [c for c in (fb.check_billet(fit, float(t), setup.machine, setup.ratio, member, setup.allowance)
                           for t in setup.lams) if c["ok"]]
    meets = [c for c in passing if c["waste_pct"] <= target]
    if meets:  # the thickest option that meets it: the fewest glue lines
        best = max(meets, key=lambda c: c["lam_mm"])
        return {"check": best, "over": False, "step": {"tag": "Decision", "limit_id": "max_waste_pct", "text": (
            f"Your waste target is {target:g}%: {chk['lam_mm']:g} mm layers would waste {chk['waste_pct']:.0f}%, "
            f"so {best['lam_mm']:g} mm layers, wasting {best['waste_pct']:.0f}%.")}}
    best = min(passing, key=lambda c: (round(c["waste_pct"], 1), c["lam_count"]))
    how = ("no layer option brings it lower" if best["lam_mm"] == chk["lam_mm"] else
           f"{best['lam_mm']:g} mm layers would reach {best['waste_pct']:.0f}%")
    return {"check": chk, "over": True, "step": {"tag": "Check", "limit_id": "max_waste_pct", "text": (
        f"Waste {chk['waste_pct']:.0f}% is over your {target:g}% target; the best reachable without moving your "
        f"line: {how}.")}}


def least_waste(ladder: Ladder, passes: int, setup: FabSetup) -> dict:
    """Among the lamellas that pass every check at this rung, the least waste; ties to fewer layers."""
    from . import fabrication as fb
    fit = ladder.fit(passes, False)
    member = fb.member_volume_mm3(ladder.get(passes))
    passing = [c for c in (fb.check_billet(fit, float(t), setup.machine, setup.ratio, member, setup.allowance)
                           for t in setup.lams) if c["ok"]]
    return min(passing, key=lambda c: (round(c["waste_pct"], 1), c["lam_count"]))


def kept_sentence(form: SurfaceForm) -> str:
    if form.straight:
        return "Your line holds. Milled from one straight piece, no bending."
    if form.fit.mode == "straight":
        return f"Your line holds. Glued straight from {form.n_lamellas} layers, then milled to shape."
    return f"Your line holds. Pressed in one curve from {form.n_lamellas} layers, then milled to shape."


def eased_sentence(form: SurfaceForm, dev: float, cause_bend: bool) -> str:
    x = jround(dev)
    if form.straight:
        return f"Line straightened by {x} mm so it mills from one straight piece."
    if cause_bend:
        return f"Line straightened by {x} mm so the layers can bend, {form.n_lamellas} layers, then milled."
    return f"Line straightened by {x} mm so the billet fits the machine."


def finish(intent: SurfaceIntent, form: SurfaceForm, dev: float, steps: list, source: str, solid_held: bool,
           cause_bend: bool, sentence: str | None = None) -> SurfaceResult:
    """Steps, sentence and governing cards for a passing form (solver or model)."""
    chk = form.check
    steps = list(steps)
    steps.append({"tag": "Limit", "text": _bend_words(chk), "limit_id": "lam_ratio"})
    steps.append({"tag": "Limit", "text": _machine_words(chk), "limit_id": "machine"})
    if form.smoothing_passes == 0:
        decision = "Kept your line. " + _billet_words(form)
    else:
        lead = "You are holding solid. " if solid_held else ""
        decision = (f"{lead}Straightened the line within the surface ({passes_text(form.smoothing_passes)}), moving "
                    f"it up to {jround(dev)} mm. " + _billet_words(form))
    steps.append({"tag": "Decision", "text": decision, "limit_id": None})
    steps.append({"tag": "Check", "text": f"Milling it to shape wastes {chk['waste_pct']:.0f}% of the billet. "
                                          f"The twist, up to {form.curve.max_twist_deg_per_m:.1f} degrees per metre, "
                                          f"is milled out.", "limit_id": None})
    if sentence is None:
        sentence = kept_sentence(form) if form.smoothing_passes == 0 else eased_sentence(form, dev, cause_bend)
        if intent.trimmed:
            sentence += " " + TRIM_NOTE
    if form.smoothing_passes != 0:
        governing = ["lam_ratio"] if cause_bend else ["machine"]
    else:
        governing = ["machine"] if form.straight else ["lam_ratio", "machine"]
    return SurfaceResult("proposed", sentence, steps, source, form, dev, intent.trimmed, governing=governing)
