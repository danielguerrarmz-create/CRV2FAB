# -*- coding: utf-8 -*-
"""The System panel's content: pure Python (IronPython 2.7 and CPython 3), no Rhino.

Everything here reads the core's response as sent (result["sent"]) and shows only what is there: a
number the core did not send is not shown, never computed here (the core is the one home of billet
logic). The company-internal machine name is never shown. SPEC_V9_UI: "This proposal" is a list of
check lines; the only "how far it moved" number is deviation_mm ("Largest move"), and a value is
never cut short (the panel wraps it).
"""
from __future__ import division

import math

# Curvature classes (the analyzer drop's four), and the radius above which a direction counts as flat.
FLAT_RADIUS_MM = 100000.0   # 100 m
CURVATURE_CLASSES = ("flat", "single", "dome", "saddle")
CURVATURE_LABELS = {"flat": "Flat", "single": "Singly curved", "dome": "Dome", "saddle": "Saddle"}
CURVATURE_RGB = {"flat": (214, 214, 204), "single": (122, 182, 122), "dome": (232, 168, 78), "saddle": (182, 108, 168)}

# Inputs the user may edit once the core offers GET /settings (spec v6 section 2).
SETTING_FIELDS = (("thickness_mm", "Thickness", "mm"), ("lam_options_mm", "Layer options", "mm"),
                  ("lam_ratio", "Bend ratio", "x layer"), ("allowance_mm", "Allowance", "mm"),
                  ("max_waste_pct", "Waste target", "%"), ("opening_mm", "Machine opening", "mm"),
                  ("max_length_mm", "Max length", "mm"), ("max_pieces", "Max pieces", ""))
NOT_AVAILABLE = "Settings not available yet."


def classify(k1, k2, flat_radius_mm=FLAT_RADIUS_MM):
    """Principal curvatures (1/mm) -> flat, single, dome or saddle. A principal radius above
    flat_radius_mm counts as flat in that direction."""
    def curved(k):
        return k is not None and abs(k) * flat_radius_mm > 1.0
    c1, c2 = curved(k1), curved(k2)
    if not c1 and not c2:
        return "flat"
    if c1 != c2:
        return "single"
    return "dome" if k1 * k2 > 0 else "saddle"


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return None if math.isinf(x) or math.isnan(x) else x


def _m(mm):
    return "%.2f m" % (mm / 1000.0)


def _mm(x):
    return "%d" % int(math.floor(x + 0.5))


def _pct(x):
    return "%d%%" % int(math.floor(x + 0.5))


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _lam_text(t):
    return ("%.1f" % t).rstrip("0").rstrip(".")


def _pass(ok):
    return "Pass" if ok else "Fail"


def _form_of(result):
    sent = (result or {}).get("sent") or {}
    return sent, (sent.get("form") if isinstance(sent.get("form"), dict) else {})


def _per_piece(form):
    """[(checks, lamella_mm)] for every billet: each piece's own, else the form's one."""
    pieces = [p for p in (form.get("pieces") or []) if isinstance(p, dict)]
    if pieces:
        return [(p.get("checks") if isinstance(p.get("checks"), dict) else {}, _num(p.get("lamella_mm")))
                for p in pieces]
    return [(form.get("checks") if isinstance(form.get("checks"), dict) else {}, _num(form.get("lamella_mm")))]


