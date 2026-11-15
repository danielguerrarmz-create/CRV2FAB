"""Offline checks of glulam_math against synthetic parts with known answers (mm).

Run:  py test_glulam_math.py
"""

import math
import time

import numpy as np

import glulam_math as gm


def swept_part(spineFn, length, depth, width, sagFn=None, count=120, rotation=None):
    """Surface points of a rectangular section (depth in plane, width along z) swept along a
    planar spine in XY, optionally with out-of-plane sag z(s); optional rigid rotation."""
    s = np.linspace(0.0, length, count)
    P, T = spineFn(s)
    N = np.column_stack([-T[:, 1], T[:, 0]])
    sag = sagFn(s) if sagFn else np.zeros_like(s)
    POINTS = []
    a = np.linspace(-depth / 2, depth / 2, 9)
    b = np.linspace(-width / 2, width / 2, 7)
    for i in range(len(s)):
        for aa in a:
            for bb in ([b[0], b[-1]] if abs(aa) < depth / 2 - 1e-9 else b):
                xy = P[i] + aa * N[i]
                POINTS.append([xy[0], xy[1], bb + sag[i]])
    POINTS = np.array(POINTS)
    if rotation is not None:
        POINTS = POINTS @ rotation.T
    return POINTS


def arc_spine(radius):
    def fn(s):
        theta = s / radius
        return (np.column_stack([radius * np.sin(theta), radius * (1 - np.cos(theta))]),
                np.column_stack([np.cos(theta), np.sin(theta)]))
    return fn


def clothoid_spine(k0, k1, length):
    """Curvature varying linearly from k0 to k1 (variable radius), integrated numerically."""
    def fn(s):
        fine = np.linspace(0.0, length, 4000)
        heading = k0 * fine + 0.5 * (k1 - k0) / length * fine ** 2
        T = np.column_stack([np.cos(heading), np.sin(heading)])
        P = np.vstack([[0, 0], np.cumsum((T[1:] + T[:-1]) / 2 * np.diff(fine)[:, None], axis=0)])
        return (np.column_stack([np.interp(s, fine, P[:, 0]), np.interp(s, fine, P[:, 1])]),
                np.column_stack([np.interp(s, fine, T[:, 0]), np.interp(s, fine, T[:, 1])]))
    return fn


def random_rotation(seed=3):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    return q if np.linalg.det(q) > 0 else -q


def fit(POINTS, allowance=0.0, lam=35.0, variable=False, ctrl=6):
    origin, u, v, n = gm.fit_bending_plane(POINTS, allowance)
    P2, W = gm.project_to_frame(POINTS, origin, u, v, n)
    spine, area, _ = gm.fit_arc_2d(gm.subset(P2, 4000), allowance)
    arcArea = area
    if variable:
        spine, area = gm.fit_freeform_2d(gm.subset(P2, 4000), spine, ctrl, allowance=allowance)
    ext = gm.billet_extents(spine, P2, W, allowance, lam)
    return n, spine, area, arcArea, ext, P2


def check(label, value, expected, tol):
    ok = abs(value - expected) <= tol
    print("  %-38s %12.2f  expected %12.2f  %s" % (label, value, expected, "ok" if ok else "FAIL"))
    return ok


