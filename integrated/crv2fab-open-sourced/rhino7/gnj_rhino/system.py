# -*- coding: utf-8 -*-
"""Mode 2: the System panel (SPEC_V9_UI, "Panel"). Inputs, This member, Members, Settings, Show, Record.

One Eto control (SystemView.control) that any host can show: a docked "CRV2FAB" tab in Rhino's
right-hand panel area (dock_in_panel), or, if docking fails at run time, a plain modeless window
(SystemWindow). It renders from the card's session, the one source of truth; it never computes a
number the core did not send. Designed for 300 px and read at the real docked width (about 170 px):
under NARROW_BELOW_PX a label sits above its value, values wrap and are never cut, Members shows
Member and Waste only. The page never scrolls; only Members and Record scroll, inside themselves.
Section headers are plain bold text with a small chevron; the whole row opens and closes it.
"""
from gnj_rhino.common import *  # noqa: F401,F403

SYSTEM_WIDTH = 300
NARROW_BELOW_PX = 250     # narrower than this: label above value, Members in two columns
LABEL_COL_PX = 96
MEMBERS_ROW_PX = 24
MEMBERS_MAX_ROWS = 6      # the grid grows to its rows, then scrolls inside itself
RECORD_HEIGHT_PX = 150    # the record scrolls inside itself
DOCK_ALLOWED = os.environ.get("GNJ_DOCK") != "0"   # GNJ_DOCK=0 forces the plain window
DOCK_GUID = "6a1d2c4e-9b1f-4f0e-8d2a-3c5b7e9f1a20"
COLLAPSED_STICKY = "gnj_system_collapsed_v9"         # section states, kept for the Rhino session
SECTIONS = (("inputs", "Inputs"), ("proposal", "This member"), ("members", "Members"), ("settings", "Settings"),
            ("show", "Show"), ("record", "Record"))
CLOSED_AT_START = ("settings", "show", "record")
SURFACE_KEYS = (("type", "Curvature type"), ("radius", "Tightest radius"))
COLOUR_MAPS = ("type", "radius")                     # only one colour map on at a time
NO_PROPOSAL = "Nothing proposed yet."
LOADING_SETTINGS = "Loading settings."
NO_SETTINGS = "Settings are not available. Is the helper running?"
CHEVRON_OPEN, CHEVRON_CLOSED = u"▾", u"▸"


def _wrapping(text, muted=False):
    lbl = _label(text, muted=muted)
    lbl.Wrap = forms.WrapMode.Word   # a value wraps; it is never cut with an ellipsis
    return lbl


def pairs_table(pairs, width_px, empty=""):
    """Label and value rows: side by side from NARROW_BELOW_PX up, else the label above its value.
    The value always wraps in the width it has."""
    table = forms.TableLayout()
    narrow = width_px < NARROW_BELOW_PX
    table.Spacing = drawing.Size(8, 1 if narrow else 4)
    for label, value in pairs:
        if narrow:
            table.Rows.Add(forms.TableRow(forms.TableCell(_wrapping(label, muted=True), True)))
            v = forms.Panel()
            v.Content = _wrapping(value)
            v.Padding = drawing.Padding(0, 0, 0, 4)
            table.Rows.Add(forms.TableRow(forms.TableCell(v, True)))
        else:
            name = _wrapping(label, muted=True)
            name.Width = LABEL_COL_PX
            table.Rows.Add(forms.TableRow(forms.TableCell(name, False), forms.TableCell(_wrapping(value), True)))
    if not pairs and empty:
        table.Rows.Add(forms.TableRow(forms.TableCell(_wrapping(empty, muted=True), True)))
    return table


class SectionHeader(forms.Panel):
    """A section's header: plain bold text and a chevron, no blue, no underline; the row is the button."""

    def __new__(cls, *args, **kwargs):
        return forms.Panel.__new__(cls)

    def __init__(self, title, on_click):
        self.title = title
        self.lbl = _label("", bold=True, size=10)
        self.lbl.Cursor = forms.Cursors.Pointer
        self.Cursor = forms.Cursors.Pointer
        self.Content = self.lbl
        self.Padding = drawing.Padding(0, 6, 0, 2)
        self.MouseDown += lambda s, e: on_click()

    def show(self, is_open):
        self.lbl.Text = (CHEVRON_OPEN if is_open else CHEVRON_CLOSED) + u"  " + self.title


