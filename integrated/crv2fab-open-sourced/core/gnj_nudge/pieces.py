"""Spec v6 section 4: splitting a member into shorter billets.

One singly curved billet must enclose the whole member. Cutting the member into P equal pieces
lets each piece have its own billet, in its own best bending plane. Each piece is fitted and
checked on its own with the same vendored sc_glulam functions fabrication.py calls (no second
billet fit); waste is the volume-weighted total over the pieces.

Splitting is tried ONLY to satisfy a failed machine check, a waste target the user set, or when
the designer said so (hold `split_ok`). Never to shave waste unasked. Order of remedies: layer
option, then pieces, then (surface_stroke only) straightening the line.

Speed: the billet fit is the slow step (about 1 to 3 s a piece, all of it inside their
Nelder-Mead). Fits are cached per piece on the intent, so /say and a re-solve never refit, and
once splitting is allowed every piece of every count is fitted at once on a process pool; the
counts are then read in order and the first that passes wins.
"""
from __future__ import annotations

import math
import os
import weakref
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field, replace

MAX_PIECES = 4  # spec v6 section 2 default for `max_pieces`; main has no such setting yet
MIN_PIECE_POINTS = 12  # a piece with fewer surface samples than this is not fitted (their PCA needs a spread)
JOINT_WORDS = "joint to be designed by the engineer"
PLANE_SAMPLE = 250  # our maxCount for their fit_bending_plane on parts and pieces (theirs 1000; the re-score
                   # then uses 1000). Measured 2026-11-14 on the 5.05 m doubly curved part: a piece fit
                   # 1.3 s -> 0.8 s, billet volumes equal to 4 figures.


# ---- THE SEAM: the only place this module reads settings -------------------------------------------

@dataclass(frozen=True)
class PieceSettings:
    lams: tuple  # layer options in mm, thickest first
    ratio: float  # minimum layer radius / layer thickness
    machine: dict  # {"name", "openingWidth", "openingHeight", "lengthMax"}; the name is never shown
    allowance: float = 0.0
    max_pieces: int = MAX_PIECES
    max_waste_pct: float | None = None  # the waste target; None = off
    grain_deg: float | None = None  # the plate kind's grain card; None = no grain check (other kinds)

    def setup(self):
        from .surface_solver import FabSetup
        return FabSetup(self.ratio, self.lams, self.machine, self.allowance)

    def with_opening(self, width_mm: float, height_mm: float) -> "PieceSettings":
        return replace(self, machine={"name": None, "openingWidth": float(width_mm),
                                      "openingHeight": float(height_mm), "lengthMax": self.machine.get("lengthMax")})


def from_settings(snapshot: dict) -> PieceSettings:
    """The session settings (gnj_nudge.settings, GET/POST /settings) as this module needs them."""
    from .settings import machine_of
    return PieceSettings(tuple(float(t) for t in sorted(snapshot["lam_options_mm"], reverse=True)),
                         float(snapshot["lam_ratio"]), machine_of(snapshot), float(snapshot["allowance_mm"]),
                         int(snapshot["max_pieces"]), snapshot.get("max_waste_pct"))


def current_settings() -> PieceSettings:
    """The default settings, for callers with no session (the server always passes its own
    snapshot through from_settings). Tests patch this to pin a route."""
    import copy
    from .settings import DEFAULTS
    return from_settings(copy.deepcopy(DEFAULTS))


# ---- fits: cached per piece, fitted on a pool when several are needed --------------------------------

_POOL: ProcessPoolExecutor | None = None
_POOL_FAILED = False
# Off unless the server's main() (or a test) switches it on: a worker is a fresh interpreter that
# re-imports the caller's main module, which is only safe behind a __main__ guard, and inside a
# host application sys.executable is the host, not Python. GNJ_PIECE_WORKERS=n also switches it on.
_ENABLED = (os.environ.get("GNJ_PIECE_WORKERS") or "0").strip() not in ("", "0")


def enable_pool(on: bool = True) -> None:
    global _ENABLED, _POOL_FAILED
    _ENABLED, _POOL_FAILED = on, False
    if not on:
        _pool_off()
        _POOL_FAILED = False


def _workers() -> int:
    raw = os.environ.get("GNJ_PIECE_WORKERS")
    if raw is not None and raw.strip().isdigit() and int(raw) > 0:
        return int(raw)
    return max(0, min(9, (os.cpu_count() or 1) - 1))  # 2 + 3 + 4 pieces: every fit at once


def _pool() -> ProcessPoolExecutor | None:
    global _POOL, _POOL_FAILED
    if _POOL is None and _ENABLED and not _POOL_FAILED and _workers() > 0:
        try:
            from .winpower import worker_init
            _POOL = ProcessPoolExecutor(max_workers=_workers(), initializer=worker_init)
        except Exception:  # no processes on this machine: fit in this one
            _POOL_FAILED = True
    return _POOL


def _pool_off() -> None:
    """The pool cannot be used here (no processes, or a script without a __main__ guard on
    Windows): fit in this process from now on."""
    global _POOL, _POOL_FAILED
    _POOL_FAILED = True
    pool, _POOL = _POOL, None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def warm_pool() -> None:
    """Start the workers (a cold Windows worker takes about a second to import numpy) while the
    first fit runs here. Costs nothing when the part needs one piece, beyond idle processes."""
    pool = _pool()
    if pool is not None:
        try:
            for _ in range(_workers()):
                pool.submit(_noop)
        except Exception:
            _pool_off()


