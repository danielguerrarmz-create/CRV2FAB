"""
CRV2FAB - shared library for the double-curved glulam Grasshopper definition
============================================================================
Keep this file NEXT TO the .gh file. Every Python component of the definition
imports it, so the logic lives in one place:

    import sys, os, importlib
    _d = os.path.dirname(ghenv.Component.OnPingDocument().FilePath or "")
    if _d and _d not in sys.path:
        sys.path.insert(0, _d)
    import crv2fab_lib as cf
    importlib.reload(cf)          # picks up edits of this file without restarting Rhino

CONTENTS
  STEP 1 - beam definition (defaults < Rhino User Text < Beam Settings)
  STEP 2 - geometry core used by the components
           Profile -> Axis Frames -> Lamellae -> Geometry
           (build_profile, frames, cut_lamellae, wood_mesh, end_grain_mesh ...)
  STEP 4 - reports per beam + global, CSV / JSON export
           (beam_summary, beam_report, global_report, export_files ...)
  STEP 5 - per-beam cache + light preview
           (BeamCache, cache_key, curve_fingerprint, envelope_mesh)

STEP 1 - BEAM DEFINITION
------------------------
Every axis curve becomes one BEAM. Its parameters are resolved with this
priority (last one wins):

    1. global defaults            (sliders / panels of STEP 1 in Grasshopper)
    2. Rhino User Text on the curve  (Properties > Attribute User Text)
    3. 'Beam Settings' components    (optional overrides inside Grasshopper)

Beam name = name of the curve object in Rhino (Properties > Name).
Unnamed curves are numbered automatically: B1, B2, ... (curve order).

Per-beam keys (User Text keys are case-insensitive):
    W            overall width (mm)
    H            overall height (mm)
    RotStart     rotation of the start profile around the axis (deg)
    RotEnd       rotation of the end profile around the axis (deg)
    TopLayerTrim thinner top layer to hit the exact H (true / false)
    MaxBlank     widest raw board / CNC blank (mm)
    Wood         material of the long faces (index or words of the material name)
    EndGrain     material of the end faces  (index or words of the material name)

A beam travels between components as a JSON text ("spec"), aligned with its
curve: easy to read in a panel and safe to pass through any Grasshopper wire.
"""
import json
import re

import Rhino

# ---------------------------------------------------------------------------
# per-beam parameters: key -> (type, default)
# ---------------------------------------------------------------------------
BEAM_KEYS = {
    "W": ("float", 229.0),
    "H": ("float", 381.0),
    "RotStart": ("float", 0.0),
    "RotEnd": ("float", 0.0),
    "TopLayerTrim": ("bool", False),
    "MaxBlank": ("float", 286.0),
    "Wood": ("text", "pine"),
    "EndGrain": ("text", "clt end grain"),
}
_KEY_LOOKUP = {k.lower(): k for k in BEAM_KEYS}


# ---------------------------------------------------------------------------
# small converters
# ---------------------------------------------------------------------------
def as_list(x):
    """Grasshopper input (item, list, panel text) -> python list of non-empty items."""
    if x is None:
        return []
    if isinstance(x, str):
        items = [x]
    else:
        try:
            items = list(x)
        except TypeError:
            items = [x]
    return [v for v in items if v is not None and str(v).strip() != ""]


def numbers(x):
    """Numbers from a slider, a list or a panel (one value per line)."""
    out = []
    for v in as_list(x):
        for s in str(v).splitlines():
            s = s.strip().replace(",", ".")
            if not s:
                continue
            try:
                out.append(float(s))
            except ValueError:
                pass
    return out


def text_lines(x):
    out = []
    for v in as_list(x):
        out += [s.strip() for s in str(v).splitlines() if s.strip()]
    return out


def convert(key, value):
    """Convert a raw value (text, number, bool) to the type of a BEAM_KEYS key. None if invalid."""
    kind = BEAM_KEYS[key][0]
    if value is None:
        return None
    if kind == "float":
        try:
            return float(str(value).strip().replace(",", "."))
        except ValueError:
            return None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "y", "oui", "on"):
            return True
        if s in ("0", "false", "no", "n", "non", "off"):
            return False
        return None
    s = str(value).strip()
    return s or None


def canonical_key(key):
    return _KEY_LOOKUP.get(str(key).strip().lower())


# ---------------------------------------------------------------------------
# Rhino side: name + User Text of the referenced axis curves
# ---------------------------------------------------------------------------
def referenced_ids(input_param):
    """Rhino object ids of the curves flowing into a Grasshopper input
    (None for curves that are not referenced Rhino objects)."""
    ids = []
    for src in input_param.Sources:
        for g in src.VolatileData.AllData(True):
            rid = None
            if getattr(g, "IsReferencedGeometry", False):
                rid = g.ReferenceID
            ids.append(rid)
    return ids


def rhino_attributes(rhino_id):
    """(name, {UserTextKey: value}) of a Rhino object, or (None, {})."""
    if rhino_id is None:
        return None, {}
    doc = Rhino.RhinoDoc.ActiveDoc
    obj = doc.Objects.FindId(rhino_id) if doc else None
    if obj is None:
        return None, {}
    name = obj.Attributes.Name or None
    us = obj.Attributes.GetUserStrings()
    data = {k: us[k] for k in us.AllKeys} if us is not None else {}
    return name, data


