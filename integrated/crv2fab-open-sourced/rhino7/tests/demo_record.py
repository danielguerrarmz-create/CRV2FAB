# -*- coding: utf-8 -*-
"""Record the demo: drive the real script inside a fresh Rhino 7 test instance and capture frames.

Run by tests/demo_make.py (one command), never in a working session:
  Rhino.exe /nosplash /scheme=GNJSmoke /runscript="_-RunPythonScript ...\\tests\\demo_record.py _-Exit _No"

Each frame is the whole Rhino window (PrintWindow: Rhino's own pixels) with the Nudge card, a separate
window, composited where it sits on screen. frames.json lists every frame with its caption and how
long it is held. A beat that does not truly run is dropped and written to dropped.json; nothing is
staged. Cores: main HEAD for beats 1 to 5 (Claude Code backend for words), the part branch for beat 6,
each on its own port with a fresh record. Never port 8742.
"""
import json
import math
import os
import struct
import sys
import time
import traceback

DEMO = os.environ.get("GNJ_DEMO_DIR", r"C:\Users\danie\scratch\2026-11-14\demo")
FRAMES = os.path.join(DEMO, "frames_raw")
MAIN_PORT, PART_PORT = 8753, 8754
CORE_MAIN = os.path.join(DEMO, "core-main")
CORE_PART = os.path.join(DEMO, "core-part")
LOG = os.path.join(DEMO, "record.log")
log = open(LOG, "w")
frames, dropped, children = [], [], []


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


try:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = r"C:\Users\danie\code\gnj-rhino7\tests"
    sys.path.insert(0, os.path.dirname(here))
    if not os.path.isdir(FRAMES):
        os.makedirs(FRAMES)
    import ctypes
    import socket
    import System
    import Rhino
    import Rhino.Geometry as rg
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Eto.Drawing as drawing
    import gnj_nudge as gn
    import gnj_rhino.system as gsys
    core, tech = gn.core, gn.tech
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

    card = [None]

    def grab(caption, seconds=3.0, settle=1.0):
        """One frame: the Rhino window, with the card composited at its place on screen."""
        pump(lambda: False, settle)
        sc.doc.Views.Redraw()
        Rhino.RhinoApp.Wait()
        main = Rhino.RhinoApp.MainWindowHandle().ToInt64()
        frame, (l, t) = print_window(main)
        if card[0] is not None and not card[0].closed:
            cb, (cl, ct) = print_window(card[0].NativeHandle.ToInt64())
            g = System.Drawing.Graphics.FromImage(frame)
            g.DrawImage(cb, cl - l, ct - t)
            g.Dispose()
        name = "%03d.png" % len(frames)
        frame.Save(os.path.join(FRAMES, name))
        frames.append({"file": name, "caption": caption, "seconds": seconds})
        say("frame", name, "|", caption)

    def drop(beat, why):
        dropped.append({"beat": beat, "why": why})
        say("DROPPED", beat, ":", why)

    def start_core(port, folder, record, model):
        psi = System.Diagnostics.ProcessStartInfo("python", '-c "from gnj_nudge import server; '
                                                  's = server.make_server(port=%d,%s record_path=r\'%s\'); '
                                                  's.serve_forever()"' % (port, "" if model else " client=None,", record))
        psi.WorkingDirectory = folder
        psi.UseShellExecute = False
        psi.CreateNoWindow = True
        for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND", "GNJ_SAY", "GNJ_SHOW_MACHINE"):
            if psi.EnvironmentVariables.ContainsKey(k):
                psi.EnvironmentVariables.Remove(k)
        p = System.Diagnostics.Process.Start(psi)
        children.append(p)

        def up():
            try:
                socket.create_connection(("127.0.0.1", port), 0.3).close()
                return True
            except Exception:
                return False
        pump(up, 15)
        say("core", folder, "on", port, "up:", up())
        return up()

    def open_card(scene, port):
        if card[0] is not None and not card[0].closed:
            card[0].Close()
            pump(lambda: False, 0.3)
        p = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % port))
        p.Owner = Rhino.UI.RhinoEtoApp.MainWindow
        l, t, r, b = rect(Rhino.RhinoApp.MainWindowHandle().ToInt64())
        scale = 1.0
        try:
            scale = Rhino.UI.RhinoEtoApp.MainWindow.Screen.LogicalPixelSize or 1.0
        except Exception:
            pass
        p.Location = drawing.Point(int((l + 70) / scale), int((t + 300) / scale))   # over the viewport's left edge
        p.Show()
        p.fit()
        card[0] = p
        pump(lambda: False, 0.5)
        return p

    def ground_sketch(vp, targets):
        """A sketch as a designer makes it in Perspective: on the ground plane, along the camera rays."""
        cam = vp.CameraLocation
        pts = []
        for target in targets:
            ok, k = rg.Intersect.Intersection.LinePlane(rg.Line(cam, target), rg.Plane.WorldXY)
            pts.append(rg.Line(cam, target).PointAt(k))
        return sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))

    def wait_answer(p, seconds=60):
        ss = p.session
        return pump(lambda: ss.phase != "thinking" and not ss.saying, seconds)

    # ---- the stage: millimetres, Rhino maximized, Perspective maximized, the panel docked wide
    user32.ShowWindow(ctypes.c_void_p(Rhino.RhinoApp.MainWindowHandle().ToInt64()), 3)
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp
    persp.Maximized = True
    sc.sticky[gsys.COLLAPSED_STICKY] = {"record": True}   # the Record text names an internal machine: never shown
    main_ok = start_core(MAIN_PORT, CORE_MAIN, os.path.join(DEMO, "record-main.jsonl"), model=True)
    vp = persp.ActiveViewport

    # ================= Beat 1: a bend on the straight timber
    beat1 = False
    if main_ok:
        frame_obj = gn.setup()
        scene = gn.BendScene(frame_obj)
        persp.ActiveViewport.ZoomBoundingBox(rg.BoundingBox(frame_obj.bbox.Min - rg.Vector3d(300, 900, 300),
                                                            frame_obj.bbox.Max + rg.Vector3d(300, 900, 900)))
        p = open_card(scene, MAIN_PORT)
        p.open_system()
        pump(lambda: False, 1.0)
        say("system host:", p.system_host)
        grab("A straight softwood 2x4 in Rhino 7. The Nudge card on the left, the CRV2FAB system panel on the right.", 4)
        f = frame_obj
        sag = core.sag_of(2450.0)
        targets = [f.origin + f.axis * (f.length * i / 29.0) + f.up * (4 * sag * (i / 29.0) * (1 - i / 29.0) * f.s)
                   for i in range(30)]
        sk = ground_sketch(vp, targets)
        grab("The designer drags a bend up over the timber in the Perspective view.", 3)
        p.use_gesture(sk, vp)
        wait_answer(p)
        ss = p.session
        say("beat1:", ss.phase, ss.headline(), ss.waste_line())
        if ss.can_judge():
            grab("One blue ghost: the closest buildable form, with one plain sentence and the waste.", 4)
            p.on_accept(None, None)
            grab("Accept. The member is baked in timber tan; blue is kept for proposals only.", 3)
            beat1 = True
        else:
            drop("1 bend", "no proposal came back: %s" % ss.headline())
    else:
        drop("1 to 5", "the main core did not start")

    # ================= Beat 2: words, through the real Claude Code backend
    beat2 = False
    if beat1:
        p.use_gesture(ground_sketch(vp, targets), vp)
        wait_answer(p)
        if ss.can_judge():
            grab("Draw again. The same offer: four glued layers.", 3)
            p.on_reject(None, None)
            p.txt_say.Text = "no glue lines please"
            grab("Reject. The designer types what to keep, in their own words.", 3, settle=0.5)
            t0 = time.time()
            p.on_say(None, None)
            grab("Working out what you meant: Claude reads the words (a live call).", 2, settle=0.4)
            wait_answer(p, 40)
            took = time.time() - t0
            hist = [ln for ln in (Rhino.RhinoApp.CommandHistoryWindowText or "").splitlines() if "words read" in ln]
            say("beat2:", ss.heard, ss.headline(), hist[-1:] if hist else "", "%.1f s" % took)
            if ss.heard and "claude" in (hist[-1] if hist else ""):
                grab("Read by Claude in %.1f s: keeping it as one piece. The ghost changes to a solid member." % took, 4)
                p.on_accept(None, None)
                beat2 = True
            else:
                drop("2 words", "the words were not read by Claude Code (%s)" % (hist[-1:] if hist else "no line"))
                if ss.can_judge():
                    p.on_accept(None, None)

    # ================= Beat 3: taste, after three solid decisions
    if beat1:
        done = 1 if beat2 else 0
        while done < 3:
            p.use_gesture(ground_sketch(vp, targets), vp)
            wait_answer(p)
            if not ss.can_judge():
                break
            p.on_reject(None, None)
            p.hold("solid")
            wait_answer(p)
            if not ss.can_judge():
                break
            p.on_accept(None, None)
            done += 1
        grab("Three times the designer kept it solid: rejected the glued offer, chose solid, accepted.", 3)
        p.use_gesture(ground_sketch(vp, targets), vp)
        wait_answer(p)
        taste = ss.result and ss.result.get("taste")
        say("beat3:", ss.headline(), taste)
        if taste and taste.get("lead") == "solid":
            grab("The fourth bend arrives solid, as this designer usually chooses. The record is read back.", 4)
            p.on_reject(None, None)
        else:
            drop("3 taste", "the fourth answer was not led by taste: %s" % ss.headline())

    # ================= Beat 4: a line on a surface, the system panel
    beat4 = False
    if main_ok:
        if card[0] is not None:
            card[0].Close()
            card[0] = None
        rs.DeleteObjects(rs.AllObjects())
        scene = gn.setup_surface()
        persp.ActiveViewport.ZoomBoundingBox(scene.bbox)
        p = open_card(scene, MAIN_PORT)
        ss = p.session
        p.open_system()
        pump(lambda: False, 1.0)
        line = [rg.Point3d(*core.saddle_point(0.15 + 0.7 * i / 29.0, 0.5)) for i in range(30)]
        sk = ground_sketch(vp, line)
        grab("A doubly curved reference surface. The designer draws a line across it.", 3)
        p.use_gesture(sk, vp)
        wait_answer(p)
        say("beat4:", ss.phase, ss.headline(), ss.waste_line())
        if ss.can_judge():
            grab("The member follows the surface: pressed in one curve from layers, then milled to shape.", 4)
            p.system_view.on_display("outline", True)
            p.system_view.on_display("type", True)
            grab("System panel: inputs, numbers, output. Display: billet outline and the surface's curvature type.", 4)
            target = vp.CameraTarget
            loc = vp.CameraLocation
            for i in range(1, 25):   # a real orbit about the view's own target: each frame rendered by Rhino
                a = math.radians(2.5 * i)
                v = loc - target
                vp.SetCameraLocations(target, target + rg.Vector3d(v.X * math.cos(a) - v.Y * math.sin(a),
                                                                   v.X * math.sin(a) + v.Y * math.cos(a), v.Z))
                grab("Orbiting the view while the proposal is on screen.", 1.0 / 12, settle=0.05)
            vp.SetCameraLocations(target, loc)   # back where the designer was
            p.system_view.on_display("type", False)
            p.on_accept(None, None)
            grab("Accept. The output table and the running tally update.", 4)
            beat4 = True
        else:
            drop("4 surface", "no proposal came back: %s" % ss.headline())

    # ================= Beat 5: less waste, asked for in words
    if beat4:
        line2 = [rg.Point3d(*core.saddle_point(0.5, 0.2 + 0.6 * i / 29.0)) for i in range(30)]
        p.use_gesture(ground_sketch(vp, line2), vp)
        wait_answer(p)
        before = ss.waste_line()
        if ss.can_judge():
            grab("A second line. %s" % before, 3)
            p.on_reject(None, None)
            p.txt_say.Text = "can you use less wood"
            t0 = time.time()
            p.on_say(None, None)
            grab("Reject, then ask in words: can you use less wood. Claude reads it (a live call).", 2, settle=0.4)
            wait_answer(p, 40)
            after = ss.waste_line()
            hist = [ln for ln in (Rhino.RhinoApp.CommandHistoryWindowText or "").splitlines() if "words read" in ln]
            say("beat5:", before, "->", after, ss.heard, hist[-1:] if hist else "")
            if ss.can_judge() and after and after != before and "less_waste" in (hist[-1] if hist else ""):
                grab("%s Thinner layers, same line: before, %s" % (after, before.lower()), 4)
            else:
                drop("5 less waste", "the waste did not change by words (%s, %s)" % (before, after))
            p.Close()
            card[0] = None
        else:
            drop("5 less waste", "no second proposal")

    # ================= Beat 6: your own part, on the part branch
    part_ok = start_core(PART_PORT, CORE_PART, os.path.join(DEMO, "record-part.jsonl"), model=False)
    if part_ok:
        rs.DeleteObjects(rs.AllObjects())
        scene = gn.setup_surface()
        layer = sc.doc.Layers.Add("Designer parts", System.Drawing.Color.FromArgb(150, 150, 150))
        sections = []
        L, R = 5050.0, 9000.0
        for i in range(41):
            t_ = i / 40.0
            x = L * t_
            z = math.sqrt(R * R - (x - L / 2) ** 2) - math.sqrt(R * R - (L / 2) ** 2)
            y = 250.0 * math.sin(2 * math.pi * t_)
            tw = math.radians(40.0 * t_)
            c, s_ = math.cos(tw), math.sin(tw)
            corners = [rg.Point3d(x, y + dy * c - dz * s_, 800 + z + dy * s_ + dz * c)
                       for dy, dz in ((-60, -120), (60, -120), (60, 120), (-60, 120), (-60, -120))]
            sections.append(rg.Polyline(corners).ToNurbsCurve())
        solid = rg.Brep.CreateFromLoft(sections, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)[0]
        solid = solid.CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex, attrs.Name = layer, "Twisted rail"
        rs.DeleteObjects(rs.AllObjects())   # the rail alone, for this beat
        pid = sc.doc.Objects.AddBrep(solid, attrs)
        bb = solid.GetBoundingBox(True)
        bb.Inflate(700)
        persp.ActiveViewport.ZoomBoundingBox(bb)
        p = open_card(scene, PART_PORT)
        ss = p.session
        p.open_system()
        p.system_view.on_display("outline", True)
        sc.doc.Objects.Select(pid)
        pump(lambda: False, 0.6)
        if p.rows["part"].Visible:
            grab("Own geometry (on a branch awaiting merge): the designer selects their own solid. The card offers a check.", 4)
            t0 = time.time()
            p.on_check_part(None, None)
            grab("Checking the part as modelled. The core fits billets around it; nothing is changed.", 2, settle=0.4)
            wait_answer(p, 90)
            took = time.time() - t0
            f = ss.result and ss.result.get("form")
            say("beat6:", ss.headline(), ss.waste_line(), "%.1f s" % took, f and f.get("n_pieces"))
            if ss.can_judge() and f:
                sc.doc.Objects.UnselectAll()
                grab("Answered in %.0f s: two pieces joined end to end, each with its own billet outline, and the cut." % took, 5)
            else:
                drop("6 own geometry", "no plan came back: %s" % ss.headline())
        else:
            drop("6 own geometry", "the card did not offer a check for the selected solid")
        p.Close()
        card[0] = None
    else:
        drop("6 own geometry", "the part branch core did not start")
    say("RECORD DONE", len(frames), "frames")
except Exception:
    say("RECORD FAILED")
    say(traceback.format_exc())
finally:
    try:
        json.dump(frames, open(os.path.join(DEMO, "frames.json"), "w"), indent=1)
        json.dump(dropped, open(os.path.join(DEMO, "dropped.json"), "w"), indent=1)
    except Exception as ex:
        say("could not write the frame list:", ex)
    for c in children:
        try:
            if not c.HasExited:
                c.Kill()
                c.WaitForExit(2000)
        except Exception:
            pass
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