def _noop() -> None:
    from . import fabrication  # noqa: F401  the import is the warm-up


def _fit_here(points, straight: bool, max_eval: int, allowance: float, grain=None):
    """fabrication.py's own wrappers round their functions: no second billet fit.

    grain (plate kind): (axis, normals, limit_deg). Returns a list of fits then: the free fit, and when
    its length axis is more than limit_deg off the axis, the same points fitted with the bending plane
    constrained (fabrication.fit_arc_billet_in_plane) to each plane that holds the axis, normal to one
    of `normals` and to the free fit's normal made square to the axis; only those that run on grain,
    smallest billet first."""
    from . import fabrication as fb
    free = (fb.fit_straight_billet(points, allowance) if straight else
            fb.fit_arc_billet(points, allowance, max_eval=max_eval, max_count=PLANE_SAMPLE))
    if grain is None:
        return free
    import numpy as np
    axis, normals, limit = np.asarray(grain[0], dtype=float), grain[1], grain[2]

    def on_grain(fit):
        ext = fb.gm.billet_extents(fit.spine, fit.P2, fit.W, allowance, 1.0)
        return fb.grain_angle_deg(fit, ext, axis) <= limit + 1e-9, ext

    ok, _ = on_grain(free)
    if ok or straight:
        return [free]
    found = []
    for nrm in [*normals, free.n]:
        nrm = np.asarray(nrm, dtype=float) - (np.asarray(nrm, dtype=float) @ axis) * axis
        if np.linalg.norm(nrm) < 1e-6:
            continue
        try:
            fit = fb.fit_arc_billet_in_plane(points, nrm / np.linalg.norm(nrm), allowance)
        except (ValueError, FloatingPointError, IndexError, ZeroDivisionError):
            continue
        ok, ext = on_grain(fit)
        if ok:
            found.append(((ext["wHigh"] - ext["wLow"]) * fb.gm.band_area(fit.spine, ext["sLow"], ext["sHigh"],
                                                                        ext["dLow"], ext["dHigh"]), fit))
    return [free] + [f for _, f in sorted(found, key=lambda x: x[0])]


def _fit_job(points, straight: bool, max_eval: int, allowance: float, grain=None):
    """Runs in a worker. Returns plain numbers: their spine classes live in a module loaded from a
    file path, which a pickle cannot name."""
    out = _fit_here(points, straight, max_eval, allowance, grain)
    return [_pack(f) for f in out] if isinstance(out, list) else _pack(out)


def _pack(fit) -> dict:
    sp = fit.spine
    spine = (("arc", sp.centre, sp.radius, sp.theta0, sp.thetaMid) if sp.kind == "arc"
             else ("line", sp.origin, sp.tangent))
    return {"mode": fit.mode, "origin": fit.origin, "u": fit.u, "v": fit.v, "n": fit.n, "spine": spine}


def _unpack(points, d):
    if isinstance(d, list):
        return [_unpack(points, x) for x in d]
    from . import fabrication as fb
    gm = fb.gm
    if d["spine"][0] == "arc":
        _, centre, radius, theta0, theta_mid = d["spine"]
        spine = gm.ArcSpine(centre, radius, theta0, 2.0 * (theta_mid - theta0))
        spine.thetaMid = theta_mid  # exactly as fitted
    else:
        spine = gm.LineSpine(d["spine"][1], d["spine"][2])
    P2, W = gm.project_to_frame(points, d["origin"], d["u"], d["v"], d["n"])
    return fb.Fit(d["mode"], d["origin"], d["u"], d["v"], d["n"], spine, P2, W)


_CACHES: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


class FitCache:
    """Fits of one member's pieces, keyed (P, k, straight, allowance). Kept on the intent object, so asking
    again about the same geometry (a /say, a hold, a re-solve) never refits a piece."""

    def __init__(self):
        self.done: dict = {}
        self.pending: dict = {}
        self.fits_run = 0  # how many fits this cache started: tests read it

    @classmethod
    def of(cls, owner) -> "FitCache":
        try:
            return _CACHES.setdefault(owner, cls())
        except TypeError:  # not weak-referenceable: no cache across calls
            return cls()

    def seed(self, key, fit) -> None:
        self.done.setdefault(key, fit)

    def submit(self, key, points, straight: bool, max_eval: int, allowance: float = 0.0, grain=None) -> None:
        """Start a fit on the pool if one is not already done or running."""
        if key in self.done or key in self.pending or len(points) < MIN_PIECE_POINTS:
            return
        pool = _pool()
        if pool is None:
            return
        try:
            self.pending[key] = (pool.submit(_fit_job, points, straight, max_eval, allowance, grain), points)
            self.fits_run += 1
        except Exception:
            _pool_off()  # get() fits here

    def get(self, key, points, straight: bool, max_eval: int, allowance: float = 0.0, grain=None):
        """The fit (a list of fits when grain is given), or None when the piece has too few points or
        their fit raised."""
        if key in self.done:
            return self.done[key]
        fit = None
        if key in self.pending:
            fut, pts = self.pending.pop(key)
            try:
                fit = _unpack(pts, fut.result())
            except Exception:  # their maths raised on this piece, or the pool itself broke
                fit = self._here(points, straight, max_eval, allowance, grain) if _pool_broken(fut) else None
        elif len(points) >= MIN_PIECE_POINTS:
            fit = self._here(points, straight, max_eval, allowance, grain)
        self.done[key] = fit
        return fit

    def _here(self, points, straight, max_eval, allowance, grain=None):
        self.fits_run += 1
        try:
            return _fit_here(points, straight, max_eval, allowance, grain)
        except (ValueError, FloatingPointError, IndexError, ZeroDivisionError):
            return None

    def cancel_pending(self) -> None:
        """Drop fits not started yet; running ones finish and stay cached for a later ask."""
        for fut, _ in self.pending.values():
            if fut.cancel():
                self.fits_run -= 1
        self.pending = {k: v for k, v in self.pending.items() if not v[0].cancelled()}