# ---------------------------------------------------------------------------
# overrides from 'Beam Settings' components
# ---------------------------------------------------------------------------
def make_override(beam, values):
    """JSON override written by a 'Beam Settings' component.
    beam = beam name (e.g. 'B2', 'Arch-North') or 1-based number."""
    data = {"beam": str(beam).strip() if beam is not None else ""}
    for k, v in values.items():
        key = canonical_key(k)
        if key is None:
            continue
        cv = convert(key, v)
        if cv is not None:
            data[key] = cv
    return json.dumps(data)


def parse_overrides(items):
    out = []
    for it in as_list(items):
        try:
            d = json.loads(str(it))
            if isinstance(d, dict) and d.get("beam"):
                out.append(d)
        except ValueError:
            pass
    return out


def _override_matches(ov, index, name):
    target = str(ov.get("beam", "")).strip()
    if not target:
        return False
    if target.isdigit():
        return int(target) == index + 1
    return target.lower() == (name or "").lower()


# ---------------------------------------------------------------------------
# beam resolution
# ---------------------------------------------------------------------------
def resolve_beams(curves, rhino_ids, defaults, overrides):
    """-> list of spec dicts (one per curve) + list of warnings.

    curves    : list of Rhino curves (same order as rhino_ids)
    rhino_ids : list of Rhino object ids or None
    defaults  : {key: value} global values from Grasshopper
    overrides : list of override dicts (parse_overrides)
    """
    specs, warnings, used_names = [], [], {}
    for i, crv in enumerate(curves):
        rid = rhino_ids[i] if i < len(rhino_ids) else None
        name, utext = rhino_attributes(rid)
        auto = name is None
        if auto:
            name = "B{}".format(i + 1)
        # unique names
        base, n = name, used_names.get(name.lower(), 0)
        if n:
            name = "{}_{}".format(base, n + 1)
            warnings.append("Duplicate beam name '{}' renamed '{}'.".format(base, name))
        used_names[base.lower()] = n + 1

        spec = {"index": i, "name": name, "rhino_id": str(rid) if rid else None,
                "auto_name": auto, "source": {}}
        # 1. defaults
        for key, (kind, hard_default) in BEAM_KEYS.items():
            v = convert(key, defaults.get(key)) if key in defaults else None
            spec[key] = v if v is not None else hard_default
            spec["source"][key] = "default"
        # 2. Rhino User Text
        for uk, uv in utext.items():
            key = canonical_key(uk)
            if key is None:
                continue
            v = convert(key, uv)
            if v is None:
                warnings.append("{}: User Text {}='{}' is not valid, ignored.".format(name, uk, uv))
                continue
            spec[key] = v
            spec["source"][key] = "user text"
        # 3. Beam Settings overrides
        for ov in overrides:
            if not _override_matches(ov, i, name):
                continue
            for key in BEAM_KEYS:
                if key in ov:
                    spec[key] = ov[key]
                    spec["source"][key] = "beam settings"
        specs.append(spec)
    for ov in overrides:
        if not any(_override_matches(ov, s["index"], s["name"]) for s in specs):
            warnings.append("Beam Settings for '{}': no beam with this name / number.".format(ov.get("beam")))
    return specs, warnings


def spec_to_json(spec):
    return json.dumps(spec)


def json_to_spec(text):
    try:
        d = json.loads(str(text))
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def specs_from(items):
    """Parse the 'Specs' list received by a downstream component."""
    out = []
    for it in as_list(items):
        d = json_to_spec(it)
        if d is not None:
            out.append(d)
    return out


def describe(spec):
    """One readable line per beam, with the source of every overridden value."""
    marks = {"default": "", "user text": " (UT)", "beam settings": " (BS)"}
    src = spec.get("source", {})
    parts = ["{}{}".format(spec["name"], " (auto)" if spec.get("auto_name") else "")]
    parts.append("W {:.0f}{}".format(spec["W"], marks[src.get("W", "default")]))
    parts.append("H {:.0f}{}".format(spec["H"], marks[src.get("H", "default")]))
    parts.append("rot {:.0f}/{:.0f}{}".format(spec["RotStart"], spec["RotEnd"],
                                              marks[src.get("RotEnd", src.get("RotStart", "default"))]))
    parts.append("blank {:.0f}{}".format(spec["MaxBlank"], marks[src.get("MaxBlank", "default")]))
    parts.append("top trim {}{}".format("yes" if spec["TopLayerTrim"] else "no", marks[src.get("TopLayerTrim", "default")]))
    parts.append("wood '{}'{}".format(spec["Wood"], marks[src.get("Wood", "default")]))
    parts.append("end '{}'{}".format(spec["EndGrain"], marks[src.get("EndGrain", "default")]))
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# material helpers (shared by 'Wood Materials')
# ---------------------------------------------------------------------------
def words(s):
    return re.findall(r"[a-z0-9]+", str(s).lower())


def has_words(name, query):
    nw = set(words(name))
    return all(w in nw for w in words(query))


