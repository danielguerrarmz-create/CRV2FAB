# -*- coding: utf-8 -*-
"""Taste read-back, end to end in the bend demo. Non-interactive, fresh Rhino 7 instance only.

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
LOG = os.path.join(OUT, "gnj-rhino7-taste.log")
RECORD = os.path.join(OUT, "gnj-taste-record.jsonl")
TASTE_PORT = 8744
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
                                              's = server.make_server(port=%d, client=None, record_path=r\'%s\'); '
                                              's.serve_forever()"' % (TASTE_PORT, RECORD))
    psi.WorkingDirectory = gn.CORE_DIR
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    if psi.EnvironmentVariables.ContainsKey("ANTHROPIC_API_KEY"):
        psi.EnvironmentVariables.Remove("ANTHROPIC_API_KEY")
    child = System.Diagnostics.Process.Start(psi)
    pump(port_open, 8)
    say("taste core on", TASTE_PORT, "up:", port_open(), "| fresh record:", RECORD)

    scene = gn.choose_scene()
    say("scene:", type(scene).__name__, "| member length mm %.1f" % (scene.frame.length / scene.frame.s))
    client = core.CoreClient("http://127.0.0.1:%d" % TASTE_PORT)
    panel = gn.NudgePanel(scene, client=client)
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    panel.Show()
    panel.fit()
    ss = panel.session
    frame = scene.frame
    s = frame.s
    front = sc.doc.Views.Find("Front", False).ActiveViewport

    def draw_2450_up():
        """A Front-view sketch of a 2450 mm bend up, as Daniel would draw it."""
        sag = core.sag_of(2450.0)
        mid = frame.origin + frame.axis * (frame.length / 2) + frame.up * (sag * s)
        arc = rg.ArcCurve(rg.Arc(frame.origin + frame.up * (5 * s), mid,
                                 frame.origin + frame.axis * frame.length + frame.up * (5 * s)))
        panel.use_gesture(sc.doc.Objects.AddCurve(arc), front)
        pump(lambda: ss.phase != "thinking", 40)

    def offer():
        f = ss.result and ss.result["form"]
        return "%s | layers %s R %s | taste %s | %s" % (ss.phase, f and f["n_lamellas"], f and f["radius_mm"],
                                                       ss.result and ss.result.get("taste"), ss.headline())

    for i in range(1, 4):
        draw_2450_up()
        say("EPISODE %d offer:" % i, offer())
        panel.on_reject(None, None)
        panel.hold("solid")
        pump(lambda: ss.phase != "thinking", 40)
        say("          after Reject + Keep it solid:", offer())
        panel.on_accept(None, None)
        say("          accepted; record entries", len(ss.record))
    import json
    say("GET /taste:", json.loads(client.opener.open(client.base + "/taste", timeout=3).read().decode("utf-8")))

    draw_2450_up()
    say("FOURTH offer:", offer())
    say("      why:", [(x["tag"], x["text"]) for x in ss.result["steps"]])
    panel.toggle("why")
    pump(lambda: False, 0.8)
    import clr
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    import System.Windows
    from System.Windows.Media.Imaging import RenderTargetBitmap, PngBitmapEncoder, BitmapFrame
    from System.Windows.Media import PixelFormats
    el = panel.ControlObject.Content
    w, h = el.ActualWidth, el.ActualHeight
    rtb = RenderTargetBitmap(int(w * 2), int(h * 2), 192, 192, PixelFormats.Pbgra32)
    rtb.Render(el)
    enc = PngBitmapEncoder()
    enc.Frames.Add(BitmapFrame.Create(rtb))
    png = os.path.join(OUT, "gnj-rhino7-taste-panel.png")
    fs = System.IO.File.Create(png)
    enc.Save(fs)
    fs.Close()
    el.Measure(System.Windows.Size(w, float("inf")))
    say("saved", png, "| %dx%d, needs %d | FITS %s" % (w, h, el.DesiredSize.Height, abs(el.DesiredSize.Height - h) <= 2))
    view = sc.doc.Views.Find("Perspective", False)
    view.ActiveViewport.ZoomBoundingBox(panel.conduit.bbox)
    view.Redraw()
    vpng = os.path.join(OUT, "gnj-rhino7-taste-persp.png")
    view.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(vpng)
    say("saved", vpng)

    panel.on_reject(None, None)  # leave the fourth episode open, then reset taste
    say("POST /taste/reset ->", client._post("/taste/reset", {}, 3))
    draw_2450_up()
    say("AFTER RESET offer:", offer())
    panel.Close()
    say("TASTE SMOKE OK")
except Exception:
    say("TASTE SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        if child is not None and not child.HasExited:
            child.Kill()
            child.WaitForExit(2000)
        say("taste core stopped")
    except Exception as ex:
        say("could not stop taste core:", ex)
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