def _pool_broken(fut: Future) -> bool:
    from concurrent.futures.process import BrokenProcessPool
    try:
        broken = isinstance(fut.exception(), BrokenProcessPool)
    except BaseException:  # cancelled
        return True
    if broken:
        _pool_off()
    return broken


# ---- one member, P equal pieces -------------------------------------------------------------------------

class Member:
    """What splitting needs from a kind (part.py and the surface hook below build one).
    points(P, k): the surface samples of piece k of P, as given (never moved or scaled).
    volume(P, k): that piece's share of the part volume, mm3. cut(P, j): cut j (1..P-1).
    owner: the intent the fit cache lives on."""

    owner: object
    total_mm3: float

    def points(self, P: int, k: int):
        raise NotImplementedError

    def volume(self, P: int, k: int) -> float:
        raise NotImplementedError

    def cut(self, P: int, j: int) -> dict:
        raise NotImplementedError

    def span(self, P: int, k: int) -> tuple[float, float]:
        """Piece k's range along the member, mm from its start."""
        raise NotImplementedError

    def grain(self, P: int, k: int):
        """(axis, normals) the grain of piece k must follow, or None (no grain check: part, surface)."""
        return None


@dataclass
class Piece:
    index: int
    fit: object | None
    options: list  # check_billet for every layer option (or one, straight); [] when unfittable
    part_mm3: float
    span: tuple

    def passing(self) -> list:
        return [c for c in self.options if c["ok"]]

    def fail_reason(self) -> str | None:
        """None when some option passes; "bend" when no layer bends far enough; "grain" when some
        billet passes bend and machine but runs off the grain; else "machine"."""
        if self.passing():
            return None
        if not self.options:
            return "fit"
        if any(c["bend"]["ok"] and c["machine"]["ok"] for c in self.options):
            return "grain"
        return "machine" if any(c["bend"]["ok"] for c in self.options) else "bend"


@dataclass
class Count:
    P: int
    pieces: list

    def ok(self) -> bool:
        return all(p.passing() for p in self.pieces)

    def reason(self) -> str | None:
        reasons = [p.fail_reason() for p in self.pieces]
        for r in ("machine", "grain", "fit", "bend"):  # machine and grain first: more pieces can fix them
            if r in reasons:
                return r
        return None

    def config(self, cap_mm: float | None = None, least: bool = False) -> list | None:
        """One check per piece. Default: the thickest passing layer (cap_mm: no thicker than this
        where some passing layer is). least: the least waste per piece, ties to fewer layers."""
        out = []
        for p in self.pieces:
            ok = p.passing()
            if not ok:
                return None
            if least:
                out.append(min(ok, key=lambda c: (round(c["billet_mm3"], 3), c["lam_count"])))
            else:
                capped = [c for c in ok if cap_mm is None or c["lam_mm"] <= cap_mm + 1e-9]
                out.append((capped or [min(ok, key=lambda c: c["lam_mm"])])[0])
        return out


def totals(checks: list) -> dict:
    """Volume-weighted totals over pieces: sum of billets against sum of part shares."""
    billet = sum(c["billet_mm3"] for c in checks)
    part = sum(c["part_mm3"] for c in checks)
    unrounded = sum(c["billet_mm3"] * (1.0 - c["waste_rounding_pct"] / 100.0) for c in checks)
    return {"billet_mm3": billet, "part_mm3": part, "waste_pct": 100.0 * (billet - part) / billet,
            "waste_rounding_pct": 100.0 * (billet - unrounded) / billet}


def evaluate_count(member: Member, P: int, settings: PieceSettings, straight: bool, cache: FitCache,
                   max_eval: int) -> Count:
    pieces = []
    for k in range(P):
        pts = member.points(P, k)
        grain = grain_of(member, P, k, settings)
        fit = cache.get((P, k, straight, settings.allowance), pts, straight, max_eval, settings.allowance, grain)
        share = member.volume(P, k)
        fits = fit if isinstance(fit, list) else ([] if fit is None else [fit])
        opts = options_for(fits, share, settings, straight, grain)
        pieces.append(Piece(k, fits[0] if fits else None, opts, share, member.span(P, k)))
    return Count(P, pieces)


def grain_of(member: Member, P: int, k: int, settings: PieceSettings):
    """The picklable grain argument for a piece's fit: (axis, normals, limit), or None."""
    g = member.grain(P, k) if settings.grain_deg is not None else None
    if g is None:
        return None
    axis, normals = g
    return (tuple(float(c) for c in axis), tuple(tuple(float(c) for c in n) for n in normals), float(settings.grain_deg))


