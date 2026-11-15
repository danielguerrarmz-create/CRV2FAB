"""Settings the user sets, and sees (spec v6, section 2). GET /settings, POST /settings (partial).

Kept for the session and written into every record entry they affected. The defaults carry no
company data: the opening is a generic placeholder. The technical member's named machine table is
optional and lives in the git-ignored private/machines.json; when present, its machines are offered
by name and the setting `machine` selects one. No machine data of any kind enters a model prompt.

Seam for other kinds: `agent.nudge(..., settings=snapshot)` and `fab_setup(snapshot)`.
"""
from __future__ import annotations

import copy
import json
import math
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_MACHINES = ROOT / "private" / "machines.json"

DEFAULTS = {
    "lam_options_mm": [38.0, 17.0, 11.0],  # the analyzer drop's list: 2x stock as is, ripped in two, in three
    "lam_ratio": 125.0,                     # minimum radius / layer thickness (sc_glulam default, to confirm)
    "allowance_mm": 0.0,                    # machining allowance per face, passed to their billet fit
    "max_waste_pct": None,                  # the waste target: off until the user sets it
    "opening_mm": [1200.0, 280.0],          # CNC opening width and height: a generic placeholder
    "max_length_mm": 18000.0,               # reported against, as their code does
    "max_pieces": 4,                        # upper limit for splitting (section 4, built elsewhere)
    "machine": None,                        # a name from private/machines.json, when that file exists
    "thickness_mm": 38.0,                   # spec v9: a plate's thickness; a plate request's own value wins
}

SOURCES = {
    "lam_options_mm": "adopted from the analyzer drop (CRV2FAB), replaces [38, 25, 19, 12, 8]",
    "lam_ratio": "sc_glulam default, confirm with a supplier",
    "opening_mm": "generic placeholder from the analyzer drop",
    "thickness_mm": "spec v9: the 2x4's 38 mm; a plate request that sends thickness_mm overrides it for that request",
}


def private_machines() -> list[dict]:
    """The technical member's named machines, if this computer has the private file. Never tracked."""
    try:
        return json.loads(PRIVATE_MACHINES.read_text(encoding="utf-8"))["machines"]
    except (OSError, ValueError, KeyError):
        return []


def _number(value, name: str, low: float, high: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return float(value)


def validate(update) -> dict:
    """A clean partial update, or ValueError with a plain reason."""
    if not isinstance(update, dict):
        raise ValueError("settings must be an object")
    unknown = set(update) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
    out = {}
    for key, value in update.items():
        if key == "lam_options_mm":
            if not isinstance(value, list) or not 1 <= len(value) <= 8:
                raise ValueError("lam_options_mm must be a list of 1 to 8 thicknesses")
            out[key] = sorted({_number(v, key, 1, 200) for v in value}, reverse=True)
        elif key == "lam_ratio":
            out[key] = _number(value, key, 10, 1000)
        elif key == "allowance_mm":
            out[key] = _number(value, key, 0, 50)
        elif key == "max_waste_pct":
            out[key] = None if value is None else _number(value, key, 0, 100)
        elif key == "opening_mm":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("opening_mm must be [width, height]")
            out[key] = [_number(v, key, 1, 10000) for v in value]
        elif key == "thickness_mm":
            from .plate import THICKNESS_RANGE_MM
            out[key] = _number(value, key, *THICKNESS_RANGE_MM)
        elif key == "max_length_mm":
            out[key] = _number(value, key, 100, 100000)
        elif key == "max_pieces":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 20:
                raise ValueError("max_pieces must be a whole number from 1 to 20")
            out[key] = value
        elif key == "machine":
            names = [m["name"] for m in private_machines()]
            if value is not None and value not in names:
                raise ValueError("machine must be null or one of the machines offered by GET /settings")
            out[key] = value
    return out


class Settings:
    """The session's settings. Thread-safe; snapshots are plain dicts."""

    def __init__(self, initial: dict | None = None):
        self._lock = threading.Lock()
        self._values = copy.deepcopy(DEFAULTS)
        if initial:
            self._values.update(validate(initial))

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._values)

    def update(self, partial) -> dict:
        clean = validate(partial)
        with self._lock:
            if "opening_mm" in clean and "machine" not in clean:
                clean["machine"] = None  # an opening typed by the user replaces a selected machine
            self._values.update(clean)
            return copy.deepcopy(self._values)

    def public(self) -> dict:
        """GET /settings: the values, where the defaults come from, and any private machines by name."""
        values = self.snapshot()
        return {"settings": values, "sources": SOURCES,
                "machines": [{"name": m["name"], "opening_mm": [m["openingWidth"], m["openingHeight"]]}
                             for m in private_machines()]}


def machine_of(settings: dict) -> dict:
    """The opening the billet must pass: a selected private machine, or the opening setting."""
    name = settings.get("machine")
    if name:
        for m in private_machines():
            if m["name"] == name:
                return {"name": m["name"], "openingWidth": float(m["openingWidth"]),
                        "openingHeight": float(m["openingHeight"]), "lengthMax": m.get("lengthMax")}
    w, h = settings["opening_mm"]
    return {"name": None, "openingWidth": float(w), "openingHeight": float(h),
            "lengthMax": settings.get("max_length_mm")}


def fab_setup(settings: dict | None = None):
    """The surface route's setup from a settings snapshot (None: the defaults)."""
    from .surface_solver import FabSetup
    s = settings or copy.deepcopy(DEFAULTS)
    return FabSetup(float(s["lam_ratio"]), tuple(float(t) for t in s["lam_options_mm"]), machine_of(s),
                    float(s["allowance_mm"]), s.get("max_waste_pct"),
                    int(s["max_pieces"]) if settings is not None else None)
