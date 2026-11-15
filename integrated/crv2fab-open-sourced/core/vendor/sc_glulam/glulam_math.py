"""Rhino-independent maths for the doubly curved glulam billet check (numpy only).

Everything here is testable outside Rhino. Units are whatever the caller passes in
(model units in Rhino); nothing in this module converts units.

Conventions
-----------
- The billet is bent in a plane with right-handed frame (u, v, n): u, v span the bending
  plane, n is the billet width direction (out of plane). 2D coordinates are (x, y) = (.u, .v).
- A spine is a planar reference curve parametrised by arc length s.
- T is the unit tangent, N the LEFT normal (n x T, i.e. T rotated +90 deg in 2D).
- d is the in-plane offset along N. A billet face is the spine offset by a constant d.
- Signed curvature kappa > 0 when the spine turns toward N. The radius of the
  offset curve at d is |1 - kappa d| / |kappa|.
"""

import math

import numpy as np

TWO_PI = 2.0 * math.pi
_trapezoid = getattr(np, "trapezoid", None) or np.trapz  # numpy 2 renamed trapz
STRAIGHT_KAPPA_HAT = 1e-6  # dimensionless curvature (kappa * Lc) below which a billet is straight


# ----------------------------------------------------------------------------------------------
# Optimiser
# ----------------------------------------------------------------------------------------------

def nelder_mead(func, x0, step, maxEval=400, xTol=1e-7, fTol=1e-9):
    """Minimise func from x0 with a Nelder-Mead simplex. Returns (xBest, fBest).

    Used only where no closed-form construction exists (the minimum-area annular sector and the
    bending-plane orientation). Infinite values mark infeasible points.
    """
    x0 = np.asarray(x0, dtype=float)
    dim = len(x0)
    simplex = np.vstack([x0] + [x0 + step[i] * np.eye(dim)[i] for i in range(dim)])
    values = np.array([func(x) for x in simplex])
    evalCount = dim + 1

    while evalCount < maxEval:
        order = np.argsort(values)
        simplex = simplex[order]
        values = values[order]
        spread = np.max(np.abs(simplex[1:] - simplex[0]))
        if np.isfinite(values[-1]) and spread <= xTol and \
                abs(values[-1] - values[0]) <= fTol * (abs(values[0]) + 1e-30):
            break

        centroid = simplex[:-1].mean(axis=0)
        xReflect = centroid + (centroid - simplex[-1])
        fReflect = func(xReflect)
        evalCount += 1

        if fReflect < values[0]:
            xExpand = centroid + 2.0 * (centroid - simplex[-1])
            fExpand = func(xExpand)
            evalCount += 1
            if fExpand < fReflect:
                simplex[-1], values[-1] = xExpand, fExpand
            else:
                simplex[-1], values[-1] = xReflect, fReflect
        elif fReflect < values[-2]:
            simplex[-1], values[-1] = xReflect, fReflect
        else:
            if fReflect < values[-1]:
                xContract = centroid + 0.5 * (xReflect - centroid)
            else:
                xContract = centroid + 0.5 * (simplex[-1] - centroid)
            fContract = func(xContract)
            evalCount += 1
            if fContract < min(fReflect, values[-1]):
                simplex[-1], values[-1] = xContract, fContract
            else:
                for i in range(1, dim + 1):
                    simplex[i] = simplex[0] + 0.5 * (simplex[i] - simplex[0])
                    values[i] = func(simplex[i])
                evalCount += dim

    best = int(np.argmin(values))
    return simplex[best], float(values[best])


# ----------------------------------------------------------------------------------------------
# Frames and projection
# ----------------------------------------------------------------------------------------------

def unit(vec):
    vec = np.asarray(vec, dtype=float)
    length = np.linalg.norm(vec)
    if length < 1e-15:
        raise ValueError("zero-length vector")
    return vec / length