def options_for(fits: list, share: float, settings: PieceSettings, straight: bool, grain=None) -> list:
    """check_billet for every layer option (thickest first) on every fit; with grain, each check also
    carries `grain` and passes only on grain. Each check names its own fit (`fit`)."""
    from . import fabrication as fb
    lams = [None] if straight else [float(t) for t in settings.lams]
    out = []
    for t in lams:
        for fit in fits:
            chk = fb.check_billet(fit, t, settings.machine, settings.ratio, share, settings.allowance)
            chk["fit"] = fit
            if grain is not None:
                angle = fb.grain_angle_deg(fit, chk["ext"], grain[0])
                chk["grain"] = {"ok": angle <= grain[2] + 1e-9, "angle_deg": angle, "limit": grain[2]}
                chk["ok"] = bool(chk["ok"] and chk["grain"]["ok"])
            out.append(chk)
    return out


def fit_of(piece: Piece, chk: dict):
    return chk.get("fit", piece.fit)


@dataclass
class Plan:
    status: str  # "proposed" | "conflict"
    P: int
    count: Count | None
    checks: list | None  # the chosen check per piece (proposed)
    reason: str | None = None  # conflict: "bend" | "machine" | "fit"
    split_reason: str | None = None  # why pieces were tried: "machine" | "waste" | "split_ok"
    target: float | None = None
    over_target: bool = False
    best: tuple | None = None  # (waste %, P, how) the least waste any allowed choice reaches
    counts: dict = field(default_factory=dict)
    fits_run: int = 0

    @property
    def totals(self) -> dict:
        return totals(self.checks)


def _meets(cfg, target) -> bool:
    return cfg is not None and (target is None or totals(cfg)["waste_pct"] <= target + 1e-9)


def _for_target(count: Count, settings: PieceSettings, target: float | None, less_waste: bool):
    """The config this count offers under the target: layer options thickest first, then the least
    waste per piece. None when the count fails a check or cannot meet the target."""
    if not count.ok():
        return None
    if less_waste:
        cfg = count.config(least=True)
        return cfg if _meets(cfg, target) else None
    if target is None:
        return count.config()
    for cap in settings.lams:  # a thinner layer option is the first remedy
        cfg = count.config(cap_mm=cap)
        if _meets(cfg, target):
            return cfg
    cfg = count.config(least=True)
    return cfg if _meets(cfg, target) else None


def plan(member: Member, settings: PieceSettings, *, straight: bool = False, split_ok: bool = False,
         less_waste: bool = False, max_waste_pct: float | None = None, max_eval: int | None = None,
         first: Count | None = None) -> Plan:
    """Choose the number of pieces and each piece's layer option. The geometry is never touched:
    only `member.points` are read. first: an already evaluated P = 1 (the surface hook has it)."""
    if max_eval is None:
        from .surface_solver import FIT_MAX_EVAL
        max_eval = FIT_MAX_EVAL
    target = max_waste_pct
    cache = FitCache.of(member.owner)
    before = cache.fits_run
    pmax = 1 if straight else max(1, int(settings.max_pieces))
    counts: dict[int, Count] = {}

    def count(P: int) -> Count:
        if P not in counts:
            counts[P] = first if (P == 1 and first is not None) else \
                evaluate_count(member, P, settings, straight, cache, max_eval)
        return counts[P]

    def done(status, P, cfg, **kw) -> Plan:
        cache.cancel_pending()
        return Plan(status, P, counts.get(P), cfg, target=target, counts=counts,
                    fits_run=cache.fits_run - before, **kw)

    c1 = count(1)
    cfg1 = _for_target(c1, settings, target, less_waste)
    allowed_by = ("split_ok" if split_ok else c1.reason() if c1.reason() in ("machine", "grain")
                  else "waste" if (target is not None and c1.ok() and cfg1 is None) else None)
    if pmax == 1 or (cfg1 is not None and not (split_ok and less_waste)) or allowed_by is None:
        if cfg1 is not None:
            return done("proposed", 1, cfg1)
        if c1.ok():  # only the target is missed, and pieces are not allowed (or max_pieces is 1)
            return done("proposed", 1, c1.config(), over_target=True, best=_best(counts, target),
                        split_reason=None)
        return done("conflict", 1, None, reason=c1.reason())

    def submit(P: int) -> None:  # this count's pieces in parallel, when the pool is on
        for k in range(P):
            cache.submit((P, k, straight, settings.allowance), member.points(P, k), straight, max_eval,
                         settings.allowance, grain_of(member, P, k, settings))

    # Pieces are allowed. Counts are tried in order and the first that passes ends the search, so a
    # count is fitted only when the one before it failed (2026-11-14: fitting 2, 3 and 4 pieces at once
    # made nine fits compete for the CPU while only the two of P = 2 were needed). Only split_ok with
    # less_waste compares every count, so only then are they all started together.
    if split_ok and less_waste:  # the designer asked for both: the count with the least waste
        for P in range(2, pmax + 1):
            submit(P)
        options = [(P, _for_target(count(P), settings, target, True)) for P in range(1, pmax + 1)]
        options = [(P, cfg) for P, cfg in options if cfg is not None]
        if options:
            P, cfg = min(options, key=lambda o: (round(totals(o[1])["waste_pct"], 6), o[0]))
            return done("proposed", P, cfg, split_reason="split_ok")
    else:
        for P in range(2, pmax + 1):
            submit(P)
            cfg = _for_target(count(P), settings, target, less_waste)
            if cfg is not None:
                return done("proposed", P, cfg, split_reason=allowed_by)

    for P in range(1, pmax + 1):  # nothing meets the target: show the fewest pieces that pass
        count(P)
    passing = [P for P in range(1, pmax + 1) if counts[P].ok()]
    if passing:
        P = passing[0]
        cfg = counts[P].config(least=True) if less_waste else counts[P].config()
        return done("proposed", P, cfg, over_target=target is not None, best=_best(counts, target),
                    split_reason=allowed_by if P > 1 else None)
    return done("conflict", pmax, None, reason=counts[pmax].reason(), split_reason=allowed_by)


