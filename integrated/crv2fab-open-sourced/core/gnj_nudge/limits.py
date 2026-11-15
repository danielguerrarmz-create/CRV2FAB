"""Limit cards and the checker.

The checker is the ONLY thing allowed to call a form buildable. The solver and
the model only propose; every proposal goes through check().

Geometry (v2): the member runs along X; the 38 mm thickness is in Z and the
89 mm width in Y. A bend of radius R in direction a (degrees in the YZ plane,
from +Z toward +Y) curves the thickness with radius Rz = R / |cos a| and the
width with radius Ry = R / |sin a|. Layers split the thickness, strips split
the width, and the bend ratio applies to each face on its own.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER_PATH = Path(__file__).with_name("limits.placeholder.json")

# Floating point slack on the >= comparisons. Small enough that 7599 mm solid
# (ratio 199.97) still fails; large enough that an exact 200.0 never reads 199.999.
EPS = 1e-9
# A direction factor below this is treated as exactly zero (no curvature on that face).
FACTOR_ZERO = 1e-6
STOCK_WIDTH_MM = 89.0  # default strip width when a form has no strips


@dataclass(frozen=True)
class LimitCard:
    id: str
    quantity: str
    value: float
    unit: str
    source: str


def load_cards(path: str | Path | None = None) -> dict[str, LimitCard]:
    raw = json.loads(Path(path or PLACEHOLDER_PATH).read_text(encoding="utf-8"))
    cards = [LimitCard(**c) for c in raw["cards"]]
    return {c.id: c for c in cards}


def normalise_angle(a: float) -> float:
    """Into [0, 360). -90 becomes 270."""
    a = float(a) % 360.0
    return 0.0 if a >= 360.0 else a  # (-1e-20) % 360 rounds to 360.0


def factors(angle_deg: float) -> tuple[float, float]:
    """(|cos a|, |sin a|) with near-zero values snapped to 0."""
    r = math.radians(angle_deg)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    return (0.0 if c < FACTOR_ZERO else c), (0.0 if s < FACTOR_ZERO else s)


def face_radii(radius_mm: float, angle_deg: float) -> tuple[float, float]:
    """(Rz across the thickness, Ry across the width); infinite where that face does not bend."""
    c, s = factors(angle_deg)
    return (radius_mm / c if c else math.inf), (radius_mm / s if s else math.inf)


def _positive(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


@dataclass(frozen=True)
class Form:
    """One candidate make-up for the member. Geometry is single curvature."""
    radius_mm: float
    n_lamellas: int
    lamella_mm: float
    chord_mm: float
    n_strips: int = 1
    strip_mm: float = STOCK_WIDTH_MM
    bend_angle_deg: float = 0.0

    def __post_init__(self) -> None:
        if not _count(self.n_lamellas) or not _count(self.n_strips):
            raise ValueError("n_lamellas and n_strips must be whole numbers of at least 1")
        for name in ("radius_mm", "lamella_mm", "chord_mm", "strip_mm"):
            if not _positive(getattr(self, name)):
                raise ValueError(f"{name} must be a positive number")
        a = self.bend_angle_deg
        if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a):
            raise ValueError("bend_angle_deg must be a finite number")
        object.__setattr__(self, "bend_angle_deg", normalise_angle(a))
        if self.radius_mm < self.chord_mm / 2:
            raise ValueError("radius is smaller than half the span, no arc can be drawn")

    @property
    def solid(self) -> bool:
        return self.n_lamellas == 1 and self.n_strips == 1

    def as_dict(self) -> dict:
        return {
            "radius_mm": round(self.radius_mm, 1),
            "n_lamellas": self.n_lamellas,
            "lamella_mm": round(self.lamella_mm, 2),
            "n_strips": self.n_strips,
            "strip_mm": round(self.strip_mm, 2),
            "bend_angle_deg": round(self.bend_angle_deg, 3),
            "chord_mm": round(self.chord_mm, 1),
        }


@dataclass(frozen=True)
class CardResult:
    id: str
    passed: bool
    measured: float
    required: float
    by: float  # how far past the limit, in the card's unit; 0 when passed
    unit: str
    detail: str
    face: str | None = None  # "thickness" or "width" for cards that apply to both


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    cards: tuple[CardResult, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> list[CardResult]:
        return [c for c in self.cards if not c.passed]

    def card(self, card_id: str, face: str | None = None) -> CardResult:
        return next(c for c in self.cards if c.id == card_id and (face is None or c.face == face))


def _at_least(card: LimitCard, measured: float, detail: str, face: str | None = None) -> CardResult:
    ok = measured >= card.value - EPS
    return CardResult(card.id, ok, measured, card.value, 0.0 if ok else card.value - measured, card.unit, detail, face)


def _at_most(card: LimitCard, measured: float, detail: str) -> CardResult:
    ok = measured <= card.value + EPS
    return CardResult(card.id, ok, measured, card.value, 0.0 if ok else measured - card.value, card.unit, detail)


def _fills(card: LimitCard, n: int, piece: float, word: str) -> CardResult:
    total = n * piece
    ok = abs(total - card.value) <= 0.01
    return CardResult(card.id, ok, total, card.value, 0.0 if ok else abs(total - card.value), card.unit,
                      f"{n} {word} of {piece:g} mm make {total:g} mm; the stock is {card.value:g} mm.")


def check(form: Form, cards: dict[str, LimitCard]) -> CheckResult:
    """Deterministic pass/fail against every card, on both faces. Per failed card:
    measured value and by how much."""
    rz, ry = face_radii(form.radius_mm, form.bend_angle_deg)
    return check_faces(rz, ry, form.n_lamellas, form.lamella_mm, form.n_strips, form.strip_mm,
                       form.chord_mm, cards)


def check_faces(rz: float, ry: float, n_lamellas: int, lamella_mm: float, n_strips: int, strip_mm: float,
                length_mm: float, cards: dict[str, LimitCard]) -> CheckResult:
    """The one checker. rz / ry: tightest radius across the thickness / width (inf if that
    face does not bend). Used by the bend (v1, v2) and the surface member (v3)."""
    ratio, minlam, length = cards["bend_ratio"], cards["min_lamella"], cards["length"]
    results = []
    for face, r_face, piece, word in (("thickness", rz, lamella_mm, "layer"),
                                      ("width", ry, strip_mm, "strip")):
        if math.isinf(r_face):
            detail = f"The {face} does not bend in this direction."
        else:
            detail = (f"A {piece:g} mm {word} needs a radius of {ratio.value * piece:.0f} mm or wider across the "
                      f"{face}; this bend gives {r_face:.0f} mm.")
        results.append(_at_least(ratio, r_face / piece, detail, face))
        results.append(_at_least(minlam, piece, f"{word.capitalize()}s are {piece:g} mm; the thinnest piece that "
                                                f"can be cut is {minlam.value:g} mm.", face))
    results.append(_fills(cards["stock_thickness"], n_lamellas, lamella_mm, "layers"))
    results.append(_fills(cards["stock_width"], n_strips, strip_mm, "strips"))
    results.append(_at_most(length, length_mm,
                            f"The span is {length_mm:.0f} mm; the member is {length.value:g} mm long."))
    return CheckResult(all(r.passed for r in results), tuple(results))


def sag(radius_mm: float, chord_mm: float) -> float:
    """Rise of the arc at mid-span."""
    return radius_mm - math.sqrt(max(0.0, radius_mm * radius_mm - chord_mm * chord_mm / 4))


def deviation_mm(intent_radius_mm: float, form_radius_mm: float, chord_mm: float) -> float:
    """How far the ghost sits from the drawn curve at mid-span."""
    return abs(sag(intent_radius_mm, chord_mm) - sag(form_radius_mm, chord_mm))


def governing_face(form: Form) -> str:
    """The face working closest to the bend ratio: "thickness" or "width"."""
    rz, ry = face_radii(form.radius_mm, form.bend_angle_deg)
    return "width" if ry / form.strip_mm < rz / form.lamella_mm else "thickness"


def governing(form: Form, cards: dict[str, LimitCard], dev_mm: float) -> list[str]:
    """Which cards decided this form. The bend ratio always does; the thinnest
    piece also does when one more piece would be too thin and the curve had to move."""
    out = ["bend_ratio"]
    minimum = cards["min_lamella"].value
    at_floor = ((form.n_lamellas > 1 and cards["stock_thickness"].value / (form.n_lamellas + 1) < minimum)
                or (form.n_strips > 1 and cards["stock_width"].value / (form.n_strips + 1) < minimum))
    if dev_mm > 0.5 and at_floor:
        out.append("min_lamella")
    return out