def pca_axes(POINTS):
    """Centroid and principal axes (longest first) of an (N, 3) point array."""
    centroid = POINTS.mean(axis=0)
    covariance = np.cov((POINTS - centroid).T)
    eigenValues, eigenVectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenValues)[::-1]
    return centroid, eigenVectors[:, order].T


def plane_frame(normal, lengthHint):
    """Right-handed (u, v, n) with u as close to lengthHint as the plane allows."""
    n = unit(normal)
    u = np.asarray(lengthHint, dtype=float) - np.dot(lengthHint, n) * n
    if np.linalg.norm(u) < 1e-9:
        u = np.cross(n, [1.0, 0.0, 0.0])
        if np.linalg.norm(u) < 1e-9:
            u = np.cross(n, [0.0, 1.0, 0.0])
    u = unit(u)
    v = np.cross(n, u)
    return u, v, n


def project_to_frame(POINTS, origin, u, v, n):
    """(N, 3) points to in-plane (N, 2) coordinates and out-of-plane coordinate (N,)."""
    rel = POINTS - origin
    return np.column_stack([rel @ u, rel @ v]), rel @ n


def _sphere_directions(count):
    """Roughly even unit directions (Fibonacci sphere), in the points' dimension 2 or 3."""
    i = np.arange(count) + 0.5
    z = 1.0 - 2.0 * i / count
    radius = np.sqrt(1.0 - z ** 2)
    phi = math.pi * (3.0 - math.sqrt(5.0)) * i
    return np.column_stack([radius * np.cos(phi), radius * np.sin(phi), z])


def subset(POINTS, maxCount, seed=7):
    """Seeded random subset plus the extreme points in ~100 directions.

    Used only to speed up the optimisation; final extents always use every point. Random
    (not stride) sampling avoids aliasing with structured mesh vertices, and the extremes
    keep the outermost faces represented. Seeded, so repeated runs give the same billet.
    """
    if len(POINTS) <= maxCount:
        return POINTS
    rng = np.random.default_rng(seed)
    picked = set(rng.choice(len(POINTS), maxCount, replace=False).tolist())
    DIRECTIONS = _sphere_directions(100)[:, :POINTS.shape[1]]
    PROJ = POINTS @ DIRECTIONS.T
    picked.update(np.argmax(PROJ, axis=0).tolist())
    picked.update(np.argmin(PROJ, axis=0).tolist())
    return POINTS[sorted(picked)]


def _rot90(VECTORS):
    VECTORS = np.atleast_2d(VECTORS)
    return np.column_stack([-VECTORS[:, 1], VECTORS[:, 0]])


# ----------------------------------------------------------------------------------------------
# Spines
# ----------------------------------------------------------------------------------------------

class LineSpine:
    """Straight spine: origin p0, unit tangent T."""

    kind = "line"

    def __init__(self, origin, tangent):
        self.origin = np.asarray(origin, dtype=float)
        self.tangent = unit(tangent)
        self.normalVec = _rot90(self.tangent)[0]

    def point(self, s, d=0.0):
        s = np.atleast_1d(np.asarray(s, dtype=float))
        d = np.broadcast_to(np.asarray(d, dtype=float), s.shape)
        return self.origin + s[:, None] * self.tangent + d[:, None] * self.normalVec

    def curvature(self, s):
        return np.zeros_like(np.atleast_1d(np.asarray(s, dtype=float)))

    def project(self, P2):
        rel = P2 - self.origin
        return rel @ self.tangent, rel @ self.normalVec


class ArcSpine:
    """Circular spine, counter-clockwise about +n, s = 0 at angle theta0. N points to the centre."""

    kind = "arc"

    def __init__(self, centre, radius, theta0, span):
        self.centre = np.asarray(centre, dtype=float)
        self.radius = float(radius)
        self.theta0 = float(theta0)
        self.thetaMid = self.theta0 + 0.5 * span

    def point(self, s, d=0.0):
        s = np.atleast_1d(np.asarray(s, dtype=float))
        d = np.broadcast_to(np.asarray(d, dtype=float), s.shape)
        theta = self.theta0 + s / self.radius
        r = self.radius - d
        return self.centre + np.column_stack([r * np.cos(theta), r * np.sin(theta)])

    def curvature(self, s):
        return np.full_like(np.atleast_1d(np.asarray(s, dtype=float)), 1.0 / self.radius)

    def project(self, P2):
        rel = P2 - self.centre
        theta = np.arctan2(rel[:, 1], rel[:, 0])
        wrapped = np.mod(theta - self.thetaMid + math.pi, TWO_PI) - math.pi
        s = (wrapped + self.thetaMid - self.theta0) * self.radius
        return s, self.radius - np.hypot(rel[:, 0], rel[:, 1])


