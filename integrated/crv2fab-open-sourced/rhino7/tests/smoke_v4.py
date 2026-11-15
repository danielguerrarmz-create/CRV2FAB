# -*- coding: utf-8 -*-
"""Spec v4 surface mode in a fresh Rhino 7 instance: clean scene, the saddle, one line drawn along
it in Perspective. Captures the panel (new sentence, waste line) and the viewport, then the viewport
with Why open (billet outline). Own core on V4_PORT, solver only; never 8742.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_v4.py _-Exit _No"
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-v4.log")
V4_PORT = 8746
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
            socket.create_connection(("127.0.0.1", V4_PORT), 0.3).close()
            return True
        except Exception:
            return False

    def panel_png(panel, fname):
        import clr
        clr.AddReference("PresentationCore")
        clr.AddReference("WindowsBase")
        import System.Windows
        from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
        from System.Windows.Media import PixelFormats
        pump(lambda: False, 0.8)
        el = panel.ControlObject.Content
        w, h = el.ActualWidth, el.ActualHeight
        rtb = RenderTargetBitmap(int(w * 2), int(h * 2), 192, 192, PixelFormats.Pbgra32)
        rtb.Render(el)
        enc = PngBitmapEncoder()
        enc.Frames.Add(BitmapFrame.Create(rtb))
        path = os.path.join(OUT, fname)
        fs = System.IO.File.Create(path)
        enc.Save(fs)
        fs.Close()
        el.Measure(System.Windows.Size(w, float("inf")))
        say("saved", path, "| %dx%d needs %d | FITS %s" % (w, h, el.DesiredSize.Height, abs(el.DesiredSize.Height - h) <= 2))

    def shot(fname, bbox):
        v = sc.doc.Views.Find("Perspective", False)
        v.ActiveViewport.ZoomBoundingBox(bbox)
        v.Redraw()
        path = os.path.join(OUT, fname)
        v.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(path)
        say("saved", path)

    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (V4_PORT, os.path.join(OUT, "gnj-v4-record.jsonl")))
    psi.WorkingDirectory = gn.CORE_DIR
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND"):
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 10)
    say("v4 core on", V4_PORT, "up:", port_open())

    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)  # empty document
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp     # the test sets the stage; the script itself never does
    scene = gn.choose_scene()           # nothing in the document: the saddle
    say("scene:", type(scene).__name__, "| objects", sc.doc.Objects.Count)
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % V4_PORT))
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    ss = panel.session

    # A line drawn along the saddle (v = 0.5, u 0.15 to 0.85), as sketched in Perspective: on the ground.
    vp = persp.ActiveViewport
    cam = vp.CameraLocation
    pts = []
    for i in range(30):
        x, y, z = core.saddle_point(0.15 + 0.7 * i / 29.0, 0.5)
        target = rg.Point3d(x, y, z)
        ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
        pts.append(rg.Line(cam, target).PointAt(k))
    sketch = sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))
    t0 = time.time()
    panel.use_gesture(sketch, vp)
    say("thinking shown:", ss.phase == "thinking", "|", ss.headline())
    pump(lambda: ss.phase != "thinking", 40)
    f = ss.result and ss.result["form"]
    say("V4 -> %.1fs" % (time.time() - t0), "| phase", ss.phase, "|", ss.headline(), "| waste line:", ss.waste_line())
    say("     layers", f and f["n_lamellas"], "strips", f and f["n_strips"], "| glue lines in ghost", len(panel.conduit.glue),
        "| billet", f and f["billet"] and dict((k, v) for k, v in f["billet"].items() if k != "outline"),
        "| outline polylines", f and f["billet"] and len(f["billet"]["outline"]), "| drawn now", len(panel.conduit.outline))
    say("     why:", ss.result and [x["text"] for x in ss.result["steps"]])
    say("     sketch left in document:", sc.doc.Objects.FindId(sketch) is not None)
    pump(lambda: False, 0.5)
    win = panel.ControlObject
    say("SIZE after result (no manual fit): ClientSize", panel.ClientSize, "| window ActualHeight", win.ActualHeight,
        "| SizeToContent", win.SizeToContent, "| Loaded", panel.Loaded)
    hist = Rhino.RhinoApp.CommandHistoryWindowText or ""
    say("command history GNJ lines:", [ln for ln in hist.splitlines() if "GNJ" in ln][-12:])
    panel_png(panel, "gnj-rhino7-v4-panel.png")
    shot("gnj-rhino7-v4-persp.png", scene.bbox)
    panel.toggle("why")
    say("Why open: outline polylines drawn", len(panel.conduit.outline))
    panel_png(panel, "gnj-rhino7-v4-panel-why.png")
    bb = panel.conduit.bbox
    bb.Inflate(300)
    shot("gnj-rhino7-v4-persp-why.png", bb)
    panel.toggle("why")
    say("Why closed: outline polylines drawn", len(panel.conduit.outline))
    panel.Close()
    say("V4 SMOKE OK")
except Exception:
    say("V4 SMOKE FAILED")
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
