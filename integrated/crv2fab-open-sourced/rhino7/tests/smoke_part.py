# -*- coding: utf-8 -*-
"""Accepted colour and your own geometry (spec v6 part), in a fresh Rhino 7 test instance.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash /scheme=GNJSmoke
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_part.py _-Exit _No"

1. A GNJ::Buildable layer left blue by an earlier version is recoloured to timber; an accepted member
   is tan beside a new blue ghost.
2. A doubly curved, twisting solid (5.05 m, 120 x 200, on a non-GNJ layer) selected: the card offers
   "Check the selected part"; the plan comes back in pieces, cut lines drawn across it; the System
   panel shows the per-piece numbers (Record collapsed); Accept bakes nothing and leaves the solid
   as it was. Own core from the part branch's export on PART_PORT; never 8742.
"""
import math
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-part.log")
PART_PORT = 8751
CORE_PART = os.environ.get("GNJ_CORE_PART", r"C:\Users\danie\scratch\2026-11-14\gnj-core-part-d3781d3")
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
    os.environ["GNJ_DOCK"] = "0"   # the System panel in a plain window here, sized for the capture
    import socket
    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import Eto.Drawing as drawing
    import gnj_nudge as gn
    import gnj_rhino.system as gsys
    import gnj_rhino.card as gcard
    gsys.DOCK_ALLOWED = gcard.DOCK_ALLOWED = False
    core = gn.core
    import clr
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    import System.Windows
    from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
    from System.Windows.Media import PixelFormats

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
            socket.create_connection(("127.0.0.1", PART_PORT), 0.3).close()
            return True
        except Exception:
            return False

    def render_png(wpf_element, fname):
        pump(lambda: False, 1.0)
        w, h = wpf_element.ActualWidth, wpf_element.ActualHeight
        rtb = RenderTargetBitmap(int(w * 2), int(h * 2), 192, 192, PixelFormats.Pbgra32)
        rtb.Render(wpf_element)
        enc = PngBitmapEncoder()
        enc.Frames.Add(BitmapFrame.Create(rtb))
        path = os.path.join(OUT, fname)
        fs = System.IO.File.Create(path)
        enc.Save(fs)
        fs.Close()
        say("saved", path, "| %dx%d" % (w, h))

    def viewport_png(fname, bbox=None):
        v = sc.doc.Views.Find("Perspective", False)
        if bbox is not None:
            v.ActiveViewport.ZoomBoundingBox(bbox)
        v.Redraw()
        v.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(os.path.join(OUT, fname))
        say("saved", os.path.join(OUT, fname))

    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (PART_PORT, os.path.join(OUT, "gnj-part-record.jsonl")))
    psi.WorkingDirectory = CORE_PART
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SAY"):
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 10)
    say("core (part branch export) on", PART_PORT, "up:", port_open())

    # ---- 1. colour
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    gn.ensure_layer(gn.LAYER_ROOT)
    gn.ensure_layer(gn.LAYER_BUILDABLE, gn.GHOST_COLOR)          # as an earlier version left it
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp
    scene = gn.choose_scene()
    bl = sc.doc.Layers[sc.doc.Layers.FindByFullPath(gn.LAYER_BUILDABLE, -1)]
    say("Buildable layer colour after start-up:", bl.Color.R, bl.Color.G, bl.Color.B,
        "| timber:", bl.Color.ToArgb() == gn.TIMBER_COLOR.ToArgb())
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % PART_PORT))
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    ss = panel.session
    vp = persp.ActiveViewport
    cam = vp.CameraLocation

    def draw(uv):
        pts = []
        for i in range(30):
            x, y, z = core.saddle_point(*uv(i / 29.0))
            target = rg.Point3d(x, y, z)
            ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
            pts.append(rg.Line(cam, target).PointAt(k))
        panel.use_gesture(sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3)), vp)
        pump(lambda: ss.phase != "thinking", 60)

    draw(lambda f: (0.15 + 0.7 * f, 0.5))
    panel.on_accept(None, None)
    baked = [o for o in sc.doc.Objects if o.Attributes.LayerIndex == bl.Index and isinstance(o.Geometry, rg.Brep)]
    say("accepted member colour source:", baked and baked[0].Attributes.ColorSource, "| on Buildable:", len(baked))
    draw(lambda f: (0.5, 0.2 + 0.6 * f))
    say("new ghost:", ss.phase)
    viewport_png("gnj-rhino7-colour-accepted-vs-ghost.png", scene.bbox)
    panel.on_reject(None, None)

    # ---- 2. your own part: long, rising on a 9 m radius, drifting 100 mm in an S, twisting 30 degrees
    designer = sc.doc.Layers.Add("Designer parts", System.Drawing.Color.FromArgb(150, 150, 150))
    sections = []
    L, R = 5050.0, 9000.0
    base = rg.Vector3d(0, 3500, 0)   # beside the saddle
    for i in range(41):
        t = i / 40.0
        x = L * t
        z = math.sqrt(R * R - (x - L / 2) ** 2) - math.sqrt(R * R - (L / 2) ** 2)
        y = 250.0 * math.sin(2 * math.pi * t)   # enough drift and twist that one billet will not fit
        tw = math.radians(40.0 * t)
        c, s = math.cos(tw), math.sin(tw)
        corners = []
        for dy, dz in ((-60, -120), (60, -120), (60, 120), (-60, 120), (-60, -120)):
            corners.append(rg.Point3d(x, y + dy * c - dz * s, 800 + z + dy * s + dz * c) + base)
        sections.append(rg.Polyline(corners).ToNurbsCurve())
    loft = rg.Brep.CreateFromLoft(sections, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)
    solid = loft[0].CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
    attrs = Rhino.DocObjects.ObjectAttributes()
    attrs.LayerIndex = designer
    attrs.Name = "Twisted rail"
    pid = sc.doc.Objects.AddBrep(solid, attrs)
    doc_obj = sc.doc.Objects.FindId(pid)          # the document's own object, as the designer has it
    before_serial = doc_obj.RuntimeSerialNumber   # changes whenever Rhino replaces the object
    before_geom = doc_obj.Geometry.Duplicate()
    say("designer solid: closed", solid.IsSolid, "| volume %.0f mm3" % rg.VolumeMassProperties.Compute(solid).Volume)
    sc.doc.Objects.UnselectAll()
    sc.doc.Objects.Select(pid)
    pump(lambda: False, 0.5)
    say("PART link shown after selecting it:", panel.rows["part"].Visible)
    sc.doc.Objects.UnselectAll()
    pump(lambda: False, 0.3)
    say("PART link hidden when nothing selected:", not panel.rows["part"].Visible)
    sc.doc.Objects.Select(pid)
    pump(lambda: False, 0.3)
    render_png(panel.ControlObject.Content, "gnj-rhino7-part-card-offer.png")
    t0 = time.time()
    panel.on_check_part(None, None)
    pump(lambda: ss.phase != "thinking", 120)
    f = ss.result and ss.result.get("form")
    say("PART answered in %.1f s:" % (time.time() - t0), ss.phase, "|", ss.headline(), "|", ss.waste_line(),
        "| pieces", f and f.get("n_pieces"), "| cut lines drawn", len(panel.conduit.dashes), "| ghost", panel.conduit.brep)
    say("     Inputs model:", panel.model_label(), "| gesture:", gn.tech.gesture_summary(ss))
    render_png(panel.ControlObject.Content, "gnj-rhino7-part-card-answer.png")
    sc.sticky[gsys.COLLAPSED_STICKY] = {"record": True}
    panel.open_system()
    panel.system_host.ClientSize = drawing.Size(460, 1000)
    view = panel.system_view
    view.on_display("outline", True)
    pump(lambda: False, 1.5)
    say("     outlines drawn:", len(panel.conduit.outline))
    render_png(view.control.ControlObject, "gnj-rhino7-part-system-460px.png")
    bb = solid.GetBoundingBox(True)
    bb.Inflate(600)
    viewport_png("gnj-rhino7-part-viewport.png", bb)
    n_before = sc.doc.Objects.Count
    panel.on_accept(None, None)
    after = sc.doc.Objects.FindId(pid)
    say("ACCEPT part: objects before %d after %d | solid still there %s | same object (serial) %s | same geometry %s | member %s" % (
        n_before, sc.doc.Objects.Count, after is not None,
        after is not None and after.RuntimeSerialNumber == before_serial,
        after is not None and rg.GeometryBase.GeometryEquals(after.Geometry, before_geom),
        ss.members and gn.tech.member_cells(ss.members[-1])))
    view.grid.SelectedRow = len(ss.members) - 1
    pump(lambda: False, 0.5)
    say("     Output row selects the designer's solid:", [o.Id for o in sc.doc.Objects.GetSelectedObjects(False, False)] == [pid])
    render_png(view.control.ControlObject, "gnj-rhino7-part-system-after-accept.png")
    panel.Close()
    say("PART SMOKE OK")
except Exception:
    say("PART SMOKE FAILED")
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
