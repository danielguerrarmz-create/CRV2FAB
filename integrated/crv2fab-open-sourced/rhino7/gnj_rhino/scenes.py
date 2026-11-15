# -*- coding: utf-8 -*-
"""What strokes are drawn over: the member to reshape into a plate (v9) or a surface (v3 on)."""
from gnj_rhino.common import *  # noqa: F401,F403
from gnj_rhino.doc import *  # noqa: F401,F403
from gnj_rhino.gesture import *  # noqa: F401,F403
from gnj_rhino.geometry import *  # noqa: F401,F403


# ---------------------------------------------------------------- scenes
# A scene is what the strokes are drawn over. The panel only talks to these:
#   ghost(form, display) -> (brep, glue_curves, dash_lines)
#   place(point_mm) -> Point3d: a point the core sent, in the model
#   name(form) -> object name for the baked member
#   bbox -> what the views zoom to
# The plate scene also reads strokes (read_stroke) and gives the end planes; the surface scene reads
# one stroke on its surface (gesture).

class PlateScene(object):
    """Spec v9: three strokes reshape the member on GNJ::Existing into a plate. The core works in its
    own frame (the straight 2x4 from (0, 0, 0) to (2400, 0, 0), mm, Z up); this scene carries points
    both ways between that frame and the member in the model."""
    idle_text = "Draw the shape you want."
    idle_sub = "Path, start and end. Skip any you do not need."
    redraw_text = "Redraw a stroke, or say what to keep."
    again_text = "Draw again to change this member."
    shape_word = "shape"
    plate = True

    def __init__(self, frame):
        self.frame = frame
        self.bbox = frame.bbox
        self.model_name = "the straight timber"
        idx = sc.doc.Layers.FindByFullPath(LAYER_EXISTING, -1)
        for o in (sc.doc.Objects.FindByLayer(sc.doc.Layers[idx]) or []) if idx >= 0 else []:
            if o.ObjectType != Rhino.DocObjects.ObjectType.Curve:
                self.model_name = o.Attributes.Name or "an unnamed member on " + LAYER_EXISTING
                break

    # -- the two frames
    def place(self, p):
        """Core mm -> the model (document units)."""
        f, s = self.frame, self.frame.s
        return f.origin + f.axis * (p[0] * s) + f.width * (p[1] * s) + f.up * (p[2] * s)

    def direction(self, v):
        f = self.frame
        out = f.axis * v[0] + f.width * v[1] + f.up * v[2]
        out.Unitize()
        return out

    def to_core(self, p):
        """The model -> core mm."""
        f, s = self.frame, self.frame.s
        d = p - f.origin
        return [round(d * f.axis / s, 3), round(d * f.width / s, 3), round(d * f.up / s, 3)]

    def end_plane(self, which, current):
        """The plane square to the current member at that end: x across, y the normal (spec v9)."""
        e = current["end_frames"][which]
        return rg.Plane(self.place(e["origin"]), self.direction(e["across"]), self.direction(e["normal"]))

    def middle(self, current):
        st = current["stations"]
        return self.place(st[len(st) // 2])

    def path_plane(self, viewport, current):
        """("upright" or "flat", Plane): Daniel, 2026-11-15. The current member's upright plane (through
        its axis, holding world Z) or its flat plane (horizontal, through its axis), whichever the view
        faces more; a tie goes upright."""
        st = current["stations"]
        mid = self.middle(current)
        axis = self.place(st[-1]) - self.place(st[0])
        if viewport.IsPerspectiveProjection:
            look = mid - viewport.CameraLocation
        else:
            look = rg.Vector3d(viewport.CameraDirection)
        kind = core.path_plane((look.X, look.Y, look.Z), (axis.X, axis.Y, axis.Z))
        if kind == "flat":
            return kind, rg.Plane(mid, rg.Vector3d.ZAxis)
        across = rg.Vector3d.CrossProduct(axis, rg.Vector3d.ZAxis)
        return kind, rg.Plane(mid, across)

    def read_stroke(self, which, curve, viewport, current):
        """A sketched stroke -> (core mm, plane kind). Start and End lie on their end plane (kind None);
        the Path is carried along the view onto the member's upright or flat plane (path_plane)."""
        kind = None
        if which != "path":
            plane = self.end_plane(which, current)
        elif viewport is not None:
            kind, plane = self.path_plane(viewport, current)
        else:
            plane = None
        pts = stroke_points(curve, viewport, plane) if plane is not None else (
            _curve_points(curve, 120) if curve is not None else None)
        return (None if pts is None else [self.to_core(p) for p in pts]), kind

    # -- what the panel draws
    def ghost(self, form, display=False):
        brep = plate_geometry(form, self.place, GHOST_DISPLAY_INFLATE_MM if display else 0.0)
        return brep, [], []

    def intent_outline(self, form):
        """The dashed outline of what was read (intent_grid), in the model: 30 mm dashes, 20 mm gaps."""
        s = self.frame.s
        return dashed(grid_outline(form["intent_grid"], self.place), 30.0 * s, 20.0 * s)

    def curvature_overlay(self, kind, limit_mm=None):
        """No host surface on a straight timber."""
        return [], []

    def name(self, form):
        return "M1 plate, %s, %s" % (core.m(form.get("length_mm") or core.LENGTH_MM), core.makeup(form))


class SurfaceScene(object):
    """v3: a stroke drawn over a doubly curved surface becomes a member lying on it."""
    idle_text = "Draw a line on the surface."
    redraw_text = "Redraw on the surface, or say what to keep."
    again_text = "Draw again to try another line."
    shape_word = "line"
    idle_sub = ""

    def __init__(self, srf, model_name="a surface"):
        self.srf = srf
        self.model_name = model_name
        self.s = mm()
        self.du, self.dv = srf.Domain(0), srf.Domain(1)
        self.bbox = srf.GetBoundingBox(True)
        self.grid = core.grid_from(self.evaluate)

    def evaluate(self, u, v):
        p = self.srf.PointAt(self.du.ParameterAt(u), self.dv.ParameterAt(v))
        return p.X / self.s, p.Y / self.s, p.Z / self.s

    def _uv(self, p, viewport):
        """Normalized (u, v) of a drawn point on the surface, or None when it misses."""
        if viewport is None:
            ok, u, v = self.srf.ClosestPoint(p)
            if not ok:
                return None
        else:
            if viewport.IsPerspectiveProjection:
                cam = viewport.CameraLocation
                ray = rg.LineCurve(cam, cam + (p - cam) * 100.0)
            else:
                look = viewport.CameraDirection
                look.Unitize()
                far = self.bbox.Diagonal.Length * 4 + (p - self.bbox.Center).Length * 2
                ray = rg.LineCurve(p - look * far, p + look * far)
            tol = sc.doc.ModelAbsoluteTolerance
            hits = rg.Intersect.Intersection.CurveSurface(ray, self.srf, tol, tol)
            pts = [h for h in (hits or []) if h.IsPoint]
            if not pts:
                return None
            first = min(pts, key=lambda h: h.ParameterA)  # the hit nearest the eye
            u, v = first.SurfacePointParameter()
        return self.du.NormalizedParameterAt(u), self.dv.NormalizedParameterAt(v)

    def gesture(self, session, curve, viewport):
        uv = [q for q in (self._uv(p, viewport) for p in _curve_points(curve)) if q is not None]
        stroke = core.clean_stroke_uv(uv)
        if stroke is None:
            return False, "That line misses the surface. Draw over the grey surface.", None
        pts = [self.srf.PointAt(self.du.ParameterAt(u), self.dv.ParameterAt(v)) for u, v in stroke]
        on_surface = rg.Curve.CreateInterpolatedCurve(pts, 3) if len(pts) > 2 else rg.LineCurve(pts[0], pts[-1])
        return session.stroke_on_surface(core.surface_intent(self.grid, stroke)), "", on_surface

    def place(self, p):
        """Core mm -> the model: a surface member is sent in world mm."""
        return rg.Point3d(p[0] * self.s, p[1] * self.s, p[2] * self.s)

    def read_curve(self, form):
        """The core's cleaned intent: hand jitter removed, on the surface."""
        pts = [rg.Point3d(x * self.s, y * self.s, z * self.s) for x, y, z in form.get("intent_stations") or []]
        return rg.Curve.CreateInterpolatedCurve(pts, 3) if len(pts) > 2 else None

    def ghost(self, form, display=False):
        """Spec v4: the member is milled from one pressed billet, so the ghost carries no glue lines."""
        lift = GHOST_DISPLAY_INFLATE_MM if display else 0.0
        brep, _, dashes = surface_member_geometry(form, self.s, lift, 0.0)
        return brep, [], dashes

    def outline(self, form):
        """The billet's outline as thin polylines, or [] when the core sent none."""
        b = form.get("billet") or {}
        return [rg.Polyline([rg.Point3d(x * self.s, y * self.s, z * self.s) for x, y, z in poly])
                for poly in b.get("outline") or [] if len(poly) > 1]

    def _samples(self):
        """Rhino's own principal curvatures at CURVATURE_SAMPLES x CURVATURE_SAMPLES points, once per
        scene: (n, points lifted OVERLAY_LIFT_MM off the surface, [(k1, k2) in 1/mm]). The lift clears
        the surface's own render mesh, whose flat facets poked through at 1 mm."""
        if getattr(self, "_curv", None) is None:
            n = CURVATURE_SAMPLES
            pts, ks = [], []
            for i in range(n):
                for j in range(n):
                    u, v = self.du.ParameterAt(i / (n - 1.0)), self.dv.ParameterAt(j / (n - 1.0))
                    k = self.srf.CurvatureAt(u, v)
                    p = self.srf.PointAt(u, v)
                    if k is not None:
                        ks.append((k.Kappa(0) / self.s, k.Kappa(1) / self.s))
                        p = p + k.Normal * (OVERLAY_LIFT_MM * self.s)
                    else:
                        ks.append((0.0, 0.0))
                    pts.append(p)
            self._curv = (n, pts, ks)
        return self._curv

    def curvature_overlay(self, kind, limit_mm=None):
        """kind "type" (flat, singly curved, dome, saddle) or "radius" (tightest radius, from the
        bend limit to flat). Returns ([(mesh, rgb)], [(rgb, legend text)]): one mesh per colour, so
        the conduit can draw each shaded and translucent over the surface."""
        n, pts, ks = self._samples()
        if kind == "type":
            keys = [tech.classify(k1, k2) for k1, k2 in ks]
            colours = dict((c, tech.CURVATURE_RGB[c]) for c in tech.CURVATURE_CLASSES)
            total = float(len(keys))
            legend = [(tech.CURVATURE_RGB[c], "%s  %d%%" % (tech.CURVATURE_LABELS[c],
                                                           int(round(100 * keys.count(c) / total))))
                      for c in tech.CURVATURE_CLASSES]
        else:
            keys = [tech.radius_bin(tech.tightest_radius_mm(k1, k2), limit_mm) for k1, k2 in ks]
            colours = dict(enumerate(tech.RADIUS_RGB))
            legend = tech.radius_legend(limit_mm)
        meshes = {}
        for i in range(n - 1):
            for j in range(n - 1):
                a = i * n + j
                key = keys[a]
                m = meshes.get(key)
                if m is None:
                    m = meshes[key] = rg.Mesh()
                base = m.Vertices.Count
                for idx in (a, a + n, a + n + 1, a + 1):
                    m.Vertices.Add(pts[idx])
                m.Faces.AddFace(base, base + 1, base + 2, base + 3)
        out = []
        for key, m in meshes.items():
            m.Normals.ComputeNormals()
            out.append((m, colours[key]))
        return out, legend

    def name(self, form):
        return "M1 on surface, %s, %s" % (core.m(form["length_mm"]), core.makeup(form))


def setup_surface():
    """v3 scene: a selected surface, else the one on GNJ::Reference, else the sample saddle there."""
    ensure_layer(LAYER_ROOT)
    ref_idx = ensure_layer(LAYER_REFERENCE, EXISTING_COLOR)
    ensure_layer(LAYER_GESTURE, System.Drawing.Color.FromArgb(30, 30, 30), _dashed_linetype())
    buildable_layer()
    srf, name = None, None
    for o in sc.doc.Objects.GetSelectedObjects(False, False):
        srf = surface_of(o)
        if srf is not None:
            name = o.Attributes.Name or "the selected surface"
            break
    if srf is None:
        for o in sc.doc.Objects.FindByLayer(sc.doc.Layers[ref_idx]) or []:
            srf = surface_of(o)
            if srf is not None:
                name = o.Attributes.Name or "the surface on " + LAYER_REFERENCE
                break
    if srf is None:
        srf = saddle_surface()
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = ref_idx
        attrs.Name = name = "Reference saddle"
        sc.doc.Objects.AddSurface(srf, attrs)
    sc.doc.Objects.UnselectAll()
    scene = SurfaceScene(srf, name)
    zoom_views(scene.bbox)
    return scene


def choose_scene():
    """The v9 plate scene by default, also in a brand new empty document (Daniel, 2026-11-15): setup()
    puts the starting straight 2x4 on GNJ::Existing and nothing else. A surface scene only when a
    surface is selected or GNJ::Reference already holds one."""
    selected_srf = any(surface_of(o) is not None for o in sc.doc.Objects.GetSelectedObjects(False, False))
    ref = sc.doc.Layers.FindByFullPath(LAYER_REFERENCE, -1)
    has_ref = ref >= 0 and bool(sc.doc.Objects.FindByLayer(sc.doc.Layers[ref]))
    if selected_srf or has_ref:
        return setup_surface()
    return PlateScene(setup())

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
