# -*- coding: utf-8 -*-
"""The ghost's geometry: a plate (spec v9), a member on a surface, the sample saddle."""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403
from gnj_rhino.gesture import *  # noqa: F401,F403


# ---------------------------------------------------------------- ghost geometry

def _unit3(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return [v[0] / n, v[1] / n, v[2] / n]


def plate_geometry(form, to_scene, inflate_mm=0.0):
    """Spec v9 plate_member -> one closed brep: the mid-surface grid thickened by thickness_mm along
    its normals (half each side), core mm, carried into the model by to_scene(point_mm) -> Point3d.
    Top and bottom are NURBS surfaces on the grid; the four sides are ruled between their matching
    edges, so they join exactly. inflate_mm (display only) grows every side, so the ghost does not
    flicker against the grey member it lies on."""
    G, Nm = form["grid"], form["normals"]
    rows, cols = len(G), len(G[0])
    h = form["thickness_mm"] / 2.0 + inflate_mm

    def at(i, j, k):
        p, n = G[i][j], Nm[i][j]
        q = [p[c] + k * h * n[c] for c in range(3)]
        if inflate_mm and j in (0, cols - 1):
            inner = G[i][1 if j == 0 else cols - 2]
            out = _unit3([p[c] - inner[c] for c in range(3)])
            q = [q[c] + inflate_mm * out[c] for c in range(3)]
        return to_scene(q)

    tol = sc.doc.ModelAbsoluteTolerance
    faces = []
    for k in (1, -1):
        pts = [at(i, j, k) for i in range(rows) for j in range(cols)]
        faces.append(rg.NurbsSurface.CreateFromPoints(pts, rows, cols, 3, 3))
    top, bottom = faces
    parts = [rg.Brep.CreateFromSurface(top), rg.Brep.CreateFromSurface(bottom)]
    du, dv = top.Domain(0), top.Domain(1)
    for direction, c in ((0, dv.Min), (0, dv.Max), (1, du.Min), (1, du.Max)):
        side = rg.NurbsSurface.CreateRuledSurface(top.IsoCurve(direction, c), bottom.IsoCurve(direction, c))
        if side is not None:
            parts.append(rg.Brep.CreateFromSurface(side))
    joined = rg.Brep.JoinBreps(parts, tol) or []
    if len(joined) == 1 and joined[0].IsSolid:
        brep = joined[0]
        if brep.SolidOrientation == rg.BrepSolidOrientation.Inward:
            brep.Flip()
        return brep
    raise ValueError("could not close the plate solid (%d pieces)" % len(joined))


def grid_outline(grid, to_scene):
    """The boundary of a grid (rows along the path, columns across), as one closed polyline."""
    rows, cols = len(grid), len(grid[0])
    ring = [grid[0][j] for j in range(cols)] + [grid[i][cols - 1] for i in range(1, rows)]
    ring += [grid[rows - 1][j] for j in range(cols - 2, -1, -1)] + [grid[i][0] for i in range(rows - 2, -1, -1)]
    return [to_scene(p) for p in ring]


def billet_brep(loops, to_scene):
    """A billet as the core sent it: two closed outlines (one per width face) -> the closed solid
    between them, the outlines lofted straight and the two faces capped. The core rounds outline points
    to 0.1 mm, so each loop is first laid on its own best-fit plane: capping needs it planar to the
    document's tolerance (often 0.001 mm)."""
    tol = sc.doc.ModelAbsoluteTolerance
    curves = []
    for loop in loops:
        pts = [to_scene(p) for p in loop]
        fit, plane = rg.Plane.FitPlaneToPoints(pts)
        if fit != rg.PlaneFitResult.Failure:
            pts = [plane.ClosestPoint(p) for p in pts]
        # Each side between corners as one smooth curve (an interpolation through coplanar points
        # stays in their plane), so the box has a face per side, not one per sample.
        sides = []
        for run in core.loop_runs(loop):
            run_pts = [pts[i] for i in run]
            sides.append(rg.LineCurve(run_pts[0], run_pts[-1]) if len(run_pts) == 2
                         else rg.Curve.CreateInterpolatedCurve(run_pts, 3))
        joined = rg.Curve.JoinCurves(sides, tol) if sides else []
        curves.append(joined[0] if len(joined) == 1 and joined[0].IsClosed else rg.PolylineCurve(pts))
    lofted = rg.Brep.CreateFromLoft(curves, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Straight, False)
    if not lofted:
        raise ValueError("could not loft the billet outlines")
    brep = lofted[0].CapPlanarHoles(tol)
    if brep is None or not brep.IsSolid:
        raise ValueError("could not close the billet")
    if brep.SolidOrientation == rg.BrepSolidOrientation.Inward:
        brep.Flip()
    return brep


def dashed(points, on, off):
    """A polyline cut into dashes of length `on` with gaps `off`, measured along it (document units).
    A display pattern restarts on every short segment and never shows a gap; these do."""
    out, draw, left = [], True, on
    for a, b in zip(points, points[1:]):
        seg = b - a
        length = seg.Length
        t = 0.0
        while length > 0 and t < length:
            step = min(left, length - t)
            p0, p1 = a + seg * (t / length), a + seg * ((t + step) / length)
            if draw:
                if out and out[-1].To.DistanceTo(p0) < 1e-9:
                    out[-1] = rg.Line(out[-1].From, p1)
                else:
                    out.append(rg.Line(p0, p1))
            t += step
            left -= step
            if left <= 1e-12:
                draw = not draw
                left = on if draw else off
    return out


def surface_of(obj):
    """An untrimmed surface, or the underlying surface of a single-face brep. None otherwise."""
    g = obj.Geometry if hasattr(obj, "Geometry") else obj
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Brep):
        if g.Faces.Count != 1:
            return None
        return g.Faces[0].UnderlyingSurface()
    if isinstance(g, rg.Surface):
        return g
    return None