def made_as(form):
    """SPEC_V9_UI 'Made as': stock board, one straight piece, pressed in one curve from N layers of
    N mm, or N pieces. From billet.mode, n_lamellas, lamella_mm and pieces, as sent."""
    pieces = [p for p in (form.get("pieces") or []) if isinstance(p, dict)]
    b = form.get("billet") if isinstance(form.get("billet"), dict) else {}
    if len(pieces) > 1:
        return "%d pieces joined end to end" % len(pieces)
    if pieces:   # one piece of a part: its own numbers
        form = dict(form, n_lamellas=pieces[0].get("n_lamellas"), lamella_mm=pieces[0].get("lamella_mm"))
        b = pieces[0].get("billet") if isinstance(pieces[0].get("billet"), dict) else b
    n, t = _num(form.get("n_lamellas")), _num(form.get("lamella_mm"))
    if b.get("mode") == "stock" or form.get("stock"):
        return "one piece as it comes"
    if form.get("straight_billet"):
        return "one straight piece"
    if n is None or t is None:
        return None
    if b.get("mode") == "straight":
        return "glued straight from %d layers of %s mm" % (int(n), _lam_text(t))
    return "pressed in one curve from %d layers of %s mm" % (int(n), _lam_text(t))


def check_lines(result):
    """[(label, value)] for 'This member': Bend, Machine, Grain, Made as, Waste, Largest move (the card's own words).
    Only the lines the core sent; [] when there is no proposal."""
    sent, form = _form_of(result)
    if not form:
        return []
    rows = []
    checks = form.get("checks") if isinstance(form.get("checks"), dict) else {}
    per = _per_piece(form)
    bends = [(c.get("bend"), t) for c, t in per if isinstance(c.get("bend"), dict)]
    if bends or isinstance(checks.get("bend"), dict):
        ok = all(b.get("ok", True) for b, _ in bends) if bends else checks["bend"].get("ok", True)
        text = _pass(ok)
        tight = [(b, t) for b, t in bends if b.get("applies", True) and _num(b.get("tightest_radius_mm")) is not None]
        if tight:
            b, t = min(tight, key=lambda bt: _num(bt[0]["tightest_radius_mm"]))
            text += ", layers bend to %s" % _m(_num(b["tightest_radius_mm"]))
            limit = _num(b.get("limit"))
            if limit is not None and t is not None:
                text += ", limit %s" % _m(limit * t)
        elif bends and not any(b.get("applies", True) for b, _ in bends):
            text += ", no pressing"
        rows.append(("Bend", text))
    machines = [c.get("machine") for c, _ in per if isinstance(c.get("machine"), dict)]
    if machines or isinstance(checks.get("machine"), dict):
        ok = all(mc.get("ok", True) for mc in machines) if machines else checks["machine"].get("ok", True)
        text = _pass(ok)
        sized = [mc for mc in machines if isinstance(mc.get("need_mm"), list) and isinstance(mc.get("opening_mm"), list)
                 and len(mc["need_mm"]) == 2 and len(mc["opening_mm"]) == 2]
        if sized:
            mc = max(sized, key=lambda x: (_num(x["need_mm"][0]) or 0) * (_num(x["need_mm"][1]) or 0))
            text += ", billet %s x %s mm, opening %s x %s mm" % (_mm(mc["need_mm"][0]), _mm(mc["need_mm"][1]),
                                                    _mm(mc["opening_mm"][0]), _mm(mc["opening_mm"][1]))
        elif machines and not any(mc.get("applies", True) for mc in machines):
            text += ", no milling"
        rows.append(("Machine", text))
    grain = checks.get("grain") if isinstance(checks.get("grain"), dict) else None
    if grain is not None and form.get("kind") == "plate_member":
        a, limit = _num(grain.get("angle_deg")), _num(grain.get("limit"))
        text = _pass(grain.get("ok", True))
        if a is not None and limit is not None:
            text += ", %s degrees off the path, limit %s" % (_mm(a), _mm(limit))
        rows.append(("Grain", text))
    made = made_as(form)
    if made:
        rows.append(("Made as", made))
    waste = _num(checks.get("waste_pct"))
    if waste is not None:
        rows.append(("Waste", _pct(waste)))
    dev = _num(sent.get("deviation_mm"))
    if dev is not None and int(math.floor(dev + 0.5)) > 0:
        rows.append(("Largest move", "%s mm" % _mm(dev)))
    return rows


