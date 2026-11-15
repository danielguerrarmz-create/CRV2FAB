# -*- coding: utf-8 -*-
"""Gesture, Nudge, Judge: everything that is not Rhino.

Pure Python that runs unchanged on IronPython 2.7 (Rhino 7) and CPython 3, so
the maths, the fallback solver, the session states and the core contract can be
tested outside Rhino. No f-strings, no Python 3 only syntax.

Shared spec v2: the bend has a direction. The fallback solver is a line by line
port of solveBend() in scratch/2026-11-14/gnj-ghost-placeholder/ghost-nudge-3d.html.
"""
from __future__ import division

import json
import math
import os
import re

import gnj_slots as slots

try:  # IronPython 2.7
    import urllib2 as _http
except ImportError:  # CPython 3, for tests outside Rhino
    import urllib.request as _http

# The demo member: one softwood 2x4, bent in single curvature over its full length.
MEMBER_ID = "M1"
LENGTH_MM = 2400.0   # X, the chord of the bend
WIDTH_MM = 89.0      # Y
STOCK_MM = 38.0      # Z, the thickness

# Placeholder fabrication limits until the real numbers arrive (same as the mock).
BEND_RATIO = 200.0   # radius / piece size across the bend, minimum
MIN_LAMELLA_MM = 8.0
MAX_LAYERS = max(1, int(math.floor(STOCK_MM / MIN_LAMELLA_MM)))   # 4 layers of 9.5 mm
MAX_STRIPS = max(1, int(math.floor(WIDTH_MM / MIN_LAMELLA_MM)))   # 11 strips of about 8.09 mm
MAX_SURFACE_LAYERS = 200   # sanity bound for a pressed billet's layer count (spec v4)

# Gesture reading.
MIN_SAG_MM = 20.0          # smaller than this is too small to read
MAX_SAG_MM = 230 / 0.35    # the mock's clamp (230 px at 0.35 px/mm), about 657 mm

CORE_URL = "http://127.0.0.1:8742"
NUDGE_TIMEOUT_S = 60.0     # rules answer at once; a part split into pieces took 20 s in the core
SAY_TIMEOUT_S = 25.0       # /say reads the words with the model: 2 to 3 s measured, the core gives up at 20
PHOTO_TIMEOUT_S = 40.0     # /photo: the core gives the model 25 s, plus upload and downsizing
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
JUDGE_TIMEOUT_S = 3.0      # runs on the UI thread, must stay short

HOLD_NAMES = {"solid": "solid section", "shape": "drawn shape", "less_waste": "less waste"}
HOLD_LABELS = {"solid": "one piece", "less_waste": "less waste", "split_ok": "shorter pieces"}
HOLD_BUTTONS = {"shape": "Keep my shape", "solid": "Keep it as one piece"}   # SPEC_V9_UI card, rejected
HOLD_NAME_RE = re.compile(r"^[a-z][a-z_]{0,31}$")  # hold names come from the core; any it reports is shown

SAYING = "Working out what you meant."
READING_PHOTO = "Reading your photo."
PHOTO_NOTICE = "Your photo is sent to Claude to be read."
PHOTO_REFUSED = "The helper could not take this photo."
HELPER_FOR_WORDS = "Typed words need the helper running."


def hold_label(name, shape_word="shape"):
    """A plain label for any hold the core reports, including one this client has never seen:
    "Keeping: " + this. SPEC_V9_UI: "my shape", "one solid piece"."""
    if name == "shape":
        return "my " + shape_word
    return HOLD_LABELS.get(name) or name.replace("_", " ")

# A drawn direction within this many degrees of up, down or sideways is read as exactly that;
# further from all four it stays as drawn, a deliberate lean (same rule as the 3D mock).
SNAP_DEG = 30

TOO_SMALL = "Too small to read. Draw further from the timber, from a view that shows its side."
ALONG_AXIS = "This view looks along the timber. Draw from a view that shows its side."


# ---------------------------------------------------------------- maths

def m(mm):
    """Metres to two places, as the mock prints them."""
    return "%.2f m" % (mm / 1000.0)


def n1(x):
    """One decimal, trailing .0 dropped (JS Math.round(x*10)/10 then toString)."""
    r = math.floor(x * 10 + 0.5) / 10.0
    return str(int(r)) if r == int(r) else "%.1f" % r


# ---------------------------------------------------------------- where the core lives (DEBT D-018)
# No path from one person's disk: the environment, the config install.ps1 writes beside gnj_nudge.py,
# or the layout (core beside rhino7 when published; gnj-nudge-core beside gnj-rhino7 in a checkout).
CONFIG_FILE = "crv2fab.config.json"


