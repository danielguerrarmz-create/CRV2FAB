# -*- coding: utf-8 -*-
"""Document set-up: units, layers, the straight member's frame, views (never the active one)."""
from gnj_rhino.common import *  # noqa: F401,F403


# ---------------------------------------------------------------- document setup

def mm():
    """Millimetres to document units."""
    return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Millimeters, sc.doc.ModelUnitSystem)


def _dashed_linetype():
    for i in range(sc.doc.Linetypes.Count):
        lt = sc.doc.Linetypes[i]
        if not lt.IsDeleted and lt.Name in ("Dashed", "GNJ Dashed"):
            return lt.LinetypeIndex
    lt = Rhino.DocObjects.Linetype()
    lt.Name = "GNJ Dashed"
    lt.AppendSegment(12.0, True)
    lt.AppendSegment(6.0, False)
    return sc.doc.Linetypes.Add(lt)


def ensure_layer(path, color=None, linetype=None):
    idx = sc.doc.Layers.FindByFullPath(path, -1)
    if idx < 0:
        parent_id = System.Guid.Empty
        name = path
        if "::" in path:
            parent_path, name = path.rsplit("::", 1)
            parent_id = sc.doc.Layers[ensure_layer(parent_path)].Id
        layer = Rhino.DocObjects.Layer()
        layer.Name = name
        layer.ParentLayerId = parent_id
        if color is not None:
            layer.Color = color
        if linetype is not None:
            layer.LinetypeIndex = linetype
        idx = sc.doc.Layers.Add(layer)
    return idx


class Frame(object):
    """The member's long axis: origin at one end on the centreline, unit axis, width and up."""

    def __init__(self, bbox):
        s = mm()
        dx, dy = bbox.Max.X - bbox.Min.X, bbox.Max.Y - bbox.Min.Y
        cz = 0.5 * (bbox.Min.Z + bbox.Max.Z)
        if dx >= dy:
            self.origin = rg.Point3d(bbox.Min.X, 0.5 * (bbox.Min.Y + bbox.Max.Y), cz)
            self.axis, self.width, self.length = rg.Vector3d.XAxis, rg.Vector3d.YAxis, dx
        else:
            self.origin = rg.Point3d(0.5 * (bbox.Min.X + bbox.Max.X), bbox.Min.Y, cz)
            self.axis, self.width, self.length = rg.Vector3d.YAxis, rg.Vector3d.XAxis, dy
        self.up = rg.Vector3d.ZAxis
        self.s = s
        self.bbox = bbox


def setup():
    """Layers, the 2x4 if none exists, shaded views zoomed to it. Returns the member Frame."""
    ensure_layer(LAYER_ROOT)
    ensure_layer(LAYER_EXISTING, EXISTING_COLOR)
    ensure_layer(LAYER_GESTURE, System.Drawing.Color.FromArgb(30, 30, 30), _dashed_linetype())
    buildable_layer()

    layer = sc.doc.Layers[sc.doc.Layers.FindByFullPath(LAYER_EXISTING, -1)]
    objs = [o for o in (sc.doc.Objects.FindByLayer(layer) or []) if o.ObjectType != Rhino.DocObjects.ObjectType.Curve]
    if not objs:
        s = mm()
        box = rg.Box(rg.Plane.WorldXY,
                     rg.Interval(0, core.LENGTH_MM * s),
                     rg.Interval(-core.WIDTH_MM / 2 * s, core.WIDTH_MM / 2 * s),
                     rg.Interval((LIFT_MM - core.STOCK_MM / 2) * s, (LIFT_MM + core.STOCK_MM / 2) * s))
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = layer.Index
        attrs.Name = "M1 softwood 2x4, 38 x 89 x 2400"
        sc.doc.Objects.AddBrep(box.ToBrep(), attrs)
        objs = list(sc.doc.Objects.FindByLayer(layer))
    bbox = rg.BoundingBox.Empty
    for o in objs:
        bbox.Union(o.Geometry.GetBoundingBox(True))
    frame = Frame(bbox)

    zoom = rg.BoundingBox(bbox.Min, bbox.Max)
    pad = 700 * frame.s  # room on every side to draw the gesture, in any direction
    zoom.Union(bbox.Min - rg.Vector3d(pad, pad, pad))
    zoom.Union(bbox.Max + rg.Vector3d(pad, pad, pad))
    shaded = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    for name in ("Perspective", "Front", "Top", "Right"):
        view = sc.doc.Views.Find(name, False)
        if view is None:
            continue
        if shaded is not None:
            view.ActiveViewport.DisplayMode = shaded
        view.ActiveViewport.ZoomBoundingBox(zoom)
    perspective_tip()
    sc.doc.Views.Redraw()
    return frame


def perspective_tip():
    """The script never changes which view is active, never maximizes, never changes a projection:
    the designer must be free to orbit at any time. It only says where orbiting works."""
    view = sc.doc.Views.ActiveView
    if view is None or not view.ActiveViewport.IsPerspectiveProjection:
        Rhino.RhinoApp.WriteLine("GNJ: Tip: draw in Perspective to orbit freely.")


def move_to_gesture_layer(obj_id):
    obj = sc.doc.Objects.FindId(obj_id)
    if obj is None:
        return
    attrs = obj.Attributes.Duplicate()
    attrs.LayerIndex = ensure_layer(LAYER_GESTURE)
    attrs.LinetypeSource = Rhino.DocObjects.ObjectLinetypeSource.LinetypeFromLayer
    sc.doc.Objects.ModifyAttributes(obj_id, attrs, True)


def zoom_views(bbox):
    shaded = Rhino.Display.DisplayModeDescription.FindByName("Shaded")
    for name in ("Perspective", "Front", "Top", "Right"):
        view = sc.doc.Views.Find(name, False)
        if view is None:
            continue
        if shaded is not None:
            view.ActiveViewport.DisplayMode = shaded
        view.ActiveViewport.ZoomBoundingBox(bbox)
    perspective_tip()
    sc.doc.Views.Redraw()


def buildable_layer():
    """GNJ::Buildable in the timber colour. A layer left blue by an earlier version is recoloured: only
    this layer, so only accepted members change colour, never the designer's own objects."""
    idx = ensure_layer(LAYER_BUILDABLE, TIMBER_COLOR)
    layer = sc.doc.Layers[idx]
    if layer.Color.ToArgb() == GHOST_COLOR.ToArgb():
        layer.Color = TIMBER_COLOR
        sc.doc.Layers.Modify(layer, idx, True)
    return idx


def billets_layer():
    """GNJ::Buildable::Billets: billet pink, its render material translucent. Each billet also carries
    BILLET_DISPLAY_MODE (Wireframe), so in any view it is drawn as its edges only."""
    buildable_layer()
    idx = ensure_layer(LAYER_BILLETS, BILLET_FILL)
    layer = sc.doc.Layers[idx]
    if layer.RenderMaterialIndex < 0:
        mat = Rhino.DocObjects.Material()
        mat.Name = "GNJ billet"
        mat.DiffuseColor = BILLET_FILL
        mat.Transparency = BILLET_TRANSPARENCY
        layer.RenderMaterialIndex = sc.doc.Materials.Add(mat)
        sc.doc.Layers.Modify(layer, idx, True)
    return idx


def has_bend_member():
    idx = sc.doc.Layers.FindByFullPath(LAYER_EXISTING, -1)
    if idx < 0:
        return False
    objs = sc.doc.Objects.FindByLayer(sc.doc.Layers[idx]) or []
    return any(o.ObjectType != Rhino.DocObjects.ObjectType.Curve for o in objs)

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