class SystemView(object):
    """The System panel's content. card: the NudgePanel that owns the session, scene and conduit."""

    def __init__(self, card):
        self.card = card
        self.control = None
        self.width = SYSTEM_WIDTH
        self.collapsed = sc.sticky.setdefault(COLLAPSED_STICKY, dict((k, True) for k in CLOSED_AT_START))
        self.settings_boxes = {}
        self.settings_note = ""
        self.settings_failed = False

        # 1 Inputs
        self.inputs = forms.Panel()
        self.txt_say = forms.TextBox()
        self.txt_say.PlaceholderText = "Say what to keep or change"
        self.txt_say.KeyDown += self.on_say_key
        self.btn_say = _button("Say", self.on_say)
        self.say_row = forms.Panel()   # the box and its button side by side, or stacked when narrow
        self.say_narrow = None
        self.lnk_redraw = PlainLink("Redraw", lambda s, e: self.card.on_redraw(s, e))
        self.lnk_open = PlainLink("Open a photo", lambda s, e: self.card.on_photo(s, e))
        inputs_col = self._column(self.inputs, self._links(self.lnk_redraw, self.lnk_open), self.say_row)

        # 2 This member
        self.proposal = forms.Panel()

        # 3 Members
        self.grid = forms.GridView()
        self.grid.ShowHeader = True
        self.grid.SelectionChanged += self.on_select_member
        self.grid_columns = None
        self._rows_shown = None
        self.lbl_tally = _wrapping("", muted=True)
        members_col = self._column(self.grid, self.lbl_tally)

        # 4 Settings
        self.settings_box = forms.Panel()
        self.lbl_settings = _wrapping("", muted=True)
        self.btn_apply = _button("Apply", self.on_apply)
        settings_col = self._column(self.settings_box, self.lbl_settings, self.btn_apply)

        # 5 Show
        self.checks = {}
        self.show_box = forms.Panel()
        self.legend = forms.Panel()

        # 6 Record
        self.txt_record = forms.TextArea()
        self.txt_record.ReadOnly = True
        self.txt_record.Wrap = True
        self.txt_record.Height = RECORD_HEIGHT_PX
        self.lnk_undo = PlainLink("Undo last accept", lambda s, e: self.card.undo_accept())
        start_over = PlainLink("Start over", lambda s, e: self.card.start_over())
        record_col = self._column(self.txt_record, self._links(self.lnk_undo, start_over), self._about())

        bodies = {"inputs": inputs_col, "proposal": self.proposal, "members": members_col,
                  "settings": settings_col, "show": self._column(self.show_box, self.legend), "record": record_col}
        self.headers, self.body_rows = {}, {}
        body = forms.TableLayout()
        body.Padding = drawing.Padding(12, 6, 12, 10)
        body.Spacing = drawing.Size(0, 2)
        for key, title in SECTIONS:
            head = SectionHeader(title, (lambda k: lambda: self.toggle(k))(key))
            self.headers[key] = head
            body.Rows.Add(forms.TableRow(forms.TableCell(head, True)))
            wrap = forms.Panel()
            wrap.Content = bodies[key]
            wrap.Padding = drawing.Padding(0, 2, 0, 8)
            self.body_rows[key] = wrap
            body.Rows.Add(forms.TableRow(forms.TableCell(wrap, True)))
        body.Rows.Add(forms.TableRow(forms.TableCell(None, True)))   # the rest of the dock stays empty
        self.control = body
        body.SizeChanged += lambda s, e: self.fit()
        self.load_settings()
        self.render()

    @staticmethod
    def _column(*controls):
        t = forms.TableLayout()
        t.Spacing = drawing.Size(0, 6)
        for c in controls:
            t.Rows.Add(forms.TableRow(forms.TableCell(c, True)))
        return t

    @staticmethod
    def _about():
        """About CRV2FAB, at the foot of Record: the creators and the event, in Daniel's words."""
        import gnj_rhino
        c = gnj_rhino.CREDITS
        return SystemView._column(_label("About CRV2FAB", bold=True),
                                  _wrapping("Credits to the creators: %s." % ", ".join(c["creators"]), muted=True),
                                  _wrapping(c["event"], muted=True),
                                  _wrapping("Version %s, %s licence." % (c["version"], c["licence"]), muted=True))

    @staticmethod
    def _links(*links):
        t = forms.TableLayout()
        t.Spacing = drawing.Size(14, 0)
        t.Rows.Add(forms.TableRow(*([forms.TableCell(lk, False) for lk in links] + [forms.TableCell(None, True)])))
        return t

    # -- sections
    def toggle(self, key):
        self.collapsed[key] = not self.collapsed.get(key, False)
        self.render()

    def _headers(self):
        for key, head in self.headers.items():
            is_open = not self.collapsed.get(key)
            head.show(is_open)
            self.body_rows[key].Visible = is_open

    # -- render from the card's state
    def render(self):
        if self.control is None:
            return
        card, ss = self.card, self.card.session
        w = self.width
        narrow = w < NARROW_BELOW_PX
        drawing_text = tech.gesture_summary(ss) or "none yet"
        self.inputs.Content = pairs_table([("Drawing", drawing_text), ("Model", tech.model_name(card.model_label())),
                                           ("Photo", ss.photo_name or "none")], w)
        self.lnk_redraw.Visible = card.plates
        if narrow != self.say_narrow:
            row = forms.TableLayout()
            row.Spacing = drawing.Size(6, 4)
            if narrow:
                row.Rows.Add(forms.TableRow(forms.TableCell(self.txt_say, True)))
                row.Rows.Add(forms.TableRow(forms.TableCell(self.btn_say, True)))
            else:
                row.Rows.Add(forms.TableRow(forms.TableCell(self.txt_say, True), forms.TableCell(self.btn_say, False)))
            self.say_row.Content = row
            self.say_narrow = narrow
        result = ss.result if ss.phase in ("proposed", "conflict") else None
        rows = tech.check_lines(result)
        if result is not None:   # the card's own Verdict and Reason first, from the same mapping
            sl = ss.slots()
            rows.insert(0, ("Verdict", (sl["verdict"] + " " + sl["reason"]).strip()))
        self.proposal.Content = pairs_table(rows, w, NO_PROPOSAL)
        self._render_members(narrow)
        if ss.tally:
            n, wst = ss.tally
            self.lbl_tally.Text = "Accepted so far: %d member%s, %d%% waste." % (n, "" if n == 1 else "s", int(round(wst)))
        else:
            self.lbl_tally.Text = "Accepted so far: none."
        self._render_settings(w)
        self._render_show()
        self.lnk_undo.set_enabled(bool(ss.members))   # repeated Undo walks back one accept at a time
        lines = []
        for e in ss.record:
            tag = {"accepted": "ACCEPTED", "rejected": "REJECTED", "undone": "UNDONE"}.get(e["v"], e["v"].upper())
            lines.append(tag + "\n" + e["text"])
        self.txt_record.Text = "\n\n".join(lines) or "Each accept or reject is written here in formal terms, newest first."
        self._headers()
        self.fit()

    def _render_members(self, narrow):
        """Member, Kind, Length, Layers, Waste, each column as wide as its longest text. When they do not
        all fit, whole columns go (Layers, then Kind, then Length; never Member or Waste) rather than a
        cell being cut: a number is never truncated. Under NARROW_BELOW_PX, Member and Waste only. The
        grid is as tall as its rows up to MEMBERS_MAX_ROWS, then scrolls inside itself."""
        rows_now = [list(tech.member_cells(m)) for m in self.card.session.members]
        inner = max(120, int(self.width) - 24 - 8)   # the panel's padding and the grid's border

        def need(i):
            texts = [tech.OUTPUT_COLUMNS[i]] + [r[i] for r in rows_now]
            return 7 * max(len(t) for t in texts) + 16
        cols = [0, 4] if narrow else [0, 1, 2, 3, 4]
        for drop in (3, 1, 2):
            if sum(need(i) for i in cols) <= inner or drop not in cols:
                continue
            cols.remove(drop)
        cols = tuple(cols)
        widths = [need(i) for i in cols]
        spare = max(0, inner - sum(widths))
        widths = [w + spare // len(cols) for w in widths]
        key = (cols, tuple(widths))
        if key != getattr(self, "_grid_key", None):
            self.grid.Columns.Clear()
            for i, w in zip(cols, widths):   # fixed widths that add up to the grid: no sideways scroll bar
                col = forms.GridColumn()
                col.HeaderText = tech.OUTPUT_COLUMNS[i]
                col.DataCell = forms.TextBoxCell(i)
                col.Editable = False
                col.AutoSize = False
                col.Width = w
                self.grid.Columns.Add(col)
            self.grid_columns, self._grid_key = cols, key
            self._rows_shown = None
        if rows_now != self._rows_shown:   # rebuild only on change: keeps the selection
            self.grid.DataStore = rows_now
            self._rows_shown = rows_now
        n = min(max(len(rows_now), 1), MEMBERS_MAX_ROWS)
        self.grid.Height = 30 + n * MEMBERS_ROW_PX   # the header and every row, up to the cap

    def _render_settings(self, w):
        ss = self.card.session
        settings = ss.settings
        if settings is None:
            self.settings_box.Content = _wrapping(NO_SETTINGS if self.settings_failed else LOADING_SETTINGS, muted=True)
            self.lbl_settings.Text = ""
            self.lbl_settings.Visible = False
            self.btn_apply.Visible = False
            return
        narrow = w < NARROW_BELOW_PX
        table = forms.TableLayout()
        table.Spacing = drawing.Size(8, 2 if narrow else 4)
        sources = getattr(ss.client, "settings_sources", None) or {}
        for key, label, unit in tech.SETTING_FIELDS:
            if key not in settings:
                continue
            box = self.settings_boxes.get(key)
            if box is None:
                box = forms.TextBox()
                self.settings_boxes[key] = box
            if not box.HasFocus:
                box.Text = tech.format_setting(key, settings.get(key))
            name = _wrapping(label + (" (%s)" % unit if unit else ""), muted=True)
            if sources.get(key):
                name.ToolTip = sources[key]
            if narrow:   # the box takes the full width, its label above it
                table.Rows.Add(forms.TableRow(forms.TableCell(name, True)))
                table.Rows.Add(forms.TableRow(forms.TableCell(box, True)))
            else:
                name.Width = LABEL_COL_PX + 20
                table.Rows.Add(forms.TableRow(forms.TableCell(name, False), forms.TableCell(box, True)))
        self.settings_box.Content = table
        self.lbl_settings.Text = self.settings_note
        self.lbl_settings.Visible = bool(self.settings_note)
        self.btn_apply.Visible = True
        self.btn_apply.Enabled = True

    def _check(self, key, text, enabled=True):
        """A check box whose words wrap at any width: the box, then a wrapping label beside it."""
        cb = self.checks.get(key)
        if cb is None:
            cb = forms.CheckBox()
            cb.CheckedChanged += (lambda k: lambda s, e: self.on_display(k, bool(s.Checked)))(key)
            self.checks[key] = cb
        cb.Enabled = enabled
        if bool(cb.Checked) != bool(self.card.display.get(key)):
            cb.Checked = bool(self.card.display.get(key))
        lbl = _wrapping(text, muted=not enabled)

        def flip(s, e):
            if cb.Enabled:
                cb.Checked = not cb.Checked
        lbl.MouseDown += flip
        return forms.TableRow(forms.TableCell(cb, False), forms.TableCell(lbl, True))

    def _render_show(self):
        card = self.card
        form = card._sent_form(card.session.result) if card.session.can_judge() else {}
        table = forms.TableLayout()
        table.Spacing = drawing.Size(4, 4)
        table.Rows.Add(self._check("billets", "Billets"))
        table.Rows.Add(self._check("outline", "Billet outline"))
        table.Rows.Add(self._check("cuts", "Cut lines", bool(form.get("cuts"))))
        if hasattr(card.scene, "srf"):   # the Surface group, only on a surface scene
            table.Rows.Add(forms.TableRow(forms.TableCell(None, False), forms.TableCell(_label("Surface", bold=True), True)))
            for key, text in SURFACE_KEYS:
                table.Rows.Add(self._check(key, text))
        self.show_box.Content = table
        self._render_legend()

    def _render_legend(self):
        card = self.card
        kind = next((k for k in COLOUR_MAPS if card.display.get(k)), None)
        if kind is None or not hasattr(card.scene, "srf"):
            self.legend.Content = None
            return
        _, legend = card.scene.curvature_overlay(kind, tech.limit_radius_mm(card.session))
        table = forms.TableLayout()
        table.Spacing = drawing.Size(8, 2)
        for rgb, text in legend:
            swatch = forms.Panel()
            swatch.Size = drawing.Size(14, 14)
            swatch.BackgroundColor = drawing.Color.FromArgb(*(tuple(rgb) + (255,)))
            table.Rows.Add(forms.TableRow(forms.TableCell(swatch, False), forms.TableCell(_wrapping(text), True)))
        self.legend.Content = table

    def fit(self):
        """After layout (WPF dispatcher, Background priority): a change of width across
        NARROW_BELOW_PX re-lays the rows."""
        try:
            import clr
            clr.AddReference("WindowsBase")
            import System.Windows.Threading as threading_wpf
            self.control.ControlObject.Dispatcher.BeginInvoke(threading_wpf.DispatcherPriority.Background,
                                                              System.Action(self._fit_now))
        except Exception:
            self._fit_now()

    def _fit_now(self):
        if self.card.closed or self.control is None:
            return
        try:
            width = int(self.control.ControlObject.ActualWidth or SYSTEM_WIDTH)
            if (width < NARROW_BELOW_PX) != (self.width < NARROW_BELOW_PX) or abs(width - self.width) > 40:
                self.width = width
                self.render()
        except Exception as ex:
            Rhino.RhinoApp.WriteLine("GNJ: System panel cannot follow its width (%s)" % ex)

    # -- actions
    def on_say(self, sender, e):
        text = self.txt_say.Text
        self.txt_say.Text = ""
        self.card.say_text(text)

    def on_say_key(self, sender, e):
        if e.Key == forms.Keys.Enter:
            e.Handled = True
            self.on_say(sender, e)

    def on_display(self, key, on):
        if bool(self.card.display.get(key)) == on:
            return
        if on and key in COLOUR_MAPS:   # one colour map at a time
            for other in COLOUR_MAPS:
                if other != key:
                    self.card.display[other] = False
        self.card.set_display(key, on)

    def on_select_member(self, sender, e):
        """Selecting a row selects that member in Rhino. The view is not zoomed or moved."""
        i = self.grid.SelectedRow
        members = self.card.session.members
        if i is None or not 0 <= i < len(members):
            return
        sc.doc.Objects.UnselectAll()
        for oid in members[i]["object_ids"]:
            sc.doc.Objects.Select(oid)
        sc.doc.Views.Redraw()

    def load_settings(self):
        """GET /settings in the background; nothing is editable until the core answers."""
        client = self.card.session.client

        def work():
            got = client.settings()

            def back():
                if self.card.closed:
                    return
                self.card.session.settings = got
                self.settings_failed = got is None
                self.render()
            Rhino.RhinoApp.InvokeOnUiThread(System.Action(back))
        th = threading.Thread(target=work)
        th.daemon = True
        th.start()

    def on_apply(self, sender, e):
        """POST only what changed; show the core's answer; then re-solve the current proposal."""
        ss = self.card.session
        if ss.settings is None:
            return
        try:
            changes = tech.changed_settings(ss.settings, dict((k, b.Text) for k, b in self.settings_boxes.items()))
        except ValueError as ex:
            self.settings_note = "%s" % ex
            self.render()
            return
        if not changes:
            self.settings_note = "Nothing changed."
            self.render()
            return
        client = ss.client
        self.btn_apply.Enabled = False
        self.settings_note = "Saving."   # never a stale "Saved." from the last time
        self.lbl_settings.Text = self.settings_note

        def work():
            got = client.post_settings(changes)

            def back():
                if self.card.closed:
                    return
                if got is None:
                    self.settings_note = "Not saved: %s" % tech.core_reason(client.last_error)
                    self.render()
                    return
                ss.settings = got.get("settings") if isinstance(got.get("settings"), dict) else got
                self.settings_note = "Saved."
                self.card.start(ss.has_gesture() and ss.phase in ("proposed", "conflict", "rejected"))
            Rhino.RhinoApp.InvokeOnUiThread(System.Action(back))
        th = threading.Thread(target=work)
        th.daemon = True
        th.start()


class SystemWindow(forms.Form):
    """For now: the System panel in a plain tall window beside Rhino."""

    def __new__(cls, *args, **kwargs):
        return forms.Form.__new__(cls)

    def __init__(self, view, on_closed):
        self.Title = "CRV2FAB"
        icon = window_icon()
        if icon is not None:
            self.Icon = icon
        self.ClientSize = drawing.Size(SYSTEM_WIDTH, 820)
        self.Resizable = True
        self.Minimizable = False
        self.Content = view.control
        self.Closed += lambda s, e: on_closed()


DOCK_STICKY = "gnj_crv2fab_panel_type"   # survives re-runs of the script within one Rhino session


def _panel_type():
    """The panel class Rhino needs: public, Guid-attributed, deriving Eto.Forms.Panel, with a
    parameterless and a uint constructor and a static Instance field. Built with Reflection.Emit,
    in memory only: no compiler, no temporary files, nothing on disk. Built once per Rhino session."""
    import clr
    from System.Reflection import AssemblyName, CallingConventions, FieldAttributes, MethodAttributes, TypeAttributes
    from System.Reflection.Emit import AssemblyBuilderAccess, CustomAttributeBuilder, OpCodes
    base = clr.GetClrType(forms.Panel)
    asm = System.AppDomain.CurrentDomain.DefineDynamicAssembly(AssemblyName("Crv2fabPanel"), AssemblyBuilderAccess.Run)
    tb = asm.DefineDynamicModule("Crv2fabPanel").DefineType("Crv2fab.SystemPanel",
                                                            TypeAttributes.Public | TypeAttributes.Class, base)
    guid_attr = clr.GetClrType(System.Runtime.InteropServices.GuidAttribute)
    tb.SetCustomAttribute(CustomAttributeBuilder(guid_attr.GetConstructor(System.Array[System.Type]([clr.GetClrType(str)])),
                                                 System.Array[System.Object]([DOCK_GUID])))
    instance = tb.DefineField("Instance", base, FieldAttributes.Public | FieldAttributes.Static)
    ctor0 = tb.DefineConstructor(MethodAttributes.Public, CallingConventions.Standard, System.Type.EmptyTypes)
    il = ctor0.GetILGenerator()
    il.Emit(OpCodes.Ldarg_0)
    il.Emit(OpCodes.Call, base.GetConstructor(System.Type.EmptyTypes))
    il.Emit(OpCodes.Ldarg_0)
    il.Emit(OpCodes.Stsfld, instance)
    il.Emit(OpCodes.Ret)
    ctor1 = tb.DefineConstructor(MethodAttributes.Public, CallingConventions.Standard,
                                 System.Array[System.Type]([clr.GetClrType(System.UInt32)]))
    il = ctor1.GetILGenerator()
    il.Emit(OpCodes.Ldarg_0)
    il.Emit(OpCodes.Call, ctor0)
    il.Emit(OpCodes.Ret)
    return tb.CreateType()


def dock_in_panel(view):
    """A true docked tab, "CRV2FAB", in Rhino's right-hand panel area: one panel registered for this
    Rhino session under the IronPython plug-in, opened beside Layers (or Properties). Nothing is
    installed and nothing is written to disk. A re-run reuses the registered panel and swaps in the
    new content, so there is never a second tab. Raises on any failure; the caller falls back."""
    guid = System.Guid(DOCK_GUID)
    ptype = sc.sticky.get(DOCK_STICKY)
    if ptype is None:
        ptype = _panel_type()
        plugin = None
        for kv in Rhino.PlugIns.PlugIn.GetInstalledPlugIns():   # a .NET Dictionary: KeyValuePairs
            if "python" in (kv.Value or "").lower():
                plugin = Rhino.PlugIns.PlugIn.Find(kv.Key)
                if plugin is not None:
                    break
        if plugin is None:
            raise RuntimeError("the IronPython plug-in was not found")
        Rhino.UI.Panels.RegisterPanel(plugin, ptype, "CRV2FAB", app_icon())
        sc.sticky[DOCK_STICKY] = ptype
    if not list(Rhino.UI.Panels.PanelDockBars(guid) or []):
        anchor = None
        for pid in (Rhino.UI.PanelIds.Layers, Rhino.UI.PanelIds.ObjectProperties):
            if Rhino.UI.Panels.IsPanelVisible(pid):
                anchor = pid
                break
        if anchor is None:
            anchor = Rhino.UI.PanelIds.Layers
            Rhino.UI.Panels.OpenPanel(anchor)
        Rhino.UI.Panels.OpenPanelAsSibling(guid, anchor)
    Rhino.UI.Panels.OpenPanel(guid)   # select the tab: Rhino builds a panel's content on first selection
    Rhino.RhinoApp.Wait()
    inst = ptype.GetField("Instance").GetValue(None)
    if inst is None:
        raise RuntimeError("Rhino did not create the panel")
    inst.Content = view.control
    return True


def close_docked():
    """Close the tab (it stays registered for the session, so the next run reuses it)."""
    ptype = sc.sticky.get(DOCK_STICKY)
    if ptype is not None:
        inst = ptype.GetField("Instance").GetValue(None)
        if inst is not None:
            inst.Content = None   # no dead content from a closed card
        Rhino.UI.Panels.ClosePanel(System.Guid(DOCK_GUID))
