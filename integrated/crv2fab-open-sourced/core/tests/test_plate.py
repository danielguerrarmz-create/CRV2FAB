"""Spec v9 slice 1: intent kind `plate`. Geometry first (no billet fits, quick), then the answer.

The geometry tests each pin a property a wrong method would break: frames that spin on a planar
path, a profile foreshortened by reading it on the wrong plane, a path not flipped or not pinned,
and a mesh that does not close (its volume would move with the origin)."""
import json
import math

import numpy as np
import pytest

from gnj_nudge import plate as pl
from gnj_nudge import vectors_plate as vp
from gnj_nudge.intent import Holds
from gnj_nudge.plate import PlateIntent, closed_volume, frames, path_stations, solve_plate
from gnj_nudge.vectors_part import v6_settings


def tilted_arc(radius=3000.0, angle_deg=40.0, tilt_deg=40.0, n=65):
    """A circular arc in the plane through X tilted tilt_deg about X: planar, but not in a world plane."""
    half = math.radians(angle_deg) / 2
    c, s = math.cos(math.radians(tilt_deg)), math.sin(math.radians(tilt_deg))
    up = np.array([0.0, -s, c])  # the arc rises along this, in its own plane
    out = []
    for th in np.linspace(-half, half, n):
        out.append(radius * math.sin(th) * np.array([1.0, 0, 0]) + (radius * math.cos(th) - radius) * -up)
    return np.array(out), np.cross([1.0, 0, 0], up)  # points, the plane's normal


# ---- frames --------------------------------------------------------------------------------------------

def test_frames_do_not_spin_on_a_path_bent_in_a_vertical_plane():
    P = path_stations(vp.arc_path(300.0))
    T, A, N = frames(P)
    assert np.allclose(A, [0.0, 1.0, 0.0], atol=1e-9)  # across stays +Y: no spin
    assert np.allclose(np.einsum("ij,ij->i", T, N), 0.0, atol=1e-12)


def test_frames_do_not_spin_on_a_planar_path_in_a_tilted_plane():
    """On any planar path a rotation-minimising frame keeps a constant angle to the plane's normal.
    Frames built from world Z made square to each tangent would turn here."""
    P, m = tilted_arc()
    T, A, N = frames(P)
    angle = np.degrees(np.arctan2(np.einsum("ij,j->i", N, m), np.einsum("ij,j->i", A, m)))
    assert np.ptp(angle) < 1e-6
    # and the frame is orthonormal at every station
    for V in (T, A, N):
        assert np.allclose(np.linalg.norm(V, axis=1), 1.0)
    assert np.allclose(np.einsum("ij,ij->i", A, N), 0.0, atol=1e-12)


def test_the_straight_member_frame_is_x_y_z():
    T, A, N = frames(path_stations(pl.STRAIGHT_PATH))
    assert np.allclose(T, [1, 0, 0]) and np.allclose(A, [0, 1, 0]) and np.allclose(N, [0, 0, 1])


# ---- the path ------------------------------------------------------------------------------------------

def test_a_path_drawn_backwards_is_flipped():
    forward = path_stations(vp.arc_path(150.0))
    backward = path_stations(vp.arc_path(150.0)[::-1])
    assert np.allclose(forward, backward, atol=1e-9)
    assert forward[0][0] < forward[-1][0]


def test_the_ends_are_pinned_to_the_current_member():
    drawn = [[60.0, 35.0, -20.0], [1200.0, 10.0, 200.0], [2330.0, -45.0, 15.0]]
    P = path_stations(drawn)
    assert P[0].tolist() == [0.0, 0.0, 0.0]
    assert P[-1].tolist() == [2400.0, 0.0, 0.0]
    gaps = np.linalg.norm(np.diff(P, axis=0), axis=1)
    # evenly spaced by arc length along the pinned polyline: only the station that cuts the drawn
    # corner has a shorter chord
    assert len(P) == 65 and np.ptp(gaps) < 5e-3 * gaps.mean()


# ---- profiles ------------------------------------------------------------------------------------------