def read_config(repo_dir):
    """The installer's config ({"core_dir", "python"}), or {} when there is none or it cannot be read."""
    try:
        with open(os.path.join(repo_dir, CONFIG_FILE)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def core_location(environ, repo_dir, config=None, isdir=os.path.isdir, isfile=os.path.isfile):
    """(core folder or None, the Python that runs it, how it was found). The first of GNJ_CORE_DIR, the
    config's core_dir, a "core" folder and a "gnj-nudge-core" folder beside this one, that holds gnj_nudge wins. Python: GNJ_CORE_PYTHON,
    the config's python, the core's own .venv, else "python" on the PATH."""
    cfg = config or {}
    parent = os.path.dirname(os.path.normpath(repo_dir))
    tried = [(environ.get("GNJ_CORE_DIR"), "GNJ_CORE_DIR"), (cfg.get("core_dir"), "config"),
             (os.path.join(parent, "core"), "beside"), (os.path.join(parent, "gnj-nudge-core"), "beside")]
    core_dir, how = None, "not found"
    for path, source in tried:
        if path and isdir(os.path.join(path, "gnj_nudge")):
            core_dir, how = os.path.normpath(path), source
            break
    python = environ.get("GNJ_CORE_PYTHON") or cfg.get("python")
    if not python and core_dir is not None:
        venv = os.path.join(core_dir, ".venv", "Scripts", "python.exe")
        if isfile(venv):
            python = venv
    return core_dir, python or "python", how


def jround(x):
    """JS Math.round: half rounds up."""
    return int(math.floor(x + 0.5))


def sag_of(radius_mm, chord_mm=LENGTH_MM):
    """Rise of the arc at mid-span."""
    return radius_mm - math.sqrt(max(0.0, radius_mm * radius_mm - chord_mm * chord_mm / 4.0))


def radius_of(sag_mm, chord_mm=LENGTH_MM):
    """Radius of the arc through both ends of the chord with this rise at mid-span."""
    s = abs(sag_mm)
    return (chord_mm * chord_mm / 4.0 + s * s) / (2.0 * s)


def deviation_mm(intent_radius, form_radius, chord_mm=LENGTH_MM):
    return abs(sag_of(intent_radius, chord_mm) - sag_of(form_radius, chord_mm))


def dir_factors(angle_deg):
    """(|cos a|, |sin a|), each zeroed under 1e-6. c bends the 38 mm thickness, s the 89 mm width."""
    r = math.radians(angle_deg)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    return (0.0 if c < 1e-6 else c), (0.0 if s < 1e-6 else s)


def direction_vector(angle_deg):
    """Unit bend direction (y, z): angle from +Z toward +Y, d = (0, sin a, cos a)."""
    r = math.radians(angle_deg)
    return math.sin(r), math.cos(r)


def snap_angle(angle_deg):
    """(angle, snapped). The 3D mock's snapAngle(): whole degrees, then the nearest of 0, 90, 180, 270
    when it is within SNAP_DEG of it (inclusive). snapped is True only when the angle moved: a bend
    drawn exactly up was not snapped, so the core's own Why steps are shown as sent."""
    a = jround(angle_deg) % 360
    p = jround(a / 90.0) * 90
    if abs(a - p) <= SNAP_DEG:
        return float(p % 360), a != p % 360 and a != p
    return float(a), False


DEGENERATE_ON_SCREEN = 0.15  # a projected axis shorter than this share of the other is not a candidate


def screen_snap(stroke, up_on_screen, side_on_screen, los_angle):
    """Snap by what is nearest on screen (approved 2026-11-14).

    stroke: the stroke's on-screen offset from the timber's projected axis, (x, y).
    up_on_screen, side_on_screen: world Z and the horizontal axis across the timber, projected at the
    timber's midpoint, as they are (any length).
    los_angle: the line-of-sight reading, degrees.
    Returns (angle, snapped) when the stroke is within SNAP_DEG on screen of a candidate, either sign:
    0 up, 180 down, 90 and 270 sideways. snapped is True only when that moved the line-of-sight
    reading. None means a deliberate lean: keep the line-of-sight reading as it is.
    """
    def length(v):
        return math.hypot(v[0], v[1])

    ls, lu, lw = length(stroke), length(up_on_screen), length(side_on_screen)
    if ls == 0:
        return None
    candidates = []
    if lu > 0 and lu >= DEGENERATE_ON_SCREEN * lw:
        candidates += [(up_on_screen, 1, 0.0), (up_on_screen, -1, 180.0)]
    if lw > 0 and lw >= DEGENERATE_ON_SCREEN * lu:
        candidates += [(side_on_screen, 1, 90.0), (side_on_screen, -1, 270.0)]
    best = None
    for v, sign, angle in candidates:
        c = sign * (stroke[0] * v[0] + stroke[1] * v[1]) / (ls * length(v))
        gap = math.degrees(math.acos(max(-1.0, min(1.0, c))))
        if best is None or gap < best[0]:
            best = (gap, angle)
    if best is None or best[0] > SNAP_DEG:
        return None
    moved = abs((los_angle - best[1] + 180.0) % 360.0 - 180.0) > 0.5
    return best[1], moved


def snap_word(angle_deg):
    a = jround(angle_deg) % 360
    return "straight up" if a == 0 else "straight down" if a == 180 else "sideways"


def read_bend(offsets_mm):
    """Sag and direction from a gesture's offsets (y, z) in mm, perpendicular to the member axis.

    The point farthest from the axis gives the sag (its distance) and the bend
    direction (angle from +Z toward +Y). Returns (sag_mm, angle_deg, None), or
    (None, None, reason) when the gesture is too small to read.
    """
    best, by, bz = 0.0, 0.0, 0.0
    for y, z in offsets_mm:
        d = math.hypot(y, z)
        if d > best:
            best, by, bz = d, y, z
    if best < MIN_SAG_MM:
        return None, None, TOO_SMALL
    angle = math.degrees(math.atan2(by, bz)) % 360.0
    return min(best, MAX_SAG_MM), angle, None


# ---------------------------------------------------------------- fallback solver

def _count_for(size, rc):
    return 1 if rc is None else max(1, int(math.ceil(size / (rc / BEND_RATIO))))


def dir_word(angle_deg):
    r = jround(angle_deg)
    if r == 180:
        return "down"
    if r in (0, 360):
        return "up"
    return "%d degrees from up" % r


def pieces_text(f):
    n, k = f["n_lamellas"], f["n_strips"]
    if k == 1:
        return "%d glued layers of %s mm" % (n, n1(f["lamella_mm"]))
    if n == 1:
        return "%d glued strips of %s mm side by side" % (k, n1(f["strip_mm"]))
    return "%d layers of %s mm, each cut into %d strips of %s mm" % (n, n1(f["lamella_mm"]), k, n1(f["strip_mm"]))


def local_solve(intent, holds):
    """Port of solveBend() in ghost-nudge-3d.html, shaped like the core's /nudge response.

    Order of what gets given up: keep the drawn shape and direction, change the
    make-up first, move the radius last. Never the direction. Holds override.
    """
    T, W, RATIO, MINLAM = STOCK_MM, WIDTH_MM, BEND_RATIO, MIN_LAMELLA_MM
    R, C = float(intent["radius_mm"]), float(intent["chord_mm"])
    a = float(intent.get("bend_angle_deg", 0.0 if intent.get("direction", "up") == "up" else 180.0))
    c, s = dir_factors(a)
    Rz = R / c if c else None   # None stands for infinite
    Ry = R / s if s else None
    Rst, Rsw = T * RATIO * c, W * RATIO * s
    Rsolid = max(Rst, Rsw)
    face = "38 mm thickness" if Rst >= Rsw else "89 mm width"
    steps = []

    def step(tag, text):
        steps.append({"tag": tag, "text": text})

    def conflict(sentence, text, pair):
        step("Cannot resolve", text)
        return {"status": "conflict", "form": None, "sentence": sentence, "steps": steps,
                "deviation_mm": None, "source": "fallback", "conflict": list(pair)}

    def piece(radius, n, k):
        return {"radius_mm": radius, "n_lamellas": n, "lamella_mm": T / n, "n_strips": k, "strip_mm": W / k,
                "chord_mm": C, "bend_angle_deg": a, "direction": "up" if math.cos(math.radians(a)) >= 0 else "down"}

    def proposed(sentence, form):
        return {"status": "proposed", "form": form, "sentence": sentence, "steps": steps,
                "deviation_mm": deviation_mm(R, form["radius_mm"], C), "source": "fallback", "conflict": None}

    step("Heard", "Bend the full 2.4 m to a radius of %s, bending %s." % (m(R), dir_word(a)))
    if R >= Rsolid:
        step("Limit", "Solid 38 x 89 mm, the %s governs: it bends to %s or wider. Your curve is inside that."
             % (face, m(Rsolid)))
        step("Decision", "No change needed.")
        return proposed("Buildable as drawn, in one solid piece.", piece(R, 1, 1))
    step("Limit", "Solid 38 x 89 mm, the %s governs: it bends no tighter than %s. Your curve is %s times too tight for one piece."
         % (face, m(Rsolid), n1(Rsolid / R)))

    if "solid" in holds:
        if "shape" in holds:
            return conflict("Solid and this curve cannot both be built.",
                            "Solid and a %s radius cannot both be true in 38 x 89 mm stock in this direction." % m(R),
                            ("solid section", "drawn radius " + m(R)))
        dev = deviation_mm(R, Rsolid, C)
        step("Decision", "You are holding solid. Kept one piece and opened the radius to %s." % m(Rsolid))
        step("Check", "Passes. The ghost sits %d mm from your curve at mid-span." % jround(dev))
        return proposed("Kept solid. Curve eased by %d mm so one piece can bend it." % jround(dev), piece(Rsolid, 1, 1))

    n, k = _count_for(T, Rz), _count_for(W, Ry)
    if n <= MAX_LAYERS and k <= MAX_STRIPS:
        p = piece(R, n, k)
        chk = []
        if n > 1:
            chk.append("A %s mm layer bends to %s." % (n1(p["lamella_mm"]), m(p["lamella_mm"] * RATIO)))
        if k > 1:
            chk.append("A %s mm strip bends to %s across the width." % (n1(p["strip_mm"]), m(p["strip_mm"] * RATIO)))
        step("Decision", "Kept your curve and changed how it is made: %s." % pieces_text(p))
        step("Check", " ".join(chk) + " Passes, 0 mm from your curve.")
        if k == 1:
            line = "Your curve holds. Made from %d glued layers in place of one solid piece." % n
        elif n == 1:
            line = "Your curve holds. Made from %d glued strips side by side in place of one solid piece." % k
        else:
            line = "Your curve holds. Glued both ways, %d layers of %d strips." % (n, k)
        return proposed(line, p)

    Rmt, Rmw = RATIO * (T / MAX_LAYERS) * c, RATIO * (W / MAX_STRIPS) * s
    Rmin = max(Rmt, Rmw)
    word = "layer" if Rmt >= Rmw else "strip"
    if "shape" in holds:
        return conflict("This curve is too tight for any %s we can cut." % word,
                        "The thinnest %s (%g mm) bends no tighter than %s. Your %s radius cannot be held."
                        % (word, MINLAM, m(Rmin), m(R)),
                        ("drawn radius " + m(R), "thinnest lamella %g mm" % MINLAM))
    dev = deviation_mm(R, Rmin, C)
    n2 = min(MAX_LAYERS, _count_for(T, Rmin / c if c else None))
    k2 = min(MAX_STRIPS, _count_for(W, Rmin / s if s else None))
    p = piece(Rmin, n2, k2)
    step("Decision", "Too tight even for the thinnest %s. Used %s and opened the radius to %s."
         % (word, pieces_text(p), m(Rmin)))
    step("Check", "Passes. The ghost sits %d mm from your curve at mid-span." % jround(dev))
    if k2 == 1:
        made = "%d glued layers" % n2
    elif n2 == 1:
        made = "%d glued strips" % k2
    else:
        made = "%d layers of %d strips" % (n2, k2)
    return proposed("Curve eased by %d mm, the tightest this timber bends, in %s." % (jround(dev), made), p)


# ---------------------------------------------------------------- v3: a stroke on a surface
# Spec v3 (scratch/2026-11-14/gnj-spec-v3.md). The core does all the maths; the client
# sends the surface as a grid and the stroke in normalized (u, v), and draws what comes back.

GRID_N = 21                 # the surface is sampled on GRID_N x GRID_N, row-major, u outer
MAX_STROKE_POINTS = 400
SADDLE_HALF_MM = 1500.0     # demo sample: z = 800 + (x^2 - y^2) / 6000, x and y in [-1500, 1500]
SADDLE_Z0_MM = 800.0
SADDLE_K = 6000.0


def saddle_point(u, v):
    """The demo saddle at normalized (u, v): u runs along x, v along y. mm."""
    x = -SADDLE_HALF_MM + 2 * SADDLE_HALF_MM * u
    y = -SADDLE_HALF_MM + 2 * SADDLE_HALF_MM * v
    return [x, y, SADDLE_Z0_MM + (x * x - y * y) / SADDLE_K]


def grid_from(evaluate, n=GRID_N):
    """Sample evaluate(u, v) -> [x, y, z] mm on an n x n grid over [0, 1]^2, row-major, u outer."""
    pts = []
    for i in range(n):
        for j in range(n):
            x, y, z = evaluate(i / (n - 1.0), j / (n - 1.0))
            pts.append([round(x, 3), round(y, 3), round(z, 3)])
    return {"nu": n, "nv": n, "points": pts}


def clean_stroke_uv(points_uv, max_points=MAX_STROKE_POINTS):
    """Clamp to [0, 1], drop repeats, thin evenly to at most max_points. None when under 2 remain."""
    out = []
    for u, v in points_uv:
        q = [round(min(1.0, max(0.0, u)), 6), round(min(1.0, max(0.0, v)), 6)]
        if not out or q != out[-1]:
            out.append(q)
    if len(out) < 2:
        return None
    if len(out) > max_points:
        step = (len(out) - 1) / (max_points - 1.0)
        out = [out[int(round(i * step))] for i in range(max_points)]
    return out


def surface_intent(grid, stroke_uv):
    return {"kind": "surface_stroke", "member_id": MEMBER_ID, "surface": grid, "stroke_uv": stroke_uv}


def is_surface(intent):
    return intent.get("kind") == "surface_stroke"


def is_part(intent):
    return intent.get("kind") == "part"


MIN_PART_POINTS, MAX_PART_POINTS = 300, 6000


def part_intent(points_mm, volume_mm3, member_id="P1"):
    """Spec v6 kind part: the designer's own closed solid, as 300 to 6000 surface points (mm, Z up)
    and its volume (mm3). The geometry is never altered; the core decides how it can be made."""
    return {"kind": "part", "member_id": member_id,
            "points": [[round(x, 1), round(y, 1), round(z, 1)] for x, y, z in points_mm],
            "volume_mm3": round(float(volume_mm3), 1)}


# ---------------------------------------------------------------- v9: three strokes build a plate
# Core contract: gnj-nudge-core docs/SPEC_V9.md, README "v9 plate". Units mm, Z up, in the core's own
# frame: the straight member runs from (0, 0, 0) to (2400, 0, 0), 89 mm across Y, 38 mm thick in Z.
# The core holds no current member between requests (slice 1 always starts from the straight one),
# so this client carries it: once a plate is accepted, a stroke left out is sent as that plate's own
# (its stations as the path, its end profiles as drawn on the straight member's end planes).

STROKES = ("path", "start", "end")
STROKE_NAMES = {"path": "Path", "start": "Start", "end": "End"}
STROKE_STATUS = {"drawn": "drawn", "kept": "kept as is", "photo": "from your photo"}
NOT_DRAWN = "not drawn"
PLATE_STATIONS = 65
MAX_PATH_POINTS, MAX_PROFILE_POINTS = 400, 100


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def straight_frames():
    return {"start": {"origin": [0.0, 0.0, 0.0], "tangent": [1.0, 0.0, 0.0], "across": [0.0, 1.0, 0.0],
                      "normal": [0.0, 0.0, 1.0]},
            "end": {"origin": [LENGTH_MM, 0.0, 0.0], "tangent": [1.0, 0.0, 0.0], "across": [0.0, 1.0, 0.0],
                    "normal": [0.0, 0.0, 1.0]}}


def straight_member():
    """The current member before any Accept: the core's straight 2x4 (core frame, mm)."""
    half = WIDTH_MM / 2.0
    return {"accepted": False,
            "stations": [[LENGTH_MM * i / (PLATE_STATIONS - 1.0), 0.0, 0.0] for i in range(PLATE_STATIONS)],
            "start": [[-half, 0.0], [half, 0.0]], "end": [[-half, 0.0], [half, 0.0]],
            "end_frames": straight_frames()}


def local_profile(points, frame):
    """3D points (core mm) -> (across, normal) in an end frame: the profile's shape on that plane."""
    o, a, n = frame["origin"], frame["across"], frame["normal"]
    return [[_dot(_sub(p, o), a), _dot(_sub(p, o), n)] for p in points]


def on_member_plane(local, which):
    """A local profile placed on the straight member's end plane, which the core reads as "member"."""
    x = 0.0 if which == "start" else LENGTH_MM
    return [[round(x, 3), round(q[0], 3), round(q[1], 3)] for q in local]


def thin(points, most):
    """Evenly thinned to at most `most` points, ends kept."""
    if len(points) <= most:
        return list(points)
    step = (len(points) - 1) / (most - 1.0)
    return [points[int(round(i * step))] for i in range(most)]


def row_means(grid):
    """The path under a plate grid: each row's mean is its station (profiles are centred on their mean)."""
    return [[sum(q[k] for q in row) / float(len(row)) for k in range(3)] for row in grid]


def plate_intent(strokes, current, member_id=MEMBER_ID):
    """Spec v9 kind plate from the strokes drawn (core mm; a missing one is not drawn) on the current
    member. thickness_mm is never sent: the session setting is the one in force."""
    path = strokes.get("path")
    if path is None and current.get("accepted"):
        path = current["stations"]
    out = {"kind": "plate", "member_id": member_id,
           "path": None if path is None else [[round(c, 2) for c in p] for p in thin(path, MAX_PATH_POINTS)]}
    for which in ("start", "end"):
        drawn = strokes.get(which)
        if drawn is not None:
            local = local_profile(thin(drawn, MAX_PROFILE_POINTS), current["end_frames"][which])
        elif current.get("accepted"):
            local = current[which]
        else:
            local = None
        out["profile_" + which] = None if local is None else on_member_plane(local, which)
        out["profile_%s_on" % which] = "member"
    return out


def is_plate(intent):
    return intent.get("kind") == "plate"


def member_from_form(form):
    """The accepted plate as the next current member: its stations, its end profiles read in its own
    end frames, and the end frames (where the next Start and End are drawn)."""
    ef = form["end_frames"]
    return {"accepted": True, "stations": [list(p) for p in form["stations"]],
            "start": local_profile(form["grid"][0], ef["start"]), "end": local_profile(form["grid"][-1], ef["end"]),
            "end_frames": ef}


def path_plane(view_dir, axis):
    """Daniel, 2026-11-15: a Path lands on the current member's upright plane (vertical, holding its
    axis and world Z) or its flat plane (horizontal, holding its axis), whichever the view faces more:
    compare |view . normal|; a tie goes upright. view_dir and axis are any-length 3-vectors."""
    def unit(v):
        n = math.sqrt(_dot(v, v)) or 1.0
        return [c / n for c in v]
    d, a = unit(view_dir), unit(axis)
    up = unit([a[1], -a[0], 0.0]) if abs(a[0]) + abs(a[1]) > 1e-9 else [1.0, 0.0, 0.0]   # axis x Z
    return "upright" if abs(_dot(d, up)) >= abs(d[2]) - 1e-12 else "flat"


# Two-view Path (Daniel, 2026-11-15): a Path drawn flat is the plan, upright the elevation; with both,
# one 3D path. "both" is the combined Path's plane, for its status line.
PATH_VIEW_WORDS = {"flat": "in plan", "upright": "in elevation", "both": "in plan and elevation"}
TWO_VIEW_STATIONS = 121


def _unit(v):
    n = math.sqrt(_dot(v, v)) or 1.0
    return [c / n for c in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _along(points, origin, along, side):
    """A stroke as (s, offset) pairs sorted by s: s along the member, offset along `side`."""
    pairs = sorted((_dot(_sub(p, origin), along), _dot(_sub(p, origin), side)) for p in points)
    return [q[0] for q in pairs], [q[1] for q in pairs]


def _at(xs, ys, x):
    """ys at x, linear between samples and held level past either end (xs ascending)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[hi] - xs[lo]
    return ys[lo] if span <= 0 else ys[lo] + (x - xs[lo]) / span * (ys[hi] - ys[lo])


def two_view_path(plan, elevation, current, stations=TWO_VIEW_STATIONS):
    """One 3D path (core mm) from a Path drawn flat (plan) and one drawn upright (elevation) over the
    current member: both resampled on the same stations along its chord, across from the plan, height
    from the elevation. The stations run from the first drawn point of either stroke to the last, each
    stroke held level past its own ends; the core pins the ends to the member's as for any Path. A
    stroke that doubles back along the member is read as sorted along it."""
    st = current["stations"]
    o = st[0]
    a = _unit(_sub(st[-1], o))
    w = _unit(_cross([0.0, 0.0, 1.0], a))   # level and square to the chord: +Y on the straight member
    h = _cross(a, w)                         # square to both: +Z on the straight member
    ps, py = _along(plan, o, a, w)
    es, ez = _along(elevation, o, a, h)
    s0, s1 = min(ps[0], es[0]), max(ps[-1], es[-1])
    out = []
    for i in range(stations):
        s = s0 + (s1 - s0) * i / (stations - 1.0)
        y, z = _at(ps, py, s), _at(es, ez, s)
        out.append([o[k] + s * a[k] + y * w[k] + z * h[k] for k in range(3)])
    return out


def drawn_words(plane):
    """'drawn', or 'drawn in plan' / 'drawn in elevation' / 'drawn in plan and elevation' for a Path."""
    return STROKE_STATUS["drawn"] + (" " + PATH_VIEW_WORDS.get(plane, plane) if plane else "")


def strokes_summary(sent, planes=None):
    """Inputs > Drawing: 'Path drawn in plan, Start kept as is, End drawn'; '' before any."""
    if not sent:
        return ""
    planes = planes or {}
    return ", ".join("%s %s" % (STROKE_NAMES[w], drawn_words(planes.get(w)) if sent.get(w) == "drawn"
                                else STROKE_STATUS.get(sent.get(w), NOT_DRAWN)) for w in STROKES)


# ---------------------------------------------------------------- billets (Daniel, 2026-11-15)
# Each piece's billet as a box, like the pink boxes of his reference image: the solid between the two
# closed outlines the core sends per billet (billet.outline, or pieces[i].billet.outline), labelled with
# the core's own sizes. Nothing here measures geometry.
def _loop_ok(loop):
    return (isinstance(loop, list) and len(loop) >= 4
            and all(isinstance(p, list) and len(p) == 3 and all(_number(c) is not None for c in p) for p in loop))


def billet_boxes(form):
    """[{"id": "B1", "outline": [loop, loop], "label": "B1 1204 x 595 x 190 mm"}], one per piece in order;
    a billet the core sent without its two outlines is left out (its id is kept for the others)."""
    if not isinstance(form, dict):
        return []
    pieces = [p for p in (form.get("pieces") or []) if isinstance(p, dict)]
    billets = [p.get("billet") for p in pieces] if pieces else [form.get("billet")]
    out = []
    for i, b in enumerate(billets):
        loops = b.get("outline") if isinstance(b, dict) else None
        if not (isinstance(loops, list) and len(loops) == 2 and all(_loop_ok(lp) for lp in loops)):
            continue
        bid = "B%d" % (i + 1)
        dims = [_number(b.get(k)) for k in ("length_mm", "width_mm", "depth_mm")]
        label = bid if None in dims else "%s %d x %d x %d mm" % ((bid,) + tuple(jround(d) for d in dims))
        out.append({"id": bid, "outline": loops, "label": label})
    return out


def loop_runs(loop, corner_deg=20.0):
    """A closed outline (last point repeating the first, or not) -> runs of point indices between its
    corners, each run sharing its end corner with the next. A billet's outline gives four: two sampled
    arcs and two straight ends, so its box is drawn with four smooth sides, not one face per sample."""
    pts = [list(p) for p in loop]
    if len(pts) > 1 and all(abs(a - b) < 1e-9 for a, b in zip(pts[0], pts[-1])):
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return []

    def turn(i):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - b[k] for k in range(3)]
        lu, lv = math.sqrt(sum(x * x for x in u)), math.sqrt(sum(x * x for x in v))
        if lu < 1e-9 or lv < 1e-9:
            return 0.0
        cos = max(-1.0, min(1.0, sum(u[k] * v[k] for k in range(3)) / (lu * lv)))
        return math.degrees(math.acos(cos))

    corners = [i for i in range(n) if turn(i) > corner_deg]
    if len(corners) < 2:
        return [list(range(n)) + [0]]
    runs = []
    for k, c in enumerate(corners):
        end = corners[(k + 1) % len(corners)]
        run = [c]
        i = c
        while i != end:
            i = (i + 1) % n
            run.append(i)
        runs.append(run)
    return runs


def _num_text(x):
    x = _number(x)
    return None if x is None else "%g" % x


def member_user_text(member_id, result):
    """[(key, text)] for an accepted member's Brep, from the answer as sent: id, layers, layer mm, waste,
    grain degrees (the largest any piece sent), piece count. A value the core did not send is left out."""
    sent = (result or {}).get("sent") or {}
    form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
    checks = form.get("checks") if isinstance(form.get("checks"), dict) else {}
    pieces = [p for p in (form.get("pieces") or []) if isinstance(p, dict)]
    grains = [checks.get("grain")] + [(p.get("checks") or {}).get("grain") for p in pieces]
    angles = [_number(g.get("angle_deg")) for g in grains if isinstance(g, dict)]
    angles = [a for a in angles if a is not None]
    pairs = [("gnj.id", member_id), ("gnj.layers", _num_text(form.get("n_lamellas"))),
             ("gnj.layer_mm", _num_text(form.get("lamella_mm"))),
             ("gnj.waste_pct", _num_text(checks.get("waste_pct"))),
             ("gnj.grain_deg", _num_text(max(angles)) if angles else None),
             ("gnj.pieces", "%d" % (len(pieces) or 1))]
    return [(k, v) for k, v in pairs if v is not None]


HELPER_DOWN ="The helper is not running, so there is no answer yet."
HELPER_REFUSED = "The helper could not read this stroke. Draw it again."
PART_REFUSED = "The helper cannot check this part yet."


def unavailable(sentence):
    return {"status": "unavailable", "form": None, "sentence": sentence, "steps": [], "deviation_mm": None,
            "source": "", "conflict": None, "via_core": False, "trimmed": False}


# ---------------------------------------------------------------- core contract
# ALL request/response mapping for gnj-nudge-core lives in this block.
# Contract: gnj-nudge-core README.md / server.py, shared spec v2.
#   POST /nudge {intent:{member_id, chord_mm, radius_mm, direction:"up"|"down", bend_angle_deg}, holds:[...]}
#     -> {status, form:{radius_mm, n_lamellas, lamella_mm, n_strips, strip_mm, chord_mm, direction,
#         bend_angle_deg}|null, sentence, steps:[{tag, text, limit_id}], deviation_mm, source, conflict, governing}
#   POST /judge {verdict:"accepted"|"rejected", hold?} -> {formal, verdict, ...}

def is_vertical(angle_deg):
    return dir_factors(angle_deg)[1] == 0.0


def nudge_request(intent, holds):
    """What goes on the wire: keys starting with "_" are this client's own and never sent."""
    return {"intent": dict((k, v) for k, v in intent.items() if not k.startswith("_")), "holds": sorted(holds)}


def nudge_response(body, intent):
    """Core (or local) /nudge body -> the one result shape the panel reads.

    A core that predates spec v2 ignores bend_angle_deg and would solve every
    bend as up or down. For a sideways bend its answer is refused here (it does
    not echo bend_angle_deg) and the caller falls back to the local v2 solver.
    """
    status = body.get("status")
    if status not in ("proposed", "conflict"):
        raise ValueError("unknown status %r" % (status,))
    if is_surface(intent):
        return _surface_response(body, status)
    if is_part(intent):
        return _part_response(body, status)
    if is_plate(intent):
        return _plate_response(body, status)
    form = body.get("form")
    angle = float(intent.get("bend_angle_deg", 0.0))
    v2 = isinstance(form, dict) and "bend_angle_deg" in form
    if not is_vertical(angle) and not v2:
        raise ValueError("the core did not answer in bend direction (spec v2)")
    if v2 and abs((float(form["bend_angle_deg"]) - angle + 180.0) % 360.0 - 180.0) > 0.5:
        raise ValueError("the core changed the bend direction, which the spec forbids")
    if status == "proposed":
        if not isinstance(form, dict):
            raise ValueError("a proposal without a form")
        n, t = int(form["n_lamellas"]), float(form["lamella_mm"])
        k = int(form.get("n_strips", 1))
        w = float(form.get("strip_mm", WIDTH_MM / k))
        form = {"radius_mm": float(form["radius_mm"]), "n_lamellas": n, "lamella_mm": t, "n_strips": k,
                "strip_mm": w, "chord_mm": float(form["chord_mm"]),
                "bend_angle_deg": float(form.get("bend_angle_deg", angle)),
                "direction": form.get("direction", intent.get("direction", "up"))}
        if form["radius_mm"] <= 0 or n < 1 or t <= 0 or k < 1 or w <= 0:
            raise ValueError("form numbers out of range")
    else:
        form = None
    steps = [{"tag": unicode_safe(s.get("tag", "")), "text": unicode_safe(s.get("text", ""))}
             for s in (body.get("steps") or []) if isinstance(s, dict)]
    dev = body.get("deviation_mm")
    return {"status": status, "form": form, "sentence": unicode_safe(body.get("sentence", ""))[:240],
            "steps": steps[:8], "deviation_mm": None if dev is None else float(dev),
            "source": unicode_safe(body.get("source", "fallback")), "conflict": body.get("conflict"),
            "taste": _taste(body.get("taste")), "waste_pct": waste_pct(body), "via_core": False,
            "sent": body}  # the response as sent, for the Technical view


def _number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if _finite(x) else None


def waste_pct(body):
    """Spec v4: checks.waste_pct, on the response or on its form. None when absent: never made up."""
    for src in (body, body.get("form") if isinstance(body.get("form"), dict) else {}):
        checks = src.get("checks") if isinstance(src, dict) else None
        if isinstance(checks, dict):
            v = _number(checks.get("waste_pct"))
            if v is not None and 0 <= v <= 100:
                return v
    return None


def tally_of(body):
    """Spec v4 tally {members, billet_m3, part_m3, waste_pct}: (members, waste_pct) or None."""
    t = body.get("tally") if isinstance(body, dict) and "tally" in body else body
    if not isinstance(t, dict):
        return None
    n, w = _number(t.get("members")), _number(t.get("waste_pct"))
    if n is None or w is None or n < 1 or not 0 <= w <= 100:
        return None
    return int(n), w


def _taste(raw):
    """{lead, because} when taste chose the answer, else None. Shown on the command line only."""
    if not isinstance(raw, dict) or raw.get("lead") not in ("solid", "makeup"):
        return None
    return {"lead": raw["lead"], "because": unicode_safe(raw.get("because", ""))[:200]}


def _finite(x):
    return not (math.isinf(x) or math.isnan(x))  # math.isfinite is Python 3 only


def _points(raw, name, n=None):
    if not isinstance(raw, list) or len(raw) < 2 or (n is not None and len(raw) != n):
        raise ValueError("form.%s must be a list of points" % name)
    out = []
    for q in raw:
        x, y, z = float(q[0]), float(q[1]), float(q[2])
        if not all(map(_finite, (x, y, z))):
            raise ValueError("form.%s has a number that is not finite" % name)
        out.append((x, y, z))
    return out


def _billet(raw):
    """Spec v4 billet: sizes, and its outline (closed polylines, world mm) drawn only while Why is open.
    None when absent or unreadable: the ghost never depends on it."""
    if not isinstance(raw, dict):
        return None
    out = {"mode": raw.get("mode") if raw.get("mode") in ("arc", "straight") else None}
    for k in ("length_mm", "width_mm", "depth_mm", "radius_mm", "volume_m3"):
        out[k] = _number(raw.get(k))
    lines = []
    for poly in raw.get("outline") or []:
        try:
            lines.append(_points(poly, "billet.outline"))
        except (ValueError, TypeError, IndexError, KeyError):
            continue
    out["outline"] = lines[:8]
    return out


def _surface_response(body, status):
    """Spec v3 /nudge body -> the result shape the panel reads. Model text is untrusted; numbers are checked."""
    form = None
    if status == "proposed":
        f = body.get("form")
        if not isinstance(f, dict) or f.get("kind") != "surface_member":
            raise ValueError("a surface proposal without a surface_member form")
        stations = _points(f.get("stations"), "stations")
        n_st = len(stations)
        form = {"kind": "surface_member", "stations": stations, "normals": _points(f.get("normals"), "normals", n_st),
                "intent_stations": _points(f.get("intent_stations") or f.get("stations"), "intent_stations"),
                "n_lamellas": int(f["n_lamellas"]), "lamella_mm": float(f["lamella_mm"]),
                "n_strips": int(f.get("n_strips") or 1),  # spec v4 drops strips for this kind
                "strip_mm": float(f.get("strip_mm") or WIDTH_MM / int(f.get("n_strips") or 1)),
                "length_mm": float(f.get("length_mm") or 0.0), "smoothing_passes": int(f.get("smoothing_passes") or 0),
                "straight_billet": bool(f.get("straight_billet")), "billet": _billet(f.get("billet"))}
        # A surface billet is pressed from the core's layer options to any depth it needs (less_waste
        # answered 5 layers of 8 mm on the saddle): sanity bounds only. MAX_LAYERS is the bend kind's
        # limit (38 mm stock in 8 mm layers) and must not be applied here.
        if not (1 <= form["n_lamellas"] <= MAX_SURFACE_LAYERS and 1 <= form["n_strips"] <= MAX_STRIPS
                and form["lamella_mm"] > 0 and form["strip_mm"] > 0):
            raise ValueError("form make-up out of range")
    steps = [{"tag": unicode_safe(s.get("tag", "")), "text": unicode_safe(s.get("text", ""))}
             for s in (body.get("steps") or []) if isinstance(s, dict)]
    dev = body.get("deviation_mm")
    return {"status": status, "form": form, "sentence": unicode_safe(body.get("sentence", ""))[:300],
            "steps": steps[:8], "deviation_mm": None if dev is None else float(dev),
            "source": unicode_safe(body.get("source", "")), "conflict": body.get("conflict"),
            "trimmed": bool(body.get("trimmed")), "waste_pct": waste_pct(body), "via_core": False,
            "sent": body}  # the response as sent, for the Technical view


def say_request(text):
    return {"text": text[:500]}


def say_response(body, intent):
    """Core /say body -> {understood, heard, actions [(op, name)], source, model_ms, nudge (or None)}.
    heard is the core's template, never model text; the nudge is read exactly as a /nudge answer."""
    if not isinstance(body, dict):
        raise ValueError("say answered something that is not an object")
    actions = []
    for a in body.get("actions") or []:
        if isinstance(a, dict) and a.get("op") in ("hold", "release") and HOLD_NAME_RE.match(a.get("name") or ""):
            actions.append((a["op"], a["name"]))
    nudge = None
    if body.get("understood") and isinstance(body.get("nudge"), dict):
        nudge = nudge_response(body["nudge"], intent)
        nudge["via_core"] = True
    return {"understood": bool(body.get("understood")) and nudge is not None,
            "heard": unicode_safe(body.get("heard", ""))[:200], "actions": actions,
            "source": unicode_safe(body.get("source", ""))[:40], "model_ms": _number(body.get("model_ms")),
            "nudge": nudge}


def _part_response(body, status):
    """Spec v6 part_plan -> the result shape the panel reads. The plan is kept as sent (for the
    System panel's per-piece numbers); cut lines and outlines are checked here, as they are drawn."""
    form = None
    if status == "proposed":
        f = body.get("form")
        if not isinstance(f, dict) or f.get("kind") != "part_plan":
            raise ValueError("a part proposal without a part_plan form")
        cuts = []
        for c in f.get("cuts") or []:
            if isinstance(c, dict) and isinstance(c.get("line"), list) and len(c["line"]) == 2:
                cuts.append({"at_mm": _number(c.get("at_mm")), "line": _points(c["line"], "cuts.line", 2)})
        outlines = []
        for poly in ((f.get("billet") or {}).get("outline") or []):
            try:
                outlines.append(_points(poly, "billet.outline"))
            except (ValueError, TypeError, IndexError, KeyError):
                continue
        n = int(f.get("n_pieces") or len(f.get("pieces") or []) or 1)
        if not 1 <= n <= 16:
            raise ValueError("n_pieces out of range")
        form = {"kind": "part_plan", "n_pieces": n, "cuts": cuts,
                "billet": {"outline": outlines[:32]},
                "length_mm": _number((f.get("axis") or {}).get("length_mm")),
                "n_lamellas": _number(((f.get("pieces") or [{}])[0] or {}).get("n_lamellas")),
                "lamella_mm": _number(((f.get("pieces") or [{}])[0] or {}).get("lamella_mm")),
                "n_strips": 1, "strip_mm": WIDTH_MM}
    steps = [{"tag": unicode_safe(s.get("tag", "")), "text": unicode_safe(s.get("text", ""))}
             for s in (body.get("steps") or []) if isinstance(s, dict)]
    return {"status": status, "form": form, "sentence": unicode_safe(body.get("sentence", ""))[:300],
            "steps": steps[:16], "deviation_mm": 0.0, "source": unicode_safe(body.get("source", "")),
            "conflict": body.get("conflict"), "trimmed": False, "waste_pct": waste_pct(body), "via_core": False,
            "sent": body}


def photo_media_type(name, head):
    """'image/jpeg' or 'image/png' from the file's first bytes (its name only as a hint), else None."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def photo_request(image_b64, media_type, member_id=MEMBER_ID):
    """The bytes themselves, never a path: the core opens no files."""
    return {"image_b64": image_b64, "media_type": media_type, "member_id": member_id}


def photo_response(body):
    """Core /photo body -> {understood, heard, bends, source, model_ms, nudge}. heard is the core's
    template; nudge is the plate the bends make (spec v9), read exactly as a /nudge answer."""
    if not isinstance(body, dict):
        raise ValueError("photo answered something that is not an object")
    nudge = body.get("nudge") if isinstance(body.get("nudge"), dict) else None
    proposal = None
    if nudge and nudge.get("status") in ("proposed", "conflict"):
        try:
            proposal = nudge_response(nudge, {"kind": "plate"})
            proposal["via_core"] = True
        except (ValueError, TypeError, KeyError, IndexError):
            proposal = None
    return {"understood": bool(body.get("understood")), "heard": unicode_safe(body.get("heard", ""))[:240],
            "bends": [b for b in (body.get("bends") or []) if isinstance(b, dict)][:3],
            "source": unicode_safe(body.get("source", ""))[:40], "model_ms": _number(body.get("model_ms")),
            "nudge": proposal}


def place_points(points, origin, axis, width, up=(0.0, 0.0, 1.0)):
    """Points in the core's member frame (X along the member, Y the width, Z up, first station at the
    origin) into the scene's frame: origin + x * axis + y * width + z * up, all in mm."""
    return [tuple(origin[k] + p[0] * axis[k] + p[1] * width[k] + p[2] * up[k] for k in range(3)) for p in points]


def _grid(raw, name):
    """A plate grid: rows of [x, y, z], every row the same length, every number finite."""
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("form.%s must be a grid of points" % name)
    rows = [_points(row, name) for row in raw]
    if len(set(len(r) for r in rows)) != 1:
        raise ValueError("form.%s rows differ in length" % name)
    return rows


def _frame(raw):
    out = {}
    for k in ("origin", "tangent", "across", "normal"):
        v = raw.get(k) if isinstance(raw, dict) else None
        if not isinstance(v, list) or len(v) != 3 or None in map(_number, v):
            raise ValueError("form.end_frames needs origin, tangent, across and normal")
        out[k] = [float(c) for c in v]
    return out


def _plate_response(body, status):
    """Spec v9 plate_member -> the result shape the panel reads. The grid, normals and end frames
    become geometry and the next current member, so they are checked here."""
    form = None
    if status == "proposed":
        f = body.get("form")
        if not isinstance(f, dict) or f.get("kind") != "plate_member":
            raise ValueError("a plate proposal without a plate_member form")
        grid = _grid(f.get("grid"), "grid")
        normals = _grid(f.get("normals"), "normals")
        if len(normals) != len(grid) or len(normals[0]) != len(grid[0]):
            raise ValueError("form.normals must match the grid")
        t = _number(f.get("thickness_mm"))
        n = int(f.get("n_lamellas") or 1)
        if t is None or not 0 < t <= 1000 or not 1 <= n <= MAX_SURFACE_LAYERS:
            raise ValueError("form thickness or layers out of range")
        ef = f.get("end_frames") or {}
        cuts = []
        for c in f.get("cuts") or []:
            if isinstance(c, dict) and isinstance(c.get("line"), list) and len(c["line"]) == 2:
                cuts.append({"at_mm": _number(c.get("at_mm")), "line": _points(c["line"], "cuts.line", 2)})
        eased = f.get("eased") if isinstance(f.get("eased"), dict) else {}
        form = {"kind": "plate_member", "grid": grid, "normals": normals,
                "intent_grid": _grid(f.get("intent_grid") or f.get("grid"), "intent_grid"),
                "stations": _points(f.get("stations"), "stations"), "thickness_mm": t,
                "end_frames": {"start": _frame(ef.get("start")), "end": _frame(ef.get("end"))},
                "eased": dict((k, _number(eased.get(k))) for k in ("path", "drift", "twist", "profiles")),
                "length_mm": _number(f.get("length_mm")), "n_lamellas": n,
                "lamella_mm": _number(f.get("lamella_mm")) or STOCK_MM, "n_strips": 1, "strip_mm": WIDTH_MM,
                "stock": bool(f.get("stock")), "straight_billet": bool(f.get("straight_billet")),
                "n_pieces": int(f.get("n_pieces") or 1), "cuts": cuts}
    steps = [{"tag": unicode_safe(s.get("tag", "")), "text": unicode_safe(s.get("text", ""))}
             for s in (body.get("steps") or []) if isinstance(s, dict)]
    dev = body.get("deviation_mm")
    return {"status": status, "form": form, "sentence": unicode_safe(body.get("sentence", ""))[:300],
            "steps": steps[:24], "deviation_mm": None if dev is None else float(dev),
            "source": unicode_safe(body.get("source", "")), "conflict": body.get("conflict"),
            "trimmed": False, "waste_pct": waste_pct(body), "via_core": False, "sent": body}


def judge_request(verdict, hold=None):
    body = {"verdict": verdict}
    if hold:
        body["hold"] = hold
    return body


def judge_response(body):
    """Core /judge body -> the formal record sentence."""
    return unicode_safe(body.get("formal", ""))


def unicode_safe(x):
    # The core already strips dashes from model text; do it again, model output is untrusted.
    s = x if isinstance(x, type(u"")) else (u"" if x is None else u"%s" % (x,))
    return re.sub(u"\\s*[\u2013\u2014]\\s*", u", ", s)


class CoreClient(object):
    """Talks to gnj-nudge-core; falls back to local_solve when it is down, errors, or predates v2."""

    def __init__(self, base=CORE_URL):
        self.base = base.rstrip("/")
        self.opener = _http.build_opener(_http.ProxyHandler({}))  # localhost, never via a proxy
        self.last_error = None

    def _post(self, path, body, timeout):
        data = json.dumps(body).encode("utf-8")
        req = _http.Request(self.base + path, data, {"Content-Type": "application/json"})
        try:
            resp = self.opener.open(req, timeout=timeout)
        except _http.HTTPError as e:  # 400 and friends: the core says why in {"error": ...}
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error") or ""
            except Exception:
                msg = ""
            raise IOError("core answered %s: %s" % (e.code, msg or "no reason given"))
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()

    def nudge(self, intent, holds):
        if is_surface(intent) or is_part(intent) or is_plate(intent):
            # No local solver for a surface, a part or a plate: the core is the single home of that maths.
            try:
                out = nudge_response(self._post("/nudge", nudge_request(intent, holds), NUDGE_TIMEOUT_S), intent)
                out["via_core"] = True
                self.last_error = None
                return out
            except Exception as e:
                self.last_error = "%s" % (e,)
                refused = self.last_error.startswith("core answered") or isinstance(e, ValueError)
                if not refused:
                    return unavailable(HELPER_DOWN)
                return unavailable(PART_REFUSED if is_part(intent) else HELPER_REFUSED)
        try:
            out = nudge_response(self._post("/nudge", nudge_request(intent, holds), NUDGE_TIMEOUT_S), intent)
            out["via_core"] = True
            self.last_error = None
            return out
        except Exception as e:  # core down, timed out, predates v2, or answered something unreadable
            self.last_error = "%s" % (e,)
            out = nudge_response(local_solve(intent, holds), intent)
            out["source"] = "fallback"
            return out

    def undo(self):
        """POST /undo (spec v9 slice 3): ("undone", body), ("nothing", None) on 409, or (None, None)
        when the core could not be asked."""
        try:
            body = self._post("/undo", {}, JUDGE_TIMEOUT_S)
            return ("undone", body) if isinstance(body, dict) and isinstance(body.get("undone"), dict) else (None, None)
        except Exception as e:
            self.last_error = "%s" % (e,)
            return ("nothing", None) if self.last_error.startswith("core answered 409") else (None, None)

    def photo(self, image_b64, media_type):
        """A photo read by the core (v8). None when the core could not be asked; last_error says why."""
        try:
            return photo_response(self._post("/photo", photo_request(image_b64, media_type), PHOTO_TIMEOUT_S))
        except Exception as e:
            self.last_error = "%s" % (e,)
            return None

    def say(self, text, intent):
        """The designer's typed words, read by the core (v5). None when the core could not be asked."""
        try:
            return say_response(self._post("/say", say_request(text), SAY_TIMEOUT_S), intent)
        except Exception as e:
            self.last_error = "%s" % (e,)
            return None

    def _get(self, path, timeout=JUDGE_TIMEOUT_S):
        resp = self.opener.open(self.base + path, timeout=timeout)
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()

    settings_sources = None   # where each setting's default comes from, as the core says

    def settings(self):
        """GET /settings (spec v6): the values in force, or None while the core has no such endpoint.
        The core answers {settings, sources, machines}; the values are unwrapped here."""
        try:
            body = self._get("/settings")
            if not isinstance(body, dict):
                return None
            if isinstance(body.get("sources"), dict):
                self.settings_sources = body["sources"]
            return body["settings"] if isinstance(body.get("settings"), dict) else body
        except Exception as e:
            self.last_error = "%s" % (e,)
            return None

    def post_settings(self, changes):
        """POST /settings with a partial update. The core's answer, or None: never a save it did not make."""
        try:
            body = self._post("/settings", dict(changes), JUDGE_TIMEOUT_S)
            return body if isinstance(body, dict) else None
        except Exception as e:
            self.last_error = "%s" % (e,)
            return None

    def tally(self):
        """(members, waste_pct) accepted so far, from GET /tally; None when the core has no tally."""
        try:
            resp = self.opener.open(self.base + "/tally", timeout=JUDGE_TIMEOUT_S)
            try:
                return tally_of(json.loads(resp.read().decode("utf-8")))
            finally:
                resp.close()
        except Exception:
            return None

    def start_over(self):
        """Rehearsals: POST /tally/reset and /taste/reset. True when the core took both."""
        ok = True
        for path in ("/tally/reset", "/taste/reset"):
            try:
                self._post(path, {}, JUDGE_TIMEOUT_S)
            except Exception as e:
                self.last_error = "%s" % (e,)
                ok = False
        return ok

    def judge(self, verdict, hold=None):
        """Formal sentence from the core, or None when it could not be recorded there."""
        try:
            return judge_response(self._post("/judge", judge_request(verdict, hold), JUDGE_TIMEOUT_S)) or None
        except Exception as e:
            self.last_error = "%s" % (e,)
            return None


class OfflineClient(CoreClient):
    """Never touches the network. Tests and a forced standalone mode."""

    def __init__(self):
        CoreClient.__init__(self)

    def _post(self, path, body, timeout):
        raise IOError("offline")

    def tally(self):
        return None

    def say(self, text, intent):
        return None

    def photo(self, image_b64, media_type):
        return None

    def undo(self):
        return None, None

    def settings(self):
        return None

    def post_settings(self, changes):
        return None


# ---------------------------------------------------------------- record text (local, as the 3D mock)

def makeup(form):
    n, k = form["n_lamellas"], form["n_strips"]
    if form.get("kind") == "plate_member":  # spec v9
        if form.get("stock"):
            return "one stock 2x4, no pressing"
        if form.get("straight_billet"):
            return "milled from one straight piece"
        if (form.get("n_pieces") or 1) > 1:
            return "%d pieces joined end to end, each pressed from layers, then milled" % form["n_pieces"]
        return "pressed from %d layers of %s mm, then milled to shape" % (n, n1(form["lamella_mm"]))
    if form.get("kind") == "surface_member":  # spec v4: one billet, pressed or straight, then milled
        if form.get("straight_billet") or n == 1:
            return "milled from one straight piece"
        return "pressed from %d layers of %s mm, then milled to shape" % (n, n1(form["lamella_mm"]))
    if n == 1 and k == 1:
        return "solid section"
    return ("glue-laminated, %d lamellas of %s mm through the thickness, %d strips of %s mm across the width"
            % (n, n1(form["lamella_mm"]), k, n1(form["strip_mm"])))


def formal_surface(form, dev):
    """Only used when the core could not record the verdict; the core's formal sentence is the real one."""
    return ("Member %s, softwood %g x %g mm, following the reference surface, length %s, %s. "
            "Deviation from intent %d mm. Not recorded by the helper." % (
                MEMBER_ID, STOCK_MM, WIDTH_MM, m(form["length_mm"]), makeup(form), jround(dev or 0.0)))


def formal_accept(form, dev, drawn_radius):
    if form["n_lamellas"] > 1 or form["n_strips"] > 1:
        beat = "a solid section, which fails the limit at this radius"
    elif dev > 0:
        beat = "the drawn %s radius, which fails the limit in solid stock" % m(drawn_radius)
    else:
        beat = "nothing, the gesture was buildable as drawn"
    return ("Member %s, softwood %g x %g mm, length %s. Single curvature, radius %s, bend direction %d degrees "
            "(0 up, 90 toward +Y, 180 down), %s. Governing limit: lamella thickness / radius no greater than 1/%g, "
            "checked across the thickness and the width. Deviation from intent %d mm at mid-span. Chosen over %s."
            % (MEMBER_ID, STOCK_MM, WIDTH_MM, m(LENGTH_MM), m(form["radius_mm"]), jround(form["bend_angle_deg"]),
               makeup(form), BEND_RATIO, jround(dev), beat))


NO_REASON = "No reason given yet."


def formal_reject(form, hold=None):
    why = ("Designer holds: %s." % HOLD_NAMES.get(hold, hold.replace("_", " "))) if hold else NO_REASON
    if form.get("kind") == "surface_member":
        return "Proposal declined: surface member, %s. %s" % (makeup(form), why)
    if form.get("kind") == "plate_member":
        return "Proposal declined: plate member, %s. %s" % (makeup(form), why)
    if form.get("kind") == "part_plan":   # a part plan has no radius and no make-up of its own
        n = int(form.get("n_pieces") or 1)
        return "Proposal declined: your own part, %s. %s" % (
            "in one piece" if n == 1 else "in %d pieces" % n, why)
    return "Proposal declined: radius %s, bend direction %d degrees, %s. %s" % (
        m(form["radius_mm"]), jround(form["bend_angle_deg"]), makeup(form), why)


# ---------------------------------------------------------------- session

PHASES = ("idle", "drawing", "thinking", "proposed", "rejected", "accepted", "conflict", "unavailable")

COMMAND_LINE = {
    "idle": "Draw the shape you want: path, start and end.",
    "drawing": "Drag in any view. Press Esc to cancel the stroke.",
    "thinking": "Finding the closest buildable shape.",
    "proposed": "Ghost shown. Accept or reject in the Nudge card.",
    "rejected": "Waiting for you. Redraw a stroke, or say what to keep.",
    "accepted": "Recorded. Draw again to change this member.",
    "conflict": "No buildable shape. Release a hold, redraw a stroke, or say what to change.",
    "unavailable": "No answer from the nudge core.",
}
# SPEC_V9_UI card table. A scene may word idle, rejected and accepted for itself (a surface: "line").
HEADLINE = {
    "idle": "Draw the shape you want.",
    "thinking": "Finding the closest buildable shape.",
    "rejected": "Rejected.",
    "accepted": "Accepted and recorded.",
}
SUBLINE = {
    "idle": "Path, start and end. Skip any you do not need.", "thinking": "", "proposed": "",
    "rejected": "I will not guess again. Redraw a stroke, or say what to keep.",
    "accepted": "Draw again to change this member.",
    "conflict": "Release a hold, redraw a stroke, or say what to change.",
    "unavailable": "",
}
DRAWING_HEAD = {"path": "Drawing the path.", "start": "Drawing the start profile.", "end": "Drawing the end profile."}
DRAWING_SUB = "Drag in any view. Press Esc to cancel the stroke."
NO_STROKE = "No stroke drawn. Press Path, Start or End, then drag in a view."
NOTHING_TO_UNDO = "Nothing to undo."
UNDID = "Undid the last accept."


class Session(object):
    """The panel's state machine, the same as the mock's.

    Nudging is split into begin_nudge() and finish_nudge() so Rhino can run the
    request off the UI thread; run_sync() does both for tests.
    On reject the session never guesses again by itself: only a new stroke,
    a hold change or Say starts another nudge.
    """

    def __init__(self, client):
        self.client = client
        self.phase = "idle"
        self.holds = {"solid": False, "shape": False}
        self.sag = None      # mm, always positive (the bend kind: tests and the offline solver)
        self.angle = 0.0     # bend direction, degrees from +Z toward +Y (after snapping)
        self.snapped = False
        self.stroke = None   # a surface_stroke intent (v3)
        self.part = None     # a part intent (v6): the designer's own solid, checked as modelled
        self.plate = None    # a plate intent (v9): the last three strokes sent
        self.strokes = {}    # v9: strokes drawn since the last Done, core mm, by "path", "start", "end"
        self.sent_strokes = {}   # what the last Done sent: "drawn", "kept" or "photo" per stroke
        self.drawing = None  # the stroke being drawn now, or None
        self.stroke_planes = {}  # the plane each drawn stroke landed on: the Path's "upright", "flat" or "both"
        self.path_views = {}     # the Path's plan ("flat") and elevation ("upright") strokes, while drawn
        self.sent_planes = {}    # ...and for the strokes the last Done sent
        self.current = straight_member()   # the member the next strokes change (v9)
        self.member_stack = []   # the current member before each Accept still on the record (Undo)
        self.result = None
        self.note = ""
        self.idle_text = None    # the scene's own words: invitation to draw,
        self.idle_sub = None     # and how,
        self.redraw_text = None  # what to do after a reject,
        self.again_text = None   # what to do after an accept,
        self.shape_word = "shape"  # and what "shape" is called (a line on a surface)
        self.record = []     # newest first: {"v": "accepted"|"rejected"|"undone", "text": ...}
        self.tally = None    # (members, waste_pct) after the last Accept, when the core keeps a tally
        self.core_live = False  # the last answer came from the core, so typed words can go to /say
        self.saying = False  # typed words are with the core
        self.reading_photo = False  # a photo is with the core
        self.photo_name = None      # Inputs > Photo
        self.photo_notice_due = True  # the first photo in a session says where it goes
        self.heard = ""      # what the core heard, shown above the new sentence until the next move
        self.heard_src = None  # ...and where it came from: ("say", actions), ("photo", bends), ("photo_no", None)
        self.members = []    # accepted and baked, oldest first: the System panel's Members grid
        self.settings = None  # the core's settings, once GET /settings answers (spec v6)
        self.gen = 0
        self._before_drawing = None

    # -- reading
    def held(self):
        return sorted(k for k in self.holds if self.holds[k])

    def has_gesture(self):
        return (self.plate is not None or self.part is not None or self.stroke is not None
                or self.sag is not None)

    def intent(self):
        if self.part is not None:
            return self.part
        if self.stroke is not None:
            return self.stroke
        if self.plate is not None:
            return self.plate
        return self._bend_intent()

    def _bend_intent(self):
        a = round(self.angle, 1) % 360.0
        return {"member_id": MEMBER_ID, "chord_mm": LENGTH_MM, "radius_mm": round(radius_of(self.sag), 1),
                "direction": "up" if math.cos(math.radians(a)) >= 0 else "down", "bend_angle_deg": a}

    def headline(self):
        if self.drawing:
            return DRAWING_HEAD[self.drawing]
        if self.saying:
            return SAYING
        if self.reading_photo:
            return READING_PHOTO
        if self.phase in ("proposed", "conflict") and self.result:
            return self.slots()["verdict"]
        if self.phase == "unavailable":
            return slots.NO_ANSWER
        if self.phase == "idle" and self.idle_text:
            return self.idle_text
        return HEADLINE.get(self.phase, "")

    def start_over(self):
        """Clear the tally and taste in the core, and this panel's own record and tally line. Undo
        cannot cross a tally reset, so nothing before it can be undone."""
        ok = self.client.start_over()
        self.record, self.tally, self.members, self.member_stack = [], None, [], []
        self.note = "" if ok else "The helper did not clear its tally."
        return ok

    def kind(self):
        """What the card is judging, for the words: part, surface, plate, or bend (the offline solver)."""
        if self.part is not None:
            return "part"
        if self.stroke is not None:
            return "surface"
        if self.plate is not None:
            return "plate"
        return "bend"

    def slots(self):
        """SPEC_V9_CARD_SLOTS: verdict, reason, facts and the trim echo of the proposal or conflict on
        screen, mapped from the core's sentence (gnj_slots). Empty slots when there is none."""
        if self.phase in ("proposed", "conflict") and self.result is not None:
            return slots.map_proposal(self.result, self.kind(), self.shape_word, self.held())
        return {"verdict": "", "reason": "", "facts": "", "echo": "", "action": None, "mapped": True, "unmapped": None}

    def unmapped(self):
        """The core sentence the slot table did not know, else None: logged once on the command line."""
        return self.slots()["unmapped"]

    def echo_line(self):
        """Slot 1: what the core heard, in up to 34 characters, else the trim note. Cleared on the next move."""
        if self.drawing or self.saying or self.reading_photo:
            return ""
        if self.heard:
            return slots.echo(self.heard_src, self.heard, self.shape_word, self.kind())
        return self.slots()["echo"] if self.phase in ("proposed", "conflict") else ""

    def waste_line(self):
        """Slot 4, Facts: 'Waste N%  Moved N mm  Needs N layers' (Moved only above 0, the one number for how
        far it moved). After an Accept or an Undo, the tally. Empty when the core sent nothing to show."""
        if self.drawing or self.saying or self.reading_photo:
            return ""
        if self.phase == "proposed" and self.result:
            return self.slots()["facts"]
        if self.phase in ("accepted", "idle") and self.tally:
            n, w = self.tally
            return "Accepted so far: %d member%s, %d%% waste." % (n, "" if n == 1 else "s", jround(w))
        return ""

    def subline(self):
        if self.drawing:
            return DRAWING_SUB
        if self.saying:
            return ""
        if self.reading_photo:
            return PHOTO_NOTICE if self.photo_notice_shown_now else ""
        if self.note:
            return self.note
        if self.phase in ("proposed", "conflict") and self.result:
            return self.slots()["reason"]
        if self.phase == "unavailable":
            return slots.NO_ANSWER_REASON
        if self.phase == "idle" and self.idle_sub is not None:
            return self.idle_sub
        if self.phase == "rejected" and self.redraw_text:
            return "I will not guess again. " + self.redraw_text
        if self.phase == "accepted" and self.again_text:
            return self.again_text
        return SUBLINE.get(self.phase, "")

    def source_line(self):
        """Where the last answer came from, for the command line."""
        r = self.result
        if r is None:
            return ""
        if not r.get("via_core"):
            return "Source: local solver (core offline or before spec v2)"
        return "Source: core, %s" % r.get("source", "")

    def can_judge(self):
        return self.phase == "proposed" and self.result is not None and self.result["form"] is not None

    # -- the three strokes (v9)
    def stroke_status(self, which):
        """The card's line under each stroke button ("drawn, upright" for a Path on the upright plane).
        After an Accept the plate is the new member: none of its strokes is drawn yet (Inputs > Drawing
        still says what was sent)."""
        if which in self.strokes:
            return drawn_words(self.stroke_planes.get(which))
        if self.strokes or self.phase == "accepted":
            return NOT_DRAWN
        if self.sent_strokes.get(which) == "drawn":
            return drawn_words(self.sent_planes.get(which))
        return STROKE_STATUS.get(self.sent_strokes.get(which), NOT_DRAWN)

    def drawing_summary(self):
        """Inputs > Drawing: the strokes as they stand now while any is drawn and not sent, else what
        the last Done sent, in the card's words. '' before anything was drawn."""
        if self.strokes:
            return ", ".join("%s %s" % (STROKE_NAMES[w], self.stroke_status(w)) for w in STROKES)
        return strokes_summary(self.sent_strokes, self.sent_planes)

    def can_done(self):
        return bool(self.strokes) and not self.drawing and self.phase != "thinking"

    def begin_drawing(self, which):
        """The card is in 'drawing a stroke' while _Sketch runs."""
        if which not in STROKES or self.phase == "thinking" or self.saying or self.reading_photo:
            return False
        if self.drawing is None:
            self._before_drawing = (self.note, self.heard)
        self.drawing, self.note, self.heard = which, "", ""
        return True

    def end_drawing(self, which, points_mm, plane=None):
        """The stroke as read, core mm (None: nothing drawn, Esc). The last one drawn counts. plane: the
        Path's "upright" (elevation) or "flat" (plan). A Path drawn in plan and in elevation is one 3D
        path (two_view_path); redrawing one view replaces only that view."""
        self.drawing = None
        if points_mm is None or len(points_mm) < 2:
            self.note = NO_STROKE
            return False
        points = [list(p) for p in points_mm]
        if which == "path":
            # The views belong to the Path drawn since the last Done: none once strokes were cleared.
            views = self.path_views if "path" in self.strokes else {}
            self.path_views = views
            if plane in ("flat", "upright"):
                views[plane] = points
            else:
                views.clear()   # a curve read in 3D is the whole path
            if len(views) == 2:
                points, plane = two_view_path(views["flat"], views["upright"], self.current), "both"
        self.strokes[which] = points
        self.stroke_planes[which] = plane
        return True

    def cancel_strokes(self):
        """Cancel: the strokes not sent yet are dropped; the card goes back to where it was."""
        self.strokes, self.drawing, self.stroke_planes = {}, None, {}
        if self._before_drawing is not None:
            self.note, self.heard = self._before_drawing
        self._before_drawing = None

    def done(self):
        """Done: one plate request from the strokes drawn, the rest kept as is. True: nudge."""
        if not self.can_done():
            return False
        self.plate = plate_intent(self.strokes, self.current)
        self.sent_strokes = dict((w, "drawn" if w in self.strokes else "kept") for w in STROKES)
        self.sent_planes = dict(self.stroke_planes)
        self.strokes, self.part, self.stroke, self.sag, self.snapped = {}, None, None, None, False
        self.stroke_planes = {}
        self._before_drawing = None
        return True

    # -- nudging
    def begin_nudge(self):
        """Start a nudge. Returns (gen, intent, holds) to send, or None when there is no gesture yet."""
        if not self.has_gesture():
            return None
        self.gen += 1
        self.phase, self.result, self.note, self.heard, self.saying = "thinking", None, "", "", False
        return self.gen, self.intent(), self.held()

    def finish_nudge(self, gen, result):
        """Apply a nudge result. A stale one (a newer gesture or hold came in meanwhile) is dropped."""
        if gen != self.gen or self.phase != "thinking":
            return False
        if (self.stroke is None and self.part is None and self.plate is None and self.snapped and result["steps"]
                and result["steps"][0]["tag"] == "Heard"):
            # The core does not know the gesture was snapped; say so plainly. A core answer keeps its
            # own words and gains one sentence; the local solver speaks as the mock does.
            if result.get("via_core"):
                result["steps"][0]["text"] += " Read as %s." % snap_word(self.angle)
            else:
                result["steps"][0]["text"] = "Bend the full 2.4 m to a radius of %s, read as %s." % (
                    m(radius_of(self.sag)), snap_word(self.angle))
        self.result = result
        self.phase = {"proposed": "proposed", "conflict": "conflict"}.get(result["status"], "unavailable")
        self.core_live = bool(result.get("via_core"))
        return True

    def run_sync(self):
        ticket = self.begin_nudge()
        if ticket:
            gen, intent, holds = ticket
            self.finish_nudge(gen, self.client.nudge(intent, holds))
        return ticket is not None

    # -- the designer's moves. Each returns True when a nudge must be started.
    def gesture(self, sag_mm, angle_deg=0.0, snapped=None):
        """The bend kind (v1, v2), kept for the offline solver and its tests; the card draws plates.
        snapped None: snap in world angle. True or False: the client already snapped on screen."""
        if sag_mm is None:
            return False
        self.sag, self.stroke, self.part, self.plate = abs(sag_mm), None, None, None
        if snapped is None:
            self.angle, self.snapped = snap_angle(angle_deg)
        else:
            self.angle, self.snapped = float(angle_deg) % 360.0, bool(snapped)
        return True

    def stroke_on_surface(self, intent):
        """v3: a stroke drawn on a surface. Returns True: a nudge must be started."""
        self.stroke, self.sag, self.snapped, self.part, self.plate = intent, None, False, None, None
        return True

    def check_part(self, intent):
        """v6: the designer's own solid, checked as modelled. Returns True: a nudge must be started."""
        self.part, self.stroke, self.sag, self.snapped = intent, None, None, False
        return True

    def accept(self):
        """Record the proposal as accepted. The caller bakes geometry first. An accepted plate becomes
        the current member; the one before it is kept for Undo last accept."""
        if not self.can_judge():
            return None
        r = self.result
        formal = self.client.judge("accepted") if r.get("via_core") else None
        dev = r["deviation_mm"] or 0.0
        form = r["form"] or {}
        if formal is None:
            if self.part is not None:
                formal = "Part %s, checked as modelled: %s. Not recorded by the helper." % (
                    self.part.get("member_id", "P1"), r["sentence"])
            elif form.get("kind") == "plate_member":
                formal = "Member %s, plate %s, %s. Largest move %d mm. Not recorded by the helper." % (
                    MEMBER_ID, m(form.get("length_mm") or LENGTH_MM), makeup(form), jround(dev))
            elif self.stroke is not None:
                formal = formal_surface(dict(form, length_mm=form.get("length_mm") or LENGTH_MM), dev)
            else:
                formal = formal_accept(form, dev, radius_of(self.sag))
        self.record.insert(0, {"v": "accepted", "text": formal})
        self.heard = ""
        self.holds = {"solid": False, "shape": False}  # holds belong to one decision; they survive Reject, not Accept
        self.tally = self.client.tally() if r.get("via_core") else None
        self.member_stack.append(self.current)
        if form.get("kind") == "plate_member" and self.part is None:
            self.current = member_from_form(form)
        self.phase, self.note = "accepted", ""
        return r

    def next_member_id(self):
        """The id the next accepted member gets (its Brep carries it as user text, baked before the row)."""
        return "M%d" % (len(self.members) + 1)

    def add_member(self, result, object_ids):
        """After Accept and bake: one row for the Members grid, from the accepted answer as sent."""
        sent = result.get("sent") or {}
        form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
        length = _number(form.get("length_mm")) or _number(form.get("chord_mm"))
        pieces = form.get("pieces") if isinstance(form.get("pieces"), list) else []
        if self.part is not None:
            length = _number((form.get("axis") or {}).get("length_mm")) if isinstance(form.get("axis"), dict) else None
            first = pieces[0] if pieces and isinstance(pieces[0], dict) else {}
            form = dict(form, n_lamellas=first.get("n_lamellas"), lamella_mm=first.get("lamella_mm"))
            kind = "part" if len(pieces) < 2 else "part, %d pieces" % len(pieces)
        elif (result.get("form") or {}).get("kind") == "plate_member":
            kind = "plate" if len(pieces) < 2 else "plate, %d pieces" % len(pieces)
        else:
            kind = "surface" if self.stroke is not None else "bend"
        row = {"id": self.next_member_id(), "kind": kind,
               "length_mm": length, "n_lamellas": _number(form.get("n_lamellas")),
               "lamella_mm": _number(form.get("lamella_mm")), "waste_pct": result.get("waste_pct"),
               "object_ids": list(object_ids or [])}
        self.members.append(row)
        return row

    def undo_last(self):
        """Undo last accept: POST /undo. Returns the Members row undone (its object_ids are the caller's
        to delete) or None. On 409, 'Nothing to undo.' and nothing else changes."""
        status, body = self.client.undo()
        if status == "nothing" or (status is None and not self.members):
            self.note = NOTHING_TO_UNDO
            return None
        if status is None:
            self.note = HELPER_DOWN
            return None
        row = self.members.pop() if self.members else None
        if self.member_stack:
            self.current = self.member_stack.pop()
        t = tally_of(body)
        self.tally = t
        self.record.insert(0, {"v": "undone", "text": UNDID})
        self.phase, self.result, self.note, self.heard, self.strokes = "idle", None, "", "", {}
        self.plate, self.part, self.stroke, self.sent_strokes = None, None, None, {}
        return row

    def _log_reject(self, hold=None):
        r = self.result
        formal = self.client.judge("rejected", hold) if r.get("via_core") else None
        self.record.insert(0, {"v": "rejected", "text": formal or formal_reject(r["form"], hold)})

    def reject(self):
        if not self.can_judge():
            return False
        self._log_reject()
        self.phase, self.result, self.note, self.heard = "rejected", None, "", ""
        return False

    def add_hold(self, k):
        if k not in self.holds:
            return False
        if self.holds[k]:
            self.note = "That is already held."
            return False
        if self.can_judge():
            self._log_reject(k)
        elif (self.phase == "rejected" and self.record and self.record[0]["v"] == "rejected"
              and NO_REASON in self.record[0]["text"]):
            # Locally amend the reason. The core's record is append-only, so its line keeps "no reason".
            self.record[0]["text"] = self.record[0]["text"].replace(
                NO_REASON, "Designer holds: %s." % HOLD_NAMES[k])
        self.holds[k] = True
        if not self.has_gesture():
            self.note = "Held. Draw a stroke to use it."
            return False
        return True

    def release_hold(self, k):
        if not self.holds.get(k):
            return False
        self.holds[k] = False
        return self.has_gesture() and self.phase not in ("idle", "accepted")

    # -- a photo (v8, v9): the core reads it into bends and answers with the plate they make
    photo_notice_shown_now = False

    def begin_photo(self, name):
        """Returns the gen to finish with, or None (one photo at a time)."""
        if self.reading_photo or self.saying:
            return None
        self.gen += 1
        self.reading_photo, self.photo_name, self.note, self.heard = True, name, "", ""
        self.photo_notice_shown_now, self.photo_notice_due = self.photo_notice_due, False
        return self.gen

    def finish_photo(self, gen, reply, refused=False):
        """Show what the core read. Not read: its line, nothing changes. Read: the plate the bends make
        is the proposal, judged like the strokes' (spec v9: the photo builds the path, profiles kept)."""
        if gen != self.gen or not self.reading_photo:
            return False
        self.reading_photo = False
        if reply is None:
            self.note = PHOTO_REFUSED if refused else HELPER_DOWN
            return True
        if not reply["understood"]:
            self.note = reply["heard"]   # the Reason slot carries the full line
            self.heard, self.heard_src = reply["heard"], ("photo_no", None)
            return True
        self.heard, self.heard_src = reply["heard"], ("photo", reply.get("bends") or [])
        if reply.get("nudge") is None:
            self.note = PHOTO_REFUSED
            return True
        r = reply["nudge"]
        self.part, self.stroke, self.sag, self.snapped, self.strokes = None, None, None, False, {}
        if r.get("form"):   # what the core built, as this client would send it again (a hold re-sends it)
            self.plate = plate_intent({"path": row_means(r["form"]["intent_grid"])}, straight_member())
        else:
            self.plate = plate_intent({}, straight_member())
        self.sent_strokes = {"path": "photo", "start": "kept", "end": "kept"}
        self.result = r
        self.phase = r["status"] if r["status"] in ("proposed", "conflict") else "unavailable"
        self.core_live, self.note = True, ""
        return True

    # -- typed words (v5): the core reads them; this client keeps no keyword list of its own
    def begin_say(self, text):
        """Returns (gen, text, intent) to send to /say, or None with a note saying why not."""
        text = (text or "").strip()
        if not text or self.saying:
            return None
        if not self.has_gesture():
            self.note = "Draw first, then say what to keep."
            return None
        if not self.core_live:
            self.note = HELPER_FOR_WORDS
            return None
        self.gen += 1
        self.saying, self.note, self.heard = True, "", ""
        return self.gen, text, self.intent()

    def finish_say(self, gen, reply):
        """Apply the core's reading. Understood: holds change as it says and its new proposal is shown
        exactly as a /nudge answer. Not understood: its line is shown and nothing changes."""
        if gen != self.gen or not self.saying:
            return False
        self.saying = False
        if reply is None:
            self.note = HELPER_FOR_WORDS
            return True
        if not reply["understood"]:
            self.heard, self.heard_src = reply["heard"], ("say", [])   # the Echo slot says it was not caught
            return True
        if self.can_judge():  # the core declined the proposal on screen first, as the Keep buttons do
            added = next((n for op, n in reply["actions"] if op == "hold" and not self.holds.get(n)), None)
            self.record.insert(0, {"v": "rejected", "text": formal_reject(self.result["form"], added)})
        for op, name in reply["actions"]:
            self.holds[name] = op == "hold"
        self.heard, self.heard_src = reply["heard"], ("say", list(reply["actions"]))
        self.phase = "thinking"
        return self.finish_nudge(gen, reply["nudge"])