def format_setting(key, value):
    """A setting's value as the text in its box."""
    if value is None:
        return ""
    if key == "opening_mm" and isinstance(value, list) and len(value) == 2:
        return "%s x %s" % (_mm(value[0]), _mm(value[1]))
    if key == "lam_options_mm" and isinstance(value, list):
        return ", ".join("%g" % v for v in value)
    v = _num(value)
    return "" if v is None else ("%g" % v)


def parse_setting(key, text):
    """The user's text -> the value to post. Raises ValueError with a plain reason."""
    s = (text or "").strip().lower()
    if key == "max_waste_pct" and s in ("", "off", "none"):
        return None
    if key == "lam_options_mm":
        parts = [p for p in s.replace(",", " ").split() if p]
        try:
            vals = sorted(set(float(p) for p in parts), reverse=True)
        except ValueError:
            raise ValueError("Layer options are thicknesses in mm, such as 38, 17, 11.")
        if not 1 <= len(vals) <= 8 or min(vals) <= 0:
            raise ValueError("Layer options are 1 to 8 thicknesses above 0 mm.")
        return vals
    if key == "opening_mm":
        parts = [p for p in s.replace(",", " ").replace("x", " ").split() if p]
        if len(parts) != 2:
            raise ValueError("Opening is width x height, in mm.")
        vals = [float(p) for p in parts]
        if min(vals) <= 0:
            raise ValueError("Opening must be above 0 mm.")
        return vals
    try:
        v = float(s)
    except ValueError:
        raise ValueError("%s must be a number." % dict((k, n) for k, n, _ in SETTING_FIELDS)[key])
    if key == "max_waste_pct" and not 0 < v < 100:
        raise ValueError("Waste target is a percentage between 0 and 100.")
    if key in ("allowance_mm",) and v < 0:
        raise ValueError("Allowance cannot be negative.")
    if key == "lam_ratio" and v <= 0:
        raise ValueError("Bend ratio must be above 0.")
    if key == "max_length_mm" and v <= 0:
        raise ValueError("Max length must be above 0 mm.")
    if key == "thickness_mm" and not 1 <= v <= 500:
        raise ValueError("Thickness is 1 to 500 mm.")
    if key == "max_pieces":
        if v != int(v) or v < 1:
            raise ValueError("Max pieces is a whole number, 1 or more.")
        return int(v)
    return v


def changed_settings(current, texts):
    """{key: value} for the boxes whose parsed value differs from the core's current value."""
    out = {}
    for key, _, _ in SETTING_FIELDS:
        if key not in texts:
            continue
        value = parse_setting(key, texts[key])
        now = current.get(key)
        if isinstance(value, list) and isinstance(now, list):
            same = len(value) == len(now) and all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(value, now))
        elif value is None or now is None:
            same = value is None and now is None
        else:
            same = abs(float(value) - float(now)) < 1e-9
        if not same:
            out[key] = value
    return out


def core_reason(error_text):
    """The core's own words from a refused request ('core answered 400: lam_ratio must be ...')."""
    text = error_text or ""
    if text.startswith("core answered") and ": " in text:
        return text.split(": ", 1)[1]
    return text or "the helper did not answer."


def gesture_summary(session):
    """Inputs > Drawing, as a person would say it, never coordinates. '' before anything was drawn.
    A plate: what the last Done sent, stroke by stroke (SPEC_V9_UI)."""
    if session is None:
        return ""
    if getattr(session, "part", None) is not None:
        sent = (session.result or {}).get("sent") or {}
        form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
        length = _num((form.get("axis") or {}).get("length_mm")) if isinstance(form.get("axis"), dict) else None
        return "Your own part, checked as modelled%s." % (", %s long" % _m(length) if length else "")
    if getattr(session, "stroke", None) is not None:
        sent = (session.result or {}).get("sent") or {}
        form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
        length = _num(form.get("length_mm"))
        return "A line across the surface, %s long." % _m(length) if length else "A line across the surface."
    live = getattr(session, "drawing_summary", None)
    return live() if live is not None else ""