def test_a_profile_drawn_obliquely_on_a_tilted_end_plane_keeps_its_true_width():
    """The arc's end planes lean back; a 300 mm line drawn in that plane at 37 degrees must read 300 mm
    wide and 37 degrees, not shortened by the lean."""
    path = vp.arc_path(300.0)
    P = path_stations(path)
    T, A, N = frames(P)
    a = math.radians(37.0)
    d = math.cos(a) * A[-1] + math.sin(a) * N[-1]
    end = [(P[-1] + w * d).tolist() for w in np.linspace(-150, 150, 9)]
    intent = PlateIntent.build("M1", path, None, end, profile_end_on="path")
    assert pl.developed_width(intent.plate.end) == pytest.approx(300.0, abs=1e-6)
    assert pl.chord_deg(intent.plate.end) == pytest.approx(37.0, abs=1e-6)
    assert intent.plate.twist_deg == pytest.approx(37.0, abs=1e-6)  # the start is the straight 89 mm line


def test_a_profile_off_its_plane_is_projected_onto_it():
    """Points lifted along the path's tangent read as if drawn on the plane."""
    flat = vp.line_profile(0.0, 300.0, 20.0, n=5)
    lifted = [[p[0] + 40.0 * k, p[1], p[2]] for k, p in enumerate(flat)]
    a = PlateIntent.build("M1", None, flat, None).plate.start
    b = PlateIntent.build("M1", None, lifted, None).plate.start
    assert np.allclose(a, b, atol=1e-9)


def test_profiles_are_centred_and_run_toward_plus_across():
    off = [[0.0, 500.0 + y, 300.0] for y in (150.0, 50.0, -150.0)]  # drawn far from the path, right to left
    L = PlateIntent.build("M1", None, off, None).plate.start
    assert np.allclose(L.mean(axis=0), 0.0, atol=1e-9)
    assert L[0, 0] < L[-1, 0]
    assert L.shape == (15, 2)


def test_thirty_degrees_of_twist_is_read_from_the_chords():
    req = vp.request("profiles_twist_30")["intent"]
    p = PlateIntent.build("M1", None, req["profile_start"], req["profile_end"]).plate
    assert p.twist_deg == pytest.approx(30.0, abs=0.1)
    mid = p.grid[32]  # half way along, the blend is level
    assert abs(mid[-1][2] - mid[0][2]) < 1e-6


# ---- the solid -----------------------------------------------------------------------------------------

def test_the_straight_member_is_38_by_89_by_2400():
    p = PlateIntent.build("M1").plate
    assert p.volume_mm3 == pytest.approx(38 * 89 * 2400, rel=1e-3)
    assert p.grid.shape == (65, 15, 3) and p.top.shape == (65, 15, 3)
    assert np.allclose(p.top[..., 2], 19.0) and np.allclose(p.bottom[..., 2], -19.0)
    assert p.grid[0, 0].tolist() == [0.0, -44.5, 0.0] and p.grid[-1, -1].tolist() == [2400.0, 44.5, 0.0]


def test_the_volume_does_not_move_with_the_origin():
    """A mesh with a missing or wrongly turned side gives a volume that depends on where the origin is."""
    req = vp.request("profiles_u_across")["intent"]
    p = PlateIntent.build("M1", vp.arc_path(150.0), req["profile_start"], req["profile_end"]).plate
    shift = np.array([3000.0, -700.0, 1200.0])
    assert closed_volume(p.top + shift, p.bottom + shift) == pytest.approx(p.volume_mm3, rel=1e-9)
    # a 300 mm U, 38 thick, along a 2.42 m path: close to developed width x thickness x length
    assert p.volume_mm3 == pytest.approx(pl.developed_width(p.start) * 38 * p.length_mm, rel=0.02)


def test_the_thickness_is_a_parameter():
    assert PlateIntent.build("M1", thickness_mm=19).plate.volume_mm3 == pytest.approx(19 * 89 * 2400, rel=1e-9)


# ---- validation ----------------------------------------------------------------------------------------

def _intent(**kw):
    return {"kind": "plate", "member_id": "M1", "path": None, "profile_start": None, "profile_end": None,
            "thickness_mm": 38} | kw