# ===========================================================================
# STEP 2 - GEOMETRY CORE (Profile / Axis Frames / Lamellae / Geometry)
# ===========================================================================
import math
import bisect
import itertools
import Rhino.Geometry as rg

STOCK = [("2x4", 89.0), ("2x6", 140.0), ("2x8", 184.0), ("2x10", 235.0)]   # finished widths (actual mm)
RAW_STOCK = STOCK + [("2x12", 286.0)]                                     # boards pieces are cut from
T = 38.0                    # lamella thickness (mm)
MINW = 89.0                 # narrowest board = 2x4
TOL = 0.5
MIN_SECTIONS_PER_PIECE = 3
MESH_ANGLE = math.radians(1.0)
MESH_STEP = 400.0
DENSE_STEP = 25.0           # mm between two dense axis frames


# ---------------- PROFILE: board mix of the cross-section ----------------
def width_candidates(w):
    """All width compositions with the minimum number of boards: (k, waste, [(name, stock, width)])."""
    kmin = max(1, int(math.ceil((w - TOL) / STOCK[-1][1])))
    out = []
    for k in range(kmin, kmin + 3):
        for combo in itertools.combinations_with_replacement(range(len(STOCK)), k):
            s = sum(STOCK[i][1] for i in combo)
            base = [(STOCK[c][0], STOCK[c][1], STOCK[c][1]) for c in combo]
            if abs(s - w) <= TOL:
                out.append((k, 0.0, base))
            elif s > w:
                seen = set()
                for j, i in enumerate(combo):
                    if i in seen:
                        continue
                    seen.add(i)
                    wr = w - (s - STOCK[i][1])
                    if wr >= MINW - 1e-6 and wr < STOCK[i][1]:
                        pcs = list(base)
                        pcs[j] = (STOCK[i][0], STOCK[i][1], wr)
                        out.append((k, STOCK[i][1] - wr, pcs))
        if out:
            break
    return out


def side_joints(pcs):
    x, js = 0.0, []
    for p in pcs[:-1]:
        x += p[2]
        js.append(x)
    return js


def layouts(cands):
    res, seen = [], set()
    for c in sorted(cands, key=lambda c: c[1])[:8]:
        for perm in itertools.permutations(c[2]):
            key = tuple((p[0], round(p[2], 1)) for p in perm)
            if key in seen:
                continue
            seen.add(key)
            res.append((c[1], list(perm)))
            if len(res) > 80:
                return res
    return res


def best_pair(w, min_side_joint):
    """Board order of the odd (A) and even (B) layers: side joints as far apart as possible, least waste."""
    lays = layouts(width_candidates(w))
    best, best_score = None, None
    for wa, A in lays:
        ja = side_joints(A)
        for wb, B in lays:
            jb = side_joints(B)
            m = min(abs(a - b) for a in ja for b in jb) if (ja and jb) else 1e9
            score = (min(m, min_side_joint), -(wa + wb), m)
            if best_score is None or score > best_score:
                best_score, best = score, (A, B, m)
    return best


def build_profile(spec, min_side_joint):
    """Cross-section of one beam -> dict (JSON friendly)."""
    warn = []
    W, H = float(spec["W"]), float(spec["H"])
    if W < MINW:
        warn.append("W={:.0f} < 89 mm (2x4): width set to 89.".format(W))
        W = MINW
    A, B, jmin = best_pair(W, min_side_joint)
    if jmin < min_side_joint and jmin < 1e8:
        warn.append("Side joint offset = {:.0f} mm < {:.0f} target.".format(jmin, min_side_joint))
    n_full = int(math.floor(H / T + 1e-9))
    rem = H - n_full * T
    if bool(spec.get("TopLayerTrim")) and rem > TOL:
        thick = [T] * n_full + [rem]
        if rem < T / 2:
            warn.append("Thin top layer: {:.1f} mm.".format(rem))
    else:
        thick = [T] * max(1, int(math.floor(H / T + 0.5)))
    Heff = sum(thick)
    layers = []
    y = -Heff / 2.0
    for li, t in enumerate(thick):
        pcs = A if li % 2 == 0 else B
        u0, pieces = -W / 2.0, []
        for name, stock, w in pcs:
            pieces.append([name, stock, w, u0 + w / 2.0])
            u0 += w
        layers.append({"li": li, "v": y + t / 2.0, "t": t, "pieces": pieces})
        y += t
    return {"name": spec["name"], "W": W, "H": H, "Heff": Heff, "thick": thick,
            "A": [list(p) for p in A], "B": [list(p) for p in B], "jmin": jmin,
            "layers": layers, "warnings": warn}


def describe_boards(pcs):
    return " | ".join("{} {:.0f}{}".format(p[0], p[2], "*" if p[2] < p[1] - TOL else "") for p in pcs)


