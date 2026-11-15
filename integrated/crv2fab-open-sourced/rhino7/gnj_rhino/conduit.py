# -*- coding: utf-8 -*-
"""The viewport: the ghost, and the overlays the System panel turns on."""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403
from gnj_rhino.gesture import *  # noqa: F401,F403
from gnj_rhino.geometry import *  # noqa: F401,F403
from gnj_rhino.scenes import *  # noqa: F401,F403


class GhostConduit(Rhino.Display.DisplayConduit):
    """Draws the proposal. It is never in the document while it is only a proposal."""

    def __init__(self):
        self.brep = None
        self.glue = []
        self.dashes = []
        self.intent = []       # v9: the dashed outline of what was read (intent_grid), 2 px dark, on top
        self.edges = []        # the ghost's edges, drawn crisp over its translucent fill
        self.billets = []      # each piece's billet, a translucent box around the ghost
        self.billet_edges = []
        self.billet_material = Rhino.Display.DisplayMaterial(BILLET_FILL, BILLET_TRANSPARENCY)
        self.outline = []      # Show: the billet outline
        self.meshes = []       # Display: the host surface coloured, [(mesh, DisplayMaterial)]
        self.bbox = rg.BoundingBox.Empty
        self.material = Rhino.Display.DisplayMaterial(GHOST_FILL, GHOST_TRANSPARENCY)

    def show(self, brep, glue, dashes=(), intent=()):
        """brep None: nothing of ours to draw but the lines (a part is the designer's own geometry).
        intent: the dashes of the outline of what was read, drawn over everything."""
        self.brep, self.glue, self.dashes, self.intent = brep, glue, list(dashes), list(intent)
        self.edges = [ed.DuplicateCurve() for ed in brep.Edges] if brep is not None else []
        self._update()

    def clear(self):
        self.brep, self.glue, self.dashes, self.intent, self.edges = None, [], [], [], []
        self.billets, self.billet_edges = [], []
        self._update()

    def show_billets(self, breps):
        """The billets of the proposal on screen ([] hides them)."""
        self.billets = list(breps)
        self.billet_edges = [ed.DuplicateCurve() for b in self.billets for ed in b.Edges]
        self._update()

    def overlays(self, coloured=(), outline=()):
        """coloured: [(mesh, rgb)], drawn shaded at OVERLAY_OPACITY over the surface so its shading
        shows through. overlays() with no arguments removes every overlay."""
        self.meshes = [(m, Rhino.Display.DisplayMaterial(System.Drawing.Color.FromArgb(*rgb), 1.0 - OVERLAY_OPACITY))
                       for m, rgb in coloured]
        self.outline = list(outline)
        self._update()

    def _update(self):
        bb = rg.BoundingBox.Empty
        if self.brep is not None:
            bb = self.brep.GetBoundingBox(False)
        for b in self.billets:
            bb = rg.BoundingBox.Union(bb, b.GetBoundingBox(False))
        for pl in self.outline:
            bb = rg.BoundingBox.Union(bb, pl.BoundingBox)  # static form: no struct mutation through an attribute
        for ln in self.intent:
            bb = rg.BoundingBox.Union(bb, ln.BoundingBox)
        for m, _ in self.meshes:
            bb = rg.BoundingBox.Union(bb, m.GetBoundingBox(False))
        self.bbox = bb
        self.Enabled = (self.brep is not None or bool(self.meshes) or bool(self.outline) or bool(self.dashes)
                        or bool(self.intent) or bool(self.billets))

    def CalculateBoundingBox(self, e):
        if self.Enabled:
            e.IncludeBoundingBox(self.bbox)

    def PostDrawObjects(self, e):
        for m, mat in self.meshes:
            e.Display.DrawMeshShaded(m, mat)
        if self.billets:   # first, writing no depth, so the ghost inside reads through them
            e.Display.PushDepthWriting(False)
            try:
                for b in self.billets:
                    e.Display.DrawBrepShaded(b, self.billet_material)
            finally:
                e.Display.PopDepthWriting()
            for c in self.billet_edges:
                e.Display.DrawCurve(c, BILLET_EDGE, BILLET_EDGE_PX)
        if self.brep is not None:
            # A ghost writes no depth: what lies behind its fill (the member it reshapes, its own far
            # faces) still draws, so the fill only tints it.
            e.Display.PushDepthWriting(False)
            try:
                e.Display.DrawBrepShaded(self.brep, self.material)
            finally:
                e.Display.PopDepthWriting()
            for c in self.edges:
                e.Display.DrawCurve(c, GHOST_COLOR, GHOST_EDGE_PX)
            for c in self.glue:
                e.Display.DrawCurve(c, GHOST_EDGE_COLOR, 1)
        for ln in self.dashes:          # cut lines: there may be no ghost (a part is the designer's own)
            e.Display.DrawLine(ln, CUT_COLOR, 2)

    def DrawForeground(self, e):
        # The billet wraps the member and passes through the surface: drawn over everything, thin,
        # so it reads while Technical is open.
        for pl in self.outline:
            e.Display.DrawPolyline(pl, GHOST_EDGE_COLOR, 1)
        for ln in self.intent:   # what was read: dashed, dark, over the ghost (SPEC_V9_UI, Daniel 2026-11-15)
            e.Display.DrawLine(ln, STROKE_COLOR, INTENT_PX)


def bake(scene, form, user_text=(), billets=()):
    """Add the accepted form to GNJ::Buildable as one group, the member's Brep carrying user_text
    [(key, text)]; and each billet [(brep, label)] as a closed Brep with a TextDot on
    GNJ::Buildable::Billets. One undo record. Returns (member ids, billet ids)."""
    brep, glue, _ = scene.ghost(form)
    name = scene.name(form)
    attrs = Rhino.DocObjects.ObjectAttributes()
    attrs.LayerIndex = buildable_layer()
    attrs.WireDensity = -1   # an accepted member reads as one piece of timber: no interior isocurves
    attrs.Name = name
    member = attrs.Duplicate()
    for k, v in user_text:
        member.SetUserString(k, v)
    undo = sc.doc.BeginUndoRecord("GNJ Accept")
    billet_ids = []
    try:
        ids = [sc.doc.Objects.AddBrep(brep, member)]
        ids.extend(sc.doc.Objects.AddCurve(c, attrs) for c in glue)
        if len(ids) > 1:
            sc.doc.Groups.Add(name, System.Collections.Generic.List[System.Guid](ids))
        if billets:
            battrs = Rhino.DocObjects.ObjectAttributes()
            battrs.LayerIndex = billets_layer()
            battrs.WireDensity = -1   # a billet reads as one box: edges only, no isocurve hatch
            battrs.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
            battrs.ObjectColor = BILLET_EDGE
            mode = Rhino.Display.DisplayModeDescription.FindByName(BILLET_DISPLAY_MODE)
            for b, label in billets:
                one = battrs.Duplicate()
                one.Name = label
                if mode is not None:
                    one.SetDisplayModeOverride(mode)
                billet_ids.append(sc.doc.Objects.AddBrep(b, one))
                billet_ids.append(sc.doc.Objects.AddTextDot(label, b.GetBoundingBox(False).Center, battrs))
    finally:
        sc.doc.EndUndoRecord(undo)
    return ids, billet_ids

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