def _best(counts: dict, target) -> tuple | None:
    """(waste %, P, how) for the least waste any evaluated count reaches with any layer option."""
    if target is None:
        return None
    best = None
    for P, c in sorted(counts.items()):
        cfg = c.config(least=True)
        if cfg is not None:
            w = totals(cfg)["waste_pct"]
            if best is None or w < best[0] - 1e-9:
                best = (w, P)
    if best is None:
        return None
    return best[0], best[1], (f"{best[1]} pieces would reach" if best[1] > 1 else "Thinner layers would reach")


# ---- words and numbers shared by part and surface pieces --------------------------------------------------

def _f(x, nd=1):
    return None if x is None or (isinstance(x, float) and math.isinf(x)) else round(float(x), nd) + 0.0


def overshoot_mm(chk: dict) -> float:
    return max(0.0, -float(chk["machine"]["margin_mm"]))


def billet_dict(fit, chk: dict, straight: bool, outline: bool = True) -> dict:
    from . import fabrication as fb
    ext = chk["ext"]
    out = {"mode": "straight" if (straight or fit.mode == "straight") else "arc",
           "length_mm": _f(ext["sHigh"] - ext["sLow"]), "width_mm": _f(ext["wHigh"] - ext["wLow"]),
           "depth_mm": _f(ext["dHigh"] - ext["dLow"]),
           "radius_mm": _f(getattr(fit.spine, "radius", None)) if fit.mode == "arc" else None,
           "volume_m3": round(chk["billet_mm3"] / 1e9, 6)}
    if outline:
        out["outline"] = fb.outline_polylines(fit, ext)
    return out


def checks_dict(chk: dict) -> dict:
    """Machine facts without the machine's name: the opening is the user's setting, shown plainly."""
    mc = chk["machine"]
    bend = {k: (_f(v) if isinstance(v, float) else v) for k, v in chk["bend"].items()}
    out = {"bend": bend,
           "machine": {"ok": mc["ok"], "orientation": mc["orientation"], "need_mm": [_f(x) for x in mc["need_mm"]],
                       "opening_mm": [_f(x) for x in mc["opening_mm"]], "overshoot_mm": _f(overshoot_mm(chk))},
           "kx": None if not math.isfinite(chk["kx"]) else round(float(chk["kx"]), 4)}
    if "grain" in chk:
        g = chk["grain"]
        out["grain"] = {"ok": g["ok"], "angle_deg": _f(g["angle_deg"]), "limit": g["limit"]}
    return out


def piece_dict(piece: Piece, chk: dict, straight: bool, outline: bool = True) -> dict:
    return {"index": piece.index, "from_mm": _f(piece.span[0]), "to_mm": _f(piece.span[1]),
            "n_lamellas": int(chk["lam_count"]), "lamella_mm": _f(chk["lam_mm"], 2),
            "billet": billet_dict(fit_of(piece, chk), chk, straight, outline),
            "part_volume_m3": round(chk["part_mm3"] / 1e9, 6), "waste_pct": _f(chk["waste_pct"]),
            "waste_rounding_pct": _f(chk["waste_rounding_pct"]), "checks": checks_dict(chk)}


def summary_checks(plan: Plan) -> dict:
    t = plan.totals
    out = {"bend": {"ok": all(c["bend"]["ok"] for c in plan.checks)},
           "machine": {"ok": all(c["machine"]["ok"] for c in plan.checks)},
           "waste_pct": _f(t["waste_pct"]), "waste_rounding_pct": _f(t["waste_rounding_pct"]),
           "max_waste_pct": plan.target, "waste_ok": None if plan.target is None else not plan.over_target}
    if all("grain" in c for c in plan.checks):
        out["grain"] = {"ok": all(c["grain"]["ok"] for c in plan.checks),
                        "angle_deg": _f(max(c["grain"]["angle_deg"] for c in plan.checks)),
                        "limit": plan.checks[0]["grain"]["limit"]}
    return out


def m_text(mm: float) -> str:
    from .solver import m
    return m(mm)


def bend_words(chk: dict) -> str:
    b = chk["bend"]
    if not b["applies"]:
        return "One straight piece is not bent, so the layer bend limit does not apply."
    if b["tightest_radius_mm"] is None:
        return f"The billet is straight, so its {chk['lam_mm']:g} mm layers do not bend."
    return (f"Its tightest layer bends to {m_text(b['tightest_radius_mm'])}, {b['ratio']:.0f} times its "
            f"{chk['lam_mm']:g} mm thickness; the limit is {b['limit']:g}.")


def machine_words(chk: dict) -> str:
    mc = chk["machine"]
    w, h = mc["need_mm"]
    ow, oh = mc["opening_mm"]
    if mc["ok"]:
        return f"It needs an opening of {w:.0f} x {h:.0f} mm lying {mc['orientation']}; the opening is {ow:.0f} x {oh:.0f} mm, so it fits."
    return (f"It needs an opening of {w:.0f} x {h:.0f} mm; the opening is {ow:.0f} x {oh:.0f} mm, so it is "
            f"too large by {overshoot_mm(chk):.0f} mm.")