# ---------------- AXIS FRAMES ----------------
def frames(crv, params, a0, a1):
    """Perpendicular frames, rotated around the tangent by an angle that goes
    linearly from a0 (start of the axis) to a1 (end of the axis) with the length."""
    out = []
    L = crv.GetLength()
    t_start = crv.Domain.T0
    for t, f in zip(params, crv.GetPerpendicularFrames(params)):
        p = rg.Plane(f)
        if a0 or a1:
            s = crv.GetLength(rg.Interval(t_start, t)) / L if (L > 0 and t > t_start) else 0.0
            ang = a0 + (a1 - a0) * s
            if ang:
                p.Rotate(math.radians(ang), p.ZAxis)
        out.append(p)
    return out


def dense_params(crv):
    M = max(200, int(crv.GetLength() / DENSE_STEP))
    return list(crv.DivideByCount(M, True))


def section_params(crv, n):
    return list(crv.DivideByCount(max(2, int(n)) - 1, True))


def at(pl, u, v):
    return pl.Origin + pl.XAxis * u + pl.YAxis * v


def cumulative(points):
    cum = [0.0]
    for a, b in zip(points[:-1], points[1:]):
        cum.append(cum[-1] + a.DistanceTo(b))
    return cum


# ---------------- RAW BOARDS ----------------
def raw_list(max_blank):
    raw = [r for r in RAW_STOCK if r[1] <= max_blank + TOL]
    if not raw or max_blank > raw[-1][1] + TOL:
        raw.append(("CNC blank {:.0f}".format(max_blank), max_blank))
    return raw


def raw_board(width, raw):
    for name, sw in raw:
        if sw >= width - TOL:
            return name
    return None


# ---------------- LAMELLAE: butt joints of every lamella ----------------
def cut_lamellae(profile, max_blank, dense, fdense, uni, StockL, Stagger, MinPiece, JointGap):
    """-> list of pieces (dicts): li, pi, si, name, stock, w, t, u, v, j0, j1, L, sag, ps.
    ps = section parameters of the piece (last item = mid parameter, for the label)."""
    last = len(dense) - 1
    axcum = cumulative([f.Origin for f in fdense])
    pieces = []
    joints_prev = []
    for lay in profile["layers"]:
        li, v, t, pcs = lay["li"], lay["v"], lay["t"], lay["pieces"]
        k = len(pcs)
        joints_cur = []
        for pi, (name, stock, w, u) in enumerate(pcs):
            pts = [at(f, u, v) for f in fdense]
            cum = cumulative(pts)
            allow = max(0.0, max_blank - w)

            def sagitta(j0, j1):
                """Lateral sagitta (in the plane of the lamella) between dense sections j0 and j1."""
                if j1 - j0 < 2:
                    return 0.0
                ln = rg.Line(pts[j0], pts[j1])
                vals = []
                for j in range(j0, j1 + 1):
                    d = pts[j] - ln.ClosestPoint(pts[j], False)
                    vals.append(d * fdense[j].XAxis)
                return max(vals) - min(vals)

            avoid = joints_prev + joints_cur
            off = ((li * k + pi) * Stagger) % StockL
            cuts, start, first = [0], 0, True
            while start < last:
                cap = off if (first and off >= MinPiece) else StockL
                first = False
                jmax = bisect.bisect_right(cum, cum[start] + cap + 1e-6) - 1
                jmax = max(start + 1, min(jmax, last))
                # longest piece whose sagitta fits in the raw board
                if sagitta(start, jmax) <= allow:
                    j = jmax
                else:
                    lo, hi = start + 1, jmax
                    while hi - lo > 1:
                        mid = (lo + hi) // 2
                        if sagitta(start, mid) <= allow:
                            lo = mid
                        else:
                            hi = mid
                    j = lo
                # keep the butt joint away from neighbouring joints
                if j < last and avoid:
                    jj = j
                    for _ in range(50):
                        a = axcum[jj]
                        clash = [p for p in avoid if abs(a - p) < JointGap]
                        if not clash:
                            break
                        target = min(clash) - JointGap
                        jn = bisect.bisect_right(axcum, target) - 1
                        if jn <= start or cum[jn] - cum[start] < 0.5 * (cum[j] - cum[start]):
                            jj = j
                            break
                        jj = jn
                    j = jj
                cuts.append(j)
                start = j
            # rebalance a too-short last piece with the previous one
            if len(cuts) > 2 and cum[last] - cum[cuts[-2]] < MinPiece:
                target = cum[last] - MinPiece
                jn = bisect.bisect_right(cum, target) - 1
                if jn > cuts[-3] and cum[jn] - cum[cuts[-3]] >= MinPiece * 0.5 and sagitta(jn, last) <= allow:
                    cuts[-2] = jn
            for c in cuts[1:-1]:
                joints_cur.append(axcum[c])

            for si in range(len(cuts) - 1):
                j0, j1 = cuts[si], cuts[si + 1]
                t0, t1 = dense[j0], dense[j1]
                ps = [t0] + [q for q in uni if t0 < q < t1] + [t1]
                if len(ps) < MIN_SECTIONS_PER_PIECE:
                    ps = [t0 + (t1 - t0) * i / (MIN_SECTIONS_PER_PIECE - 1) for i in range(MIN_SECTIONS_PER_PIECE)]
                ps.append((t0 + t1) / 2.0)
                pieces.append({"li": li, "pi": pi, "si": si, "name": name, "stock": stock, "w": w, "t": t,
                               "u": u, "v": v, "j0": j0, "j1": j1, "L": cum[j1] - cum[j0],
                               "sag": sagitta(j0, j1), "ps": ps})
        joints_prev = joints_cur
    return pieces


