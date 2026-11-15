# -*- coding: utf-8 -*-
"""Mode 1: the small Nudge card for quick decisions (SPEC_V9_UI, "Card").

One column, 280 px, as tall as its content. The stroke row (Path, Start, End, then Done and Cancel)
replaces the single Draw button; one sentence, the waste line, Reject and Accept while a ghost is
proposed; holds and the Say box after a Reject or on a conflict; every state ends with Why? and
System. The card owns the one state both views render from: the session, the scene, the switches.
"""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403
from gnj_rhino.gesture import *  # noqa: F401,F403
from gnj_rhino.geometry import *  # noqa: F401,F403
from gnj_rhino.scenes import *  # noqa: F401,F403
from gnj_rhino.conduit import *  # noqa: F401,F403
from gnj_rhino.coreproc import *  # noqa: F401,F403
from gnj_rhino.part import *  # noqa: F401,F403
from gnj_rhino.system import *  # noqa: F401,F403


def _primary(text, handler, height=30):
    """A primary button: filled dark with white text. Blue is the ghost only."""
    b = _button(text, handler, height)
    _primary_state(b, True)
    return b


def _primary_state(b, on):
    """Enable or disable a primary button so its word stays readable either way."""
    b.Enabled = bool(on)
    b.BackgroundColor = PRIMARY_FILL if on else PRIMARY_OFF
    b.TextColor = drawing.Colors.White if on else drawing.Colors.Gray


def _link(text, handler):
    return PlainLink(text, handler)


ACTION_TEXT = {"release": "Release the hold", "redraw": "Redraw", "other_part": "Check another part",
               "retry": "Try again"}


