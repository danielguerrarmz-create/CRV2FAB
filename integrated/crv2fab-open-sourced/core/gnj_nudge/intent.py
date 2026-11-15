"""What the designer drew, and what they said must be kept."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .limits import Form, deviation_mm, normalise_angle

HOLD_NAMES = {"solid": "solid section", "shape": "drawn curve", "less_waste": "less waste",
              "split_ok": "shorter pieces allowed"}
# less_waste (spec v5): set only through /say; among make-ups that pass every check, the least waste.
# split_ok (spec v6 section 4): said in words only; the member may be cut into shorter pieces.

# A form keeps the drawn shape if it sits within this distance of it at mid-span.
SHAPE_TOLERANCE_MM = 0.5

MEMBER_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


LEGACY_ANGLE = {"up": 0.0, "down": 180.0}


@dataclass(frozen=True)
class Intent:
    """A drawn bend. bend_angle_deg is the bend direction in the YZ plane, from +Z
    (up, 0) toward +Y (90). When it is absent, the v1 `direction` field sets it:
    up = 0, down = 180. After construction `direction` is "up" or "down" when the
    angle is exactly 0 or 180, and None otherwise."""
    member_id: str
    chord_mm: float
    radius_mm: float
    direction: str | None = None
    bend_angle_deg: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.member_id, str) or not MEMBER_ID.fullmatch(self.member_id):
            raise ValueError("member_id must be 1 to 32 letters, digits, underscores or hyphens")
        for name in ("chord_mm", "radius_mm"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be a positive number")
        if self.radius_mm < self.chord_mm / 2:
            raise ValueError("radius_mm must be at least half of chord_mm")
        if self.direction is not None and self.direction not in LEGACY_ANGLE:
            raise ValueError("direction must be 'up' or 'down'")
        a = self.bend_angle_deg
        if a is None:
            if self.direction is None:
                raise ValueError("give bend_angle_deg, or direction 'up' or 'down'")
            a = LEGACY_ANGLE[self.direction]
        if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a):
            raise ValueError("bend_angle_deg must be a finite number")
        a = normalise_angle(a)
        object.__setattr__(self, "bend_angle_deg", a)
        object.__setattr__(self, "direction", {0.0: "up", 180.0: "down"}.get(a))

    @classmethod
    def from_dict(cls, d: dict) -> "Intent":
        if not isinstance(d, dict):
            raise ValueError("intent must be an object")
        return cls(d.get("member_id"), d.get("chord_mm"), d.get("radius_mm"), d.get("direction"),
                   d.get("bend_angle_deg"))

    def as_dict(self) -> dict:
        out = {"member_id": self.member_id, "chord_mm": self.chord_mm,
               "radius_mm": self.radius_mm, "bend_angle_deg": self.bend_angle_deg}
        if self.direction:
            out["direction"] = self.direction
        return out


class Holds(frozenset):
    """The set of things the designer has said must be kept: "solid", "shape"."""

    def __new__(cls, items=()):
        items = list(items or ())
        for h in items:
            if not isinstance(h, str) or h not in HOLD_NAMES:
                raise ValueError("unknown hold; the known holds are solid, shape, less_waste and split_ok")
        return super().__new__(cls, items)


def hold_violations(form: Form, intent: Intent, holds: Holds) -> list[str]:
    """Plain reasons a form breaks a hold. Empty list means every hold is kept."""
    out = []
    if "solid" in holds and not form.solid:
        out.append(f"You are holding solid, but this form uses {form.n_lamellas} layers "
                   f"and {form.n_strips} strips.")
    if "shape" in holds:
        dev = deviation_mm(intent.radius_mm, form.radius_mm, intent.chord_mm)
        if dev > SHAPE_TOLERANCE_MM:
            out.append(f"You are holding the drawn curve, but this form sits {dev:.0f} mm from it at mid-span.")
    return out
