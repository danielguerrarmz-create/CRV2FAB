# -*- coding: utf-8 -*-
"""Reading a drawn stroke (spec v9): its points in 3D, carried along the view onto a plane."""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403


# ---------------------------------------------------------------- strokes

def _curve_points(curve, samples=200):
    return [curve.PointAt(t) for t in curve.DivideByCount(samples, True)]


def onto_plane(p, viewport, plane):
    """A sketched point carried along the view ray onto `plane` (a _Sketch lies on the construction
    plane, not where it was meant). viewport None: the point as it is (a modelled curve, read in 3D)."""
    if viewport is None:
        return p
    if viewport.IsPerspectiveProjection:
        cam = viewport.CameraLocation
        line = rg.Line(cam, p)
    else:
        look = viewport.CameraDirection
        look.Unitize()
        line = rg.Line(p - look, p + look)
    ok, t = rg.Intersect.Intersection.LinePlane(line, plane)
    if not ok:
        return p
    return line.PointAt(t)


def camera_plane(viewport, through):
    """The plane through `through` facing the camera: where a path drawn in that view is meant."""
    if viewport.IsPerspectiveProjection:
        n = through - viewport.CameraLocation
    else:
        n = rg.Vector3d(viewport.CameraDirection)
    n.Unitize()
    return rg.Plane(through, n)


def stroke_points(curve, viewport, plane, samples=120):
    """The stroke as points on `plane` (doc units), or None when it is too short to be a stroke."""
    if curve is None or curve.GetLength() <= sc.doc.ModelAbsoluteTolerance * 10:
        return None
    return [onto_plane(p, viewport, plane) for p in _curve_points(curve, samples)]

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