@pytest.mark.parametrize("bad, words", [
    ({"member_id": "M 1"}, "member_id"),
    ({"path": [[0, 0, 0]]}, "path must be null or hold 2 to 400"),
    ({"path": [[0, 0, k] for k in range(401)]}, "path must be null or hold 2 to 400"),
    ({"path": "line"}, "path must be null or hold"),
    ({"path": [[0, 0, 0], [1, 2]]}, "each point of path"),
    ({"path": [[0, 0, 0], [1, 2, float("inf")]]}, "each point of path"),
    ({"path": [[0, 0, 0], [1, 2, True]]}, "each point of path"),
    ({"path": [[0, 0, 0], [2_000_000, 0, 0]]}, "within 1e+06 mm"),
    ({"profile_start": [[0, 0, 0]] * 101}, "profile_start must be null or hold 2 to 100"),
    ({"profile_end": [[0, 0, 0], ["a", 0, 0]]}, "each point of profile_end"),
    ({"thickness_mm": 0}, "thickness_mm"),
    ({"thickness_mm": 600}, "thickness_mm"),
    ({"thickness_mm": "38"}, "thickness_mm"),
    ({"path": [[5, 5, 5], [5, 5, 5]]}, "path has no length"),
    ({"profile_start": [[0, 0, 0], [500, 0, 0]]}, "profile_start has no width across the path"),
])
def test_bad_plates_are_refused_with_a_reason(bad, words):
    with pytest.raises(ValueError, match=words.replace("+", r"\+")):
        PlateIntent.from_dict(_intent(**bad))


def test_every_stroke_may_be_null_and_thickness_may_be_absent():
    d = _intent()
    d.pop("thickness_mm")
    i = PlateIntent.from_dict(d)
    assert i.thickness_mm == 38.0 and i.drawn() == []
    assert i.summary()["volume_mm3"] == pytest.approx(38 * 89 * 2400, rel=1e-6)


# ---- the answer (billet fits: slow) --------------------------------------------------------------------

@pytest.mark.slow
def test_the_form_carries_the_plate_and_the_checks():
    req = vp.request("path_arc_up")["intent"]
    r = solve_plate(PlateIntent.build("M1", req["path"]), Holds(), v6_settings())
    d = r.as_dict()
    f = d["form"]
    assert d["status"] == "proposed" and d["deviation_mm"] == 0.0 and f["kind"] == "plate_member"
    assert len(f["stations"]) == 65 and len(f["grid"]) == 65 and all(len(row) == 15 for row in f["grid"])
    assert f["intent_grid"] == f["grid"] and len(f["normals"]) == 65
    assert f["eased"] == {"path": 1.0, "drift": 1.0, "twist": 1.0, "profiles": 1.0} and f["twist_deg"] == 0.0
    assert f["thickness_mm"] == 38.0 and f["checks"]["bend"]["ok"] and f["checks"]["machine"]["ok"]
    assert {"waste_pct", "waste_rounding_pct", "kx"} <= set(f["checks"]) and "outline" in f["billet"]
    assert d["sentence"].startswith("Your shape holds. Pressed in one curve from ")
    json.dumps(d, allow_nan=False)
    s = r.form.summary()
    assert not {"stations", "grid", "normals", "intent_grid"} & set(s) and "outline" not in s["billet"]


@pytest.mark.slow
def test_a_failed_plate_is_a_conflict_not_an_eased_shape():
    req = vp.request("path_too_tight")["intent"]
    r = solve_plate(PlateIntent.build("M1", req["path"]), Holds(["shape"]), v6_settings())
    assert r.status == "conflict" and r.form is None
    assert r.sentence == "This bends too tightly for the thinnest layer."
    assert r.steps[-1]["text"].startswith("You are holding the shape, so this is a finding")


@pytest.mark.slow
def test_vectors_file_matches_the_code():
    """tests/vectors_plate.json is what the Rhino client checks against. Regenerate with
    python -m gnj_nudge.vectors_plate after any intended change."""
    on_disk = json.loads(vp.PATH.read_text(encoding="utf-8"))
    assert on_disk == json.loads(vp.dumps(vp.build()))
    names = {c["name"] for c in on_disk["cases"]}
    assert {"no_strokes", "path_arc_up", "profiles_twist_30", "profiles_u_across", "path_arc_up_hold_solid",
            "too_wide_for_opening"} <= names


