# -*- coding: utf-8 -*-
"""Read a photo (spec v8) in a fresh Rhino 7 test instance, against the real Claude Code backend.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash /scheme=GNJSmoke
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_photo.py _-Exit _No"

Two drawn test images (an arc up, a plain grey gradient) go through the card's own read path (the
file dialog is the only step skipped). Captures: the card while reading (with the once-a-session
notice), after an arc (the heard line and "Shaping from a photo arrives with sculpting."), after the
gradient (not read, nothing changes), and the System panel's Inputs with the file name (Record
collapsed). Own core from the photo branch's export on PHOTO_PORT; never 8742.
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-photo.log")
PHOTO_PORT = 8752
CORE_PHOTO = os.environ.get("GNJ_CORE_PHOTO", r"C:\Users\danie\scratch\2026-11-14\gnj-core-photo-3daa02f")
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
            socket.create_connection(("127.0.0.1", PHOTO_PORT), 0.3).close()
            return True
        except Exception:
            return False

    def render_png(wpf_element, fname):
        pump(lambda: False, 0.8)
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

    # Two test images, drawn here.
    arc_png = os.path.join(OUT, "gnj-photo-test-arc.png")
    bmp = System.Drawing.Bitmap(1200, 600)
    g = System.Drawing.Graphics.FromImage(bmp)
    g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias
    g.Clear(System.Drawing.Color.White)
    pen = System.Drawing.Pen(System.Drawing.Color.FromArgb(150, 110, 60), 40)
    g.DrawArc(pen, 100, 150, 1000, 700, 200, 140)   # a timber arching up
    g.Dispose()
    bmp.Save(arc_png, System.Drawing.Imaging.ImageFormat.Png)
    grey_png = os.path.join(OUT, "gnj-photo-test-grey.png")
    bmp = System.Drawing.Bitmap(800, 600)
    g = System.Drawing.Graphics.FromImage(bmp)
    brush = System.Drawing.Drawing2D.LinearGradientBrush(System.Drawing.Point(0, 0), System.Drawing.Point(800, 0),
                                                         System.Drawing.Color.FromArgb(90, 90, 90), System.Drawing.Color.FromArgb(200, 200, 200))
    g.FillRectangle(brush, 0, 0, 800, 600)
    g.Dispose()
    bmp.Save(grey_png, System.Drawing.Imaging.ImageFormat.Png)
    say("test images:", arc_png, grey_png)

    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (PHOTO_PORT, os.path.join(OUT, "gnj-photo-record.jsonl")))
    psi.WorkingDirectory = CORE_PHOTO
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SAY"):   # default backend: Claude Code, signed in here
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 10)
    say("core (photo branch export) on", PHOTO_PORT, "up:", port_open())

    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    scene = gn.choose_scene()
    panel = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % PHOTO_PORT))
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    ss = panel.session
    say("photo link shown at rest:", panel.rows["photo"].Visible)
    render_png(panel.ControlObject.Content, "gnj-rhino7-photo-card-rest.png")

    t0 = time.time()
    panel.read_photo(arc_png)
    say("ARC reading: line:", ss.subline(), "| Draw hidden:", not panel.rows["draw"].Visible)
    render_png(panel.ControlObject.Content, "gnj-rhino7-photo-card-reading.png")
    pump(lambda: not ss.reading_photo, 45)
    hist = [ln for ln in (Rhino.RhinoApp.CommandHistoryWindowText or "").splitlines() if "photo" in ln]
    say("ARC answered in %.1f s | heard: %r | line: %r | phase %s" % (time.time() - t0, ss.heard, ss.subline(), ss.phase))
    say("     command line:", hist[-1:] if hist else "(none)")
    render_png(panel.ControlObject.Content, "gnj-rhino7-photo-card-after.png")

    t0 = time.time()
    panel.read_photo(grey_png)
    say("GREY reading: notice again?", core.PHOTO_NOTICE in ss.subline())
    pump(lambda: not ss.reading_photo, 45)
    say("GREY answered in %.1f s | heard: %r | line: %r | phase %s" % (time.time() - t0, ss.heard, ss.subline(), ss.phase))
    render_png(panel.ControlObject.Content, "gnj-rhino7-photo-card-not-read.png")

    sc.sticky[gsys.COLLAPSED_STICKY] = {"record": True}
    panel.open_system()
    panel.system_host.ClientSize = drawing.Size(460, 1000)
    pump(lambda: False, 1.0)
    render_png(panel.system_view.control.ControlObject, "gnj-rhino7-photo-system-inputs.png")
    panel.Close()
    say("PHOTO SMOKE OK")
except Exception:
    say("PHOTO SMOKE FAILED")
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