def _clamped_knots(ctrlCount, degree):
    interior = ctrlCount - degree - 1
    return np.concatenate([np.zeros(degree + 1),
                           np.linspace(0.0, 1.0, interior + 2)[1:-1],
                           np.ones(degree + 1)])


def _basis(params, knots, degree):
    """B-spline basis matrix, shape (len(params), len(knots) - degree - 1). Cox-de Boor."""
    params = np.clip(np.asarray(params, dtype=float), knots[0], knots[-1])
    spanCount = len(knots) - 1
    BASIS = np.zeros((len(params), spanCount))
    for i in range(spanCount):
        BASIS[:, i] = (params >= knots[i]) & (params < knots[i + 1])
    lastSpan = max(i for i in range(spanCount) if knots[i] < knots[i + 1])
    BASIS[params >= knots[-1], lastSpan] = 1.0
    for k in range(1, degree + 1):
        NEXT = np.zeros((len(params), spanCount - k))
        for i in range(spanCount - k):
            left = knots[i + k] - knots[i]
            right = knots[i + k + 1] - knots[i + 1]
            if left > 0:
                NEXT[:, i] += (params - knots[i]) / left * BASIS[:, i]
            if right > 0:
                NEXT[:, i] += (knots[i + k + 1] - params) / right * BASIS[:, i + 1]
        BASIS = NEXT
    return BASIS


def _bspline_eval(CTRL, knots, degree, params, derivative=0):
    if derivative == 0:
        return _basis(params, knots, degree) @ CTRL
    denominators = knots[degree + 1:degree + len(CTRL)] - knots[1:len(CTRL)]
    DCTRL = degree * (CTRL[1:] - CTRL[:-1]) / denominators[:, None]
    return _bspline_eval(DCTRL, knots[1:-1], degree - 1, params, derivative - 1)