def grain_words(chk: dict) -> str:
    g = chk["grain"]
    return (f"Its billet runs {g['angle_deg']:.0f} degrees off the path; the grain must stay within {g['limit']:g}"
            + (", so it does." if g["ok"] else "."))


def made_words(fit, chk: dict, straight: bool) -> str:
    b = billet_dict(fit, chk, straight, outline=False)
    size = f"{b['length_mm']:.0f} x {b['width_mm']:.0f} x {b['depth_mm']:.0f} mm (length x width x depth)"
    if straight:
        return f"one straight piece {size}, no pressing"
    if b["mode"] == "straight":
        return f"a straight billet {size}, glued from {chk['lam_count']} layers of {chk['lam_mm']:g} mm"
    return (f"a billet pressed to a {m_text(b['radius_mm'])} radius, {size}, from {chk['lam_count']} layers of "
            f"{chk['lam_mm']:g} mm")


def joint_steps(member: Member, plan: Plan) -> list[dict]:
    return [{"tag": "Joint", "text": f"Joint {j} at {m_text(member.span(plan.P, j)[0])} along the member: "
                                     f"{JOINT_WORDS}.", "limit_id": None} for j in range(1, plan.P)]


def joints(member: Member, plan: Plan) -> list[dict]:
    out = []
    for j in range(1, plan.P):
        c = member.cut(plan.P, j)
        out.append({"index": j, "at_mm": _f(member.span(plan.P, j)[0]), "note": JOINT_WORDS} | c)
    return out


def explaining(piece: Piece, reason: str) -> dict:
    """The check that best explains a failed piece: for a bend failure the thinnest layer; for a
    machine failure the bending layer with the smallest overshoot."""
    if reason == "bend" or not any(c["bend"]["ok"] for c in piece.options):
        return piece.options[-1]
    if reason == "grain":  # the billet that would pass if grain did not count
        return next(c for c in piece.options if c["bend"]["ok"] and c["machine"]["ok"])
    return max((c for c in piece.options if c["bend"]["ok"]), key=lambda c: c["machine"]["margin_mm"])


def failure_steps(plan: Plan) -> list[dict]:
    """Limit steps for a plan that failed: the bend and machine words of up to two failed pieces."""
    steps = []
    for p in [p for p in plan.count.pieces if p.fail_reason()][:2]:
        if p.options:
            chk = explaining(p, p.fail_reason())
            lead = "" if plan.P == 1 else f"Piece {p.index + 1} of {plan.P}: "
            steps.append({"tag": "Limit", "text": lead + bend_words(chk), "limit_id": "lam_ratio"})
            steps.append({"tag": "Limit", "text": lead + machine_words(chk), "limit_id": "machine"})
            if "grain" in chk:
                steps.append({"tag": "Limit", "text": lead + grain_words(chk), "limit_id": "grain_deg"})
    return steps


def conflict_cause(plan: Plan, settings: PieceSettings, straight: bool, noun: str,
                   reason: str | None = None) -> tuple[str, tuple, str | None]:
    """(cause, conflict pair, limit id) for a plan that failed. cause: straight | bend | machine | grain |
    fit. noun names the designer's side of the pair ("your part", "your shape"). reason: the failure to
    name (default the plan's own, found at the last piece count tried)."""
    w, h = settings.machine["openingWidth"], settings.machine["openingHeight"]
    opening = f"machine opening {w:.0f} x {h:.0f} mm"
    reason = reason or plan.reason
    if straight:
        return "straight", ("one straight piece", opening), "machine"
    if reason == "bend":
        return "bend", (noun, f"thinnest layer {settings.lams[-1]:g} mm at R/t {settings.ratio:g}"), "lam_ratio"
    if reason == "machine":
        return "machine", (noun, opening), "machine"
    if reason == "grain":
        return "grain", (noun, f"grain within {settings.grain_deg:g} degrees of the path"), "grain_deg"
    return "fit", (noun, "billet fit"), None


def piece_steps(plan: Plan, straight: bool) -> list[dict]:
    """Limit and Decision steps, one pair per piece (one piece: no piece numbers)."""
    steps = []
    for piece, chk in zip(plan.count.pieces, plan.checks):
        lead = "" if plan.P == 1 else f"Piece {piece.index + 1} of {plan.P}: "
        steps.append({"tag": "Limit", "text": lead + bend_words(chk), "limit_id": "lam_ratio"})
        steps.append({"tag": "Limit", "text": lead + machine_words(chk), "limit_id": "machine"})
        if "grain" in chk:
            steps.append({"tag": "Limit", "text": lead + grain_words(chk), "limit_id": "grain_deg"})
        made = made_words(fit_of(piece, chk), chk, straight)
        steps.append({"tag": "Decision", "text": lead + made[0].upper() + made[1:] + ".", "limit_id": None})
    return steps


def waste_steps(plan: Plan) -> list[dict]:
    t = plan.totals
    whole = "the billet" if plan.P == 1 else "the billets, weighted by volume"
    steps = [{"tag": "Check", "text": f"Milling it to shape wastes {t['waste_pct']:.0f}% of {whole}.", "limit_id": None}]
    if plan.target is not None:
        if plan.over_target and plan.best is not None:
            w, P, how = plan.best
            text = (f"Your waste target is {plan.target:g}%. {how} {w:.0f}%." if w < t["waste_pct"] - 0.5 else
                    f"Your waste target is {plan.target:g}%. {t['waste_pct']:.0f}% is the least this allows.")
        else:
            text = f"Your waste target is {plan.target:g}%; this meets it."
        steps.append({"tag": "Check", "text": text, "limit_id": "max_waste_pct"})
    return steps


