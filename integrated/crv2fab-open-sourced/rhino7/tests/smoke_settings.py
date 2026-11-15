# -*- coding: utf-8 -*-
"""Live settings (spec v6 section 2) and the Output table's three rows, in a fresh Rhino 7 test instance.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash /scheme=GNJSmoke
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_settings.py _-Exit _No"

Saddle, a line, the System panel docked: Settings show the core's values; a waste target typed and
applied re-solves the proposal (the sentence as sent); a bad bend ratio is refused with the core's
reason; three members accepted with Numbers expanded keep three Output rows visible. Whole Rhino
window captured (PrintWindow), the card composited at its place. Own core: main 1983b42 export on
SET_PORT; never 8742. Record stays collapsed.
"""
import os
import struct
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-settings.log")
SET_PORT = 8755
CORE = os.environ.get("GNJ_CORE_MAIN", r"C:\Users\danie\scratch\2026-11-14\gnj-core-main-1983b42")
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
    import ctypes
    import socket
    import System
    import Rhino
    import Rhino.Geometry as rg
    import scriptcontext as sc
    import Eto.Drawing as drawing
    import gnj_nudge as gn
    import gnj_rhino.system as gsys
    core = gn.core
    user32 = ctypes.windll.user32

    def pump(cond, seconds):
        end = time.time() + seconds
        while time.time() < end:
            Rhino.RhinoApp.Wait()
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def rect(hwnd):
        buf = ctypes.create_string_buffer(16)
        user32.GetWindowRect(ctypes.c_void_p(hwnd), buf)
        return struct.unpack("4i", buf.raw)

    def print_window(hwnd):
        l, t, r, b = rect(hwnd)
        bmp = System.Drawing.Bitmap(r - l, b - t)
        g = System.Drawing.Graphics.FromImage(bmp)
        hdc = g.GetHdc()
        user32.PrintWindow(ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc.ToInt64()), 2)
        g.ReleaseHdc(hdc)
        g.Dispose()
        return bmp, (l, t)

    def capture(panel, fname):
        pump(lambda: False, 1.0)
        frame, (l, t) = print_window(Rhino.RhinoApp.MainWindowHandle().ToInt64())
        cb, (cl, ct) = print_window(panel.NativeHandle.ToInt64())
        g = System.Drawing.Graphics.FromImage(frame)
        g.DrawImage(cb, cl - l, ct - t)
        g.Dispose()
        path = os.path.join(OUT, fname)
        frame.Save(path)
        say("saved", path)

    def up():
        try:
            socket.create_connection(("127.0.0.1", SET_PORT), 0.3).close()
            return True
        except Exception:
            return False

    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (SET_PORT, os.path.join(OUT, "gnj-settings-record.jsonl")))
    psi.WorkingDirectory = CORE
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SAY", "GNJ_SHOW_MACHINE"):
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(up, 15)
    say("core main 1983b42 on", SET_PORT, "up:", up())

    user32.ShowWindow(ctypes.c_void_p(Rhino.RhinoApp.MainWindowHandle().ToInt64()), 3)
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp
    persp.Maximized = True
    sc.sticky[gsys.COLLAPSED_STICKY] = {"record": True}
    scene = gn.choose_scene()
    persp.ActiveViewport.ZoomBoundingBox(scene.bbox)
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % SET_PORT))
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    l, t, r, b = rect(Rhino.RhinoApp.MainWindowHandle().ToInt64())
    scale = Rhino.UI.RhinoEtoApp.MainWindow.Screen.LogicalPixelSize or 1.0
    panel.Location = drawing.Point(int((l + 70) / scale), int((t + 300) / scale))
    panel.Show()
    panel.fit()
    ss = panel.session
    panel.open_system()
    view = panel.system_view
    pump(lambda: ss.settings is not None, 5)
    say("settings in the panel:", ss.settings, "| editable boxes:", sorted(view.settings_boxes))
    vp = persp.ActiveViewport
    cam = vp.CameraLocation

    def draw(uv):
        pts = []
        for i in range(30):
            target = rg.Point3d(*core.saddle_point(*uv(i / 29.0)))
            ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
            pts.append(rg.Line(cam, target).PointAt(k))
        panel.use_gesture(sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3)), vp)
        pump(lambda: ss.phase != "thinking", 60)

    draw(lambda f: (0.15 + 0.7 * f, 0.5))
    say("offer:", ss.headline(), "|", ss.waste_line())
    capture(panel, "gnj-rhino7-settings-before.png")

    # A waste target, typed and applied: the core re-solves.
    view.settings_boxes["max_waste_pct"].Text = "20"
    view.on_apply(None, None)
    pump(lambda: ss.settings and ss.settings.get("max_waste_pct") == 20.0 and ss.phase != "thinking", 30)
    pump(lambda: ss.phase != "thinking", 60)
    say("after waste target 20:", ss.headline(), "|", ss.waste_line(), "| note:", view.lbl_settings.Text)
    capture(panel, "gnj-rhino7-settings-target.png")

    # A target that cannot be met: the core says so in the sentence, as sent.
    view.settings_boxes["max_waste_pct"].Text = "5"
    view.on_apply(None, None)
    pump(lambda: ss.settings and ss.settings.get("max_waste_pct") == 5.0 and ss.phase != "thinking", 30)
    pump(lambda: ss.phase != "thinking", 60)
    say("after waste target 5:", ss.headline(), "|", ss.waste_line())
    capture(panel, "gnj-rhino7-settings-over-target.png")

    # A bad value: the core refuses with its reason, nothing changes.
    view.settings_boxes["lam_ratio"].Text = "5"
    view.on_apply(None, None)
    pump(lambda: view.lbl_settings.Text not in ("Saving.", "Saved."), 10)
    say("bad bend ratio:", view.lbl_settings.Text, "| lam_ratio still:", ss.settings.get("lam_ratio"))
    capture(panel, "gnj-rhino7-settings-refused.png")
    view.settings_boxes["lam_ratio"].Text = "125"
    view.settings_boxes["max_waste_pct"].Text = ""
    view.on_apply(None, None)
    pump(lambda: ss.settings and ss.settings.get("max_waste_pct") is None, 10)

    # Output keeps three rows with Numbers expanded.
    for uv in (lambda f: (0.15 + 0.7 * f, 0.5), lambda f: (0.5, 0.2 + 0.6 * f), lambda f: (0.25 + 0.5 * f, 0.3)):
        if not ss.can_judge():
            draw(uv)
        if ss.can_judge():
            panel.on_accept(None, None)
    draw(lambda f: (0.2 + 0.6 * f, 0.7))
    pump(lambda: False, 1.5)
    g = view.grid.ControlObject
    say("members %d | Output grid height %.0f (min %d) | Numbers open: %s" % (
        len(ss.members), g.ActualHeight, gsys.OUTPUT_MIN_HEIGHT, not view.collapsed.get("numbers")))
    capture(panel, "gnj-rhino7-settings-output-rows.png")
    panel.Close()
    say("SETTINGS SMOKE OK")
except Exception:
    say("SETTINGS SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        if child is not None and not child.HasExited:
            child.Kill()
            child.WaitForExit(2000)
    except Exception:
        pass
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