class BSplineSpine:
    """Cubic clamped-uniform B-spline spine, extended past both ends along its end tangents.

    Arc length is tabulated so s maps to the curve parameter. For s < 0 or s > length the
    spine continues as a straight tangent line (curvature 0); projection uses the same model.
    """

    kind = "bspline"
    TABLE_SAMPLES = 2000

    def __init__(self, CTRL, degree=3):
        self.CTRL = np.asarray(CTRL, dtype=float)
        self.degree = degree
        self.knots = _clamped_knots(len(self.CTRL), degree)
        self.TABLE_U = np.linspace(0.0, 1.0, self.TABLE_SAMPLES)
        self.TABLE_P = _bspline_eval(self.CTRL, self.knots, degree, self.TABLE_U)
        segLength = np.linalg.norm(np.diff(self.TABLE_P, axis=0), axis=1)
        self.TABLE_S = np.concatenate([[0.0], np.cumsum(segLength)])
        self.length = float(self.TABLE_S[-1])
        self.startTangent = self._tangent_at_u(np.array([0.0]))[0]
        self.endTangent = self._tangent_at_u(np.array([1.0]))[0]

    @classmethod
    def fit(cls, TARGETS, ctrlCount, degree=3, smoothing=1e-4):
        """Least-squares fit through ordered 2D targets with a small second-difference penalty."""
        TARGETS = np.asarray(TARGETS, dtype=float)
        ctrlCount = max(degree + 1, min(ctrlCount, len(TARGETS)))
        chord = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(TARGETS, axis=0), axis=1))])
        params = chord / chord[-1]
        knots = _clamped_knots(ctrlCount, degree)
        BASIS = _basis(params, knots, degree)
        SECOND = np.diff(np.eye(ctrlCount), n=2, axis=0) * math.sqrt(smoothing * len(TARGETS))
        lhs = np.vstack([BASIS, SECOND])
        rhs = np.vstack([TARGETS, np.zeros((len(SECOND), 2))])
        CTRL = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
        return cls(CTRL, degree)

    def _tangent_at_u(self, params):
        return np.array([unit(t) for t in _bspline_eval(self.CTRL, self.knots, self.degree, params, 1)])

    def _u_of_s(self, s):
        return np.interp(np.clip(s, 0.0, self.length), self.TABLE_S, self.TABLE_U)

    def point(self, s, d=0.0):
        s = np.atleast_1d(np.asarray(s, dtype=float))
        d = np.broadcast_to(np.asarray(d, dtype=float), s.shape)
        params = self._u_of_s(s)
        base = _bspline_eval(self.CTRL, self.knots, self.degree, params)
        TANGENTS = self._tangent_at_u(params)
        before, after = s < 0.0, s > self.length
        base[before] = self.TABLE_P[0] + s[before, None] * self.startTangent
        base[after] = self.TABLE_P[-1] + (s[after, None] - self.length) * self.endTangent
        TANGENTS[before] = self.startTangent
        TANGENTS[after] = self.endTangent
        return base + d[:, None] * _rot90(TANGENTS)

    def curvature(self, s):
        s = np.atleast_1d(np.asarray(s, dtype=float))
        params = self._u_of_s(s)
        FIRST = _bspline_eval(self.CTRL, self.knots, self.degree, params, 1)
        SECOND = _bspline_eval(self.CTRL, self.knots, self.degree, params, 2)
        cross = FIRST[:, 0] * SECOND[:, 1] - FIRST[:, 1] * SECOND[:, 0]
        kappa = cross / np.linalg.norm(FIRST, axis=1) ** 3
        kappa[(s < 0.0) | (s > self.length)] = 0.0
        return kappa

    def project(self, P2, chunk=400):
        """Signed normal coordinates (s, d) of 2D points against the tabulated, extended spine."""
        reach = 2.0 * (self.length + 1.0)
        POLY = np.vstack([self.TABLE_P[0] - reach * self.startTangent,
                          self.TABLE_P,
                          self.TABLE_P[-1] + reach * self.endTangent])
        POLY_S = np.concatenate([[-reach], self.TABLE_S, [self.length + reach]])
        SEG = np.diff(POLY, axis=0)
        segLen2 = np.einsum("ij,ij->i", SEG, SEG)
        SEG_N = _rot90(SEG / np.sqrt(segLen2)[:, None])
        sOut = np.empty(len(P2))
        dOut = np.empty(len(P2))
        for start in range(0, len(P2), chunk):
            BLOCK = P2[start:start + chunk]
            REL = BLOCK[:, None, :] - POLY[None, :-1, :]
            t = np.clip(np.einsum("pij,ij->pi", REL, SEG) / segLen2, 0.0, 1.0)
            FOOT = REL - t[:, :, None] * SEG[None]
            dist2 = np.einsum("pij,pij->pi", FOOT, FOOT)
            best = np.argmin(dist2, axis=1)
            rows = np.arange(len(BLOCK))
            sOut[start:start + chunk] = POLY_S[best] + t[rows, best] * np.sqrt(segLen2[best])
            dOut[start:start + chunk] = np.einsum("pj,pj->p", REL[rows, best], SEG_N[best])
        return sOut, dOut


# ----------------------------------------------------------------------------------------------
# Constant-radius (arc) billet fit
# ----------------------------------------------------------------------------------------------

