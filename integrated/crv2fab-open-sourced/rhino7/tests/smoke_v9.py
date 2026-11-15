# -*- coding: utf-8 -*-
"""SPEC_V9_UI acceptance checks 1 to 11 (12: the ghost reads as a ghost; 13: a Path in plan and elevation), in a fresh Rhino 7 test instance (/scheme=GNJSmoke).

Run in a BRAND NEW empty document (Daniel, 2026-11-15), from the default template, set to millimetres,
never saved:  Rhino.exe /nosplash /scheme=GNJSmoke /runscript="_-RunPythonScript <this file> _-Exit _No"
The only geometry is what the v9 flow makes (the starting 2x4, the strokes, the ghosts and accepted
plates) and, for My solid, one curved beam this script lofts on a "Designer" layer of its own.
Own core: a git archive export of core main c64ed6d on PORT (never 8742), started here through
tests/v9_core_child.py with the core's fake Claude Code child (no model is called), killed at the end.

A hand is not scripted: each stroke goes through the card's own begin_stroke and end_stroke, with
the curve a _Sketch would leave (the meant 3D stroke carried along the view rays onto the active
view's construction plane). What a hand does that this does not: drag in _Sketch, press Esc, see
Rhino's own 3 px feedback while dragging, click a different view than the active one.
Screenshots: OUT, each named as SPEC_V9_UI says. Log: OUT/smoke_v9.log, one CHECK line per check.
"""
import math
import os
import re
import struct
import sys
import time
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", r"C:\Users\danie\scratch\2026-11-15\v9-ui")
LOG = os.path.join(OUT, "smoke_v9.log")
PORT = int(os.environ.get("GNJ_SMOKE_PORT", "8781"))   # a builder passes its own port, never 8742
CORE = os.environ.get("GNJ_CORE_MAIN_DIR", r"C:\Users\danie\scratch\2026-11-15\gnj-core-main-c64ed6d")
log = open(LOG, "w")
results = {}


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


def check(n, ok, detail=""):
    results[n] = results.get(n, True) and bool(ok)
    say("CHECK %s %s %s" % (n, "PASS" if ok else "FAIL", detail))


