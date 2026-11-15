# -*- coding: utf-8 -*-
"""Build samples/gnj-three-timbers.3dm: three 38 x 89 mm timbers, 2400 mm centreline each.

Run ONLY in a fresh Rhino 7 instance (it changes the open document's units):
  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\gnj-rhino7\\samples\\make_three_timbers.py _-Exit _No"

1 Straight       box along X on GNJ::Existing, exactly where gnj_nudge.py puts its 2x4, so it adopts it.
2 Single curved  the section swept along a planar arc, radius 4000 mm, bending up in XZ, no twist.
3 Doubly curved  the section swept along a gently bowed line on the spec's saddle
                 z = 800 + (x^2 - y^2) / 6000, 38 mm along the surface normal (so it twists), 89 mm in it.

Saves in Rhino 7 format to the one path below, reads the file back and logs what is in it.
"""
import math
import os
import sys
import traceback

try:
    SAMPLES = os.path.dirname(os.path.abspath(__file__))
except NameError:   # run from Rhino's script editor: the current folder
    SAMPLES = os.getcwd()
OUT_3DM = os.path.join(SAMPLES, "gnj-three-timbers.3dm")
OUT_PNG = os.path.join(SAMPLES, "gnj-three-timbers.png")
LOG = os.path.join(SAMPLES, "gnj-three-timbers.log")
log = open(LOG, "w")


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


try:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = SAMPLES
    sys.path.insert(0, os.path.dirname(here))

    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import gnj_nudge as gn
    core = gn.core

    doc = sc.doc
    doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)  # empty document: no scaling
    doc.ModelAbsoluteTolerance = 0.01
    tol = doc.ModelAbsoluteTolerance
    T, W, L, Z0, R1 = core.STOCK_MM, core.WIDTH_MM, core.LENGTH_MM, gn.LIFT_MM, 4000.0

    gn.ensure_layer(gn.LAYER_ROOT)
    existing = gn.ensure_layer(gn.LAYER_EXISTING, gn.EXISTING_COLOR)
    samples = gn.ensure_layer("GNJ::Samples", gn.EXISTING_COLOR)

    def add(brep, name, layer):
        if brep.SolidOrientation == rg.BrepSolidOrientation.Inward:
            brep.Flip()
        a = Rhino.DocObjects.ObjectAttributes()
        a.Name, a.LayerIndex = name, layer
        return doc.Objects.AddBrep(brep, a)

    # 1 Straight: the same box gnj_nudge.setup() would create.
    box = rg.Box(rg.Plane.WorldXY, rg.Interval(0, L), rg.Interval(-W / 2, W / 2), rg.Interval(Z0 - T / 2, Z0 + T / 2))
    add(box.ToBrep(), "Straight", existing)

    # 2 Single curved: annular sector in XZ (radius 4000 at the centreline, arc length 2400), extruded 89 in Y.
    y1 = 700.0
    half = L / (2 * R1)                       # half angle, 0.3 rad
    chord = 2 * R1 * math.sin(half)
    sag = R1 * (1 - math.cos(half))
    centre = rg.Point3d(chord / 2, y1 - W / 2, Z0 + sag - R1)
    plane = rg.Plane(centre, rg.Vector3d.XAxis, rg.Vector3d.ZAxis)
    span = rg.Interval(math.pi / 2 - half, math.pi / 2 + half)
    outer = rg.ArcCurve(rg.Arc(rg.Circle(plane, R1 + T / 2), span))
    inner = rg.ArcCurve(rg.Arc(rg.Circle(plane, R1 - T / 2), span))
    ends = [rg.LineCurve(outer.PointAtStart, inner.PointAtStart), rg.LineCurve(outer.PointAtEnd, inner.PointAtEnd)]
    profile = rg.Curve.JoinCurves([outer, inner] + ends, tol)[0]
    arc_brep = rg.Surface.CreateExtrusion(profile, rg.Vector3d(0, W, 0)).ToBrep().CapPlanarHoles(tol)
    add(arc_brep, "Single curved", samples)

    # 3 Doubly curved: a bowed line on the saddle, scaled until its 3D length is 2400.
    def saddle(x, y):
        return Z0 + (x * x - y * y) / core.SADDLE_K

    def path(k, n):
        out = []
        for i in range(n):
            t = i / (n - 1.0)
            x = k * (-1000 + 2000 * t)
            y = k * (-600 + 1200 * t) + 150 * math.sin(math.pi * t)  # the gentle sideways curve
            out.append((x, y, saddle(x, y)))
        return out

    def length(pts):
        return sum(math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q))) for p, q in zip(pts, pts[1:]))

    lo, hi = 0.5, 1.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if length(path(mid, 2001)) < L:
            lo = mid
        else:
            hi = mid
    stations = path(lo, 65)
    normals = []
    for x, y, z in stations:
        nx, ny, nz = -2 * x / core.SADDLE_K, 2 * y / core.SADDLE_K, 1.0
        n = math.sqrt(nx * nx + ny * ny + nz * nz)
        normals.append((nx / n, ny / n, nz / n))
    form = {"stations": stations, "normals": normals, "intent_stations": stations, "n_lamellas": 1, "n_strips": 1}
    brep3, _, _ = gn.surface_member_geometry(form, 1.0)
    bb = brep3.GetBoundingBox(True)
    gap = 600.0
    shift = rg.Vector3d(L / 2 - bb.Center.X, (y1 + W / 2 + gap) - bb.Min.Y, 0)
    brep3.Translate(shift)
    add(brep3, "Doubly curved", samples)
    say("doubly curved: path scale %.4f, 3D centreline length %.1f mm, moved by %s" % (lo, length(path(lo, 2001)), shift))

    # Tidy what the template left: its empty "Layer 01" to "Layer 05", and a grid sized in feet.
    for i in range(doc.Layers.Count - 1, -1, -1):
        lay = doc.Layers[i]
        if lay.Name.startswith("Layer 0") and not doc.Objects.FindByLayer(lay):
            doc.Layers.Delete(i, True)
    for v in doc.Views:
        cp = v.ActiveViewport.GetConstructionPlane()
        cp.GridSpacing, cp.GridLineCount, cp.ThickLineFrequency = 100.0, 30, 10
        v.ActiveViewport.SetConstructionPlane(cp)

    # Render meshes now, so the saved view and the capture show shaded solids, not unmeshed wires.
    mp = Rhino.Geometry.MeshingParameters.Default
    for o in doc.Objects:
        o.CreateMeshes(Rhino.Geometry.MeshType.Render, mp, False)

    # Saved view: shaded perspective, maximised, zoomed to all three.
    persp = doc.Views.Find("Perspective", False)
    shaded = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    persp.ActiveViewport.DisplayMode = shaded
    persp.Maximized = True
    doc.Views.ActiveView = persp
    persp.ActiveViewport.ZoomExtents()
    for _ in range(20):
        Rhino.RhinoApp.Wait()
    persp.Redraw()
    persp.CaptureToBitmap(System.Drawing.Size(1400, 800)).Save(OUT_PNG)
    say("saved", OUT_PNG)

    opts = Rhino.FileIO.FileWriteOptions()
    opts.FileVersion = 7
    ok = doc.WriteFile(OUT_3DM, opts)
    say("wrote", OUT_3DM, ok)

    # Read the file back.
    f = Rhino.FileIO.File3dm.Read(OUT_3DM)
    say("READBACK archive version", Rhino.FileIO.File3dm.ReadArchiveVersion(OUT_3DM),
        "| units", f.Settings.ModelUnitSystem, "| objects", f.Objects.Count)
    for o in f.Objects:
        g = o.Geometry
        lay = f.AllLayers.FindIndex(o.Attributes.LayerIndex)
        b = g.GetBoundingBox(True)
        say("  %-14s layer %-15s %s valid %s closed %s volume %.0f mm3 | bbox (%.0f, %.0f, %.0f) to (%.0f, %.0f, %.0f)" % (
            o.Attributes.Name, lay.FullPath, type(g).__name__, g.IsValid, g.IsSolid,
            g.GetVolume() if g.IsSolid else 0, b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z))
    say("  expected volume each %.0f mm3 (38 x 89 x 2400)" % (T * W * L))
    say("  layers in file:", [l.FullPath for l in f.AllLayers])

    # Does gnj_nudge.py adopt the straight one? (live document only; the file is already written)
    choose_bend = gn.has_bend_member()
    frame = gn.setup()
    n_existing = len(doc.Objects.FindByLayer(doc.Layers[doc.Layers.FindByFullPath(gn.LAYER_EXISTING, -1)]))
    say("ADOPT: has_bend_member", choose_bend, "| objects on GNJ::Existing after setup()", n_existing,
        "| member length mm %.1f, axis origin %s" % (frame.length / frame.s, frame.origin))
    say("DONE")
except Exception:
    say("FAILED")
    say(traceback.format_exc())
finally:
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
