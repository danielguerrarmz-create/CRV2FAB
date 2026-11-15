# -*- coding: utf-8 -*-
"""Mode 1 and Mode 2 in a fresh Rhino 7 test instance with its own settings scheme.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash /scheme=GNJSmoke
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_system.py _-Exit _No"

Clean saddle; a line drawn and accepted (Output gets a row), a second line proposed. The System
panel: with docking made to fail (the plain window, one command-line line); its content at 460 and
300 px; each colour map; a row selected (the view must not move); then docked as the "CRV2FAB" tab
in Rhino's right-hand panel area; then a re-run (card closed, modules reloaded, a new card): the
same registered tab is reused. Record stays collapsed in every capture (its text is the core's,
being reworded there). Own core from the core's main export on SYS_PORT; never 8742.
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-system.log")
SYS_PORT = 8750
CORE_MAIN = os.environ.get("GNJ_CORE_MAIN", r"C:\Users\danie\scratch\2026-11-14\gnj-core-main-eccea23")
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
    import struct
    import ctypes
    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import Eto.Forms as forms
    import Eto.Drawing as drawing
    import gnj_nudge as gn
    import gnj_rhino.system as gsys
    import gnj_rhino.card as gcard
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
            socket.create_connection(("127.0.0.1", SYS_PORT), 0.3).close()
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

    def window_png(fname):
        """Rhino's own window, via PrintWindow: only Rhino's pixels, even if something covers it."""
        pump(lambda: False, 1.0)
        hwnd = ctypes.c_void_p(Rhino.RhinoApp.MainWindowHandle().ToInt64())
        rect = ctypes.create_string_buffer(16)
        ctypes.windll.user32.GetWindowRect(hwnd, rect)
        l, t, r, b = struct.unpack("4i", rect.raw)
        bmp = System.Drawing.Bitmap(r - l, b - t)
        g = System.Drawing.Graphics.FromImage(bmp)
        hdc = g.GetHdc()
        ctypes.windll.user32.PrintWindow(hwnd, ctypes.c_void_p(hdc.ToInt64()), 2)
        g.ReleaseHdc(hdc)
        g.Dispose()
        path = os.path.join(OUT, fname)
        bmp.Save(path)
        say("saved", path, "| %dx%d" % (r - l, b - t))

    def last_gnj_line():
        lines = [ln for ln in (Rhino.RhinoApp.CommandHistoryWindowText or "").splitlines() if ln.startswith("GNJ:")]
        return lines[-1] if lines else ""

    def viewport_png(fname):
        v = sc.doc.Views.Find("Perspective", False)
        v.Redraw()
        v.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(os.path.join(OUT, fname))
        say("saved", os.path.join(OUT, fname))

    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (SYS_PORT, os.path.join(OUT, "gnj-system-record.jsonl")))
    psi.WorkingDirectory = CORE_MAIN
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SAY"):
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 10)
    say("core (main export) on", SYS_PORT, "up:", port_open())

    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp
    scene = gn.choose_scene()
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % SYS_PORT))
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
        pump(lambda: ss.phase != "thinking", 40)

    draw(lambda f: (0.15 + 0.7 * f, 0.5))
    panel.on_accept(None, None)
    draw(lambda f: (0.5, 0.2 + 0.6 * f))
    say("offer:", ss.phase, "| members", [m["id"] for m in ss.members], "| gesture line:", gn.tech.gesture_summary(ss))
    sc.sticky[gsys.COLLAPSED_STICKY] = {"record": True}   # Record's text is the core's: never in a capture

    # 1. The fallback: docking made to fail.
    real_dock = gcard.dock_in_panel

    def failing_dock(view):
        raise RuntimeError("test: docking switched off")
    gcard.dock_in_panel = failing_dock
    panel.open_system()
    gcard.dock_in_panel = real_dock
    view = panel.system_view
    say("FALLBACK host:", panel.system_host.__class__.__name__, "| command line:", last_gnj_line())

    # 2. The content at 460 and at 300 px.
    for width in (460, 300):
        panel.system_host.ClientSize = drawing.Size(width, 1000)
        pump(lambda: False, 1.5)
        render_png(view.control.ControlObject, "gnj-rhino7-mode2-%dpx.png" % width)
        say("  width %d: rows stacked %s | capped sections %s" % (
            width, view.width < gsys.STACK_BELOW_PX, dict((k, s.Height) for k, (s, _) in view.scrolls.items())))

    # 3. The colour maps, one at a time, over the shaded surface.
    persp.ActiveViewport.ZoomBoundingBox(scene.bbox)
    view.on_display("type", True)
    pump(lambda: False, 0.5)
    say("type map: display", panel.display, "| coloured meshes", len(panel.conduit.meshes))
    viewport_png("gnj-rhino7-mode2-type-map.png")
    view.on_display("radius", True)
    pump(lambda: False, 0.5)
    say("radius map: display", panel.display, "| coloured meshes", len(panel.conduit.meshes),
        "| only one map on:", not (panel.display["type"] and panel.display["radius"]))
    viewport_png("gnj-rhino7-mode2-radius-map.png")
    render_png(view.control.ControlObject, "gnj-rhino7-mode2-300px-radius-legend.png")

    # 4. Selecting a row selects the member and leaves the view where it was.
    before = (vp.CameraLocation, vp.CameraTarget)
    view.grid.SelectedRow = 0
    pump(lambda: False, 0.5)
    after = (vp.CameraLocation, vp.CameraTarget)
    say("row 0 -> selected in Rhino:", len(list(sc.doc.Objects.GetSelectedObjects(False, False))),
        "| view unchanged:", before[0].DistanceTo(after[0]) < 1e-6 and before[1].DistanceTo(after[1]) < 1e-6)
    panel.system_host.Close()
    pump(lambda: False, 0.5)
    say("window closed -> overlays off:", panel.display, "| meshes", len(panel.conduit.meshes))

    # 5. Docked, the default.
    guid = System.Guid(gsys.DOCK_GUID)
    panel.open_system()
    ptype = sc.sticky.get(gsys.DOCK_STICKY)
    say("DOCKED host:", panel.system_host, "| tab visible:", Rhino.UI.Panels.IsPanelVisible(guid),
        "| dock bars:", len(list(Rhino.UI.Panels.PanelDockBars(guid) or [])), "| built in memory:", ptype.Assembly.IsDynamic,
        "| docked width:", panel.system_view.control.ControlObject.ActualWidth)
    window_png("gnj-rhino7-mode2-docked-rhino.png")

    # 6. A re-run, as Daniel would: the card closes, the modules reload, a new card docks again.
    panel.Close()
    pump(lambda: False, 0.5)
    inst = ptype.GetField("Instance").GetValue(None)
    say("card closed -> tab visible:", Rhino.UI.Panels.IsPanelVisible(guid), "| content left:",
        inst is not None and inst.Content is not None, "| conduit enabled:", panel.conduit.Enabled)
    gn = reload(gn)                     # the entry's module body: reloads gnj_rhino in order, no main()
    import gnj_rhino.system as gsys2
    panel2 = gn.NudgePanel(gn.choose_scene(), client=core.CoreClient("http://127.0.0.1:%d" % SYS_PORT))
    panel2.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel2.Show()
    panel2.open_system()
    pump(lambda: False, 0.8)
    inst = ptype.GetField("Instance").GetValue(None)
    say("RERUN host:", panel2.system_host, "| same registered type:", sc.sticky.get(gsys2.DOCK_STICKY) is ptype,
        "| dock bars:", len(list(Rhino.UI.Panels.PanelDockBars(guid) or [])),
        "| tab shows the new view:", inst is not None and inst.Content is panel2.system_view.control)
    panel2.Close()
    pump(lambda: False, 0.5)
    say("second card closed -> tab visible:", Rhino.UI.Panels.IsPanelVisible(guid))
    say("SYSTEM SMOKE OK")
except Exception:
    say("SYSTEM SMOKE FAILED")
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