class NudgePanel(forms.Form):
    """Diagnostics go to the Rhino command line, never into the card."""

    def __new__(cls, *args, **kwargs):
        # IronPython hands constructor args to the .NET base too; Form(frame) would pick Form(IHandler).
        return forms.Form.__new__(cls)

    def __init__(self, scene, client=None, core_child=None):
        self.scene = scene
        self.core_child = core_child  # a core process this panel started; stopped on close
        self.session = core.Session(client or core.CoreClient())
        ss = self.session
        ss.idle_text = scene.idle_text
        ss.idle_sub = getattr(scene, "idle_sub", None)
        ss.redraw_text = scene.redraw_text
        ss.again_text = scene.again_text
        ss.shape_word = scene.shape_word
        self.conduit = GhostConduit()
        self.display = {"outline": False, "type": False, "radius": False, "cuts": False,   # System panel: Show
                        "billets": True}
        self._billets = (None, [])    # (the result they were built for, [(brep, label)])
        self.billet_errors = []       # the last answer's billets that could not be drawn, for the smoke
        self.system_view = None       # Mode 2's content, once opened
        self.system_host = None       # its window (or the docked tab)
        self.closed = False
        self.synchronous = False      # tests run the nudge on the calling thread
        self.read_id = None           # a surface stroke's read line, on GNJ::Gesture
        self.stroke_ids = {}          # v9: the strokes on GNJ::Gesture until Done or Cancel
        self.show_strokes = False     # proposed: the stroke row is one Redraw link until pressed
        self.part_obj = None          # (id, name) of the designer's solid being checked, never modified
        self.last_phase = None
        self.plates = getattr(scene, "plate", False)

        self.Title = "CRV2FAB - Nudge"   # Daniel's wording, a plain hyphen
        icon = window_icon()
        if icon is not None:
            self.Icon = icon
        self.Resizable = False
        self.Minimizable = False
        self.Maximizable = False
        self.ClientSize = drawing.Size(PANEL_WIDTH, 160)
        self.Padding = drawing.Padding(12, 12, 12, 6)

        self.lbl_heard = _label(muted=True)   # what the core heard in typed words, above the new sentence
        self.lbl_head = _label(bold=True, size=11)
        self.lbl_waste = _label(muted=True)
        self.lbl_sub = _label(muted=True)
        self.btn_reject = _button("Reject", self.on_reject, 30)
        self.btn_accept = _primary("Accept", self.on_accept)
        self.lnk_redraw = _link("Redraw", self.on_redraw)
        self.btn_action = _button("Redraw", self.on_action, 30)   # the one next step of a conflict or a rejection
        self.btn_shape = _button(core.HOLD_BUTTONS["shape"], lambda s, e: self.hold("shape"))
        self.btn_solid = _button(core.HOLD_BUTTONS["solid"], lambda s, e: self.hold("solid"))
        self.txt_say = forms.TextBox()
        self.txt_say.PlaceholderText = "Say what to keep or change"
        self.txt_say.KeyDown += self.on_say_key
        self.btn_say = _button("Say", self.on_say)
        say_row = forms.TableLayout()
        say_row.Spacing = drawing.Size(6, 0)
        say_row.Rows.Add(forms.TableRow(forms.TableCell(self.txt_say, True), forms.TableCell(self.btn_say, False)))
        self.holds_box = forms.Panel()   # rebuilt whenever the set of holds changes
        self.holds_shown = None

        # The stroke row: three equal buttons, each with its status beneath, then Done and Cancel.
        self.stroke_buttons, self.stroke_labels = {}, {}
        strokes = forms.TableLayout()
        strokes.Spacing = drawing.Size(6, 2)
        buttons, labels = [], []
        for which in core.STROKES:
            b = _button(core.STROKE_NAMES[which], (lambda w: lambda s, e: self.on_stroke(w))(which), 28)
            lbl = _label(core.NOT_DRAWN, muted=True)
            lbl.TextAlignment = forms.TextAlignment.Center
            self.stroke_buttons[which], self.stroke_labels[which] = b, lbl
            buttons.append(forms.TableCell(b, True))
            labels.append(forms.TableCell(lbl, True))
        strokes.Rows.Add(forms.TableRow(*buttons))
        strokes.Rows.Add(forms.TableRow(*labels))
        self.btn_done = _primary("Done", self.on_done)
        self.lnk_cancel = _link("Cancel", self.on_cancel)
        done_row = forms.TableLayout()
        done_row.Spacing = drawing.Size(12, 0)
        done_row.Rows.Add(forms.TableRow(forms.TableCell(self.btn_done, True), forms.TableCell(self.lnk_cancel, False)))
        stroke_col = forms.TableLayout()
        stroke_col.Spacing = drawing.Size(0, 8)
        stroke_col.Rows.Add(forms.TableRow(forms.TableCell(strokes, True)))
        stroke_col.Rows.Add(forms.TableRow(forms.TableCell(done_row, True)))

        self.btn_draw = _button("Draw", self.on_gesture, 28)   # a surface scene: one line, read on the surface
        self.lnk_photo = _link("Photo", self.on_photo)
        self.lnk_part = _link("My solid", self.on_check_part)
        more = forms.TableLayout()
        more.Spacing = drawing.Size(14, 0)
        more.Rows.Add(forms.TableRow(forms.TableCell(self.lnk_photo, False), forms.TableCell(self.lnk_part, False),
                                     forms.TableCell(None, True)))

        self.lnk_why = _link("Why?", lambda s, e: self.toggle("why"))
        self.lnk_system = _link("System", lambda s, e: self.open_system())
        links = forms.TableLayout()
        links.Spacing = drawing.Size(14, 0)
        links.Rows.Add(forms.TableRow(forms.TableCell(self.lnk_why, False), forms.TableCell(self.lnk_system, False),
                                      forms.TableCell(None, True)))
        self.lbl_steps = _label(muted=True)
        self.open = {"why": False}

        # One column; each row is wrapped so its gap below hides with it. Every row is pinned to
        # the window width, so labels wrap and pairs fit (a Scrollable let content outgrow it).
        self.rows = {}
        table = forms.TableLayout()
        # SPEC_V9_CARD_SLOTS order: Echo, Verdict, Reason, Facts, Actions, Links.
        for key, c, gap in (("heard", self.lbl_heard, 4), ("head", self.lbl_head, 4), ("sub", self.lbl_sub, 4),
                            ("waste", self.lbl_waste, 10),
                            ("judge", _row(self.btn_reject, self.btn_accept), 6), ("redraw", self.lnk_redraw, 8),
                            ("action", self.btn_action, 8),
                            ("holdbtns", self._stack(self.btn_shape, self.btn_solid), 8), ("say", say_row, 8),
                            ("holds", self.holds_box, 8), ("strokes", stroke_col, 10), ("draw", self.btn_draw, 8),
                            ("more", more, 10),
                            ("links", links, 4), ("why", self.lbl_steps, 6)):
            wrap = forms.Panel()
            wrap.Content = c
            wrap.Padding = drawing.Padding(0, 0, 0, gap)
            self.rows[key] = wrap
            table.Rows.Add(forms.TableRow(forms.TableCell(wrap, True)))
        self.Content = table

        self.Closed += self.on_closed
        self.Shown += lambda s, e: self.fit()
        # The My solid link follows Rhino's selection while the card is open. One handler object, so
        # the same one comes off again on close.
        self._sel_handler = self.on_selection
        Rhino.RhinoDoc.SelectObjects += self._sel_handler
        Rhino.RhinoDoc.DeselectObjects += self._sel_handler
        Rhino.RhinoDoc.DeselectAllObjects += self._sel_handler
        self.refresh()

    @staticmethod
    def _stack(*controls):
        t = forms.TableLayout()
        t.Spacing = drawing.Size(0, 6)
        for c in controls:
            t.Rows.Add(forms.TableRow(forms.TableCell(c, True)))
        return t

    def fit(self):
        """Width fixed, height measured from the content, so the card is exactly as tall as what it
        shows. Deferred to the WPF dispatcher at Background priority, which runs after layout."""
        try:
            import clr
            clr.AddReference("WindowsBase")
            import System.Windows.Threading as threading_wpf
            self.ControlObject.Dispatcher.BeginInvoke(threading_wpf.DispatcherPriority.Background,
                                                      System.Action(self._fit_now))
        except Exception:
            self._fit_now()

    def _fit_now(self):
        if self.closed:
            return
        try:
            import clr
            clr.AddReference("PresentationCore")
            clr.AddReference("WindowsBase")
            import System.Windows
            el = self.ControlObject.Content
            el.Measure(System.Windows.Size(float(PANEL_WIDTH), float("inf")))
            need = int(math.ceil(el.DesiredSize.Height))
            if need > 0 and abs(self.ClientSize.Height - need) > 1:
                self.ClientSize = drawing.Size(PANEL_WIDTH, need)
        except Exception as ex:
            Rhino.RhinoApp.WriteLine("GNJ: card cannot size to its content here (%s)" % ex)

    def toggle(self, key):
        self.open[key] = not self.open[key]
        self.refresh()

    # -- Mode 2
    def open_system(self):
        """Open the System panel, or bring it forward: docked as the CRV2FAB tab, else a plain window."""
        if self.system_view is None:
            self.system_view = SystemView(self)
        docked = False
        if DOCK_ALLOWED and (self.system_host is None or self.system_host == "docked"):
            try:
                docked = dock_in_panel(self.system_view)
            except Exception as ex:
                Rhino.RhinoApp.WriteLine("GNJ: the System panel opens in its own window (could not dock it: %s)" % ex)
        if docked:
            self.system_host = "docked"
        elif self.system_host is None or self.system_host == "docked":
            win = SystemWindow(self.system_view, self.system_closed)
            win.Owner = Rhino.UI.RhinoEtoApp.MainWindow
            win.Show()
            self.system_host = win
        else:
            self.system_host.BringToFront()
            self.system_host.Focus()
        self.system_view.render()

    def system_closed(self):
        """The System window was closed: its overlays go with it."""
        self.system_host, self.system_view = None, None
        for k in self.display:
            self.display[k] = False
        if not self.closed:
            self.draw_ghost()

    def set_display(self, key, on):
        self.display[key] = on
        if key == "billets":   # the toggle also shows or hides the billets already baked
            idx = sc.doc.Layers.FindByFullPath(LAYER_BILLETS, -1)
            if idx >= 0 and sc.doc.Layers[idx].IsVisible != on:
                layer = sc.doc.Layers[idx]
                layer.IsVisible = on
                sc.doc.Layers.Modify(layer, idx, True)
        self.draw_ghost()
        if self.system_view is not None:
            self.system_view.render()

    def start_over(self):
        """Rehearsals: clear the tally and the taste in the core, and the record and Members grid."""
        ok = self.session.start_over()
        Rhino.RhinoApp.WriteLine("GNJ: started over: tally and taste cleared." if ok else
                                 "GNJ: could not clear the tally: %s" % self.session.client.last_error)
        self.refresh()

    # -- render
    def action_kind(self):
        """The one next step on a conflict or a rejection, else None: release, redraw, other_part or retry."""
        ss = self.session
        if ss.phase == "thinking" or ss.saying or ss.reading_photo or ss.drawing is not None:
            return None
        if ss.phase == "conflict" and ss.result is not None:
            return ss.slots()["action"]
        if ss.phase == "rejected":
            return "redraw"
        if ss.phase == "unavailable":
            return "retry"
        return None

    def on_action(self, sender, e):
        kind = self.action_kind()
        ss = self.session
        if kind == "redraw":
            self.on_redraw(sender, e)
        elif kind == "release":
            held = ss.held()
            if held:
                self.release("shape" if "shape" in held else held[0])
        elif kind == "other_part":
            if selected_part() is None:
                ss.note = "Select a closed solid, then press Check another part."
                self.refresh()
            else:
                self.on_check_part(sender, e)
        elif kind == "retry":
            self.start(True)

    def refresh(self):
        ss = self.session
        ph = ss.phase
        busy = ph == "thinking" or ss.saying or ss.reading_photo
        drawing_now = ss.drawing is not None
        self.lbl_head.Text = ss.headline()
        self.lbl_head.TextColor = CONFLICT_TEXT if (ph == "conflict" and not busy and not drawing_now) \
            else drawing.SystemColors.ControlText
        self.lbl_sub.Text = ss.subline()
        self.lbl_waste.Text = ss.waste_line()
        steps = ss.result["steps"] if ss.result else []
        self.lbl_steps.Text = "\n".join("%d. %s" % (i + 1, slots.words(s["text"])) for i, s in enumerate(steps)) \
            or "Nothing yet."
        self.lbl_heard.Text = ss.echo_line()
        held = ss.held()
        if held != self.holds_shown:
            self.holds_box.Content = self._holds_table(held)
            self.holds_shown = held
        for which in core.STROKES:
            self.stroke_labels[which].Text = ss.stroke_status(which)
            self.stroke_buttons[which].Enabled = not busy and (not drawing_now or ss.drawing == which)
        _primary_state(self.btn_done, ss.can_done())
        proposed = ss.can_judge() and not busy and not drawing_now
        action = self.action_kind()
        # After a Reject or on a conflict the stroke row waits behind one Redraw (SPEC_V9_CARD_SLOTS).
        waiting = proposed or ph in ("rejected", "conflict", "unavailable")
        strokes_here = self.plates and not busy and (not waiting or self.show_strokes or drawing_now)
        asking = ph == "rejected" and not busy and not drawing_now
        show = {"heard": bool(ss.heard) and not drawing_now, "head": True, "waste": bool(self.lbl_waste.Text),
                "sub": bool(self.lbl_sub.Text), "judge": proposed,
                "redraw": proposed and self.plates and not self.show_strokes,
                "action": action is not None and not (action == "redraw" and (self.show_strokes or not self.plates)),
                "holdbtns": asking, "say": asking, "holds": bool(held) and not busy,
                "strokes": strokes_here,
                "draw": not self.plates and not busy and not proposed,
                "more": not busy and not drawing_now and ph == "idle",   # Photo and My solid: idle only
                "links": True, "why": self.open["why"]}
        if action is not None:
            self.btn_action.Text = ACTION_TEXT[action]
        self.lnk_part.Visible = selected_part() is not None   # a closed solid is selected
        self.lnk_photo.Visible = True
        for key, wrap in self.rows.items():
            wrap.Visible = show[key]
        state = "drawing" if drawing_now else ph
        if state != self.last_phase:
            Rhino.RhinoApp.WriteLine("GNJ: " + core.COMMAND_LINE.get(state, ""))
            self.last_phase = state
        if self.Loaded:
            self.fit()
        self.draw_ghost()
        if self.system_view is not None:
            self.system_view.render()

    def _holds_table(self, held):
        table = forms.TableLayout()
        table.Spacing = drawing.Size(12, 4)
        for k in held:
            rel = _link("release", (lambda key: lambda s, e: self.release(key))(k))
            table.Rows.Add(forms.TableRow(
                forms.TableCell(_label("Keeping: " + core.hold_label(k, self.scene.shape_word)), False),
                forms.TableCell(rel, False), forms.TableCell(None, True)))
        return table

    def arrived(self):
        r = self.session.result
        self.show_strokes = False
        if self.session.part is not None and r and r.get("form") and r["form"].get("cuts"):
            self.display["cuts"] = True       # a part's cut lines show from the start
        if r and r.get("form") and self.session.stroke is not None:
            read = self.scene.read_curve(r["form"])
            if read is not None:
                self.show_read(read)
        self.refresh()
        self.diagnose()

    def diagnose(self):
        """Where the answer came from, and any core error: command line only."""
        ss = self.session
        if ss.result is not None:
            Rhino.RhinoApp.WriteLine("GNJ: " + ss.source_line())
            if ss.unmapped():
                Rhino.RhinoApp.WriteLine("GNJ: unmapped sentence: " + ss.unmapped())
            if ss.result.get("taste"):
                Rhino.RhinoApp.WriteLine("GNJ: taste led this answer (%s): %s" % (
                    ss.result["taste"]["lead"], ss.result["taste"]["because"]))
        err = ss.client.last_error
        if err and ss.result is not None and not ss.result.get("via_core"):
            Rhino.RhinoApp.WriteLine("GNJ: core not used: %s" % err)

    def draw_ghost(self):
        ss = self.session
        cuts = self.cut_lines(ss.result) if (ss.can_judge() and self.display["cuts"]) else []
        if ss.can_judge() and not self.closed and ss.part is None:
            form = ss.result["form"]
            try:
                brep, glue, _ = self.scene.ghost(form, display=True)
            except Exception as ex:
                brep, glue = None, []
                Rhino.RhinoApp.WriteLine("GNJ: could not build the ghost: %s" % ex)
            intent = self.scene.intent_outline(form) if form.get("kind") == "plate_member" else []
            self.conduit.show(brep, glue, cuts, intent)
        elif ss.can_judge() and not self.closed:
            self.conduit.show(None, [], cuts)    # a part: the geometry is the designer's own
        else:
            self.conduit.clear()
        shown = ss.can_judge() and not self.closed and self.display["billets"]
        self.conduit.show_billets([b for b, _ in self.billet_breps(ss.result)] if shown else [])
        if self.closed:
            self.conduit.overlays()
        else:   # overlays only as switched on in the System panel's Show section
            form = ss.result["form"] if ss.can_judge() else None
            kind = "type" if self.display["type"] else "radius" if self.display["radius"] else None
            coloured = self.scene.curvature_overlay(kind, tech.limit_radius_mm(ss))[0] if kind else []
            outline = self.billet_outline(ss.result) if (self.display["outline"] and form) else []
            self.conduit.overlays(coloured, outline)
        sc.doc.Views.Redraw()

    def _sent_form(self, result):
        sent = (result or {}).get("sent") or {}
        return sent.get("form") if isinstance(sent.get("form"), dict) else {}

    def _placer(self, form):
        """A plate is sent in the core's member frame; a part or a surface member in world mm."""
        if form.get("kind") == "plate_member":
            return self.scene.place
        s = mm()
        return lambda p: rg.Point3d(p[0] * s, p[1] * s, p[2] * s)

    def cut_lines(self, result):
        """Thin lines across the member at each cut, as the core sent them, placed in the model."""
        form = self._sent_form(result)
        place = self._placer(form)
        out = []
        for c in form.get("cuts") or []:
            line = (c or {}).get("line")
            if isinstance(line, list) and len(line) == 2:
                out.append(rg.Line(place(line[0]), place(line[1])))
        return out

    def billet_breps(self, result):
        """[(brep, label)]: each piece's billet as the core sent it, placed in the model. Built once
        per answer; a billet that cannot be closed is left out and said on the command line."""
        if self._billets[0] is result:
            return self._billets[1]
        form = self._sent_form(result)
        place = self._placer(form) if form else None
        out, self.billet_errors = [], []
        for box in core.billet_boxes(form):
            try:
                out.append((billet_brep(box["outline"], place), box["label"]))
            except Exception as ex:
                self.billet_errors.append("%s: %s" % (box["id"], ex))
                Rhino.RhinoApp.WriteLine("GNJ: could not draw billet %s: %s" % (box["id"], ex))
        self._billets = (result, out)
        return out

    def billet_outline(self, result):
        """Every billet outline the core sent (one billet, or one per piece), placed in the model."""
        form = self._sent_form(result)
        place = self._placer(form)
        polys = list((form.get("billet") or {}).get("outline") or [])
        for p in form.get("pieces") or []:
            if isinstance(p, dict) and not polys:
                polys.extend(((p.get("billet") or {}).get("outline") or []))
        out = []
        for poly in polys:
            pts = [place(p) for p in poly if isinstance(p, list) and len(p) == 3]
            if len(pts) > 1:
                out.append(rg.Polyline(pts))
        return out

    def model_label(self):
        """Inputs > Model: the part being checked, else the scene's model."""
        if self.session.part is not None and self.part_obj:
            return self.part_obj[1]
        return self.scene.model_name

    # -- the three strokes (spec v9)
    def on_stroke(self, which):
        """Press Path, Start or End: _Sketch in the view the designer clicks into. Start and End are
        drawn on the end plane: the active view's construction plane is set to it for the stroke and
        put back after, so the document is left as it was."""
        token = self.begin_stroke(which)
        if token is None:
            return
        made = None
        try:
            rs.Command("_Sketch", False)
            made = [i for i in (rs.LastCreatedObjects() or []) if rs.IsCurve(i)]
        finally:
            view = sc.doc.Views.ActiveView
            self.end_stroke(token, made[-1] if made else None, view.ActiveViewport if view else None)

    def begin_stroke(self, which):
        ss = self.session
        if not self.plates or not ss.begin_drawing(which):
            return None
        token = {"which": which, "cplane": None}
        view = sc.doc.Views.ActiveView
        if which != "path" and view is not None:
            vp = view.ActiveViewport
            before = vp.GetConstructionPlane()
            cp = vp.GetConstructionPlane()
            cp.Plane = self.scene.end_plane(which, ss.current)
            cp.Name = "GNJ %s plane" % which
            # A grid sized to a profile, so the end plane is plain to see in any template; the view's
            # own plane, grid and all, comes back after the stroke.
            cp.GridSpacing = END_PLANE_GRID_MM * mm()
            cp.GridLineCount = END_PLANE_GRID_LINES
            cp.ThickLineFrequency = 4
            cp.ShowGrid = True
            cp.ShowAxes = True
            vp.SetConstructionPlane(cp)
            token["cplane"] = (vp, before)
            view.Redraw()
        self.refresh()
        return token

    def end_stroke(self, token, obj_id, viewport):
        """Read the stroke, put the construction plane back, and show the stroke where it was meant:
        one thin dark curve on GNJ::Gesture (the sketch itself lies on the construction plane)."""
        ss = self.session
        which = token["which"]
        if token["cplane"] is not None:
            vp, before = token["cplane"]
            vp.SetConstructionPlane(before)
        curve = rs.coercecurve(obj_id) if obj_id is not None else None
        pts, kind = None, None
        try:
            if curve is not None:
                pts, kind = self.scene.read_stroke(which, curve, viewport, ss.current)
        except Exception as ex:
            Rhino.RhinoApp.WriteLine("GNJ: could not read the stroke: %s" % ex)
        if obj_id is not None:
            sc.doc.Objects.Delete(obj_id, True)
        if ss.end_drawing(which, pts, kind):   # a Path in plan and elevation shows as its one 3D path
            self._show_stroke(which, [self.scene.place(p) for p in ss.strokes[which]])
        self.refresh()

    def _show_stroke(self, which, points):
        old = self.stroke_ids.pop(which, None)
        if old is not None:
            sc.doc.Objects.Delete(old, True)
        crv = rg.Curve.CreateInterpolatedCurve(points, 3) if len(points) > 2 else rg.LineCurve(points[0], points[-1])
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = ensure_layer(LAYER_GESTURE)
        attrs.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
        attrs.ObjectColor = STROKE_COLOR
        attrs.LinetypeSource = Rhino.DocObjects.ObjectLinetypeSource.LinetypeFromObject
        attrs.LinetypeIndex = -1   # continuous: the layer's dashes are for read lines
        attrs.Name = "GNJ stroke: " + core.STROKE_NAMES[which]
        self.stroke_ids[which] = sc.doc.Objects.AddCurve(crv, attrs)
        sc.doc.Views.Redraw()

    def _clear_strokes(self):
        for oid in self.stroke_ids.values():
            sc.doc.Objects.Delete(oid, True)
        self.stroke_ids = {}
        sc.doc.Views.Redraw()

    def on_done(self, sender, e):
        """Done: the strokes go to the core as one plate request and leave the document."""
        if not self.session.done():
            return
        self._clear_strokes()
        self.start(True)

    def on_cancel(self, sender, e):
        self.session.cancel_strokes()
        self._clear_strokes()
        self.show_strokes = False
        self.refresh()

    def on_redraw(self, sender, e):
        self.show_strokes = True
        self.refresh()

    # -- a photo (spec v8, v9): this client reads the file and sends its bytes; the core opens no paths
    def on_photo(self, sender, e):
        dlg = forms.OpenFileDialog()
        dlg.Title = "Read a photo"
        dlg.Filters.Add(forms.FileFilter("Photos (JPEG, PNG)", ".jpg", ".jpeg", ".png"))
        if dlg.ShowDialog(self) == forms.DialogResult.Ok:
            self.read_photo(dlg.FileName)

    def read_photo(self, path):
        ss = self.session
        try:
            if System.IO.FileInfo(path).Length > core.MAX_PHOTO_BYTES:
                ss.note = "This photo is over 8 MB."
                self.refresh()
                return
            data = System.IO.File.ReadAllBytes(path)
        except Exception as ex:
            ss.note = "Could not open that file."
            Rhino.RhinoApp.WriteLine("GNJ: could not open the photo: %s" % ex)
            self.refresh()
            return
        head = "".join(chr(b) for b in data[0:8])
        media = core.photo_media_type(path, head)
        if media is None:
            ss.note = "Only JPEG and PNG photos can be read."
            self.refresh()
            return
        b64 = System.Convert.ToBase64String(data)
        gen = ss.begin_photo(os.path.basename(path))
        if gen is None:
            return
        client = ss.client
        started = time.time()
        self.refresh()

        def done(reply):
            if self.closed:
                return
            try:
                refused = reply is None and (client.last_error or "").startswith("core answered")
                if reply is not None:
                    Rhino.RhinoApp.WriteLine("GNJ: photo read by %s in %.1f s: %s" % (
                        reply["source"] or "the core", time.time() - started,
                        "; ".join("%s %s %s" % (b.get("size"), b.get("direction"), b.get("span")) for b in reply["bends"])
                        or "nothing read"))
                else:
                    Rhino.RhinoApp.WriteLine("GNJ: could not read the photo: %s" % client.last_error)
                if ss.finish_photo(gen, reply, refused):
                    self._clear_strokes()
                    self.arrived()
            except Exception as ex:
                Rhino.RhinoApp.WriteLine("GNJ: could not show the photo's reading: %s" % ex)

        if self.synchronous:
            done(client.photo(b64, media))
            return
        box = [None]

        def work():
            box[0] = client.photo(b64, media)  # never raises
            Rhino.RhinoApp.InvokeOnUiThread(System.Action(lambda: done(box[0])))

        th = threading.Thread(target=work)
        th.daemon = True
        th.start()

    # -- your own geometry (spec v6)
    def on_selection(self, sender, e):
        if not self.closed:
            self.refresh()

    def on_check_part(self, sender, e):
        obj = selected_part()
        if obj is None:
            return
        try:
            points, volume = sample_part(obj)
        except ValueError as ex:
            self.session.note = "%s" % ex
            self.refresh()
            return
        self.show_read(None)
        self.part_obj = (obj.Id, obj.Attributes.Name or "your part")
        Rhino.RhinoApp.WriteLine("GNJ: checking %s: %d points, %.0f mm3." % (self.part_obj[1], len(points), volume))
        self.start(self.session.check_part(core.part_intent(points, volume)))

    # -- nudge, off the UI thread
    def start(self, needed=True):
        if not needed:
            self.refresh()
            return
        ticket = self.session.begin_nudge()
        self.refresh()
        if not ticket:
            return
        gen, intent, holds = ticket
        client = self.session.client
        if self.synchronous:
            if self.session.finish_nudge(gen, client.nudge(intent, holds)):
                self.arrived()
            return

        def back():
            if self.closed:
                return
            try:
                if self.session.finish_nudge(gen, result[0]):
                    self.arrived()
            except Exception as ex:
                Rhino.RhinoApp.WriteLine("GNJ: could not show the result: %s" % ex)

        result = [None]

        def work():
            result[0] = client.nudge(intent, holds)  # never raises
            Rhino.RhinoApp.InvokeOnUiThread(System.Action(back))

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()

    # -- a line on a surface (v3): one stroke, read on the surface
    def on_gesture(self, sender, e):
        rs.Command("_Sketch", False)
        made = [i for i in (rs.LastCreatedObjects() or []) if rs.IsCurve(i)]
        if not made:
            self.session.note = "No line drawn. Drag over the surface in any view."
            self.refresh()
            return
        self.use_gesture(made[-1], sc.doc.Views.ActiveView.ActiveViewport)

    def use_gesture(self, obj_id, viewport=None):
        """A surface stroke. viewport: the view a sketch was drawn in; None: a curve read in 3D."""
        sc.doc.Objects.UnselectAll()
        curve = rs.coercecurve(obj_id)
        needed, note, read = self.scene.gesture(self.session, curve, viewport)
        if viewport is not None:
            sc.doc.Objects.Delete(obj_id, True)
        self.show_read(read)
        if note:
            self.session.note = note
            self.refresh()
            return
        self.start(needed)

    # -- judge
    def on_accept(self, sender, e):
        """Accept: the plate is baked in the timber colour on GNJ::Buildable (one group, one undo
        record) and becomes the current member. A part is the designer's own: nothing is baked."""
        ss = self.session
        if not ss.can_judge():
            return
        form = ss.result["form"]
        if ss.part is not None:
            ids = [self.part_obj[0]] if self.part_obj else []   # selectable from Members, never deleted
            billet_ids = []
        else:
            ids, billet_ids = bake(self.scene, form, core.member_user_text(ss.next_member_id(), ss.result),
                                   self.billet_breps(ss.result))  # geometry first; record only what was baked
        r = ss.accept()
        if r is not None:
            row = ss.add_member(r, ids)
            row["baked"] = ss.part is None
            row["billet_ids"] = billet_ids
        self.show_read(None)
        self.show_strokes = False
        self.refresh()

    def undo_accept(self):
        """Record > Undo last accept: POST /undo, then that member's baked objects go and the member
        before it is current again. On 409 the card says 'Nothing to undo.' and nothing else changes."""
        ss = self.session
        row = ss.undo_last()
        if row is not None and row.get("baked", True):
            for oid in (row.get("object_ids") or []) + (row.get("billet_ids") or []):
                sc.doc.Objects.Delete(oid, True)
        if row is not None:
            self._clear_strokes()
            self.show_read(None)
        self.refresh()

    def show_read(self, curve):
        """Replace the one dashed read line of a surface stroke (None clears it)."""
        if self.read_id is not None and sc.doc.Objects.FindId(self.read_id) is not None:
            sc.doc.Objects.Delete(self.read_id, True)
        self.read_id = None
        if curve is not None:
            self.read_id = sc.doc.Objects.AddCurve(curve)
            move_to_gesture_layer(self.read_id)
        sc.doc.Views.Redraw()

    def on_reject(self, sender, e):
        self.session.reject()
        self.show_strokes = False
        self.refresh()
        self.txt_say.Focus()

    def hold(self, k):
        self.start(self.session.add_hold(k))

    def release(self, k):
        self.start(self.session.release_hold(k))

    def on_say(self, sender, e):
        text = self.txt_say.Text
        self.txt_say.Text = ""
        self.say_text(text)

    def say_text(self, text):
        """Typed words (the card's box or the System panel's) go to the core's /say (v5), off the UI
        thread: the model takes 2 to 3 s."""
        ticket = self.session.begin_say(text)
        if not ticket:
            self.refresh()
            return
        gen, text, intent = ticket
        client = self.session.client
        self.refresh()
        started = time.time()

        def done(reply):
            if self.closed:
                return
            try:
                if reply is not None:
                    Rhino.RhinoApp.WriteLine("GNJ: words read by %s in %.1f s: %s" % (
                        reply["source"] or "the core", time.time() - started,
                        ", ".join("%s %s" % a for a in reply["actions"]) or "no change"))
                else:
                    Rhino.RhinoApp.WriteLine("GNJ: could not ask the core: %s" % client.last_error)
                if self.session.finish_say(gen, reply):
                    self.arrived()
            except Exception as ex:
                Rhino.RhinoApp.WriteLine("GNJ: could not show the answer: %s" % ex)

        if self.synchronous:
            done(client.say(text, intent))
            return
        box = [None]

        def work():
            box[0] = client.say(text, intent)  # never raises
            Rhino.RhinoApp.InvokeOnUiThread(System.Action(lambda: done(box[0])))

        th = threading.Thread(target=work)
        th.daemon = True
        th.start()

    def on_say_key(self, sender, e):
        if e.Key == forms.Keys.Enter:
            e.Handled = True
            self.on_say(sender, e)

    def on_closed(self, sender, e):
        self.closed = True
        Rhino.RhinoDoc.SelectObjects -= self._sel_handler
        Rhino.RhinoDoc.DeselectObjects -= self._sel_handler
        Rhino.RhinoDoc.DeselectAllObjects -= self._sel_handler
        self.conduit.clear()
        self.conduit.overlays()
        self.show_read(None)
        self._clear_strokes()
        host = self.system_host
        self.system_host, self.system_view = None, None
        if host == "docked":
            close_docked()
        elif host is not None:
            host.Close()
        stop_core_child(self.core_child)
        self.core_child = None
        sc.doc.Views.Redraw()
        if sc.sticky.get(STICKY_KEY) is self:
            del sc.sticky[STICKY_KEY]


__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