def fr_txt(r):
    return "straight" if r > 1e11 else "{:.0f} mm".format(r)


# ---------------- RENDER MESHES (UVs in mm) ----------------
def adaptive(fr, axc, j0, j1):
    """Sub-set of dense sections: new one after 1 deg of turning/twist or 400 mm."""
    keep, last = [j0], j0
    for j in range(j0 + 1, j1):
        a = max(rg.Vector3d.VectorAngle(fr[last].ZAxis, fr[j].ZAxis),
                rg.Vector3d.VectorAngle(fr[last].XAxis, fr[j].XAxis))
        if a > MESH_ANGLE or axc[j] - axc[last] > MESH_STEP:
            keep.append(j)
            last = j
    keep.append(j1)
    return keep


def wood_mesh(fr, cum, idx, u, v, w, t):
    """4 long faces ; U = mm along the lamella (grain), V = mm around the profile."""
    m = rg.Mesh()
    hw, ht = w / 2.0, t / 2.0
    sides = [((-hw, -ht), (hw, -ht)), ((hw, -ht), (hw, ht)), ((hw, ht), (-hw, ht)), ((-hw, ht), (-hw, -ht))]
    vpos = 0.0
    j0 = idx[0]
    for a, b in sides:
        flen = abs(b[0] - a[0]) + abs(b[1] - a[1])
        base = m.Vertices.Count
        for j in idx:
            f = fr[j]
            m.Vertices.Add(at(f, u + a[0], v + a[1]))
            m.Vertices.Add(at(f, u + b[0], v + b[1]))
            U = cum[j] - cum[j0]
            m.TextureCoordinates.Add(U, vpos)
            m.TextureCoordinates.Add(U, vpos + flen)
        for i in range(len(idx) - 1):
            k = base + 2 * i
            m.Faces.AddFace(k, k + 1, k + 3, k + 2)
        vpos += flen
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def end_grain_mesh(fr, j0, j1, u, v, w, t):
    """2 end faces ; UVs = (x, y) in mm from the lower-left corner of the section."""
    m = rg.Mesh()
    hw, ht = w / 2.0, t / 2.0
    corners = [(-hw, -ht), (hw, -ht), (hw, ht), (-hw, ht)]
    for j, sign in ((j0, -1), (j1, 1)):
        f = fr[j]
        base = m.Vertices.Count
        for x, yy in corners:
            m.Vertices.Add(at(f, u + x, v + yy))
            m.TextureCoordinates.Add(x + hw, yy + ht)
        if sign > 0:
            m.Faces.AddFace(base, base + 1, base + 2, base + 3)
        else:
            m.Faces.AddFace(base, base + 3, base + 2, base + 1)
    m.Normals.ComputeNormals()
    m.Compact()
    return m


# ---------------- small helpers for GH trees ----------------
def gh_value(x):
    return x.Value if hasattr(x, "Value") else x


def coerce_curves(items):
    import rhinoscriptsyntax as rs
    out = []
    for c in as_list(items):
        c = gh_value(c)
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None:
            out.append(cc)
    return out


def tree_branches_by_beam(tree):
    """{beam index: [values]} from a {beam} tree."""
    out = {}
    if tree is None:
        return out
    for path in tree.Paths:
        bi = path.Indices[0] if path.Length > 0 else 0
        out.setdefault(bi, []).extend(gh_value(x) for x in tree.Branch(path))
    return out


# ===========================================================================
# STEP 4 - REPORTS AND EXPORT (per beam + global, CSV / JSON)
# ===========================================================================
# Every report is built from the data already flowing in the definition:
#   Specs (Beam Definition), Profiles (Profile), Pieces (Lamellae),
#   raw blocks + waste (Raw Blocks). Nothing is recomputed here.
import csv
import os
import datetime

PIECE_FIELDS = ["beam", "tag", "layer", "board_in_layer", "segment", "board", "stock_width",
                "width", "thickness", "length", "sagitta", "blank", "ripped", "u", "v", "bake_layer"]
BEAM_FIELDS = ["beam", "rhino_id", "wood", "end_grain", "W_asked", "H_asked", "W", "H",
               "layers", "rot_start", "rot_end", "max_blank", "axis_length", "pieces",
               "linear_m", "net_volume_m3", "out_of_stock",
               "raw_blocks", "raw_volume_m3", "waste_avg_pct", "waste_max_pct"]


def select_beams(names, wanted_items):
    """Indices of the beams asked by name or 1-based number. Empty selection = all beams."""
    wanted = []
    for item in as_list(wanted_items):
        for s in str(item).replace(",", "\n").splitlines():
            s = s.strip()
            if s and not s.lower().startswith("double click"):   # empty-panel placeholder
                wanted.append(s)
    if not wanted:
        return list(range(len(names))), False
    out = []
    for i, n in enumerate(names):
        if any((w.isdigit() and int(w) == i + 1) or w.lower() == str(n).lower() for w in wanted):
            out.append(i)
    return out, True


