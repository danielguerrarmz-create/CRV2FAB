# -*- coding: utf-8 -*-
"""Typed words through the core's /say (v5), end to end in the bend demo. Non-interactive, fresh Rhino 7 instance only.

  "C:\\Program Files\\Rhino 7\\System\\Rhino.exe" /nosplash
      /runscript="_-RunPythonScript C:\\...\\tests\\smoke_taste.py _-Exit _No"

The sample's objects and layers are copied from a scratch copy into the new empty document after
setting it to millimetres (passing the file on the command line stalled on a dialog once).

Own core on TASTE_PORT (solver only, no API key, fresh record in scratch); never 8742, never the
original sample. Three times: glued offer, Reject, Keep it solid, Accept. Then the same bend a fourth
time must come back solid "as you usually do" with a Taste step; after POST /taste/reset, glued again.
"""
import os
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-14")
LOG = os.path.join(OUT, "gnj-rhino7-say.log")
RECORD = os.path.join(OUT, "gnj-say-record.jsonl")
TASTE_PORT = 8748
CORE_HEAD = os.environ.get("GNJ_CORE_HEAD", r"C:\Users\danie\scratch\2026-11-14\gnj-core-head-553531e")
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
            socket.create_connection(("127.0.0.1", TASTE_PORT), 0.3).close()
            return True
        except Exception:
            return False

    import shutil
    copy = os.path.join(OUT, "gnj-taste-copy.3dm")
    shutil.copyfile(os.path.join(os.path.dirname(here), "samples", "gnj-three-timbers.3dm"), copy)
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)  # empty document: no scaling
    f3 = Rhino.FileIO.File3dm.Read(copy)
    for o in f3.Objects:
        lay = f3.AllLayers.FindIndex(o.Attributes.LayerIndex)
        a = Rhino.DocObjects.ObjectAttributes()
        a.Name, a.LayerIndex = o.Attributes.Name, gn.ensure_layer(lay.FullPath, gn.EXISTING_COLOR)
        sc.doc.Objects.AddBrep(o.Geometry, a)
    say("document from", copy, "| units", sc.doc.ModelUnitSystem, "| objects", sc.doc.Objects.Count,
        [o.Attributes.Name for o in sc.doc.Objects])
    if os.path.exists(RECORD):
        os.remove(RECORD)
    psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                              's = server.make_server(port=%d, record_path=r\'%s\'); '  # default backend
                                              's.serve_forever()"' % (TASTE_PORT, RECORD))
    psi.WorkingDirectory = CORE_HEAD  # the core at its committed HEAD, exported to scratch
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    for k in ("ANTHROPIC_API_KEY", "GNJ_SAY", "GNJ_BACKEND"):  # default backend: Claude Code, signed in here
        if psi.EnvironmentVariables.ContainsKey(k):
            psi.EnvironmentVariables.Remove(k)
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 8)
    say("say core (HEAD export) on", TASTE_PORT, "up:", port_open(), "| fresh record:", RECORD)

    scene = gn.choose_scene()
    say("scene:", type(scene).__name__)
    client = core.CoreClient("http://127.0.0.1:%d" % TASTE_PORT)
    panel = gn.NudgePanel(scene, client=client)
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    ss = panel.session
    frame = scene.frame
    s = frame.s
    front = sc.doc.Views.Find("Front", False).ActiveViewport

    import clr
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    import System.Windows
    from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
    from System.Windows.Media import PixelFormats

    def panel_png(fname):
        pump(lambda: False, 0.6)
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
        say("saved", path, "| %dx%d needs %d" % (w, h, el.DesiredSize.Height))

    sag = core.sag_of(2450.0)
    mid = frame.origin + frame.axis * (frame.length / 2) + frame.up * (sag * s)
    arc = rg.ArcCurve(rg.Arc(frame.origin + frame.up * (5 * s), mid, frame.origin + frame.axis * frame.length + frame.up * (5 * s)))
    panel.use_gesture(sc.doc.Objects.AddCurve(arc), front)
    pump(lambda: ss.phase != "thinking", 20)
    say("offer:", ss.phase, "|", ss.headline(), "|", ss.source_line())

    def type_and_wait(words, tag):
        panel.on_reject(None, None)
        panel.txt_say.Text = words
        t0 = time.time()
        panel.on_say(None, None)
        say("typed %r -> saying %s | line: %s | say box enabled %s" % (words, ss.saying, ss.subline(), panel.txt_say.Enabled))
        panel_png("gnj-rhino7-say-%s-waiting.png" % tag)
        pump(lambda: not ss.saying, 30)
        wait = time.time() - t0
        hist = [ln for ln in (Rhino.RhinoApp.CommandHistoryWindowText or "").splitlines() if "words read" in ln]
        say("  answered in %.1f s | phase %s | heard %r | holds %s | line %r | headline %r" % (
            wait, ss.phase, ss.heard, ss.held(), ss.subline(), ss.headline()))
        say("  command line:", hist[-1:] if hist else "(none)")
        panel_png("gnj-rhino7-say-%s-after.png" % tag)

    type_and_wait("no glue lines please", "solid")
    type_and_wait("make it blue", "blue")
    panel.Close()
    say("SAY SMOKE OK")
except Exception:
    say("SAY SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        if child is not None and not child.HasExited:
            child.Kill()
            child.WaitForExit(2000)
        say("say core stopped")
    except Exception as ex:
        say("could not stop the core:", ex)
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