def _angular_span(angles):
    """Smallest arc containing all angles: (startAngle, span)."""
    ordered = np.sort(np.mod(angles, TWO_PI))
    gaps = np.diff(ordered)
    wrapGap = ordered[0] + TWO_PI - ordered[-1]
    if len(gaps) == 0 or wrapGap >= gaps.max():
        return ordered[0], ordered[-1] - ordered[0]
    i = int(np.argmax(gaps))
    return ordered[i + 1], TWO_PI - gaps[i]


def sector_fit(P2, centre, allowance):
    """Annular sector about centre that holds every point with the allowance. None if infeasible."""
    rel = P2 - centre
    r = np.hypot(rel[:, 0], rel[:, 1])
    rIn = r.min() - allowance
    rOut = r.max() + allowance
    if rIn <= 0.0:
        return None
    start, span = _angular_span(np.arctan2(rel[:, 1], rel[:, 0]))
    rMid = 0.5 * (rIn + rOut)
    pad = allowance / rMid
    paddedSpan = span + 2.0 * pad
    if paddedSpan >= TWO_PI:
        return None
    return {"rIn": r.min(), "rOut": r.max(), "start": start, "span": span,
            "area": 0.5 * paddedSpan * (rOut - rIn) * (rOut + rIn)}


def strip_area(P2, bandNormal, allowance):
    """Area of the straight band with the given in-plane normal that holds every point."""
    bandNormal = unit(bandNormal)
    tangent = _rot90(bandNormal)[0]
    return (np.ptp(P2 @ bandNormal) + 2 * allowance) * (np.ptp(P2 @ tangent) + 2 * allowance)


def _kasa_centre(P2):
    """Algebraic least-squares circle centre (exact linear solve)."""
    lhs = np.column_stack([2.0 * P2, np.ones(len(P2))])
    rhs = (P2 ** 2).sum(axis=1)
    solution = np.linalg.lstsq(lhs, rhs, rcond=None)[0]
    return solution[:2]


def fit_arc_2d(P2, allowance, quick=False, warmStart=None):
    """Minimum-area annular sector (or straight band) holding the 2D points.

    Parametrised by the centre direction psi from the centroid and the dimensionless
    curvature kHat = Lc / R, so the straight billet (kHat = 0) is reached continuously.
    Returns (spine, area, (psi, kHat)).
    """
    centroid = P2.mean(axis=0)
    lc = float(np.ptp(P2, axis=0).max())

    def direction(psi):
        return np.array([math.cos(psi), math.sin(psi)])

    def area(x):
        psi, kHat = x
        if abs(kHat) < STRAIGHT_KAPPA_HAT:
            return strip_area(P2, direction(psi), allowance)
        result = sector_fit(P2, centroid + direction(psi) * lc / kHat, allowance)
        return math.inf if result is None else result["area"]

    kasa = _kasa_centre(P2) - centroid
    kasaR = np.linalg.norm(kasa)
    STARTS = []
    if warmStart is not None:
        STARTS.append(tuple(warmStart))
    if kasaR > 1e-9 * lc:
        STARTS.append((math.atan2(kasa[1], kasa[0]), lc / kasaR))
    _, axes2d = np.linalg.eigh(np.cov((P2 - centroid).T))
    minor = axes2d[:, 0]
    psiMinor = math.atan2(minor[1], minor[0])
    STARTS.append((psiMinor, 0.0))
    if not quick:
        STARTS += [(psiMinor, 0.5), (psiMinor + math.pi, 0.5)]

    bestX, bestArea = None, math.inf
    for start in STARTS:
        step = [0.25, 0.25 * max(1.0, abs(start[1]))]
        x, value = nelder_mead(area, start, step, maxEval=200 if quick else 500)
        if value < bestArea:
            bestX, bestArea = x, value

    psi, kHat = bestX
    if abs(kHat) < STRAIGHT_KAPPA_HAT:
        bandNormal = direction(psi)
        spine = LineSpine(centroid, _rot90(bandNormal)[0])
        return spine, bestArea, tuple(bestX)

    centre = centroid + direction(psi) * lc / kHat
    sector = sector_fit(P2, centre, allowance)
    spine = ArcSpine(centre, 0.5 * (sector["rIn"] + sector["rOut"]), sector["start"], sector["span"])
    return spine, bestArea, tuple(bestX)