# ---- grain follows the path (Daniel, 2026-11-14) ---------------------------------------------------

@pytest.mark.slow
def test_no_plate_answer_runs_across_the_grain():
    """Every billet the rules offer runs within the grain card of its piece's path. Before the grain
    check the 1400 mm plate was answered in 3 pieces whose billets ran straight across the plate."""
    for name, *_ in vp.CASES:
        it = vp.request(name)["intent"]
        intent = PlateIntent.build("M1", it["path"], it["profile_start"], it["profile_end"], it["thickness_mm"])
        r = solve_plate(intent, Holds(vp.request(name)["holds"]), v6_settings())
        if r.form is None:
            continue
        g = r.form.summary()["checks"]["grain"]
        assert g["ok"] and g["angle_deg"] <= pl.GRAIN_CARD["value"], name


@pytest.mark.slow
def test_the_plate_wider_than_the_opening_is_refused_on_grain_in_pieces():
    """Slice 3 rule: the sentence names the drawn plate's one-billet failure (the opening); the pieces'
    only way through, across the grain, is refused and said in the Why steps."""
    it = vp.request("too_wide_for_opening")["intent"]
    r = solve_plate(PlateIntent.build("M1", None, it["profile_start"], it["profile_end"]), Holds(), v6_settings())
    assert r.status == "conflict" and r.form is None
    assert r.sentence == "This billet will not fit through the machine."
    assert r.conflict == ("your shape", "machine opening 1200 x 280 mm")
    assert any(s["limit_id"] == "grain_deg" and "90 degrees off the path" in s["text"] for s in r.steps)


@pytest.mark.slow
def test_an_off_grain_fit_is_refitted_with_its_plane_holding_the_path():
    """The free fit of a 800 mm long piece of the 1400 mm plate runs across it; the constrained fits
    (fabrication.fit_arc_billet_in_plane) run along it."""
    from gnj_nudge import pieces as pc
    from gnj_nudge.fabrication import gm, grain_angle_deg
    it = vp.request("too_wide_for_opening")["intent"]
    m = pl.PlateMember(PlateIntent.build("M1", None, it["profile_start"], it["profile_end"]))
    axis, normals = m.grain(3, 0)
    fits = pc._fit_here(m.points(3, 0), False, 20, 0.0, (tuple(axis), tuple(map(tuple, normals)), 10.0))
    angles = [grain_angle_deg(f, gm.billet_extents(f.spine, f.P2, f.W, 0.0, 1.0), axis) for f in fits]
    assert angles[0] > 80 and len(fits) > 1 and all(a <= 10 for a in angles[1:])


# ---- stock: one 2x4 as it comes (Daniel, 2026-11-14) -----------------------------------------------

def test_no_strokes_is_one_stock_2x4_with_no_waste():
    """Before this rule the straight member was fitted on edge, 3 layers of 38 mm, 22% waste."""
    r = solve_plate(PlateIntent.build("M1"), Holds(), v6_settings())
    assert r.status == "proposed" and r.sentence == "Your shape holds. One stock 2x4, no pressing."
    f = r.form.summary()
    assert (f["n_lamellas"], f["lamella_mm"], f["straight_billet"], f["stock"]) == (1, 38.0, False, True)
    assert f["checks"]["waste_pct"] == 0.0 and f["billet"]["mode"] == "stock"
    assert [f["billet"][k] for k in ("length_mm", "width_mm", "depth_mm")] == [2400.0, 89.0, 38.0]
    assert r.plan is None  # no billet fit was run