def piece_record(p, beam_name):
    """One finished piece as a flat dict (CSV / JSON row)."""
    return {
        "beam": beam_name, "tag": p.get("tag"), "layer": p["li"] + 1, "board_in_layer": p["pi"] + 1,
        "segment": p["si"] + 1, "board": p["name"], "stock_width": p["stock"], "width": p["w"],
        "thickness": p["t"], "length": p["L"], "sagitta": p["sag"],
        "blank": p.get("blank") or "OUT OF STOCK", "ripped": p["w"] < p["stock"] - TOL,
        "u": p.get("u"), "v": p.get("v"), "bake_layer": p.get("layer"),
    }


def box_dims(brep):
    """Sorted (long, mid, short) edge lengths of a box-shaped Brep (mm)."""
    lens = sorted(e.GetLength() for e in brep.Edges)
    if len(lens) == 12:
        return sorted([lens[1], lens[5], lens[9]], reverse=True)
    bb = brep.GetBoundingBox(True)
    d = bb.Diagonal
    return sorted([d.X, d.Y, d.Z], reverse=True)


def beam_summary(spec, profile, pieces, axis_len, blocks, wastes, stock_l):
    """Numbers of one beam (dict). pieces = records of piece_record()."""
    lin = sum(p["length"] for p in pieces)
    net = sum(p["length"] * p["width"] * p["thickness"] for p in pieces) / 1e9
    finished, raw = {}, {}
    for p in pieces:
        k = (p["board"], round(p["width"]), round(p["thickness"]), p["ripped"])
        f = finished.setdefault(k, [0, 0.0, 1e12, 0.0])
        f[0] += 1
        f[1] += p["length"]
        f[2] = min(f[2], p["length"])
        f[3] = max(f[3], p["length"])
        r = raw.setdefault((p["blank"], round(p["thickness"])), [0, 0.0])
        r[0] += 1
        r[1] += p["length"]
    dims = [box_dims(b) for b in blocks]
    raw_vol = sum(a * b * c for a, b, c in dims) / 1e9
    wastes = [float(w) for w in wastes]
    return {
        "beam": spec["name"], "rhino_id": spec.get("rhino_id"), "wood": spec.get("Wood"),
        "end_grain": spec.get("EndGrain"), "W_asked": spec["W"], "H_asked": spec["H"],
        "W": profile["W"], "H": profile["Heff"], "layers": len(profile["thick"]),
        "rot_start": spec["RotStart"], "rot_end": spec["RotEnd"], "max_blank": spec["MaxBlank"],
        "axis_length": axis_len, "pieces": len(pieces), "linear_m": lin / 1000.0,
        "net_volume_m3": net,
        "out_of_stock": sum(1 for p in pieces if p["blank"] == "OUT OF STOCK"),
        "raw_blocks": len(blocks), "raw_volume_m3": raw_vol,
        "waste_avg_pct": sum(wastes) / len(wastes) if wastes else 0.0,
        "waste_max_pct": max(wastes) if wastes else 0.0,
        # detail tables (not CSV columns)
        "_finished": finished, "_raw": raw, "_blocks": [(d, w) for d, w in zip(dims, wastes + [None] * len(dims))],
        "_mix": (describe_boards(profile["A"]), describe_boards(profile["B"])),
        "_warnings": list(profile.get("warnings", [])), "_stock_l": stock_l,
    }


def summary_line(s):
    return ("{beam:<6} {W:.0f}x{H:.0f} | {layers} layers | axis {axis_length:.0f} mm | {pieces} pcs | "
            "{linear_m:.1f} m lin | net {net_volume_m3:.3f} m3 | raw blocks {raw_blocks} "
            "({raw_volume_m3:.3f} m3, waste max {waste_max_pct:.0f} %) | {wood}").format(**s)


def _boards_lines(raw, stock_l, indent="    "):
    out = []
    for (blank, t), (n, tot) in sorted(raw.items()):
        out.append("{}{:<14} t={:<3} {:>4} pcs | {:>7.2f} m lin | ~{} boards of {:.0f} mm (no waste)".format(
            indent, blank, t, n, tot / 1000.0, int(math.ceil(tot / stock_l)), stock_l))
    return out


