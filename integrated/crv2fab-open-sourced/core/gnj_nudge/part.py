"""Spec v6 section 3: intent kind `part`, the designer's own geometry.

Request: {kind: "part", member_id, points: [[x, y, z], ...], volume_mm3}, mm, Z up. `points` are
surface samples of the designer's closed solid (300 to 6000, from Rhino's mesh); `volume_mm3` is
the solid's own volume from Rhino.

Treated exactly as the technical member's Grasshopper flow treats a part: fit the minimum-volume
singly curved billet around the points (fit_bending_plane, fit_arc_2d, billet_extents, through
fabrication.fit_arc_billet), walk the layer options for the bend check (offset_radii), check the
opening (min_width_box), report waste. The geometry is the designer's and is never altered: no
ghost of a changed shape exists for this kind. The agent may change only how it is made, the layer
option and the number of pieces (pieces.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import pieces as pc

MIN_POINTS, MAX_POINTS = 300, 6000
COORD_LIMIT_MM = 1_000_000.0
NEVER_MOVED = "Your geometry is never moved."


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True, eq=False)  # eq=False: hashed by identity, so the fit cache lives on this object
class PartIntent:
    member_id: str
    points: tuple
    volume_mm3: float
    kind = "part"

    @classmethod
    def from_dict(cls, d) -> "PartIntent":
        from .intent import MEMBER_ID
        if not isinstance(d, dict):
            raise ValueError("intent must be an object")
        mid = d.get("member_id")
        if not isinstance(mid, str) or not MEMBER_ID.fullmatch(mid):
            raise ValueError("member_id must be 1 to 32 letters, digits, underscores or hyphens")
        pts = d.get("points")
        if not isinstance(pts, list) or not MIN_POINTS <= len(pts) <= MAX_POINTS:
            raise ValueError(f"points must hold {MIN_POINTS} to {MAX_POINTS} points")
        for p in pts:
            if not isinstance(p, list) or len(p) != 3 or not all(_finite(c) and abs(c) <= COORD_LIMIT_MM for c in p):
                raise ValueError(f"each point must be [x, y, z], finite, within {COORD_LIMIT_MM:g} mm")
        vol = d.get("volume_mm3")
        if not _finite(vol) or vol <= 0:
            raise ValueError("volume_mm3 must be a positive number")
        return cls.build(mid, pts, float(vol))

    @classmethod
    def build(cls, member_id: str, points, volume_mm3: float) -> "PartIntent":
        pts = tuple(tuple(float(c) for c in p) for p in points)
        spans = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
        box = spans[0] * spans[1] * spans[2]
        if min(spans) <= 0:
            raise ValueError("the points are flat or a line: they do not sample a solid")
        if volume_mm3 > box * 1.001:  # a solid holds no more than the box around it
            raise ValueError("volume_mm3 is larger than the box around the points")
        return cls(member_id, pts, float(volume_mm3))

    def summary(self) -> dict:
        return {"member_id": self.member_id, "kind": "part", "points": len(self.points),
                "volume_mm3": round(self.volume_mm3, 1)}


class PartMember(pc.Member):
    """Pieces are equal ranges along the part's principal length axis (their pca_axes)."""

    def __init__(self, intent: PartIntent):
        import numpy as np
        from . import fabrication as fb
        self.owner = intent
        self.P_all = np.array(intent.points, dtype=float)  # a copy: the intent's own tuple is never touched
        self.origin, axes = fb.gm.pca_axes(self.P_all)
        self.axis, self.across = axes[0], axes[1]
        self.s = (self.P_all - self.origin) @ self.axis
        self.s0, self.s1 = float(self.s.min()), float(self.s.max())
        self.length = self.s1 - self.s0
        self.total_mm3 = intent.volume_mm3
        self._masks: dict = {}

    def _bound(self, P: int, k: int) -> float:
        return self.s0 + self.length * k / P

    def points(self, P, k):
        if (P, k) not in self._masks:
            eps = 1e-9 * max(1.0, self.length)
            lo, hi = self._bound(P, k) - eps, self._bound(P, k + 1) + eps
            self._masks[(P, k)] = (self.s >= lo) & (self.s <= hi)
        return self.P_all[self._masks[(P, k)]]

    def volume(self, P, k):
        return self.total_mm3 / P  # equal shares: exact for a constant section; the total is exact

    def span(self, P, k):
        return self._bound(P, k) - self.s0, self._bound(P, k + 1) - self.s0

    def cut(self, P, j):
        """The cut plane (origin, normal) and a line across the part in it, for clients to draw."""
        import numpy as np
        b = self._bound(P, j)
        near = np.argsort(np.abs(self.s - b))[:max(8, len(self.s) // 50)]
        across = (self.P_all[near] - self.origin) @ self.across
        o = self.origin + b * self.axis
        ends = []
        for i in (near[int(np.argmin(across))], near[int(np.argmax(across))]):
            p = self.P_all[i]
            ends.append([round(float(c), 1) + 0.0 for c in p - ((p - o) @ self.axis) * self.axis])
        return {"origin": [round(float(c), 1) + 0.0 for c in o], "normal": [round(float(c), 6) + 0.0 for c in self.axis],
                "line": ends}


@dataclass(frozen=True)
class PartPlanForm:
    member: PartMember
    plan: pc.Plan
    straight: bool

    @property
    def solid(self) -> bool:  # taste reads this: one straight piece, no pressing
        return self.straight

    @property
    def n_pieces(self) -> int:
        return self.plan.P

    @property
    def check(self) -> dict:  # what record.volumes reads: the volume-weighted totals
        t = self.plan.totals
        return {"billet_mm3": t["billet_mm3"], "part_mm3": t["part_mm3"], "waste_pct": t["waste_pct"]}

    def joints(self) -> list[dict]:
        return pc.joints(self.member, self.plan)

    def as_dict(self, outline: bool = True) -> dict:
        pcs = [pc.piece_dict(p, c, self.straight, outline) for p, c in zip(self.plan.count.pieces, self.plan.checks)]
        t = self.plan.totals
        billet = {"volume_m3": round(t["billet_mm3"] / 1e9, 6)}
        if outline:
            billet["outline"] = [loop for p in pcs for loop in p["billet"]["outline"]]
        mb = self.member
        return {"kind": "part_plan", "n_pieces": self.plan.P, "straight_billet": self.straight,
                "pieces": pcs, "cuts": self.joints(),
                "axis": {"origin": [round(float(c), 1) + 0.0 for c in mb.origin + mb.s0 * mb.axis],
                         "direction": [round(float(c), 6) + 0.0 for c in mb.axis], "length_mm": pc._f(mb.length)},
                "billet": billet, "part_volume_m3": round(t["part_mm3"] / 1e9, 6),
                "checks": pc.summary_checks(self.plan)}

    def summary(self) -> dict:
        return self.as_dict(outline=False)


@dataclass
class PartResult:
    status: str  # "proposed" | "conflict"
    sentence: str
    steps: list[dict]
    source: str = "rules"
    form: PartPlanForm | None = None
    deviation_mm: float = 0.0  # always: the geometry is never moved
    conflict: tuple[str, str] | None = None
    governing: list[str] = field(default_factory=list)
    rejected_proposals: list[dict] = field(default_factory=list)
    taste: dict | None = None
    model_text: dict | None = None
    model_ms: int | None = None
    plan: pc.Plan | None = None  # also on conflicts: what was tried (tests and timing read it)

    def as_dict(self, intent=None) -> dict:
        return {"status": self.status, "form": self.form.as_dict() if self.form else None,
                "sentence": self.sentence, "steps": self.steps, "deviation_mm": 0.0, "source": self.source,
                "conflict": list(self.conflict) if self.conflict else None, "governing": self.governing,
                "taste": None, "model_ms": None}


def _sentence(plan: pc.Plan, straight: bool) -> str:
    if plan.P > 1:
        s = f"Buildable as modelled, in {plan.P} pieces joined end to end. Each pressed from layers, then milled."
    elif straight:
        s = "Buildable as modelled. Milled from one straight piece, no bending."
    else:
        piece, chk = plan.count.pieces[0], plan.checks[0]
        if pc.fit_of(piece, chk).mode == "straight":
            s = f"Buildable as modelled. Glued straight from {chk['lam_count']} layers, then milled to shape."
        else:
            s = f"Buildable as modelled. Pressed in one curve from {chk['lam_count']} layers, then milled to shape."
    return s + pc.target_suffix(plan)


def solve_part(intent: PartIntent, holds=frozenset(), settings: pc.PieceSettings | None = None,
               max_waste_pct: float | None = None) -> PartResult:
    """settings: None reads the seam (pieces.current_settings). max_waste_pct: overrides the
    settings' waste target (tests pass it directly)."""
    settings = settings or pc.current_settings()
    target = settings.max_waste_pct if max_waste_pct is None else max_waste_pct
    straight = "solid" in holds
    member = PartMember(intent)
    steps = [{"tag": "Heard", "text": f"Your own part, {pc.m_text(member.length)} long and {intent.volume_mm3 / 1e9:.3f} m3, "
                                      f"kept exactly as modelled.", "limit_id": None}]
    if "shape" in holds:
        steps.append({"tag": "Heard", "text": NEVER_MOVED, "limit_id": None})
    if not straight and settings.max_pieces > 1:
        pc.warm_pool()
    plan = pc.plan(member, settings, straight=straight, split_ok="split_ok" in holds,
                   less_waste="less_waste" in holds, max_waste_pct=target)

    if plan.status == "conflict":
        steps += pc.failure_steps(plan)
        cause, pair, lid = pc.conflict_cause(plan, settings, straight, "your part")
        sentence = {"straight": "This part will not mill from one straight piece on this machine.",
                    "bend": "This part bends too tightly for the thinnest layer.",
                    "machine": "This part will not fit through the machine" +
                               (f", even in {plan.P} pieces." if plan.P > 1 else "."),
                    "fit": "This part could not be fitted with a billet."}[cause]
        steps.append({"tag": "Cannot resolve", "text": "Your geometry is never moved, so this is a finding, not a change."
                      + (f" Tried up to {plan.P} pieces." if plan.P > 1 else ""), "limit_id": lid})
        return PartResult("conflict", sentence, steps, conflict=pair, plan=plan)

    form = PartPlanForm(member, plan, straight)
    steps += pc.split_why(plan) + pc.piece_steps(plan, straight) + pc.joint_steps(member, plan) + pc.waste_steps(plan)
    governing = ["machine"] if straight else ["lam_ratio", "machine"]
    return PartResult("proposed", _sentence(plan, straight), steps, form=form, governing=governing, plan=plan)


def formal_sentence(intent: PartIntent, result: PartResult) -> str:
    from .record import SPECIES, volumes_text
    f = result.form
    t = f.plan.totals
    how = ("milled from one straight piece, no pressing" if f.straight else
           "pressed in one curve, then milled" if f.plan.P == 1 else
           f"made in {f.plan.P} pieces joined end to end, each pressed, then milled")
    return (f"Member {intent.member_id}, {SPECIES}, the designer's own part as modelled, "
            f"{pc.m_text(f.member.length)} along its length axis, {len(intent.points)} surface points. "
            f"Geometry not altered; {how}. " + pc.formal_text(f.plan, f.member, f.straight) + " "
            + volumes_text(t["billet_mm3"] / 1e9, t["part_mm3"] / 1e9, t["waste_pct"])
            + " Governing limit: " + ("machine opening" if f.straight else "lamella bend radius / thickness; machine opening")
            + ". Deviation from intent 0 mm.")