def fit_bending_plane(POINTS, allowance, maxCount=1000, maxEval=60):
    """Bending-plane normal that minimises (billet width) x (in-plane arc-billet area).

    Starts from the two principal-axis normals that keep the part's length in plane, and
    refines each by Nelder-Mead over a small rotation of the normal. Returns (origin, u, v, n).
    """
    SAMPLE = subset(POINTS, maxCount)
    origin, axes = pca_axes(POINTS)  # all points: a sampled PCA tilts an exact plane slightly
    lengthAxis = axes[0]

    RESCORE = subset(POINTS, 4 * maxCount)

    def billet_volume(n, quick, warm=None):
        u, v, n = plane_frame(n, lengthAxis)
        P2, W = project_to_frame(SAMPLE if quick else RESCORE, origin, u, v, n)
        _, area, x = fit_arc_2d(P2, allowance, quick=quick, warmStart=warm)
        return (np.ptp(W) + 2 * allowance) * area, x

    CANDIDATES = []
    for n0 in (axes[2], axes[1]):
        ea, eb = plane_frame(n0, lengthAxis)[:2]
        warm = [None]

        def objective(x):
            value, warm[0] = billet_volume(unit(n0 + x[0] * ea + x[1] * eb), True, warm[0])
            return value

        x, _ = nelder_mead(objective, [0.0, 0.0], [0.12, 0.12], maxEval=maxEval)
        CANDIDATES += [n0, unit(n0 + x[0] * ea + x[1] * eb)]

    # The quick, warm-started inner fit on a small sample makes the outer objective slightly
    # noisy: re-score the start normals and the optimised ones with full inner fits on a larger
    # sample and keep the best. An optimised normal replaces its start only when clearly better
    # (sample noise otherwise tilts an exact plane by ~1e-5 rad, which can cost a whole lam).
    best = (math.inf, None)
    for i in range(0, len(CANDIDATES), 2):
        startScore = billet_volume(CANDIDATES[i], False)[0]
        optScore = billet_volume(CANDIDATES[i + 1], False)[0]
        score, n = (optScore, CANDIDATES[i + 1]) if optScore < startScore * (1 - 5e-4) \
            else (startScore, CANDIDATES[i])
        if score < best[0]:
            best = (score, n)
    u, v, n = plane_frame(best[1], lengthAxis)
    return origin, u, v, n


# ----------------------------------------------------------------------------------------------
# Variable-curvature billet fit
# ----------------------------------------------------------------------------------------------

def fit_freeform_2d(P2, seedSpine, ctrlCount=6, iterations=15, allowance=0.0):
    """Variable-curvature spine for a constant-depth band around the 2D points.

    Heuristic (no exact minimum exists): bin the points along the spine, move each station to
    the middle of its offset range, refit a smooth cubic B-spline through the stations, repeat.
    ctrlCount sets the smoothness (fewer = stiffer spine, larger radii). Keeps the iterate with
    the smallest band area.
    """
    lc = float(np.ptp(P2, axis=0).max())
    spine = seedSpine
    best = (math.inf, None)
    for _ in range(iterations):
        s, d = spine.project(P2)
        area = band_area(spine, s.min() - allowance, s.max() + allowance,
                         d.min() - allowance, d.max() + allowance)
        if area < best[0]:
            best = (area, spine)

        binCount = max(3 * ctrlCount, 12)
        edges = np.linspace(s.min(), s.max(), binCount + 1)
        index = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, binCount - 1)
        STATION_S, STATION_D = [], []
        for j in range(binCount):
            mask = index == j
            if mask.any():
                STATION_S.append(0.5 * (edges[j] + edges[j + 1]))
                STATION_D.append(0.5 * (d[mask].min() + d[mask].max()))
        STATION_D = np.array(STATION_D)
        spine = BSplineSpine.fit(spine.point(np.array(STATION_S), STATION_D), ctrlCount)
        if np.abs(STATION_D).max() < 1e-5 * lc:
            break

    s, d = spine.project(P2)
    area = band_area(spine, s.min() - allowance, s.max() + allowance,
                     d.min() - allowance, d.max() + allowance)
    if area < best[0]:
        best = (area, spine)
    return best[1], best[0]