def beam_report(s):
    """Detailed text report of one beam (list of lines)."""
    L = ["=" * 70,
         "{}  | wood '{}' / end grain '{}' | Rhino id {}".format(s["beam"], s["wood"], s["end_grain"], s["rhino_id"]),
         "  Axis {:.0f} mm | section {:.0f} x {:.0f} mm (asked {:.0f} x {:.0f}) | {} layers | profiles {:.0f} / {:.0f} deg | blank {:.0f}".format(
             s["axis_length"], s["W"], s["H"], s["W_asked"], s["H_asked"], s["layers"],
             s["rot_start"], s["rot_end"], s["max_blank"]),
         "  Board mix: odd layers {} | even layers {}   (* = ripped)".format(*s["_mix"]),
         "  {} pieces | {:.2f} m lin | net wood {:.3f} m3".format(
             s["pieces"], s["linear_m"], s["net_volume_m3"]),
         "  Finished pieces:"]
    for (name, w, t, rp), (n, tot, lmin, lmax) in sorted(s["_finished"].items()):
        L.append("    {:<24} {:>4} pcs | {:>7.2f} m lin | L {:.0f} to {:.0f} mm".format(
            "{} {}x{}{}".format(name, w, t, " (ripped)" if rp else ""), n, tot / 1000.0, lmin, lmax))
    L.append("  Raw boards to buy (straight, CNC-cut):")
    L += _boards_lines(s["_raw"], s["_stock_l"])
    L.append("  Raw CNC blocks: {} | {:.3f} m3 | waste avg {:.1f} % / max {:.1f} %".format(
        s["raw_blocks"], s["raw_volume_m3"], s["waste_avg_pct"], s["waste_max_pct"]))
    for k, (d, w) in enumerate(s["_blocks"]):
        L.append("    {}-R{:<3} {:.0f} x {:.0f} x {:.0f} mm{}".format(
            s["beam"], k + 1, d[0], d[1], d[2], "" if w is None else " | waste {:.1f} %".format(w)))
    warns = s["_warnings"] + (["{} piece(s) OUT OF STOCK".format(s["out_of_stock"])] if s["out_of_stock"] else [])
    L.append("  Warnings: " + ("; ".join(warns) if warns else "none"))
    return L


def global_report(summaries):
    """Totals over the given beams (list of lines)."""
    if not summaries:
        return ["No beam."]
    raw = {}
    for s in summaries:
        for k, (n, tot) in s["_raw"].items():
            r = raw.setdefault(k, [0, 0.0])
            r[0] += n
            r[1] += tot
    tot = lambda key: sum(s[key] for s in summaries)
    L = ["ASSEMBLY - {} beam(s): {}".format(len(summaries), ", ".join(s["beam"] for s in summaries)),
         "  {} pieces | {:.1f} m lin | net wood {:.3f} m3 | raw blocks {} ({:.3f} m3)".format(
             tot("pieces"), tot("linear_m"), tot("net_volume_m3"),
             tot("raw_blocks"), tot("raw_volume_m3")),
         "  Raw boards to buy, all beams:"]
    L += _boards_lines(raw, summaries[0]["_stock_l"])
    oos = tot("out_of_stock")
    if oos:
        L.append("  WARNING: {} piece(s) OUT OF STOCK".format(oos))
    return L


def cut_list_lines(records):
    L = ["tag              board   width x t    length  sagitta  blank"]
    for p in records:
        L.append("{:<16} {:<5} {:>6.0f} x {:<4.0f} {:>7.0f} {:>7.0f}  {}{}".format(
            p["tag"], p["board"], p["width"], p["thickness"], p["length"], p["sagitta"], p["blank"],
            " (ripped)" if p["ripped"] else ""))
    return L


def _fmt(v, dec_comma):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        s = "{:.3f}".format(v).rstrip("0").rstrip(".")
        return s.replace(".", ",") if dec_comma else s
    return "" if v is None else str(v)


def write_csv(path, fields, rows, sep=","):
    """UTF-8 (with BOM, opens cleanly in Excel). sep ';' -> decimal comma (French Excel)."""
    dec_comma = sep == ";"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=sep)
        w.writerow(fields)
        for r in rows:
            w.writerow([_fmt(r.get(k), dec_comma) for k in fields])
    return path


