# -*- coding: utf-8 -*-
"""The script must leave the designer free to orbit. Non-interactive, fresh Rhino 7 instance only.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_views.py _-Exit _No"

As Daniel has it: the three-timbers sample (objects copied from a scratch copy into a millimetre
document) with Perspective maximized and active. Runs the script's own start-up path, then checks the
active view, its maximized state and projection are unchanged, and that a bend sketched in
Perspective returns a ghost. Own core on VIEWS_PORT, solver only; never 8742, never the original file.
"""
import math
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-views.log")
VIEWS_PORT = 8745
log = open(LOG, "w")


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


child = None
try:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = r"C:\Users\danie\code\gnj-rhino7\tests"
    sys.path.insert(0, os.path.dirname(here))
    import shutil
    import socket
    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import gnj_nudge as gn
    core = gn.core

    def pump(cond, seconds):
        end = time.time() + seconds
        while time.time() < end:
            Rhino.RhinoApp.Wait()
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def port_open():
        try:
            socket.create_connection(("127.0.0.1", VIEWS_PORT), 0.3).close()
            return True
        except Exception:
            return False

    copy = os.path.join(OUT, "gnj-views-copy.3dm")
    shutil.copyfile(os.path.join(os.path.dirname(here), "samples", "gnj-three-timbers.3dm"), copy)
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    f3 = Rhino.FileIO.File3dm.Read(copy)
    for o in f3.Objects:
        lay = f3.AllLayers.FindIndex(o.Attributes.LayerIndex)
        a = Rhino.DocObjects.ObjectAttributes()
        a.Name, a.LayerIndex = o.Attributes.Name, gn.ensure_layer(lay.FullPath, gn.EXISTING_COLOR)
        sc.doc.Objects.AddBrep(o.Geometry, a)
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp       # as the sample was saved: Perspective, maximized
    persp.Maximized = True
    persp.ActiveViewport.ZoomExtents()

    def view_state():
        v = sc.doc.Views.ActiveView
        return (v.ActiveViewport.Name, v.Maximized, v.ActiveViewport.IsPerspectiveProjection)

    before = view_state()
    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (VIEWS_PORT, os.path.join(OUT, "gnj-views-record.jsonl")))
    psi.WorkingDirectory = gn.CORE_DIR
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    if psi.EnvironmentVariables.ContainsKey("ANTHROPIC_API_KEY"):
        psi.EnvironmentVariables.Remove("ANTHROPIC_API_KEY")
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 8)

    scene = gn.choose_scene()           # the same start-up path main() takes
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % VIEWS_PORT))
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    pump(lambda: False, 0.5)
    after = view_state()
    say("VIEW before (name, maximized, perspective):", before, "| after start-up:", after, "| UNCHANGED", before == after)

    # A bend sketched in Perspective: the designer draws "up" over the timber; the sketch lands on the
    # ground plane along the camera rays. Read through the line-of-sight rule, then the snap.
    vp = persp.ActiveViewport
    frame = scene.frame
    s = frame.s
    look = vp.CameraDirection
    look.Unitize()
    ny, nz = look * frame.width, look * frame.up
    tilt = math.degrees(math.atan2(abs(nz), abs(ny)))
    say("Perspective camera: the plane through the timber facing the camera leans %.1f deg from vertical" % (90 - tilt))
    sag = core.sag_of(2450.0)
    cam = vp.CameraLocation
    pts = []
    for i in range(40):
        t = i / 39.0
        x = frame.length * t
        z = 4 * sag * t * (1 - t)  # an upward bow drawn over the timber
        target = frame.origin + frame.axis * x + frame.up * (z * s)
        ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
        pts.append(rg.Line(cam, target).PointAt(k))
    sketch = sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))
    ss = panel.session
    panel.use_gesture(sketch, vp)
    pump(lambda: ss.phase != "thinking", 40)
    f = ss.result and ss.result["form"]
    say("PERSPECTIVE sketch -> phase", ss.phase, "| read angle %.0f snapped %s" % (ss.angle, ss.snapped),
        "| layers", f and f["n_lamellas"], "strips", f and f["n_strips"], "| conduit", panel.conduit.Enabled,
        "|", ss.headline())
    say("     why[0]:", ss.result and ss.result["steps"][0]["text"])
    say("VIEW after the gesture:", view_state(), "| UNCHANGED", view_state() == before)
    persp.Redraw()
    png = os.path.join(OUT, "gnj-rhino7-views-persp.png")
    persp.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(png)
    say("saved", png)
    panel.Close()
    say("VIEWS SMOKE OK")
except Exception:
    say("VIEWS SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        if child is not None and not child.HasExited:
            child.Kill()
            child.WaitForExit(2000)
    except Exception as ex:
        say("could not stop the core:", ex)
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