# ----------------------------------------------------------------------------------------------
# Billet extents, area, envelope, lams
# ----------------------------------------------------------------------------------------------

def band_area(spine, sLow, sHigh, dLow, dHigh, samples=600):
    """In-plane area between the offsets dLow and dHigh over [sLow, sHigh] (exact for no cusps)."""
    s = np.linspace(sLow, sHigh, samples)
    stretch = 1.0 - spine.curvature(s) * 0.5 * (dLow + dHigh)
    return (dHigh - dLow) * _trapezoid(stretch, s)


def billet_extents(spine, P2, W, allowance, lamThickness):
    """Final billet extents from all points: s, d (rounded up to whole lams) and w ranges."""
    s, d = spine.project(P2)
    depthNeeded = np.ptp(d) + 2.0 * allowance
    lamCount = max(1, int(math.ceil(depthNeeded / lamThickness - 1e-6)))  # 1e-6: float noise
    extra = lamCount * lamThickness - depthNeeded
    dLow = d.min() - allowance - 0.5 * extra
    return {"sLow": s.min() - allowance, "sHigh": s.max() + allowance,
            "dLow": dLow, "dHigh": dLow + lamCount * lamThickness,
            "wLow": W.min() - allowance, "wHigh": W.max() + allowance,
            "lamCount": lamCount, "depthNeeded": depthNeeded}


def offset_radii(spine, sLow, sHigh, OFFSETS, samples=800):
    """Minimum radius of each offset curve over [sLow, sHigh]; inf where straight.

    Raises ValueError if an offset passes through its centre of curvature (cusp), i.e. the
    billet is deeper than the spine can bend.
    """
    s = np.linspace(sLow, sHigh, samples)
    kappa = spine.curvature(s)
    RADII = []
    for offset in OFFSETS:
        stretch = 1.0 - kappa * offset
        if (stretch <= 0.0).any():
            raise ValueError("billet face at offset %.1f passes its centre of curvature" % offset)
        curved = np.abs(kappa) > 1e-15
        RADII.append(float((stretch[curved] / np.abs(kappa[curved])).min()) if curved.any() else math.inf)
    return np.array(RADII)


def convex_hull(P2):
    """Andrew's monotone chain. Returns hull vertices counter-clockwise."""
    ORDERED = np.unique(P2, axis=0)
    if len(ORDERED) < 3:
        return ORDERED

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in ORDERED:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in ORDERED[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def min_width_box(P2):
    """Minimum-width enclosing rectangle (rotating calipers over hull edges).

    The width is the smallest extent of the shape in any direction: the cross-section a
    planar piece presents when fed through a machine along the perpendicular direction.
    Returns width, length, feed and across unit vectors (right-handed) and the rectangle origin.
    """
    HULL = convex_hull(P2)
    best = None
    for i in range(len(HULL)):
        edge = HULL[(i + 1) % len(HULL)] - HULL[i]
        if np.linalg.norm(edge) < 1e-12:
            continue
        feed = unit(edge)
        across = _rot90(feed)[0]
        alongValues = HULL @ feed
        acrossValues = HULL @ across
        width = float(np.ptp(acrossValues))
        if best is None or width < best["width"]:
            best = {"width": width, "length": float(np.ptp(alongValues)), "feed": feed,
                    "across": across,
                    "origin": feed * alongValues.min() + across * acrossValues.min()}
    return best


def curvature_factor_kx(lamThickness, innerRadius):
    """CSA O86 curvature factor Kx = 1 - 2000 (t / Ri)^2 (curved portion only)."""
    if not math.isfinite(innerRadius):
        return 1.0
    return 1.0 - 2000.0 * (lamThickness / innerRadius) ** 2
