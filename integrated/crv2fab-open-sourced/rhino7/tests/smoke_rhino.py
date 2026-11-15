# -*- coding: utf-8 -*-
"""Non-interactive smoke test INSIDE a fresh Rhino 7 instance. Never run it in a working session.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\gnj-rhino7\\tests\\smoke_rhino.py _-Exit _No"

Never touches port 8742 or the sample file: Daniel may be running the script with his own core.
It starts its own core (solver only, no API key) on SMOKE_PORT and stops it at the end, and reads
the three-timbers sample only through a copy in the scratch folder.
Writes a log and PNGs to GNJ_SMOKE_DIR (default C:\\Users\\danie\\scratch\\2026-11-14). The panel is
rendered from its own WPF content, never from the screen. Leaves the document flagged unmodified.
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
SMOKE_PORT = 8743
SMOKE_URL = "http://127.0.0.1:%d" % SMOKE_PORT
LOG = os.path.join(OUT, "gnj-rhino7-smoke.log")
log = open(LOG, "w")


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


def pump(cond, seconds):
    import Rhino
    end = time.time() + seconds
    while time.time() < end:
        Rhino.RhinoApp.Wait()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


child = None
try:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = r"C:\Users\danie\code\gnj-rhino7\tests"
    sys.path.insert(0, os.path.dirname(here))
    sys.path.insert(0, here)

    import math
    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import gnj_nudge as gn
    core = gn.core
    import test_surface_v3 as v3
    say("Rhino", Rhino.RhinoApp.Version, "| units", sc.doc.ModelUnitSystem)

    def shot(view_name, fname, bbox=None, size=(1200, 700)):
        v = sc.doc.Views.Find(view_name, False)
        if bbox is not None:
            v.ActiveViewport.ZoomBoundingBox(bbox)
        v.Redraw()
        path = os.path.join(OUT, fname)
        v.CaptureToBitmap(System.Drawing.Size(size[0], size[1])).Save(path)
        say("saved", path)

    def panel_png(panel, fname):
        import clr
        clr.AddReference("PresentationCore")
        clr.AddReference("WindowsBase")
        from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
        from System.Windows.Media import PixelFormats
        import System.Windows
        pump(lambda: False, 0.8)
        try:
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
            win = panel.ControlObject
            el.Measure(System.Windows.Size(w, float("inf")))
            need = el.DesiredSize.Height
            say("saved", path, "| content %dx%d, needs %d tall, window %dx%d | FITS %s" % (
                w, h, need, win.ActualWidth, win.ActualHeight, abs(need - h) <= 2))
        except Exception as ex:
            say("panel render failed:", ex)

    def on_gesture_layer():
        idx = sc.doc.Layers.FindByFullPath(gn.LAYER_GESTURE, -1)
        return len(sc.doc.Objects.FindByLayer(sc.doc.Layers[idx]) or []) if idx >= 0 else 0

    def open_panel(scene, client=None):
        p = gn.NudgePanel(scene, client=client or core.CoreClient(SMOKE_URL))
        p.Owner = Rhino.UI.RhinoEtoApp.MainWindow
        p.Show()
        p.fit()
        return p

    # ---- our own core on SMOKE_PORT (never 8742)
    import socket
    def smoke_port_open():
        try:
            socket.create_connection(("127.0.0.1", SMOKE_PORT), 0.3).close()
            return True
        except Exception:
            return False
    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (SMOKE_PORT, os.path.join(OUT, "gnj-smoke-record.jsonl")))
    psi.WorkingDirectory = gn.CORE_DIR
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    if psi.EnvironmentVariables.ContainsKey("ANTHROPIC_API_KEY"):
        psi.EnvironmentVariables.Remove("ANTHROPIC_API_KEY")
    child = System.Diagnostics.Process.Start(psi)
    t0 = time.time()
    while time.time() - t0 < 8 and not smoke_port_open():
        time.sleep(0.2)
    say("smoke core on port", SMOKE_PORT, "up:", smoke_port_open(), "| port 8742 untouched")

    # ---- what gnj_nudge.py does on the three-timbers sample (a scratch copy, never the original)
    import shutil
    copy = os.path.join(OUT, "gnj-three-timbers-copy.3dm")
    shutil.copyfile(os.path.join(os.path.dirname(here), "samples", "gnj-three-timbers.3dm"), copy)
    f3 = Rhino.FileIO.File3dm.Read(copy)
    for o in f3.Objects:
        lay = f3.AllLayers.FindIndex(o.Attributes.LayerIndex)
        a = Rhino.DocObjects.ObjectAttributes()
        a.Name, a.LayerIndex = o.Attributes.Name, gn.ensure_layer(lay.FullPath, gn.EXISTING_COLOR)
        sc.doc.Objects.AddBrep(o.Geometry, a)
    before = sc.doc.Objects.Count
    scene0 = gn.choose_scene()
    ref = sc.doc.Layers.FindByFullPath(gn.LAYER_REFERENCE, -1)
    say("SAMPLE scene chosen:", type(scene0).__name__, "| objects before", before, "after", sc.doc.Objects.Count,
        "| saddle added:", ref >= 0 and bool(sc.doc.Objects.FindByLayer(sc.doc.Layers[ref])),
        "| member length mm %.0f" % (scene0.frame.length / scene0.frame.s) if hasattr(scene0, "frame") else "")
    import rhinoscriptsyntax as rs
    rs.DeleteObjects(rs.AllObjects())

    # ---- v2 bend: panel states
    frame = gn.setup()
    bend = gn.BendScene(frame)
    s = frame.s
    sag = core.sag_of(2450.0)
    mid = frame.origin + frame.axis * (frame.length / 2)
    end = frame.origin + frame.axis * frame.length
    vp = lambda name: sc.doc.Views.Find(name, False).ActiveViewport

    panel = open_panel(bend)
    ss = panel.session
    panel_png(panel, "gnj-rhino7-smoke-panel-rest.png")
    tilted = rg.ArcCurve(rg.Arc(frame.origin + frame.up * (5 * s),
                                mid + (frame.up * math.cos(math.radians(20)) + frame.width * math.sin(math.radians(20))) * (sag * s),
                                end + frame.up * (5 * s)))
    tilted_id = sc.doc.Objects.AddCurve(tilted)
    panel.use_gesture(tilted_id)     # a selected curve, 20 degrees off up: snaps to up
    pump(lambda: ss.phase != "thinking", 40)
    say("SKETCH selected curve kept (designer's own):", sc.doc.Objects.FindId(tilted_id) is not None,
        "| read lines on GNJ::Gesture:", on_gesture_layer())
    f = ss.result and ss.result["form"]
    say("BEND 20 deg -> phase", ss.phase, "| a", f and f["bend_angle_deg"], "layers", f and f["n_lamellas"],
        "strips", f and f["n_strips"], "|", ss.source_line(), "|", ss.headline())
    say("     why[0]:", ss.result and ss.result["steps"][0]["text"])
    panel_png(panel, "gnj-rhino7-smoke-panel-proposed.png")
    shot("Perspective", "gnj-rhino7-smoke-v2-persp.png", panel.conduit.bbox)
    panel.on_reject(None, None)
    say("after reject: phase", ss.phase, "| conduit", panel.conduit.Enabled)
    panel_png(panel, "gnj-rhino7-smoke-panel-rejected.png")
    panel.hold("solid")
    pump(lambda: ss.phase != "thinking", 40)
    panel.hold("shape")
    pump(lambda: ss.phase != "thinking", 40)
    say("solid + shape: phase", ss.phase, "|", ss.headline())
    panel.toggle("why")
    panel_png(panel, "gnj-rhino7-smoke-panel-conflict.png")
    panel.Close()

    # ---- v3 surface, in a cleared document (this smoke's own fresh instance)
    import rhinoscriptsyntax as rs
    rs.DeleteObjects(rs.AllObjects())
    scene = gn.setup_surface()
    srf = scene.srf
    say("saddle on", gn.LAYER_REFERENCE, "| bbox", scene.bbox.Min, scene.bbox.Max,
        "| grid corner and centre", scene.grid["points"][0], scene.grid["points"][220])
    worst = 0.0
    for i in range(21):
        for j in range(21):
            want = core.saddle_point(i / 20.0, j / 20.0)
            got = scene.grid["points"][i * 21 + j]
            worst = max(worst, max(abs(a - b) for a, b in zip(want, got)))
    say("saddle NURBS vs formula, worst grid error mm: %.6f" % worst)

    # A sketch lies on the ground (z = 0). Make one that, seen from each view, covers v = 0.5, u 0.15..0.85.
    def ground_sketch(viewport, uv=lambda f: (0.15 + 0.7 * f, 0.5)):
        pts = []
        for i in range(30):
            x, y, z = core.saddle_point(*uv(i / 29.0))
            target = rg.Point3d(x * s, y * s, z * s)
            if viewport.IsPerspectiveProjection:
                cam = viewport.CameraLocation
                ray = rg.Line(cam, target)
            else:
                ray = rg.Line(target, target + viewport.CameraDirection)
            ok, t = rg.Intersect.Intersection.LinePlane(ray, rg.Plane.WorldXY)
            pts.append(ray.PointAt(t))
        return rg.Curve.CreateInterpolatedCurve(pts, 3)

    class Probe(object):
        def stroke_on_surface(self, intent):
            self.intent = intent
            return True

    for view in ("Top", "Perspective"):
        probe = Probe()
        needed, note, on_srf = scene.gesture(probe, ground_sketch(vp(view)), vp(view))
        st = probe.intent["stroke_uv"] if needed else []
        say("READ", view, "sketch on ground -> points", len(st), "| first", st and st[0], "last", st and st[-1],
            "| v range %.4f..%.4f" % (min(q[1] for q in st), max(q[1] for q in st)) if st else note)

    # The swept member on the saddle, through the real panel, with a canned core answer.
    canned = v3.CannedCore(v3.saddle_member_body(3, 2))
    panel = open_panel(scene, client=canned)
    ss = panel.session
    panel_png(panel, "gnj-rhino7-smoke-v3-panel-rest.png")
    sketch_id = sc.doc.Objects.AddCurve(ground_sketch(vp("Perspective")))
    panel.use_gesture(sketch_id, vp("Perspective"))
    pump(lambda: ss.phase != "thinking", 40)
    say("SKETCH raw sketch deleted:", sc.doc.Objects.FindId(sketch_id) is None,
        "| read lines on GNJ::Gesture:", on_gesture_layer(), "| curves on ground left:",
        len([o for o in sc.doc.Objects if isinstance(o.Geometry, rg.Curve) and o.Geometry.GetBoundingBox(True).Max.Z < 1e-6]))
    say("V3 canned -> phase", ss.phase, "|", ss.headline(), "| conduit", panel.conduit.Enabled,
        "glue", len(panel.conduit.glue), "dashes", len(panel.conduit.dashes),
        "| sketch replaced on surface:", sc.doc.Objects.FindId(sketch_id) is None)
    brep = panel.conduit.brep
    say("     ghost brep valid", brep.IsValid, "solid", brep.IsSolid, "faces", brep.Faces.Count)
    panel_png(panel, "gnj-rhino7-smoke-v3-panel-proposed.png")
    shot("Perspective", "gnj-rhino7-smoke-v3-saddle-persp.png", scene.bbox)
    close = rg.BoundingBox(brep.GetBoundingBox(True).Min, brep.GetBoundingBox(True).Max)
    close.Inflate(200 * s)
    shot("Perspective", "gnj-rhino7-smoke-v3-member-close.png", close)
    panel.on_accept(None, None)
    say("SKETCH after accept, read lines on GNJ::Gesture:", on_gesture_layer())
    layer = sc.doc.Layers[sc.doc.Layers.FindByFullPath(gn.LAYER_BUILDABLE, -1)]
    baked = [o for o in (sc.doc.Objects.FindByLayer(layer) or []) if isinstance(o.Geometry, rg.Brep)]
    last = baked[-1].Geometry if baked else None
    say("after accept: phase", ss.phase, "| baked breps on Buildable", len(baked),
        "| last valid", last and last.IsValid, "solid", last and last.IsSolid, "| record", ss.record[0]["text"])
    panel.Close()

    # The real core on a surface stroke: the diagonal u = v (a reference case), on a clear saddle.
    rs.DeleteObjects([o.Id for o in sc.doc.Objects.FindByLayer(layer) or []])
    panel = open_panel(scene)
    ss = panel.session
    diag = ground_sketch(vp("Top"), lambda f: (0.2 + 0.6 * f, 0.2 + 0.6 * f))
    panel.use_gesture(sc.doc.Objects.AddCurve(diag), vp("Top"))
    pump(lambda: ss.phase != "thinking", 40)
    f = ss.result and ss.result["form"]
    say("V3 real core -> phase", ss.phase, "|", ss.headline(), "| last error:", ss.client.last_error,
        "| layers", f and f["n_lamellas"], "strips", f and f["n_strips"], "stations", f and len(f["stations"]),
        "| dev", ss.result and ss.result["deviation_mm"], "|", ss.source_line())
    say("     why:", ss.result and [x["text"] for x in ss.result["steps"]])
    panel_png(panel, "gnj-rhino7-smoke-v3-panel-real-core.png")
    if ss.can_judge():
        shot("Perspective", "gnj-rhino7-smoke-v3-real-core-persp.png", scene.bbox)
        panel.on_reject(None, None)
        panel_png(panel, "gnj-rhino7-smoke-v3-panel-rejected.png")
        panel.hold("shape")
        pump(lambda: ss.phase != "thinking", 40)
        say("     after reject + hold shape:", ss.phase, "|", ss.headline())
    say("SKETCH before close, read lines on GNJ::Gesture:", on_gesture_layer())
    panel.Close()
    say("after close: conduit", panel.conduit.Enabled, "| sticky clean", gn.STICKY_KEY not in sc.sticky,
        "| read lines on GNJ::Gesture:", on_gesture_layer())
    say("SMOKE OK")
except Exception:
    say("SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        gn.stop_core_child(child)
        say("smoke core stopped")
    except Exception as ex:
        say("child stop failed:", ex)
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