def target_suffix(plan: Plan) -> str:
    if plan.target is None or not plan.over_target:
        return ""
    return f" Waste {plan.totals['waste_pct']:.0f}%, over your {plan.target:g}% target."


def split_why(plan: Plan) -> list[dict]:
    if plan.P == 1 or plan.split_reason is None:
        return []
    why = {"machine": "One billet will not fit through the machine, so the member is cut into "
                      f"{plan.P} equal pieces, each with its own billet.",
           "waste": f"One billet wastes more than your target, so the member is cut into {plan.P} equal pieces.",
           "grain": "One billet cannot run along the grain and fit through the machine, so the member is cut "
                    f"into {plan.P} equal pieces, each with its own billet.",
           "split_ok": f"You said shorter pieces are fine, so the member is cut into {plan.P} equal pieces."}
    return [{"tag": "Decision", "text": why[plan.split_reason], "limit_id": "max_pieces"}]


# ---- surface_stroke: the hook solve_surface calls before it straightens the line ---------------------------

class SurfaceMember(Member):
    """The drawn line's member (rung 0): pieces are equal runs of stations (the stations are evenly
    spaced along the line, so equal runs are equal lengths)."""

    def __init__(self, intent, curve):
        from . import fabrication as fb
        self.owner = intent
        self.curve = curve
        self.pts = fb.member_points(curve)  # 4 corner points per station, station by station
        self.n = len(curve.pts)
        self.cum = [0.0]
        for a, b in zip(curve.pts, curve.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.total_mm3 = fb.member_volume_mm3(curve)

    def bounds(self, P: int, k: int) -> tuple[int, int]:
        last = self.n - 1
        return round(last * k / P), round(last * (k + 1) / P)

    def points(self, P, k):
        a, b = self.bounds(P, k)
        return self.pts[4 * a: 4 * (b + 1)]

    def span(self, P, k):
        a, b = self.bounds(P, k)
        return self.cum[a], self.cum[b]

    def volume(self, P, k):
        from . import fabrication as fb
        a, b = self.span(P, k)
        return fb.SECTION_DEPTH_MM * fb.SECTION_WIDTH_MM * (b - a)

    def cut(self, P, j):
        from .surface import cross, unit, sub
        from . import fabrication as fb
        i = self.bounds(P, j)[0]
        p, nrm = self.curve.pts[i], self.curve.normals[i]
        t = unit(sub(self.curve.pts[min(i + 1, self.n - 1)], self.curve.pts[max(i - 1, 0)]))
        side = unit(cross(nrm, t))
        h = fb.SECTION_WIDTH_MM / 2
        line = [[round(p[c] - side[c] * h, 1) + 0.0 for c in range(3)], [round(p[c] + side[c] * h, 1) + 0.0 for c in range(3)]]
        return {"station": i, "origin": [round(c, 1) + 0.0 for c in p], "normal": [round(c, 6) + 0.0 for c in t],
                "line": line}


@dataclass(frozen=True)
class SurfacePiecesForm:
    """A surface member made in P pieces. Duck-types SurfaceForm for the server, record and taste."""
    curve: object
    intent: object
    member: SurfaceMember
    plan: Plan
    smoothing_passes: int = 0
    straight: bool = False

    @property
    def solid(self) -> bool:
        return False

    @property
    def pieces(self) -> int:
        return self.plan.P

    @property
    def n_lamellas(self) -> int:
        return max(c["lam_count"] for c in self.plan.checks)

    @property
    def lamella_mm(self) -> float:
        return min(c["lam_mm"] for c in self.plan.checks)

    @property
    def check(self) -> dict:  # what record.volumes reads
        t = self.plan.totals
        return {"billet_mm3": t["billet_mm3"], "part_mm3": t["part_mm3"], "waste_pct": t["waste_pct"]}

    def joints(self) -> list[dict]:
        return joints(self.member, self.plan)

    def as_dict(self) -> dict:
        cv = self.curve
        vec = lambda pts, nd: [[round(a, nd) + 0.0 for a in p] for p in pts]  # noqa: E731
        pcs = [piece_dict(p, c, False) for p, c in zip(self.plan.count.pieces, self.plan.checks)]
        t = self.plan.totals
        return {
            "kind": "surface_member",
            "stations": vec(cv.pts, 2), "normals": vec(cv.normals, 6), "uv": vec(cv.uv, 6),
            "intent_stations": vec(self.intent.pts, 2),
            "n_lamellas": self.n_lamellas, "lamella_mm": _f(self.lamella_mm, 2), "straight_billet": False,
            "n_pieces": self.plan.P, "pieces": pcs, "cuts": self.joints(),
            "billet": {"mode": "pieces", "volume_m3": round(t["billet_mm3"] / 1e9, 6),
                       "outline": [loop for p in pcs for loop in p["billet"]["outline"]]},
            "part_volume_m3": round(t["part_mm3"] / 1e9, 6),
            "checks": summary_checks(self.plan),
            "min_radius_normal_mm": _f(cv.r_normal), "min_radius_side_mm": _f(cv.r_side),
            "max_twist_deg_per_m": round(cv.max_twist_deg_per_m, 1), "length_mm": round(cv.length_mm, 1),
            "smoothing_passes": 0,
        }

    def summary(self) -> dict:
        d = self.as_dict()
        for k in ("stations", "normals", "uv", "intent_stations"):
            d.pop(k)
        d["billet"].pop("outline", None)
        for p in d["pieces"]:
            p["billet"].pop("outline", None)
        return d


def try_split_surface(intent, holds, ladder, setup, first_check, settings: PieceSettings | None = None):
    """Called by solve_surface after the drawn line (rung 0) was checked and before any
    straightening. Returns a SurfaceResult in pieces, or None to carry on as before.
    first_check: the (passing, explaining) pair solve_surface has for rung 0."""
    from .surface_solver import SurfaceResult, TRIM_NOTE
    if "solid" in holds:
        return None  # one straight piece is one piece
    settings = settings or current_settings()
    session = {k: v for k, v in (("max_pieces", setup.max_pieces), ("max_waste_pct", setup.max_waste_pct))
               if v is not None}  # the session's own values, when the setup came from /settings
    settings = replace(settings, lams=tuple(setup.lams), ratio=setup.ratio, machine=setup.machine,
                       allowance=setup.allowance, **session)
    split_ok, less_waste = "split_ok" in holds, "less_waste" in holds
    passing, why = first_check
    target = settings.max_waste_pct
    rung0_ok = passing is not None
    machine_failed = why is not None and not passing and why["bend"]["ok"] is True and not why["machine"]["ok"]
    over = rung0_ok and target is not None and passing["waste_pct"] > target
    if not (machine_failed or over or split_ok):
        return None  # a bend failure is not a reason to cut; nor is waste nobody asked about
    if rung0_ok and not over and not (split_ok and less_waste):
        return None  # one piece passes: the fewest pieces that satisfy the checks
    member = SurfaceMember(intent, ladder.get(0))
    if settings.allowance == 0:  # the ladder fits with their default allowance, 0
        FitCache.of(intent).seed((1, 0, False, 0.0), ladder.fit(0, False))
    p = plan(member, settings, split_ok=split_ok, less_waste=less_waste, max_waste_pct=target)
    if p.status != "proposed" or p.P == 1:
        return None  # pieces do not help: the line is straightened as before
    form = SurfacePiecesForm(ladder.get(0), intent.intent, member, p)
    steps = [{"tag": "Heard", "text": f"Follow your line on the surface, {m_text(intent.intent.length_mm)} long."
              + (" " + TRIM_NOTE if intent.trimmed else ""), "limit_id": "length" if intent.trimmed else None}]
    steps += split_why(p) + piece_steps(p, False) + joint_steps(member, p) + waste_steps(p)
    steps.append({"tag": "Check", "text": f"The twist, up to {form.curve.max_twist_deg_per_m:.1f} degrees per metre, "
                                          f"is milled out.", "limit_id": None})
    sentence = f"Your line holds, in {p.P} pieces joined end to end. Each pressed from layers, then milled."
    if intent.trimmed:
        sentence += " " + TRIM_NOTE
    sentence += target_suffix(p)
    return SurfaceResult("proposed", sentence, steps, "rules", form, 0.0, intent.trimmed,
                         governing=["lam_ratio", "machine"])


def formal_surface_pieces(intent, result, cards) -> str:
    """The record sentence for a surface member made in pieces (record.make_entry calls this)."""
    from .record import SPECIES, volumes_text
    f = result.form
    c = f.curve
    t = f.plan.totals
    depth, width = cards["stock_thickness"].value, cards["stock_width"].value
    return (f"Member {intent.member_id}, {SPECIES} {depth:g} x {width:g} mm, surface member following the drawn line, "
            f"length {m_text(c.length_mm)}{', trimmed to the stock length' if result.trimmed else ''}; "
            f"twist up to {c.max_twist_deg_per_m:.1f} degrees per metre, milled out. Line kept as drawn, made in "
            f"{f.plan.P} pieces joined end to end, each pressed, then milled. " + formal_text(f.plan, f.member, False)
            + " " + volumes_text(t["billet_mm3"] / 1e9, t["part_mm3"] / 1e9, t["waste_pct"])
            + " Governing limit: machine opening. Deviation from intent 0 mm.")


def formal_text(plan: Plan, member: Member, straight: bool) -> str:
    """The pieces' part of the record sentence: each billet, each joint, and the weighted waste."""
    parts = []
    for piece, chk in zip(plan.count.pieces, plan.checks):
        b = billet_dict(fit_of(piece, chk), chk, straight, outline=False)
        lead = "" if plan.P == 1 else f"Piece {piece.index + 1} of {plan.P} ({piece.span[0]:.0f} to {piece.span[1]:.0f} mm): "
        made = made_words(fit_of(piece, chk), chk, straight)
        parts.append(f"{lead}{made[0].upper()}{made[1:]}, {b['volume_m3']:.3f} m3, waste {chk['waste_pct']:.1f}%.")
    for j in joints(member, plan):
        parts.append(f"Joint {j['index']} at {j['at_mm']:.0f} mm: {JOINT_WORDS}.")
    if plan.P > 1:
        parts.append(f"Waste over all pieces, weighted by volume, {plan.totals['waste_pct']:.1f}%.")
    if plan.target is not None:
        parts.append(f"Waste target {plan.target:g}%, " + ("missed." if plan.over_target else "met."))
    return " ".join(parts)