def saddle_surface():
    """The spec's sample, exactly: z = 800 + (x^2 - y^2) / 6000 is biquadratic, so one degree 2
    Bezier patch carries it with no error. u runs along x, v along y, domain [0, 1]."""
    s = mm()
    h, z0, k = core.SADDLE_HALF_MM, core.SADDLE_Z0_MM, core.SADDLE_K
    srf = rg.NurbsSurface.Create(3, False, 3, 3, 3, 3)
    for i, knot in enumerate((0.0, 0.0, 1.0, 1.0)):
        srf.KnotsU[i] = knot
        srf.KnotsV[i] = knot
    xs = (-h, 0.0, h)
    sq = (h * h, -h * h, h * h)  # Bezier control values of x^2 over [-h, h]
    for i in range(3):
        for j in range(3):
            srf.Points.SetPoint(i, j, rg.Point3d(xs[i] * s, xs[j] * s, (z0 + (sq[i] - sq[j]) / k) * s))
    return srf


def surface_member_geometry(form, s, inflate_mm=0.0, glue_inflate_mm=0.0):
    """Sweep the 89 x 38 section along the stations: 38 mm along the surface normal (the member
    sits on the surface), 89 mm in the surface. Four ruled faces between corner curves that share
    one parametrisation (uniform knots, one parameter per station), two planar end caps."""
    tol = sc.doc.ModelAbsoluteTolerance
    P = [rg.Point3d(x * s, y * s, z * s) for x, y, z in form["stations"]]
    Ns = [rg.Vector3d(x, y, z) for x, y, z in form["normals"]]
    count = len(P)
    frames = []
    for i in range(count):
        tng = P[min(i + 1, count - 1)] - P[max(i - 1, 0)]
        tng.Unitize()
        nrm = Ns[i]
        nrm.Unitize()
        side = rg.Vector3d.CrossProduct(nrm, tng)
        side.Unitize()
        nrm = rg.Vector3d.CrossProduct(tng, side)  # re-square the normal to the path
        nrm.Unitize()
        frames.append((side, nrm))

    def rail(y, z):
        pts = [P[i] + frames[i][0] * (y * s) + frames[i][1] * (z * s) for i in range(count)]
        return rg.Curve.CreateInterpolatedCurve(pts, 3, rg.CurveKnotStyle.Uniform)

    W, T, g = core.WIDTH_MM, core.STOCK_MM, inflate_mm
    # Centred on the surface, as the core models it (38 mm along the normal, 19 mm each side): the
    # billet the core fits, and its outline, belong to exactly this member. For display only, the
    # section grows by g on every side.
    lift = -T / 2
    corners = [(-W / 2 - g, lift - g), (W / 2 + g, lift - g), (W / 2 + g, lift + T + g), (-W / 2 - g, lift + T + g)]
    rails = [rail(y, z) for y, z in corners]
    parts = []
    for i in range(4):
        ruled = rg.NurbsSurface.CreateRuledSurface(rails[i], rails[(i + 1) % 4])
        parts.append(rg.Brep.CreateFromSurface(ruled))
    for end in (0, count - 1):
        cap = rg.Polyline([rails[i].PointAtStart if end == 0 else rails[i].PointAtEnd for i in range(4)] +
                          [rails[0].PointAtStart if end == 0 else rails[0].PointAtEnd]).ToNurbsCurve()
        parts.extend(rg.Brep.CreatePlanarBreps(cap, tol) or [])
    joined = rg.Brep.JoinBreps(parts, tol)
    if not joined or len(joined) != 1 or not joined[0].IsSolid:
        raise ValueError("could not close the member solid")
    brep = joined[0]
    if brep.SolidOrientation == rg.BrepSolidOrientation.Inward:
        brep.Flip()

    glue = []
    n, k = form["n_lamellas"], form["n_strips"]
    gw, gb, gt = W / 2 + glue_inflate_mm, lift - glue_inflate_mm, lift + T + glue_inflate_mm
    for i in range(1, n):          # layer lines, on the 38 mm faces
        z = lift + i * T / n
        glue.extend([rail(-gw, z), rail(gw, z)])
    for j in range(1, k):          # strip lines, on the 89 mm faces
        y = -W / 2 + j * W / k
        glue.extend([rail(y, gb), rail(y, gt)])

    dashes = []
    ip = [rg.Point3d(x * s, y * s, z * s) for x, y, z in form["intent_stations"]]
    if len(ip) == count:  # lift the dashed intent 2 mm off the surface so it reads
        ip = [ip[i] + frames[i][1] * (2.0 * s) for i in range(count)]
    for i in range(0, len(ip) - 1, 2):
        dashes.append(rg.Line(ip[i], ip[i + 1]))
    return brep, glue, dashes

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
