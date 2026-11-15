# -*- coding: utf-8 -*-
"""The running tally in a fresh Rhino 7 instance: clean scene, the saddle, two lines accepted, the panel
captured after each Accept, then Start over. Own core on V4_PORT with a fresh record, solver only;
never 8742.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_v4.py _-Exit _No"
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-tally.log")
V4_PORT = 8747
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
                                              's.serve_forever()"' % (V4_PORT, os.path.join(OUT, "gnj-tally-record.jsonl")))
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

    # Two lines on the saddle, each accepted; the panel after each Accept shows the tally.
    vp = persp.ActiveViewport
    cam = vp.CameraLocation

    def sketch(uv):
        pts = []
        for i in range(30):
            x, y, z = core.saddle_point(*uv(i / 29.0))
            target = rg.Point3d(x, y, z)
            ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
            pts.append(rg.Line(cam, target).PointAt(k))
        return sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))

    strokes = [lambda f: (0.15 + 0.7 * f, 0.5), lambda f: (0.5, 0.2 + 0.6 * f)]
    for n, uv in enumerate(strokes, 1):
        panel.use_gesture(sketch(uv), vp)
        pump(lambda: ss.phase != "thinking", 40)
        say("MEMBER %d offer:" % n, ss.phase, "|", ss.headline(), "|", ss.waste_line())
        panel.on_accept(None, None)
        pump(lambda: False, 0.5)
        say("MEMBER %d accepted:" % n, ss.phase, "| line:", ss.waste_line(), "| tally", ss.tally)
        panel_png(panel, "gnj-rhino7-tally-%d.png" % n)
    shot("gnj-rhino7-tally-persp.png", scene.bbox)
    panel.toggle("record")
    panel_png(panel, "gnj-rhino7-tally-record-open.png")
    panel.on_start_over(None, None)
    import json
    after = json.loads(panel.session.client.opener.open(panel.session.client.base + "/tally", timeout=3).read().decode("utf-8"))
    say("START OVER: GET /tally ->", after, "| line now: '%s'" % ss.waste_line(), "| record entries", len(ss.record))
    panel.Close()
    say("TALLY SMOKE OK")
except Exception:
    say("TALLY SMOKE FAILED")
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