def main():
    results = []

    print("1. Pure arc beam R=6000, 60 deg, 400 deep x 200 wide, randomly rotated in space")
    R, span, depth, width = 6000.0, math.radians(60), 400.0, 200.0
    rot = random_rotation()
    POINTS = swept_part(arc_spine(R), R * span, depth, width, rotation=rot)
    t0 = time.time()
    n, spine, area, _, ext, P2 = fit(POINTS, lam=40.0)
    print("  fit time %.1f s, spine kind %s" % (time.time() - t0, spine.kind))
    results.append(check("|n . true plane normal|", abs(n @ rot[:, 2]), 1.0, 1e-3))
    results.append(check("spine radius", spine.radius, R, 2.0))
    results.append(check("billet depth (10 lams x 40)", ext["dHigh"] - ext["dLow"], 400.0, 1e-6))
    results.append(check("billet width", ext["wHigh"] - ext["wLow"], width, 0.5))
    results.append(check("centreline length", ext["sHigh"] - ext["sLow"], R * span, 3.0))
    radii = gm.offset_radii(spine, ext["sLow"], ext["sHigh"], [ext["dHigh"], ext["dLow"]])
    results.append(check("inner face radius", radii[0], R - depth / 2, 2.0))
    box = gm.min_width_box(np.vstack([spine.point(np.linspace(ext["sLow"], ext["sHigh"], 600), ext["dLow"]),
                                      spine.point(np.linspace(ext["sLow"], ext["sHigh"], 600), ext["dHigh"])]))
    rise = (R + depth / 2) - (R - depth / 2) * math.cos(span / 2)
    results.append(check("envelope across feed (rise + depth)", box["width"], rise, 2.0))

    print("2. Same arc + out-of-plane sag 300 (doubly curved)")
    sag = lambda s: 300.0 * np.sin(np.pi * s / (R * span))
    POINTS = swept_part(arc_spine(R), R * span, depth, width, sagFn=sag)
    n, spine, area, _, ext, _ = fit(POINTS, lam=40.0)
    # A tilted bending plane can beat the obvious arc plane here (found while testing), so the
    # check is only that the optimum is no worse than bending in the arc plane (n = z).
    volume = (ext["wHigh"] - ext["wLow"]) * area / 1e9
    o2, axes = gm.pca_axes(POINTS)
    u, v, nz = gm.plane_frame(np.array([0.0, 0.0, 1.0]), axes[0])
    P2z, Wz = gm.project_to_frame(POINTS, o2, u, v, nz)
    areaZ = gm.fit_arc_2d(gm.subset(P2z, 4000), 0.0)[1]
    print("  optimised n = %s, volume %.3f m3; bending in the arc plane %.3f m3"
          % (np.round(n, 3), volume, np.ptp(Wz) * areaZ / 1e9))
    results.append(check("optimised volume <= arc-plane volume", float(volume <= np.ptp(Wz) * areaZ / 1e9 + 1e-3), 1.0, 0))

    print("3. Variable curvature beam: k from 1/3000 to 1/12000 over 8 m, 300 deep")
    L = 8000.0
    POINTS = swept_part(clothoid_spine(1 / 3000.0, 1 / 12000.0, L), L, 300.0, 160.0, count=200)
    n, spine, area, arcArea, ext, P2 = fit(POINTS, lam=20.0, variable=True, ctrl=6)
    print("  arc billet area %.3f m2, variable billet area %.3f m2, saving %.0f%%"
          % (arcArea / 1e6, area / 1e6, 100 * (1 - area / arcArea)))
    results.append(check("variable area <= arc area", float(area <= arcArea), 1.0, 0))
    results.append(check("variable billet depth (ideal 300)", ext["dHigh"] - ext["dLow"], 300.0, 20.0))
    kappa = spine.curvature(np.array([0.05 * spine.length, 0.95 * spine.length]))
    print("  spine radius near ends: %.0f / %.0f (true 3000-ish / 12000-ish, ends move)" % tuple(1 / kappa))

    print("4. Straight beam (no in-plane curvature, sag out of plane only)")
    straight = lambda s: (np.column_stack([s, 0 * s]), np.column_stack([np.ones_like(s), 0 * s]))
    POINTS = swept_part(straight, 6000.0, 600.0, 200.0, sagFn=lambda s: 150 * np.sin(np.pi * s / 6000))
    n, spine, area, _, ext, _ = fit(POINTS, lam=40.0)
    radii = gm.offset_radii(spine, ext["sLow"], ext["sHigh"], [ext["dLow"], ext["dHigh"]])
    print("  spine kind %s, min face radius %.0f" % (spine.kind, radii.min()))
    # Best billet bends in the sag plane (XZ): 600 wide, R ~ L^2 / (8 x 150) = 30 m. A half-sine
    # is not a circle (about 7 mm off at the quarter points), so the arc billet needs ~207 mm,
    # rounded up to 6 x 40 = 240 mm: 0.6 x 0.24 x 6 = 0.864 m3.
    results.append(check("|n . y|  (bends in the sag plane)", abs(n[1]), 1.0, 1e-2))
    results.append(check("billet volume (m3)",
                         (ext["wHigh"] - ext["wLow"]) * (ext["dHigh"] - ext["dLow"]) *
                         (ext["sHigh"] - ext["sLow"]) / 1e9, 0.864, 0.01))

    print("5. Kx for t=19, Ri=4000: %.4f (1 - 2000 (19/4000)^2 = %.4f)"
          % (gm.curvature_factor_kx(19, 4000), 1 - 2000 * (19 / 4000) ** 2))

    print("\n%d / %d checks passed" % (sum(results), len(results)))


if __name__ == "__main__":
    main()