child = None
try:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = os.environ["GNJ_SMOKE_TESTS"]   # run_smoke_v9.ps1 sets it: this checkout's tests folder
    repo = os.path.dirname(here)
    sys.path.insert(0, repo)
    import ctypes
    import socket
    import System
    import Rhino
    import Rhino.Geometry as rg
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Eto.Drawing as drawing
    import Eto.Forms as forms
    import gnj_nudge as gn
    import gnj_rhino.system as gsys
    import gnj_tech as tech
    core = gn.core
    user32 = ctypes.windll.user32
    say("repo", repo, "| core export", CORE, "| port", PORT)

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

    def capture(fname, extra=None):
        """Rhino's own window (the docked panel is inside it) with the card, and any extra window,
        drawn where they sit. Nothing else on screen can reach the PNG."""
        pump(lambda: False, 0.8)
        frame, (l, t) = print_window(Rhino.RhinoApp.MainWindowHandle().ToInt64())
        g = System.Drawing.Graphics.FromImage(frame)
        for w in [card] + ([extra] if extra is not None else []):
            if w is not None and not w.IsDisposed and w.Visible:
                cb, (cl, ct) = print_window(w.NativeHandle.ToInt64())
                g.DrawImage(cb, cl - l, ct - t)
        g.Dispose()
        path = os.path.join(OUT, fname)
        frame.Save(path)
        say("saved", path)

    def capture_window(w, fname):
        pump(lambda: False, 0.8)
        bmp, _ = print_window(w.NativeHandle.ToInt64())
        path = os.path.join(OUT, fname)
        bmp.Save(path)
        say("saved", path)

    def capture_view(fname):
        pump(lambda: False, 0.5)
        persp.Redraw()
        path = os.path.join(OUT, fname)
        persp.CaptureToBitmap(System.Drawing.Size(1200, 700)).Save(path)
        say("saved", path)

    def texts(ctrl, out):
        """Every visible text in a window, as a person would read it."""
        if ctrl is None or not getattr(ctrl, "Visible", True):
            return out
        if hasattr(ctrl, "Columns") and hasattr(ctrl, "DataStore"):   # a GridView (isinstance meets a generic twin)
            for row in (ctrl.DataStore or []):
                out.extend("%s" % c for c in row)
            for col in ctrl.Columns:
                out.append(col.HeaderText)
            return out
        t = getattr(ctrl, "Text", None)
        if isinstance(t, basestring) and t:
            out.append(t)
        for attr in ("Controls",):
            kids = getattr(ctrl, attr, None)
            if kids is not None:
                for k in kids:
                    texts(k, out)
        return out

    MOVED = re.compile(r"(?:Largest move|Moved|moving the (?:plate|member) at most|sits at most) (\d+) mm")
    PER_SCALE = re.compile(r"(?:eased by|straightened by|flattened by|drift eased by|eased from) \d")

    def screen_text(name, windows):
        """Check 11 on every screen: one moved number at most, no per-scale number, no dash, no ellipsis."""
        words = []
        for w in windows:
            texts(w, words)
        blob = u"\n".join(words)
        moved = set(MOVED.findall(blob))
        bad = [ch for ch in (u"\u2013", u"\u2014", u"\u2026") if ch in blob]
        ok = len(moved) <= 1 and not PER_SCALE.search(blob) and not bad
        check(11, ok, "%s: moved numbers %s, per-scale %s, dashes or ellipsis %s" % (
            name, sorted(moved), bool(PER_SCALE.search(blob)), bad))
        return blob

    def object_count():
        return len(rs.AllObjects() or [])

    # ---- the core, our own
    def up():
        try:
            socket.create_connection(("127.0.0.1", PORT), 0.3).close()
            return True
        except Exception:
            return False

    record = os.path.join(OUT, "v9-smoke-record.jsonl")
    if os.path.exists(record):
        os.remove(record)
    psi = System.Diagnostics.ProcessStartInfo("python", '"%s" "%s" %d "%s"' % (
        os.path.join(here, "v9_core_child.py"), CORE, PORT, record))
    psi.WorkingDirectory = OUT
    psi.UseShellExecute = False
    psi.CreateNoWindow = True
    child = System.Diagnostics.Process.Start(psi)
    pump(up, 20)
    say("core child pid", child.Id, "up:", up())

    # ---- the document (a copy of the sample), views, the card, the docked panel
    user32.ShowWindow(ctypes.c_void_p(Rhino.RhinoApp.MainWindowHandle().ToInt64()), 3)
    start_objects = len(rs.AllObjects() or [])
    sc.doc.AdjustModelUnitSystem(Rhino.UnitSystem.Millimeters, False)
    say("document:", sc.doc.Path or "new, unsaved", "| objects at start", start_objects, "| units", sc.doc.ModelUnitSystem)
    if start_objects:
        raise RuntimeError("the smoke must start from an empty document")
    persp = sc.doc.Views.Find("Perspective", False)
    sc.doc.Views.ActiveView = persp
    persp.Maximized = True
    sc.sticky.pop(gsys.COLLAPSED_STICKY, None)   # the spec's open and closed sections
    scene = gn.choose_scene()   # an empty document starts the plate scene with the 2x4 only
    frame = scene.frame
    say("scene:", type(scene).__name__, "| objects now", len(rs.AllObjects() or []))
    card = gn.NudgePanel(scene, client=core.CoreClient("http://127.0.0.1:%d" % PORT))
    card.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    l, t, r, b = rect(Rhino.RhinoApp.MainWindowHandle().ToInt64())
    scale = Rhino.UI.RhinoEtoApp.MainWindow.Screen.LogicalPixelSize or 1.0
    card.Location = drawing.Point(int((l + 70) / scale), int((t + 170) / scale))
    card.Show()
    card.fit()
    ss = card.session
    card.open_system()
    view = card.system_view
    pump(lambda: ss.settings is not None, 10)
    say("docked:", card.system_host, "| width", view.control.ControlObject.ActualWidth, "| settings", ss.settings is not None)
    vp = persp.ActiveViewport
    mid = frame.origin + frame.axis * (frame.length * 0.5)

    def camera(offset):
        vp.SetCameraLocations(mid, mid + offset)
        box = rg.BoundingBox(frame.bbox.Min, frame.bbox.Max)
        box.Union(mid + frame.up * 1100 + frame.width * 700)
        box.Union(mid - frame.width * 700 - frame.up * 200)
        vp.ZoomBoundingBox(box)
        persp.Redraw()

    camera(rg.Vector3d(-1800, -4200, 2000))

    def sketch_path(rise_mm):
        """The path a hand means (an arc rising rise_mm over the member, in its vertical plane), left
        where _Sketch leaves it: on the view's construction plane along the view rays."""
        cam = vp.CameraLocation
        cplane = vp.GetConstructionPlane().Plane
        pts = []
        for i in range(41):
            f = i / 40.0
            meant = scene.place([core.LENGTH_MM * f, 0.0, rise_mm * math.sin(math.pi * f)])
            ok, h = rg.Intersect.Intersection.LinePlane(rg.Line(cam, meant), cplane)
            pts.append(rg.Line(cam, meant).PointAt(h))
        return sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))

    def stroke_path(rise_mm):
        token = card.begin_stroke("path")
        card.end_stroke(token, sketch_path(rise_mm), vp)

    def wait_answer(seconds=40):
        return pump(lambda: ss.phase != "thinking" and not ss.saying and not ss.reading_photo, seconds)

    # ---- 1 Idle
    pump(lambda: False, 1.0)
    statuses = [card.stroke_labels[w].Text for w in core.STROKES]
    check(1, card.lbl_head.Text == "Draw the shape you want." and statuses == ["not drawn"] * 3
          and not card.btn_done.Enabled and card.rows["strokes"].Visible
          and card.btn_done.BackgroundColor.ToArgb() == gn.PRIMARY_OFF.ToArgb(),
          "head %r, statuses %r, Done enabled %s" % (card.lbl_head.Text, statuses, card.btn_done.Enabled))
    capture("v9-card-idle.png")
    screen_text("idle", [card, view.control])

    # ---- 2 Path: draw, release; orbit
    n0 = object_count()
    stroke_path(900.0)   # tight enough that the core eases it (radius about 1.25 m)
    sid = card.stroke_ids.get("path")
    bb0 = rs.BoundingBox(sid)
    camera(rg.Vector3d(-3500, -2600, 1200))
    bb1 = rs.BoundingBox(sid)
    obj = sc.doc.Objects.FindId(sid)
    panel_drawing = texts(view.inputs, [])
    say("panel Inputs after the path:", panel_drawing)
    check(2, sid is not None and card.stroke_labels["path"].Text == "drawn in elevation" and card.btn_done.Enabled
          and "Path drawn in elevation, Start not drawn, End not drawn" in panel_drawing
          and [p.DistanceTo(q) for p, q in zip(bb0, bb1)] == [0.0] * 8
          and obj.Attributes.ObjectColor.ToArgb() == gn.STROKE_COLOR.ToArgb(),
          "status %r, Done %s, stroke on %s, moved after orbit %s" % (
              card.stroke_labels["path"].Text, card.btn_done.Enabled,
              sc.doc.Layers[obj.Attributes.LayerIndex].FullPath, max(p.DistanceTo(q) for p, q in zip(bb0, bb1))))
    capture("v9-card-path-drawn.png")
    screen_text("path drawn", [card, view.control])
    camera(rg.Vector3d(-1800, -4200, 2000))

    # ---- 3 Start: the construction plane is the end plane for the stroke, then back
    before = vp.GetConstructionPlane()
    token = card.begin_stroke("start")
    during = vp.GetConstructionPlane()
    end_plane = scene.end_plane("start", ss.current)
    persp.Redraw()
    capture("v9-start-plane.png")
    cp = during.Plane
    pts = [cp.PointAt(u, u * math.tan(math.radians(20.0))) for u in (-150.0, 0.0, 150.0)]
    sid = sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))
    card.end_stroke(token, sid, vp)
    after = vp.GetConstructionPlane()
    sent_start = ss.strokes.get("start")
    check(3, during.Name == "GNJ start plane" and during.Plane.Origin.DistanceTo(end_plane.Origin) < 1e-6
          and abs(during.GridSpacing - gn.END_PLANE_GRID_MM * frame.s) < 1e-9 and during.ShowGrid
          and after.GridSpacing == before.GridSpacing and after.GridLineCount == before.GridLineCount
          and abs(during.Plane.ZAxis * end_plane.ZAxis) > 0.999999 and after.Name == before.Name
          and after.Plane.Origin.DistanceTo(before.Plane.Origin) < 1e-9
          and card.stroke_labels["start"].Text == "drawn",
          "cplane before %r, during %r, after %r; start read %s points" % (
              before.Name, during.Name, after.Name, len(sent_start or [])))

    # ---- 4 Done: thinking, strokes gone (object count as before drawing), then the ghost
    card.on_done(None, None)
    thinking_head = card.lbl_head.Text
    count_after_done = object_count()
    wait_answer()
    check(4, thinking_head == "Finding the closest buildable shape." and count_after_done == n0
          and card.stroke_labels["path"].Text == "drawn in elevation"
          and ss.phase == "proposed" and card.conduit.brep is not None and len(card.conduit.intent) > 4,
          "thinking %r, objects %d before drawing and %d after Done, phase %s, ghost %s, outline points %d" % (
              thinking_head, n0, count_after_done, ss.phase, card.conduit.brep is not None, len(card.conduit.intent)))
    say("answer:", ss.headline(), "|", ss.waste_line(), "| statuses", [card.stroke_labels[w].Text for w in core.STROKES])
    say("made as:", dict(tech.check_lines(ss.result)).get("Made as"), "| machine:", dict(tech.check_lines(ss.result)).get("Machine"),
        "| sent path max |y| %.0f mm" % max(abs(p[1]) for p in ss.plate["path"]))
    capture("v9-card-proposed.png")
    capture_view("v9-persp-ghost.png")

    # ---- 12 The ghost reads as a ghost (Daniel, 2026-11-15): the 2x4 under it and the dashed drawing
    # over it stay visible. Measured, and measured again with an opaque fill, so the check can go red.
    def view_bytes():
        persp.Redraw()
        bmp = persp.CaptureToBitmap(System.Drawing.Size(600, 350))
        box = System.Drawing.Rectangle(0, 0, bmp.Width, bmp.Height)
        data = bmp.LockBits(box, System.Drawing.Imaging.ImageLockMode.ReadOnly,
                            System.Drawing.Imaging.PixelFormat.Format24bppRgb)
        n = data.Stride * bmp.Height
        buf = System.Array.CreateInstance(System.Byte, n)
        System.Runtime.InteropServices.Marshal.Copy(data.Scan0, buf, 0, n)
        bmp.UnlockBits(data)
        bmp.Dispose()
        return buf

    def member_shown(on):
        idx = sc.doc.Layers.FindByFullPath(gn.LAYER_EXISTING, -1)
        layer = sc.doc.Layers[idx]
        layer.IsVisible = on
        sc.doc.Layers.Modify(layer, idx, True)

    def ghost_counts():
        """(pixels the ghost changes, of those the ones the 2x4 still changes, dash pixels the ghost changes)."""
        every = view_bytes()
        member_shown(False)
        no_member = view_bytes()
        member_shown(True)
        intent, card.conduit.intent = card.conduit.intent, []
        no_dash = view_bytes()
        card.conduit.intent = intent
        card.conduit.Enabled = False
        no_ghost = view_bytes()
        card.conduit.Enabled = True
        ghost = through = dash = 0
        for i in range(0, len(every) - 2, 6):   # every other pixel (600 px rows: no stride padding)
            def differs(other):
                return abs(every[i] - other[i]) + abs(every[i + 1] - other[i + 1]) + abs(every[i + 2] - other[i + 2]) > 24
            if differs(no_ghost):
                ghost += 1
                if differs(no_member):
                    through += 1
            if differs(no_dash):
                dash += 1
        return ghost, through, dash

    card.set_display("billets", False)   # the ghost alone: its billets are check 13's
    seen = ghost_counts()
    translucent = card.conduit.material
    card.conduit.material = Rhino.Display.DisplayMaterial(gn.GHOST_FILL, 0.0)
    opaque = ghost_counts()
    card.conduit.material = translucent
    card.set_display("billets", True)
    persp.Redraw()
    check(12, seen[1] >= 100 and seen[1] >= 2 * opaque[1] and seen[2] >= 50
          and abs(translucent.Transparency - gn.GHOST_TRANSPARENCY) < 1e-6,
          "display mode %r; ghost pixels %d, 2x4 seen through %d (opaque fill: %d), dash pixels %d; fill %s at %.2f" % (
              persp.ActiveViewport.DisplayMode.EnglishName, seen[0], seen[1], opaque[1], seen[2],
              translucent.Diffuse, translucent.Transparency))

    # ---- 5 Proposed, eased: one sentence, waste and Largest move, Accept filled dark
    dev = ss.result.get("deviation_mm") or 0.0
    waste = card.lbl_waste.Text
    # SPEC_V9_CARD_SLOTS: Verdict, a Reason with no number, Facts "Waste N%  Moved N mm  Needs N ...", in that order
    once = (card.lbl_head.Text == "Buildable, eased." and "mm" not in card.lbl_sub.Text
            and re.match(r"^Waste \d+%%  Moved %d mm  Needs " % core.jround(dev), waste) is not None)
    check(5, card.rows["judge"].Visible and once
          and card.btn_accept.BackgroundColor.ToArgb() == gn.PRIMARY_FILL.ToArgb() and card.rows["redraw"].Visible
          and not card.rows["strokes"].Visible,
          "sentence %r, waste line %r, deviation %s, Accept fill %s" % (
              card.lbl_head.Text, waste, dev, card.btn_accept.BackgroundColor))
    capture("v9-card-proposed-eased.png")
    screen_text("proposed", [card, view.control])

    # ---- 6 Reject: ghost gone; nothing new for 10 s
    card.on_reject(None, None)
    gen = ss.gen
    pump(lambda: False, 10.0)
    check(6, card.lbl_head.Text == "Rejected." and card.lbl_sub.Text.startswith("I will not guess again.")
          and not card.conduit.Enabled and card.rows["holdbtns"].Visible and card.rows["say"].Visible
          and card.rows["action"].Visible and card.btn_action.Text == "Redraw" and not card.rows["strokes"].Visible
          and ss.gen == gen and ss.phase == "rejected",
          "head %r, conduit on %s, holds %s, say %s, new requests %d" % (
              card.lbl_head.Text, card.conduit.Enabled, card.rows["holdbtns"].Visible, card.rows["say"].Visible,
              ss.gen - gen))
    capture("v9-card-rejected.png")
    screen_text("rejected", [card, view.control])

    # ---- 7 Keep my shape, on a shape that needs easing: the red conflict and the holds row
    card.hold("shape")
    wait_answer()
    holds_text = texts(card.holds_box, [])
    check(7, ss.phase == "conflict" and card.lbl_head.TextColor.ToArgb() == gn.CONFLICT_TEXT.ToArgb()
          and card.lbl_head.Text == "Not buildable." and card.rows["action"].Visible
          and card.btn_action.Text == "Release the hold" and not card.rows["say"].Visible
          and not card.rows["holdbtns"].Visible and not card.rows["strokes"].Visible
          and "Keeping: my shape" in holds_text and "release" in holds_text,
          "phase %s, sentence %r, holds row %r" % (ss.phase, card.lbl_head.Text, holds_text))
    capture("v9-card-conflict.png")
    screen_text("conflict", [card, view.control])

    # ---- 8 Accept, then Undo last accept
    card.release("shape")
    wait_answer()
    rows_before = len(ss.members)
    card.on_accept(None, None)
    baked = ss.members[-1]["object_ids"] if ss.members else []
    layer_ok = all(sc.doc.Layers[sc.doc.Objects.FindId(i).Attributes.LayerIndex].FullPath == gn.LAYER_BUILDABLE
                   for i in baked)
    colour = sc.doc.Layers[sc.doc.Layers.FindByFullPath(gn.LAYER_BUILDABLE, -1)].Color
    solid = baked and isinstance(sc.doc.Objects.FindId(baked[0]).Geometry, rg.Brep) and \
        sc.doc.Objects.FindId(baked[0]).Geometry.IsSolid
    accepted_ok = (ss.phase == "accepted" and card.lbl_head.Text == "Accepted and recorded." and layer_ok and solid
                   and colour.ToArgb() == gn.TIMBER_COLOR.ToArgb() and len(ss.members) == rows_before + 1
                   and len(view._rows_shown or []) == len(ss.members) and ss.current["accepted"])
    say("accepted:", baked, "| tally", ss.tally, "| waste line", card.lbl_waste.Text)
    capture("v9-accepted.png")
    screen_text("accepted", [card, view.control])
    view.lnk_undo.click()   # what a click on Record > Undo last accept does
    gone = all(sc.doc.Objects.FindId(i) is None for i in baked)
    undone_ok = (gone and ss.members == [] and not ss.current["accepted"] and ss.record[0]["text"] == "Undid the last accept."
                 and ss.phase == "idle" and card.lbl_head.Text == "Draw the shape you want." and not view.lnk_undo.Enabled)
    capture("v9-undone.png")
    screen_text("undone", [card, view.control])
    card.undo_accept()   # nothing left: 409
    nothing = card.lbl_sub.Text
    check(8, accepted_ok and undone_ok and nothing == "Nothing to undo.",
          "accepted %s (solid brep %s on %s), undone %s, tally after undo %s, second undo says %r" % (
              accepted_ok, solid, gn.LAYER_BUILDABLE, undone_ok, ss.tally, nothing))
    ss.note = ""

    # ---- 13 Billets per piece (Daniel, 2026-11-15), on a 2-piece plate: the core's twist_50_splits case,
    # start and end 600 mm wide turned 25 degrees each way, no path. Translucent boxes around the ghost;
    # on Accept, closed Breps with a TextDot each on GNJ::Buildable::Billets and user text on the member.
    for which, deg in (("start", -25.0), ("end", 25.0)):
        token = card.begin_stroke(which)
        cp = vp.GetConstructionPlane().Plane
        a = math.radians(deg)
        pts = [cp.PointAt(u * math.cos(a), u * math.sin(a)) for u in (-300.0, 0.0, 300.0)]
        card.end_stroke(token, sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3)), vp)
    card.on_done(None, None)
    wait_answer(60)
    sent = card._sent_form(ss.result) if ss.result else {}
    boxes = core.billet_boxes(sent)
    drawn = list(card.conduit.billets)
    ghost_ok = (ss.phase == "proposed" and len(sent.get("pieces") or []) == 2 and len(boxes) == 2
                and len(drawn) == 2 and all(b.IsSolid for b in drawn) and card.display["billets"])
    say("billets:", card.lbl_head.Text, "|", [b["label"] for b in boxes], "| drawn", len(drawn),
        "| errors", card.billet_errors)
    capture_view("v9-billets-ghost.png")
    shaded_mode = persp.ActiveViewport.DisplayMode
    rendered_mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered")
    if rendered_mode is not None:
        persp.ActiveViewport.DisplayMode = rendered_mode
        capture_view("v9-billets-ghost-rendered.png")
        persp.ActiveViewport.DisplayMode = shaded_mode
    card.on_accept(None, None)
    row = ss.members[-1] if ss.members else {}
    bids = row.get("billet_ids") or []
    objs = [sc.doc.Objects.FindId(i) for i in bids]
    bbreps = [o for o in objs if o is not None and isinstance(o.Geometry, rg.Brep)]
    dots = [o for o in objs if o is not None and isinstance(o.Geometry, rg.TextDot)]
    member = sc.doc.Objects.FindId(row["object_ids"][0]) if row.get("object_ids") else None
    utext = {}
    if member is not None:
        keys = member.Attributes.GetUserStrings()
        utext = dict((k, keys[k]) for k in keys.AllKeys)
    on_layer = all(o is not None and sc.doc.Layers[o.Attributes.LayerIndex].FullPath == gn.LAYER_BILLETS for o in objs)
    accepted_ok = (len(bbreps) == 2 and all(o.Geometry.IsSolid for o in bbreps) and on_layer
                   and sorted(d.Geometry.Text for d in dots) == sorted(b["label"] for b in boxes)
                   and utext.get("gnj.id") == row.get("id") and utext.get("gnj.pieces") == "2"
                   and set(utext) >= set(["gnj.layers", "gnj.layer_mm", "gnj.waste_pct", "gnj.grain_deg"]))
    say("billets baked:", sorted(d.Geometry.Text for d in dots), "| user text", sorted(utext.items()),
        "| display mode override", [o.Attributes.HasDisplayModeOverride(System.Guid.Empty) for o in bbreps])
    capture_view("v9-billets-accepted.png")
    blayer = sc.doc.Layers.FindByFullPath(gn.LAYER_BILLETS, -1)

    # The accepted timber reads fully inside its billets (Daniel, cut of 2026-11-15): the pixels the
    # member changes, with the billets shown, against with them hidden; then again with the billets
    # forced to Shaded (opaque), so the measure can go red.
    def member_pixels():
        """The labels stay on top by design, so they are set aside while the boxes are measured."""
        member_shown_ = sc.doc.Objects.FindId(row["object_ids"][0])
        for d in dots:
            sc.doc.Objects.Hide(d.Id, True)
        on = view_bytes()
        sc.doc.Objects.Hide(member_shown_.Id, True)
        off = view_bytes()
        sc.doc.Objects.Show(member_shown_.Id, True)
        for d in dots:
            sc.doc.Objects.Show(d.Id, True)
        return sum(1 for i in range(0, len(on) - 2, 6)
                   if abs(on[i] - off[i]) + abs(on[i + 1] - off[i + 1]) + abs(on[i + 2] - off[i + 2]) > 24)

    with_billets = member_pixels()
    card.set_display("billets", False)
    bare = member_pixels()
    card.set_display("billets", True)
    opaque_mode = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    for o in bbreps:
        a2 = o.Attributes.Duplicate()
        a2.SetDisplayModeOverride(opaque_mode)
        sc.doc.Objects.ModifyAttributes(o.Id, a2, True)
    opaque = member_pixels()
    wire_id = Rhino.Display.DisplayModeDescription.FindByName(gn.BILLET_DISPLAY_MODE).Id
    for o in bbreps:
        a2 = sc.doc.Objects.FindId(o.Id).Attributes.Duplicate()
        a2.SetDisplayModeOverride(Rhino.Display.DisplayModeDescription.FindByName(gn.BILLET_DISPLAY_MODE))
        sc.doc.Objects.ModifyAttributes(o.Id, a2, True)
    modes = [sc.doc.Objects.FindId(o.Id).Attributes.GetDisplayModeOverride(System.Guid.Empty) for o in bbreps]
    reads = bare > 0 and with_billets >= 0.85 * bare and opaque < 0.5 * bare and all(m == wire_id for m in modes)
    say("member pixels: billets shown %d, hidden %d, billets forced opaque %d; billet display mode %s" % (
        with_billets, bare, opaque, gn.BILLET_DISPLAY_MODE))
    if rendered_mode is not None:
        persp.ActiveViewport.DisplayMode = rendered_mode
        capture_view("v9-billets-accepted-rendered.png")
        persp.ActiveViewport.DisplayMode = shaded_mode
    card.set_display("billets", False)
    hidden = not sc.doc.Layers[blayer].IsVisible
    card.set_display("billets", True)
    shown = sc.doc.Layers[blayer].IsVisible
    card.undo_accept()
    gone = all(sc.doc.Objects.FindId(i) is None for i in bids + list(row.get("object_ids") or []))
    check(13, ghost_ok and accepted_ok and reads and hidden and shown and gone and not ss.members,
          "proposed with 2 billets drawn %s; baked %d billets and %d dots on %s %s; user text %s; member reads "
          "inside them %s; Show hides %s, shows %s; undo removes them %s" % (
              ghost_ok, len(bbreps), len(dots), gn.LAYER_BILLETS, on_layer, sorted(utext), reads, hidden, shown, gone))
    ss.note = ""

    # ---- 14 Two-view Path (Daniel, 2026-11-15): drawn once in plan (Top) and once in elevation (Front),
    # the two make one doubly curved path: a 150 mm S in plan, a 300 mm arch in elevation.
    def sketched(meant):
        """Core mm points a hand means, left where _Sketch leaves them: on the view's construction
        plane, carried along the view rays (parallel in Top and Front)."""
        cplane = vp.GetConstructionPlane().Plane
        pts = []
        for q in meant:
            m = scene.place(q)
            if vp.IsPerspectiveProjection:
                ray = rg.Line(vp.CameraLocation, m)
            else:
                d = rg.Vector3d(vp.CameraDirection)
                d.Unitize()
                ray = rg.Line(m - d * 100000.0, m + d)
            ok, h = rg.Intersect.Intersection.LinePlane(ray, cplane)
            pts.append(ray.PointAt(h))
        return sc.doc.Objects.AddCurve(rg.Curve.CreateInterpolatedCurve(pts, 3))

    def look_from(projection, name):
        vp.SetProjection(projection, name, True)
        box = rg.BoundingBox(frame.bbox.Min, frame.bbox.Max)
        box.Union(mid + frame.up * 450 + frame.width * 300)
        box.Union(mid - frame.width * 300 - frame.up * 150)
        vp.ZoomBoundingBox(box)
        persp.Redraw()

    DVP = Rhino.Display.DefinedViewportProjection
    side = (DVP.Front, "Front") if abs(frame.axis.X) >= abs(frame.axis.Y) else (DVP.Right, "Right")
    n_tv = object_count()
    look_from(DVP.Top, "Top")
    token = card.begin_stroke("path")
    card.end_stroke(token, sketched([[core.LENGTH_MM * i / 40.0, 150.0 * math.sin(2 * math.pi * i / 40.0), 0.0]
                                     for i in range(41)]), vp)
    plan_status = card.stroke_labels["path"].Text
    capture_view("tv-plan-stroke.png")
    look_from(*side)
    token = card.begin_stroke("path")
    card.end_stroke(token, sketched([[core.LENGTH_MM * i / 40.0, 0.0, 300.0 * math.sin(math.pi * i / 40.0)]
                                     for i in range(41)]), vp)
    both_status = card.stroke_labels["path"].Text
    both_drawing = texts(view.inputs, [])
    capture_view("tv-elevation-stroke.png")
    path3d = ss.strokes.get("path") or [[0.0, 0.0, 0.0]]
    shown_crv = rs.coercecurve(card.stroke_ids.get("path"))
    shown = [shown_crv.PointAt(tp) for tp in shown_crv.DivideByCount(80, True)] if shown_crv else []

    def extent(v):   # the stroke on screen across `v`, mm
        d = [rg.Vector3d(p) * v for p in shown]   # Point3d * Vector3d is not a dot product in RhinoCommon
        return (max(d) - min(d)) / frame.s if d else 0.0
    vp.SetProjection(DVP.Perspective, "Perspective", True)
    camera(rg.Vector3d(-1800, -4200, 2000))
    capture("tv-card-both.png")
    card.on_done(None, None)
    wait_answer(60)
    lines = dict(tech.check_lines(ss.result)) if ss.result else {}
    pieces = len(card._sent_form(ss.result).get("pieces") or [])   # the core's own pieces, not a panel row
    sent = ss.plate["path"]
    say("two-view:", plan_status, "|", both_status, "| answer:", ss.headline(), "|", ss.waste_line(),
        "| made as", lines.get("Made as"), "| pieces", pieces, "| waste", lines.get("Waste"),
        "| sent path max |y| %.0f mm, max z %.0f mm" % (max(abs(p[1]) for p in sent), max(p[2] for p in sent)))
    camera(rg.Vector3d(-2200, -3000, 3400))   # from above and aside: the S and the arch both read
    capture_view("tv-persp-ghost.png")
    camera(rg.Vector3d(-1800, -4200, 2000))
    capture("tv-card-proposed.png")
    check(14, plan_status == "drawn in plan" and both_status == "drawn in plan and elevation"
          and "Path drawn in plan and elevation, Start not drawn, End not drawn" in both_drawing
          and max(abs(p[1]) for p in path3d) > 140.0 and max(p[2] for p in path3d) > 290.0
          and extent(rg.Vector3d(frame.width)) > 280.0 and extent(rg.Vector3d(frame.up)) > 290.0
          and object_count() == n_tv and ss.phase == "proposed" and card.conduit.brep is not None and pieces > 1
          and card.stroke_labels["path"].Text == "drawn in plan and elevation",
          "plan %r, both %r, panel %r, 3D path max |y| %.0f max z %.0f, stroke shown %.0f across %.0f up, "
          "phase %s, pieces %d, ghost %s" % (
              plan_status, both_status, [txt for txt in both_drawing if txt.startswith("Path")],
              max(abs(p[1]) for p in path3d), max(p[2] for p in path3d),
              extent(rg.Vector3d(frame.width)), extent(rg.Vector3d(frame.up)), ss.phase, pieces,
              card.conduit.brep is not None))
    screen_text("two-view", [card, view.control])
    card.on_reject(None, None)

    # ---- 9 Say, Photo, My solid: each leaves a sentence on the card
    stroke_path(300.0)
    card.on_done(None, None)
    wait_answer()
    card.say_text("keep it as one solid piece")
    wait_answer(30)
    say_ok = (ss.phase in ("proposed", "conflict") and bool(card.lbl_head.Text) and ss.held() == ["solid"]
              and card.lbl_heard.Text == "Keeping it as one piece.")
    say("say:", ss.heard, "|", card.lbl_head.Text)
    capture("v9-say.png")
    screen_text("say", [card, view.control])
    card.release("solid")
    wait_answer()

    img = System.Drawing.Bitmap(600, 300)
    g = System.Drawing.Graphics.FromImage(img)
    g.Clear(System.Drawing.Color.White)
    g.DrawArc(System.Drawing.Pen(System.Drawing.Color.Black, 6), 40, 60, 520, 360, 200, 140)
    g.Dispose()
    photo_path = os.path.join(OUT, "v9-photo-input.png")
    img.Save(photo_path, System.Drawing.Imaging.ImageFormat.Png)
    card.read_photo(photo_path)
    reading_head = card.lbl_head.Text
    wait_answer(40)
    photo_text = (card.lbl_head.Text + " " + card.lbl_sub.Text + " " + card.lbl_heard.Text).lower()
    photo_ok = (reading_head == "Reading your photo." and ss.phase == "proposed" and card.conduit.brep is not None
                and card.lbl_heard.Text == "Photo read: moderate bend up."
                and "sculpt" not in photo_text and ss.sent_strokes.get("path") == "photo")
    say("photo:", card.lbl_heard.Text, "|", card.lbl_head.Text, "| drawing:", tech.gesture_summary(ss))
    capture("v9-photo.png")
    screen_text("photo", [card, view.control])

    # My solid: a curved beam the designer might model, built here (the document starts empty and is
    # never saved). 2.4 m, 160 x 100 mm, rising 260 mm and drifting 120 mm in an S, twisting 30 degrees,
    # lofted through 9 sections and capped, on a "Designer" layer 1500 mm behind the member.
    s = frame.s
    sections = []
    for k in range(9):
        f = k / 8.0
        c = rg.Point3d(2400.0 * f * s, (1500.0 + 120.0 * math.sin(2 * math.pi * f)) * s,
                       (800.0 + 260.0 * math.sin(math.pi * f)) * s)
        a = math.radians(-15.0 + 30.0 * f)
        v1, v2 = rg.Vector3d(0, math.cos(a), math.sin(a)), rg.Vector3d(0, -math.sin(a), math.cos(a))
        hw, hd = 80.0 * s, 50.0 * s
        corners = [c + v1 * hw + v2 * hd, c - v1 * hw + v2 * hd, c - v1 * hw - v2 * hd, c + v1 * hw - v2 * hd]
        sections.append(rg.Polyline(corners + [corners[0]]).ToNurbsCurve())
    loft = rg.Brep.CreateFromLoft(sections, rg.Point3d.Unset, rg.Point3d.Unset, rg.LoftType.Normal, False)[0]
    beam = loft.CapPlanarHoles(sc.doc.ModelAbsoluteTolerance)
    if beam.SolidOrientation == rg.BrepSolidOrientation.Inward:
        beam.Flip()   # outward faces: a well-formed solid, positive volume
    layer = Rhino.DocObjects.Layer()
    layer.Name = "Designer"
    attrs = Rhino.DocObjects.ObjectAttributes()
    attrs.LayerIndex = sc.doc.Layers.Add(layer)
    attrs.Name = "My curved beam"
    part = sc.doc.Objects.FindId(sc.doc.Objects.AddBrep(beam, attrs))
    say("my solid built: closed", beam.IsSolid, "| volume %.0f mm3" % (beam.GetVolume() / s ** 3))
    say("my solid:", part.Attributes.Name if part else None)
    sc.doc.Objects.UnselectAll()
    sc.doc.Objects.Select(part.Id)
    pump(lambda: card.lnk_part.Visible, 3)
    link_shown = card.lnk_part.Visible
    card.on_check_part(None, None)
    wait_answer(60)
    one_billet = ss.result and ss.result["sentence"]
    # Shorter pieces and less waste, said in words: the core cuts the part, and its cut lines show.
    t_say = time.time()
    card.say_text("shorter pieces are fine and waste less")
    wait_answer(90)
    say("part words: %.1f s, note %r, client error %r, holds %s, saying %s" % (
        time.time() - t_say, ss.note, ss.client.last_error, ss.held(), ss.saying))
    count = object_count()
    cuts = card.cut_lines(ss.result)
    box = part.Geometry.GetBoundingBox(True)
    box.Inflate(5.0)
    on_part = all(box.Contains(ln.PointAt(0.5)) for ln in cuts)   # a cut lies across the part, not beside it
    has_cuts = bool(cuts) and card.display["cuts"] and on_part
    say("cut lines:", len(cuts), "| each on the part:", on_part)
    sc.doc.Objects.UnselectAll()   # the selection highlight would hide the cut lines
    capture("v9-part.png")   # the sentence and the cut lines, before Accept
    screen_text("part", [card, view.control])
    say("part in one billet:", one_billet, "| after words:", ss.heard, "|", ss.result and ss.result["sentence"])
    card.on_accept(None, None)
    part_ok = (link_shown and has_cuts and ss.phase == "accepted" and object_count() == count
               and ss.members[-1]["kind"].startswith("part"))
    say("part accepted: cuts", has_cuts, "| baked nothing", object_count() == count)
    capture("v9-part-accepted.png")
    check(9, say_ok and photo_ok and part_ok, "say %s, photo %s, my solid %s (cut lines %s)" % (
        say_ok, photo_ok, part_ok, has_cuts))

    # ---- 10 The panel at 300 px, and at the docked width
    docked_w = view.control.ControlObject.ActualWidth
    capture("v9-panel-docked.png")
    docked_text = screen_text("panel docked", [view.control])
    wins = []
    for width, fname in ((300, "v9-panel-300.png"), (170, "v9-panel-170.png")):
        v2 = gsys.SystemView(card)
        win = gsys.SystemWindow(v2, lambda: None)
        win.ClientSize = drawing.Size(width, 820)
        win.Location = drawing.Point(int((l + 420) / scale), int((t + 120) / scale))
        win.Show()
        pump(lambda: v2.control.ControlObject.ActualWidth > 0, 5)
        v2.fit()
        pump(lambda: False, 1.5)
        capture_window(win, fname)
        blob = screen_text("panel %d px" % width, [v2.control])
        say("panel %d px: narrow layout %s, members columns %s" % (
            width, v2.width < gsys.NARROW_BELOW_PX, v2.grid_columns))
        wins.append((width, v2, win, blob))
    nested = [w for w in (view.control.ControlObject,) if "ScrollViewer" in str(type(w))]
    ok10 = (all(u"\u2026" not in b for _, _, _, b in wins) and u"\u2026" not in docked_text and not nested
            and wins[1][1].grid_columns == (0, 4) and 0 in wins[0][1].grid_columns and 4 in wins[0][1].grid_columns)
    for width, v2, _, _ in wins:   # every column as wide as its longest text: nothing cut
        cells = [list(tech.member_cells(m)) for m in ss.members]
        for c in v2.grid.Columns:
            i = list(tech.OUTPUT_COLUMNS).index(c.HeaderText)
            longest = max([len(c.HeaderText)] + [len(r[i]) for r in cells])
            ok10 = ok10 and c.Width >= 7 * longest + 16
        say("panel %d px members columns:" % width, [c.HeaderText for c in v2.grid.Columns], [c.Width for c in v2.grid.Columns])
    check(10, ok10, "docked width %s, 300 px wide layout, 170 px narrow layout, no ellipsis" % docked_w)
    for _, v2, win, _ in wins:
        win.Close()

    card.Close()
    say("RESULTS", sorted(results.items()))
    say("V9 SMOKE %s" % ("OK" if results and all(results.values()) and len(results) == 14 else "INCOMPLETE OR FAILED"))
except Exception:
    say("V9 SMOKE FAILED")
    say(traceback.format_exc())
finally:
    try:
        if "card" in globals() and card is not None and not card.IsDisposed:
            card.Close()   # a card left open makes Rhino crash on _-Exit
    except Exception:
        pass
    try:
        if child is not None and not child.HasExited:
            child.Kill()
            child.WaitForExit(3000)
            say("core child stopped")
    except Exception:
        pass
    try:
        import scriptcontext as sc
        sc.doc.Modified = False
    except Exception:
        pass
    log.close()