@pytest.mark.parametrize("strokes, stock", [
    ({}, True),
    ({"path": vp.arc_path(0.4)}, True),  # 0.4 mm of sag: inside the 1 mm tolerance
    ({"path": vp.arc_path(2.0)}, False),  # 2 mm: a bend
    ({"profile_end": vp.line_profile(2400.0, 89.0, 1.0)}, False),  # 1 degree of twist: 39.6 mm deep
    ({"profile_start": vp.line_profile(0.0, 90.5), "profile_end": vp.line_profile(2400.0, 90.5)}, False),
    ({"profile_start": vp.u_profile(0.0, 89.0, 3.0), "profile_end": vp.u_profile(2400.0, 89.0, 3.0)}, False),
    ({"path": [[0, 0, 0], [2400, 0, 0]], "profile_start": vp.line_profile(0.0, 89.0, 90.0),
      "profile_end": vp.line_profile(2400.0, 89.0, 90.0)}, True),  # the board on edge is still a board
])
def test_stock_is_a_plate_inside_one_38_by_89_board_within_1_mm(strokes, stock):
    p = PlateIntent.build("M1", strokes.get("path"), strokes.get("profile_start"), strokes.get("profile_end")).plate
    assert (pl.stock_fit(p) is not None) is stock


def test_a_thinner_plate_inside_the_board_is_stock_with_its_waste_reported():
    st = pl.stock_fit(PlateIntent.build("M1", thickness_mm=19).plate)
    assert st is not None and st["waste_pct"] == pytest.approx(50.0)


def test_a_stock_answer_is_recorded_with_its_board():
    from gnj_nudge.limits import load_cards
    from gnj_nudge.record import make_entry
    intent = PlateIntent.build("M1")
    e = make_entry("accepted", intent, Holds(), solve_plate(intent, Holds(), v6_settings()), load_cards())
    assert e["kind"] == "plate" and e["formal"].startswith("Member M1, softwood, one stock 2x4 (38 x 89 mm)")
    assert (e["billet_m3"], e["part_m3"], e["waste_pct"]) == (0.008117, 0.008117, 0.0)
    assert e["joints"] == [] and e["first_offer_trade"] == "none"


# ---- a profile follows its end when the path is redrawn (spec v9 Contract) --------------------------

def test_a_redrawn_path_does_not_shorten_a_profile_drawn_on_the_member():
    """Drawn on the straight member's end plane (x = 2400), 300 mm at 37 degrees, then the path is
    redrawn as an arc whose end plane leans 28 degrees back. Read on the member's plane it keeps its
    300 mm and 37 degrees; read on the new path's plane (the slice 1 rule) it came out shorter."""
    end = vp.line_profile(2400.0, 300.0, 37.0, n=9)
    kept = PlateIntent.build("M1", vp.arc_path(300.0), None, end, profile_end_on="member").plate
    assert pl.developed_width(kept.end) == pytest.approx(300.0, abs=1e-6)
    assert pl.chord_deg(kept.end) == pytest.approx(37.0, abs=1e-6)
    # placed at the new end in the plate's own frame: its width lies across the new end plane
    tip = kept.grid[-1]
    assert np.linalg.norm(tip[-1] - tip[0]) == pytest.approx(300.0, abs=1e-6)
    assert abs((tip[-1] - tip[0]) @ kept.T[-1]) < 1e-6
    read_on_path = PlateIntent.build("M1", vp.arc_path(300.0), None, end, profile_end_on="path").plate
    assert pl.developed_width(read_on_path.end) < 290.0


def test_member_is_the_default_plane_and_anything_else_is_refused():
    assert PlateIntent.from_dict(_intent()).profile_end_on == "member"
    with pytest.raises(ValueError, match="profile_start_on must be 'member' or 'path'"):
        PlateIntent.from_dict(_intent(profile_start_on="view"))


# ---- easing (slice 2): each scale moves only what it names ------------------------------------------

ONE = dict.fromkeys(pl.SCALES, 1.0)


def _drawn(name):
    it = vp.request(name)["intent"]
    return PlateIntent.build("M1", it["path"], it["profile_start"], it["profile_end"]).plate


def test_all_scales_at_one_is_the_drawn_plate():
    p = _drawn("deep_u_twisted")
    assert pl.deviation(p, pl.shape_at(p, ONE)) == 0.0


def test_the_twist_scale_scales_the_twist_and_nothing_else():
    p = _drawn("twist_too_large")
    half = pl.shape_at(p, ONE | {"twist": 0.5})
    assert half.twist_deg == pytest.approx(0.5 * p.twist_deg, abs=1e-9)
    assert np.allclose(half.stations, p.stations)
    assert pl.developed_width(half.start) == pytest.approx(pl.developed_width(p.start))