def _public(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def export_files(folder, summaries, records_by_beam, specs, profiles, stock_l, sep=",", source=""):
    """Writes the CSV + JSON files of the given beams. Returns the written paths."""
    if not os.path.isdir(folder):
        os.makedirs(folder)
    out = []
    all_rec = [r for s in summaries for r in records_by_beam.get(s["beam"], [])]
    out.append(write_csv(os.path.join(folder, "crv2fab_beams.csv"), BEAM_FIELDS, [_public(s) for s in summaries], sep))
    out.append(write_csv(os.path.join(folder, "crv2fab_pieces.csv"), PIECE_FIELDS, all_rec, sep))
    rows = []
    for s in summaries:
        for (blank, t), (n, tot) in sorted(s["_raw"].items()):
            rows.append({"beam": s["beam"], "blank": blank, "thickness": t, "pieces": n,
                         "linear_m": tot / 1000.0, "boards_est": int(math.ceil(tot / stock_l))})
    out.append(write_csv(os.path.join(folder, "crv2fab_raw_boards.csv"),
                         ["beam", "blank", "thickness", "pieces", "linear_m", "boards_est"], rows, sep))
    rows = []
    for s in summaries:
        for k, (d, w) in enumerate(s["_blocks"]):
            rows.append({"beam": s["beam"], "block": "{}-R{}".format(s["beam"], k + 1), "length": d[0],
                         "width": d[1], "height": d[2], "volume_m3": d[0] * d[1] * d[2] / 1e9, "waste_pct": w})
    out.append(write_csv(os.path.join(folder, "crv2fab_raw_blocks.csv"),
                         ["beam", "block", "length", "width", "height", "volume_m3", "waste_pct"], rows, sep))
    for s in summaries:
        out.append(write_csv(os.path.join(folder, "{}_cutlist.csv".format(s["beam"])), PIECE_FIELDS,
                             records_by_beam.get(s["beam"], []), sep))
    data = {"generator": "CRV2FAB glulam slicer", "source": source, "units": "mm",
            "created": datetime.datetime.now().isoformat(timespec="seconds"), "stock_length": stock_l,
            "beams": []}
    for s in summaries:
        data["beams"].append({"summary": _public(s), "spec": specs.get(s["beam"]),
                              "profile": profiles.get(s["beam"]),
                              "raw_blocks": [{"dims": d, "waste_pct": w} for d, w in s["_blocks"]],
                              "pieces": records_by_beam.get(s["beam"], [])})
    jp = os.path.join(folder, "crv2fab_report.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    out.append(jp)
    return out


# ===========================================================================
# STEP 5 - PER-BEAM CACHE + LIGHT PREVIEW
# ===========================================================================
# The heavy components (Lamellae, Geometry) remember the result of every beam,
# keyed by everything that shapes it: axis curve, section/rotation/blank of the
# beam, global parameters, and the version of this file. When one beam changes,
# only that beam is recomputed; the others are reused.
# Materials (Wood / EndGrain) are NOT part of the key: changing a material never
# recomputes lamellae or geometry.
import hashlib

GEOM_KEYS = ("W", "H", "RotStart", "RotEnd", "TopLayerTrim", "MaxBlank")
_CACHE_ROOT = "crv2fab_cache"


def _lib_version():
    try:
        return os.path.getmtime(__file__)
    except Exception:
        return 0


def curve_fingerprint(crv):
    """Short hash of the exact shape of a curve (control points, weights, knots, degree)."""
    n = crv.ToNurbsCurve()
    h = hashlib.md5()
    h.update("{}|{}|{}".format(n.Degree, n.IsPeriodic, n.Points.Count).encode())
    for i in range(n.Points.Count):
        p = n.Points[i]
        h.update("{:.6f},{:.6f},{:.6f},{:.6f};".format(p.Location.X, p.Location.Y, p.Location.Z, p.Weight).encode())
    for i in range(n.Knots.Count):
        h.update("{:.9f};".format(n.Knots[i]).encode())
    return h.hexdigest()


def spec_geometry(spec):
    """The part of a beam spec that changes its geometry (materials / name excluded)."""
    return {k: spec.get(k) for k in GEOM_KEYS}


def cache_key(*parts):
    """Hash of any JSON-friendly parts + version of this library file."""
    txt = json.dumps([_lib_version()] + list(parts), sort_keys=True, default=str)
    return hashlib.md5(txt.encode()).hexdigest()


class BeamCache(object):
    """Per-component, per-beam memory kept in scriptcontext.sticky (lives until Rhino closes).

        cache = cf.BeamCache(ghenv.Component, enabled)
        hit = cache.get(beam_name, key)      # None when missing / changed / disabled
        cache.put(beam_name, key, value)
        cache.prune(names_still_used)
        cache.status()                        # 'cache: 2 / 3 beams reused'
    """

    def __init__(self, component, enabled=True):
        import scriptcontext as sc
        root = sc.sticky.setdefault(_CACHE_ROOT, {})
        self.store = root.setdefault(str(component.InstanceGuid), {})
        self.enabled = bool(enabled)
        if not self.enabled:
            self.store.clear()
        self.hits, self.total = 0, 0

    def get(self, beam, key):
        self.total += 1
        if not self.enabled:
            return None
        e = self.store.get(beam)
        if e is not None and e[0] == key:
            self.hits += 1
            return e[1]
        return None

    def put(self, beam, key, value):
        if self.enabled:
            self.store[beam] = (key, value)

    def prune(self, names):
        keep = set(names)
        for k in list(self.store):
            if k not in keep:
                del self.store[k]

    def status(self):
        if not self.enabled:
            return "cache off"
        return "cache: {} / {} beam(s) reused".format(self.hits, self.total)


def clear_all_caches():
    import scriptcontext as sc
    sc.sticky.pop(_CACHE_ROOT, None)


def envelope_mesh(frames, W, H, step=4):
    """Light preview: closed box-section mesh W x H swept on every 'step'-th frame."""
    idx = list(range(0, len(frames), step))
    if idx[-1] != len(frames) - 1:
        idx.append(len(frames) - 1)
    m = rg.Mesh()
    corners = [(-W / 2, -H / 2), (W / 2, -H / 2), (W / 2, H / 2), (-W / 2, H / 2)]
    for j in idx:
        pl = frames[j]
        for (u, v) in corners:
            m.Vertices.Add(at(pl, u, v))
    n = len(idx)
    for s in range(n - 1):
        a, b = 4 * s, 4 * (s + 1)
        for k in range(4):
            k2 = (k + 1) % 4
            m.Faces.AddFace(a + k, a + k2, b + k2, b + k)
    m.Faces.AddFace(3, 2, 1, 0)
    e = 4 * (n - 1)
    m.Faces.AddFace(e, e + 1, e + 2, e + 3)
    m.Normals.ComputeNormals()
    m.Compact()
    return m
