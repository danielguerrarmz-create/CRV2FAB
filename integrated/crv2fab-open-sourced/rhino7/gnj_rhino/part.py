# -*- coding: utf-8 -*-
"""Your own geometry (spec v6, kind part): which selected object can be checked, and how it is sent.

The designer's object is only read, never modified. It is meshed, and points are spread over the
mesh by area (a deterministic grid on each triangle), so a box and a fine NURBS solid both send a
few thousand evenly spread surface points; the volume is the solid's own. Both go in millimetres,
whatever the document's units.
"""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403

PART_TARGET_POINTS = 2000


def part_candidate(obj):
    """The object if it is one closed solid (Brep, extrusion or closed mesh) not on a GNJ layer."""
    if obj is None:
        return None
    layer = sc.doc.Layers[obj.Attributes.LayerIndex]
    if layer.FullPath == LAYER_ROOT or layer.FullPath.startswith(LAYER_ROOT + "::"):
        return None
    g = obj.Geometry
    if isinstance(g, rg.Extrusion):
        return obj if g.IsSolid else None
    if isinstance(g, rg.Brep):
        return obj if g.IsSolid else None
    if isinstance(g, rg.Mesh):
        return obj if g.IsClosed else None
    return None


def selected_part():
    """The one selected object that can be checked as a part, else None (none, or more than one)."""
    found = [o for o in sc.doc.Objects.GetSelectedObjects(False, False) if part_candidate(o) is not None]
    return found[0] if len(found) == 1 else None


def _mesh_and_volume(g):
    if isinstance(g, rg.Extrusion):
        g = g.ToBrep()
    if isinstance(g, rg.Brep):
        parts = rg.Mesh.CreateFromBrep(g, rg.MeshingParameters.QualityRenderMesh)
        mesh = rg.Mesh()
        for m in parts or []:
            mesh.Append(m)
        vp = rg.VolumeMassProperties.Compute(g)
        return mesh, (abs(vp.Volume) if vp is not None else None)   # a solid modelled inside out is still its size
    vp = rg.VolumeMassProperties.Compute(g)
    return g.DuplicateMesh(), (abs(vp.Volume) if vp is not None else None)


def sample_part(obj):
    """(points in mm, volume in mm3) for the core. Raises ValueError with a plain reason."""
    s = mm()
    mesh, volume = _mesh_and_volume(obj.Geometry)
    if mesh is None or mesh.Faces.Count == 0 or not volume or volume <= 0:
        raise ValueError("Rhino could not mesh this solid or measure its volume.")
    mesh = mesh.DuplicateMesh()
    mesh.Faces.ConvertQuadsToTriangles()
    tris = []
    total = 0.0
    for i in range(mesh.Faces.Count):
        f = mesh.Faces[i]
        a, b, c = (rg.Point3d(mesh.Vertices[k]) for k in (f.A, f.B, f.C))
        area = rg.Vector3d.CrossProduct(b - a, c - a).Length / 2.0
        if area > 0:
            tris.append((a, b, c, area))
            total += area
    if total <= 0:
        raise ValueError("This solid has no area to sample.")
    pts = []
    for a, b, c, area in tris:
        k = max(1, int(math.ceil(math.sqrt(PART_TARGET_POINTS * area / total))))
        for i in range(k):
            for j in range(k - i):
                u, v = (i + 1.0 / 3) / k, (j + 1.0 / 3) / k
                pts.append(a + (b - a) * u + (c - a) * v)
    if len(pts) > core.MAX_PART_POINTS:
        step = len(pts) / float(core.MAX_PART_POINTS)
        pts = [pts[int(i * step)] for i in range(core.MAX_PART_POINTS)]
    if len(pts) < core.MIN_PART_POINTS:
        raise ValueError("This solid gave too few points to check.")
    return [(p.X / s, p.Y / s, p.Z / s) for p in pts], volume / (s ** 3)


__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