def test_flattening_a_profile_keeps_its_span_and_ends():
    p = _drawn("deep_u_twisted")
    flat = pl.shape_at(p, ONE | {"profiles": 0.0})
    for drawn, eased in ((p.start, flat.start), (p.end, flat.end)):
        assert np.linalg.norm(eased[-1] - eased[0]) == pytest.approx(np.linalg.norm(drawn[-1] - drawn[0]))
        assert pl.developed_width(eased) == pytest.approx(np.linalg.norm(drawn[-1] - drawn[0]))  # now straight
    assert flat.twist_deg == pytest.approx(p.twist_deg)


def test_the_path_scale_straightens_toward_the_chord_with_the_ends_pinned():
    p = _drawn("path_too_tight")
    straight = pl.shape_at(p, ONE | {"path": 0.0})
    assert np.allclose(straight.stations[:, 1:], 0.0) and straight.length_mm == pytest.approx(2400.0)
    half = pl.shape_at(p, ONE | {"path": 0.5})
    assert half.stations[0].tolist() == [0.0, 0.0, 0.0] and half.stations[-1].tolist() == [2400.0, 0.0, 0.0]
    assert half.stations[:, 2].max() == pytest.approx(0.5 * p.stations[:, 2].max(), rel=0.02)


def test_drift_is_only_what_leaves_the_best_plane():
    p = _drawn("path_too_tight")  # an arc in XZ: planar, no drift
    assert pl.deviation(p, pl.shape_at(p, ONE | {"drift": 0.0})) < 1e-3  # resampling noise only
    wavy = [[x, 120.0 * math.sin(2 * math.pi * x / 2400.0), 300.0 * math.sin(math.pi * x / 2400.0)]
            for x in np.linspace(0.0, 2400.0, 49)]
    q = PlateIntent.build("M1", wavy).plate
    e = pl.drift_axis(q.stations)
    assert abs(e @ [0.0, 1.0, 0.0]) > 0.99  # the S in Y leaves the vertical plane of the arch
    flat = pl.shape_at(q, ONE | {"drift": 0.0})
    assert np.abs(flat.stations[:, 1]).max() < 1.0 and flat.stations[:, 2].max() > 250.0


def test_deviation_counts_the_whole_grid_not_only_the_centreline():
    p = _drawn("twist_too_large")
    eased = pl.shape_at(p, ONE | {"twist": 0.0})
    assert np.allclose(eased.stations, p.stations)  # the centreline never moved
    assert pl.deviation(p, eased) == pytest.approx(500.0 * math.sqrt(2 - 2 * math.cos(math.radians(45))), rel=1e-3)


@pytest.mark.slow
def test_hold_shape_never_eases_a_plate():
    it = vp.request("twist_too_large")["intent"]
    intent = PlateIntent.build("M1", None, it["profile_start"], it["profile_end"])
    r = solve_plate(intent, Holds(["shape"]), v6_settings())
    assert r.status == "conflict" and r.steps[-1]["text"].startswith("You are holding the shape")
    free = solve_plate(intent, Holds(), v6_settings())
    assert free.status == "proposed" and free.sentence.startswith("Twist eased so the billet fits the machine")
    assert free.deviation_mm > 0
    assert free.form.scales["twist"] < 1.0 and free.form.scales["profiles"] == 1.0


@pytest.mark.slow
def test_machine_easing_takes_the_twist_before_the_profiles():
    """The deep U passes with its profiles flattened alone too; the order says the twist goes first, so
    the answer has no twist left and the profiles only as flat as still needed."""
    r = solve_plate(PlateIntent.build("M1", None, *[vp.request("deep_u_twisted")["intent"][k]
                                                    for k in ("profile_start", "profile_end")]), Holds(), v6_settings())
    sc = r.form.scales
    assert sc["twist"] == 0.0 and 0.0 < sc["profiles"] < 1.0 and sc["path"] == sc["drift"] == 1.0
    assert r.sentence.startswith("Twist and profiles eased so the billet fits the machine, moving the plate at most ")
    eased = [s["text"].split(",")[0] for s in r.steps if s["text"].startswith(("Twist ", "Profiles "))]
    assert eased == ["Twist removed", "Profiles flattened toward their chords"]