def model_name(name):
    """The object's name as a person reads it: no formula ("Reference saddle, z = ..." -> "Reference saddle")."""
    name = (name or "").strip()
    return name.split(",")[0].strip() if name else "none"


# Tightest radius of a surface, as a colour gradient from the bend limit (tight) to flat (100 m).
RADIUS_RGB = ((196, 64, 52), (224, 112, 64), (236, 166, 88), (228, 208, 120), (192, 210, 168), (214, 214, 204))


def tightest_radius_mm(k1, k2):
    """The smaller principal radius at a point, mm; None when both directions are flat (above 100 m)."""
    k = max(abs(k1 or 0.0), abs(k2 or 0.0))
    if k * FLAT_RADIUS_MM <= 1.0:
        return None
    return 1.0 / k


def radius_bin(radius_mm, limit_mm):
    """0 (at or under the limit) .. len(RADIUS_RGB)-1 (flat), on a log scale from the limit to 100 m."""
    last = len(RADIUS_RGB) - 1
    if radius_mm is None or radius_mm >= FLAT_RADIUS_MM:
        return last
    lo = limit_mm if limit_mm and limit_mm > 0 else 1000.0
    if radius_mm <= lo:
        return 0
    f = math.log(radius_mm / lo) / math.log(FLAT_RADIUS_MM / lo)
    return max(1, min(last - 1, 1 + int(f * (last - 1))))


def radius_legend(limit_mm):
    """[(rgb, text)] for the gradient, tight to flat."""
    last = len(RADIUS_RGB) - 1
    lo = limit_mm if limit_mm and limit_mm > 0 else 1000.0
    edges = [lo * (FLAT_RADIUS_MM / lo) ** (i / float(last - 1)) for i in range(last)]
    rows = [(RADIUS_RGB[0], "at or under %s%s" % (_m(lo), "" if limit_mm else " (no limit known yet)"))]
    for i in range(1, last):
        rows.append((RADIUS_RGB[i], "%s to %s" % (_m(edges[i - 1]), _m(edges[i]))))
    rows.append((RADIUS_RGB[last], "flat (over 100 m)"))
    return rows


def limit_radius_mm(session):
    """The radius the thinnest layer may bend to, if the core has said: settings first, else the
    current proposal's own check. None when the core has not said."""
    s = getattr(session, "settings", None) or {}
    ratio, options = _num(s.get("lam_ratio")), s.get("lam_options_mm")
    if ratio and isinstance(options, list) and options:
        vals = [v for v in map(_num, options) if v]
        if vals:
            return ratio * min(vals)
    sent = ((session.result or {}).get("sent") or {}) if session else {}
    form = sent.get("form") if isinstance(sent.get("form"), dict) else {}
    limit = _num(_get(form, "checks", "bend", "limit"))
    t = _num(form.get("lamella_mm"))
    return limit * t if limit and t else None


OUTPUT_COLUMNS = ("Member", "Kind", "Length", "Layers", "Waste")


KIND_WORDS = (("plate", "drawn"), ("surface", "on surface"), ("part", "own solid"))


def member_kind(kind):
    """The Members grid's Kind in the card's glossary: drawn, on surface, own solid. Never 'plate'."""
    for old, new in KIND_WORDS:
        if kind == old or kind.startswith(old + ","):
            return new + kind[len(old):]
    return kind


def member_cells(member):
    """The Output table's cells for one accepted member."""
    n, t = member.get("n_lamellas"), member.get("lamella_mm")
    layers = ("%d of %s mm" % (int(n), ("%.1f" % t).rstrip("0").rstrip("."))) if n and t else ""
    w = member.get("waste_pct")
    return (member.get("id", ""), member_kind(member.get("kind", "")),
            _m(member["length_mm"]) if member.get("length_mm") else "", layers,
            _pct(w) if w is not None else "")
