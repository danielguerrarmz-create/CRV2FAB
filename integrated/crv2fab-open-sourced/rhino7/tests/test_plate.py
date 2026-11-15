# -*- coding: utf-8 -*-
"""Spec v9 (three strokes build a plate), client side: pure, no Rhino. Bodies are the core's own
answers (tests/fixtures/plate_bodies.json, from core main c64ed6d).

The round trip at the end is CPython only: it runs that core in this process (an export of main at
c64ed6d, GNJ_CORE_MAIN_DIR) and checks that an accepted plate, sent again with no new strokes, comes
back as the same plate: this client carries the current member, since the core's slice 1 always
starts from the straight one."""
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gnj_core as core  # noqa: E402

CORE_DIR = os.environ.get("GNJ_CORE_MAIN_DIR", r"C:\Users\danie\scratch\2026-11-15\gnj-core-main-c64ed6d")


def bodies():
    with open(os.path.join(HERE, "fixtures", "plate_bodies.json")) as fh:
        return json.load(fh)["bodies"]


BODIES = bodies()


class Canned(core.CoreClient):
    """Answers /nudge with the next body; /judge, /tally and /undo as given."""

    def __init__(self, nudges, undo=None):
        core.CoreClient.__init__(self, "http://canned")
        self.nudges, self.undo_replies, self.posts = list(nudges), list(undo or []), []

    def _post(self, path, body, timeout):
        self.posts.append((path, body))
        if path == "/nudge":
            return self.nudges.pop(0)
        if path == "/judge":
            return {"formal": "Member M1, a plate."}
        if path == "/undo":
            r = self.undo_replies.pop(0)
            if r == 409:
                raise IOError("core answered 409: nothing to undo since the last tally reset in this session")
            return r
        raise IOError("core answered 404: not found")

    def tally(self):
        return (1, 30.9)


def arc(n=9, rise=200.0):
    return [[2400.0 * i / (n - 1), 0.0, rise * (1 - (2.0 * i / (n - 1) - 1) ** 2)] for i in range(n)]


class Intent(unittest.TestCase):
    def test_nothing_drawn_on_the_straight_member_sends_nulls(self):
        i = core.plate_intent({}, core.straight_member())
        self.assertEqual((i["kind"], i["path"], i["profile_start"], i["profile_end"]), ("plate", None, None, None))
        self.assertEqual((i["profile_start_on"], i["profile_end_on"]), ("member", "member"))
        self.assertNotIn("thickness_mm", i)   # the session setting is the one in force

    def test_a_profile_is_sent_as_its_shape_on_the_member_end_plane(self):
        current = dict(core.straight_member(), end_frames={
            "start": {"origin": [0.0, 0.0, 0.0], "tangent": [0.6, 0.0, 0.8], "across": [0.0, 1.0, 0.0],
                      "normal": [-0.8, 0.0, 0.6]},
            "end": core.straight_frames()["end"]})
        # drawn on the leaning start plane: 300 mm along `across`, 100 mm up its `normal`
        drawn = [[0.0, -150.0, 0.0], [-80.0, 150.0, 60.0]]
        i = core.plate_intent({"start": drawn}, current)
        self.assertEqual(i["profile_start"], [[0.0, -150.0, 0.0], [0.0, 150.0, 100.0]])
        self.assertIsNone(i["profile_end"])

    def test_long_strokes_are_thinned_to_the_contract(self):
        i = core.plate_intent({"path": arc(1000), "end": [[2400.0, y, 0.0] for y in range(500)]},
                              core.straight_member())
        self.assertEqual((len(i["path"]), len(i["profile_end"])), (core.MAX_PATH_POINTS, core.MAX_PROFILE_POINTS))
        self.assertEqual((i["path"][0], i["path"][-1]), ([0.0, 0.0, 0.0], [2400.0, 0.0, 0.0]))


class PathPlane(unittest.TestCase):
    """Daniel, 2026-11-15: a Path lands upright or flat, whichever the view faces more; a tie, upright."""

    def test_front_and_most_perspectives_land_upright(self):
        self.assertEqual(core.path_plane((0.0, 1.0, 0.0), (1.0, 0.0, 0.0)), "upright")        # Front
        self.assertEqual(core.path_plane((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), "upright")        # Right, member along Y
        self.assertEqual(core.path_plane((1800.0, 4200.0, -2000.0), (2400.0, 0.0, 0.0)), "upright")

    def test_top_lands_flat(self):
        self.assertEqual(core.path_plane((0.0, 0.0, -1.0), (1.0, 0.0, 0.0)), "flat")
        self.assertEqual(core.path_plane((0.3, 0.4, -2.0), (1.0, 0.0, 0.0)), "flat")

    def test_a_tie_goes_upright(self):
        self.assertEqual(core.path_plane((0.0, 1.0, -1.0), (1.0, 0.0, 0.0)), "upright")
        self.assertEqual(core.path_plane((0.0, -3.0, 3.0), (5.0, 0.0, 0.0)), "upright")

    def test_the_status_says_which(self):
        s = core.Session(core.OfflineClient())
        s.begin_drawing("path")
        s.end_drawing("path", arc(), "flat")
        self.assertEqual(s.stroke_status("path"), "drawn in plan")
        self.assertEqual(s.drawing_summary(), "Path drawn in plan, Start not drawn, End not drawn")
        s.done()
        self.assertEqual([s.stroke_status(w) for w in core.STROKES], ["drawn in plan", "kept as is", "kept as is"])
        self.assertEqual(s.drawing_summary(), "Path drawn in plan, Start kept as is, End kept as is")


L = core.LENGTH_MM


def plan_y(x):
    return 150.0 * math.sin(2 * math.pi * x / L)     # a 150 mm S


def elevation_z(x):
    return 300.0 * math.sin(math.pi * x / L)         # a 300 mm arch


def plan_stroke(n=121, y=plan_y, height=0.0):
    """As read on the flat plane: across from y(x), the plane's own height."""
    return [[L * i / (n - 1.0), y(L * i / (n - 1.0)), height] for i in range(n)]


def elevation_stroke(n=121, z=elevation_z, across=0.0):
    return [[L * i / (n - 1.0), across, z(L * i / (n - 1.0))] for i in range(n)]


def draw(s, points, plane):
    s.begin_drawing("path")
    return s.end_drawing("path", points, plane)


class TwoViewPath(unittest.TestCase):
    """Daniel, 2026-11-15: a Path drawn once in plan and once in elevation is one 3D path: across from
    the plan stroke, height from the elevation stroke, on shared stations along the member."""

    def test_plan_and_elevation_make_one_path_with_both_curves(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(n=97, height=12.0), "flat")    # the flat plane's height is not the path's
        draw(s, elevation_stroke(n=150, across=-7.0)[::-1], "upright")   # drawn right to left
        path = s.strokes["path"]
        self.assertEqual((path[0][0], path[-1][0]), (0.0, L))
        self.assertGreater(len(path), 60)
        for x, y, z in path:
            self.assertAlmostEqual(y, plan_y(x), delta=0.5)
            self.assertAlmostEqual(z, elevation_z(x), delta=0.5)
        self.assertGreater(max(abs(p[1]) for p in path), 149.0)   # both curves are there in full
        self.assertGreater(max(p[2] for p in path), 299.0)
        self.assertEqual(s.stroke_status("path"), "drawn in plan and elevation")
        self.assertEqual(s.drawing_summary(), "Path drawn in plan and elevation, Start not drawn, End not drawn")

    def test_one_view_is_sent_exactly_as_today(self):
        for plane, stroke, word in (("flat", plan_stroke(), "plan"), ("upright", elevation_stroke(), "elevation")):
            s = core.Session(core.OfflineClient())
            draw(s, stroke, plane)
            self.assertEqual(s.strokes["path"], stroke)
            self.assertEqual(s.stroke_status("path"), "drawn in " + word)
            s.done()
            self.assertEqual(s.plate["path"], [[round(c, 2) for c in p] for p in stroke])

    def test_redrawing_one_view_replaces_only_that_view(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(), "flat")
        draw(s, elevation_stroke(), "upright")
        draw(s, plan_stroke(y=lambda x: -0.1 * x * (L - x) / L), "flat")   # a new plan: one bow, not an S
        path = s.strokes["path"]
        for x, y, z in path:
            self.assertAlmostEqual(y, -0.1 * x * (L - x) / L, delta=0.5)
            self.assertAlmostEqual(z, elevation_z(x), delta=0.5)
        draw(s, elevation_stroke(z=lambda x: 0.0), "upright")   # a new elevation: flat again
        self.assertLess(max(abs(p[2]) for p in s.strokes["path"]), 1e-6)
        self.assertGreater(max(abs(p[1]) for p in s.strokes["path"]), 59.0)

    def test_after_done_the_words_stay_and_the_next_path_starts_fresh(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(), "flat")
        draw(s, elevation_stroke(), "upright")
        s.done()
        self.assertGreater(max(p[2] for p in s.plate["path"]), 299.0)
        self.assertGreater(max(abs(p[1]) for p in s.plate["path"]), 149.0)
        self.assertEqual([s.stroke_status(w) for w in core.STROKES],
                         ["drawn in plan and elevation", "kept as is", "kept as is"])
        self.assertEqual(s.drawing_summary(), "Path drawn in plan and elevation, Start kept as is, End kept as is")
        draw(s, elevation_stroke(), "upright")   # a new Path after Done: the old plan is not in it
        self.assertEqual(s.strokes["path"], elevation_stroke())
        self.assertEqual(s.stroke_status("path"), "drawn in elevation")

    def test_cancel_drops_both_views(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(), "flat")
        s.cancel_strokes()
        draw(s, elevation_stroke(), "upright")
        self.assertEqual(s.strokes["path"], elevation_stroke())

    def test_a_curve_read_in_3d_is_the_whole_path(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(), "flat")
        modelled = [[x, y, z + 50.0] for x, y, z in plan_stroke()]
        draw(s, modelled, None)
        self.assertEqual((s.strokes["path"], s.stroke_status("path")), (modelled, "drawn"))
        draw(s, elevation_stroke(), "upright")   # the modelled curve is no plan view
        self.assertEqual(s.strokes["path"], elevation_stroke())


class Response(unittest.TestCase):
    def test_an_eased_plate_is_read_with_its_grid_frames_and_scales(self):
        r = core.nudge_response(BODIES["path_too_tight"], {"kind": "plate"})
        f = r["form"]
        self.assertEqual((len(f["grid"]), len(f["grid"][0]), len(f["normals"])), (65, 15, 65))
        self.assertEqual(f["eased"]["path"], 0.6814)
        self.assertEqual(f["end_frames"]["start"]["across"], [0.0, 1.0, 0.0])
        self.assertEqual((r["deviation_mm"], r["waste_pct"], f["thickness_mm"]), (330.8, 30.9, 38.0))

    def test_a_conflict_has_no_form(self):
        r = core.nudge_response(BODIES["twist_too_large_hold_shape"], {"kind": "plate"})
        self.assertEqual((r["status"], r["form"], r["sentence"]),
                         ("conflict", None, "This billet will not fit through the machine."))

    def test_a_bad_grid_is_refused(self):
        for broken in ("grid", "normals", "end_frames"):
            body = json.loads(json.dumps(BODIES["no_strokes"]))
            if broken == "grid":
                body["form"]["grid"][3] = body["form"]["grid"][3][:-1]
            elif broken == "normals":
                body["form"]["normals"] = body["form"]["normals"][:10]
            else:
                body["form"]["end_frames"]["end"].pop("across")
            self.assertRaises(ValueError, core.nudge_response, body, {"kind": "plate"})


class Strokes(unittest.TestCase):
    def test_statuses_done_and_kept_as_is(self):
        s = core.Session(Canned([BODIES["path_too_tight"]]))
        self.assertEqual([s.stroke_status(w) for w in core.STROKES], ["not drawn"] * 3)
        self.assertFalse(s.can_done())
        self.assertTrue(s.begin_drawing("path"))
        self.assertEqual((s.headline(), s.subline()), ("Drawing the path.", core.DRAWING_SUB))
        s.end_drawing("path", arc())
        self.assertEqual([s.stroke_status(w) for w in core.STROKES], ["drawn", "not drawn", "not drawn"])
        self.assertTrue(s.can_done() and s.done())
        self.assertEqual([s.stroke_status(w) for w in core.STROKES], ["drawn", "kept as is", "kept as is"])
        self.assertEqual(core.strokes_summary(s.sent_strokes), "Path drawn, Start kept as is, End kept as is")
        self.assertTrue(s.run_sync())
        self.assertEqual(s.phase, "proposed")
        # the sentence says "moving the plate at most 331 mm.": the number is shown once, there
        self.assertEqual((s.headline(), s.subline()), ("Buildable, eased.", "Path straightened so the layers can bend."))
        self.assertNotIn("331", s.subline())   # the one number is Moved, in Facts, never in Reason
        self.assertTrue(s.waste_line().startswith("Waste 31%  Moved 331 mm  Needs "))

    def test_no_largest_move_at_zero(self):
        s = core.Session(Canned([BODIES["twist_50_splits"]]))
        s.begin_drawing("end")
        s.end_drawing("end", [[2400.0, -300.0, 0.0], [2400.0, 300.0, 100.0]])
        s.done()
        s.run_sync()
        self.assertEqual(s.waste_line(), "Waste 81%  Needs 2 pieces")   # Moved hidden at 0

    def test_esc_draws_nothing_and_cancel_drops_unsent_strokes(self):
        s = core.Session(core.OfflineClient())
        s.begin_drawing("start")
        self.assertFalse(s.end_drawing("start", None))
        self.assertEqual((s.note, s.drawing, s.strokes), (core.NO_STROKE, None, {}))
        s.begin_drawing("path")
        s.end_drawing("path", arc())
        s.cancel_strokes()
        self.assertEqual((s.strokes, s.can_done(), s.phase), ({}, False, "idle"))

    def test_after_reject_nothing_is_sent_until_a_stroke_is_redrawn(self):
        s = core.Session(Canned([BODIES["path_too_tight"]]))
        s.begin_drawing("path")
        s.end_drawing("path", arc())
        s.done()
        s.run_sync()
        s.reject()
        self.assertEqual((s.phase, s.headline(), s.can_done()), ("rejected", "Rejected.", False))
        self.assertEqual(len([p for p in s.client.posts if p[0] == "/nudge"]), 1)


class AcceptAndUndo(unittest.TestCase):
    def accepted(self, undo=()):
        s = core.Session(Canned([BODIES["path_too_tight"]], undo))
        s.begin_drawing("path")
        s.end_drawing("path", arc())
        s.done()
        s.run_sync()
        r = s.accept()
        s.add_member(r, ["a", "b"])
        return s

    def test_an_accepted_plate_becomes_the_current_member(self):
        s = self.accepted()
        form = s.result["form"]
        self.assertTrue(s.current["accepted"])
        self.assertEqual(s.current["stations"], [list(p) for p in form["stations"]])
        self.assertEqual(s.current["end_frames"], form["end_frames"])
        self.assertEqual(len(s.current["start"]), 15)
        self.assertAlmostEqual(s.current["start"][-1][0] - s.current["start"][0][0], 89.0, places=1)
        self.assertEqual([m["kind"] for m in s.members], ["plate"])
        # the accepted plate is the new member: the card's stroke lines start again; Inputs keeps what was sent
        self.assertEqual([s.stroke_status(w) for w in core.STROKES], ["not drawn"] * 3)
        self.assertEqual(core.strokes_summary(s.sent_strokes), "Path drawn, Start kept as is, End kept as is")
        # the next request carries the accepted plate for every stroke left out
        nxt = core.plate_intent({}, s.current)
        self.assertEqual(len(nxt["path"]), 65)
        self.assertEqual(nxt["profile_start"][0][0], 0.0)
        self.assertEqual(nxt["profile_end"][0][0], core.LENGTH_MM)

    def test_undo_restores_the_member_before_and_takes_the_tally(self):
        s = self.accepted([{"undone": {"member_id": "M1", "timestamp": "t", "kind": "plate"},
                            "tally": {"members": 0, "billet_m3": 0, "part_m3": 0, "waste_pct": None}}, 409])
        row = s.undo_last()
        self.assertEqual(row["object_ids"], ["a", "b"])
        self.assertEqual((s.members, s.current["accepted"], s.tally, s.phase), ([], False, None, "idle"))
        self.assertEqual(s.record[0], {"v": "undone", "text": "Undid the last accept."})
        self.assertEqual(s.client.posts[-1], ("/undo", {}))
        self.assertIsNone(s.undo_last())   # 409
        self.assertEqual(s.note, "Nothing to undo.")
        self.assertEqual(s.record[0]["text"], "Undid the last accept.")   # nothing else changed

    def test_repeated_undo_walks_back_one_accept_at_a_time(self):
        s = self.accepted([{"undone": {}, "tally": {"members": 1, "waste_pct": 30.9}},
                           {"undone": {}, "tally": {"members": 0}}])
        first = s.current
        s.client.nudges.append(BODIES["twist_50_splits"])
        s.begin_drawing("end")
        s.end_drawing("end", [[2400.0, -300.0, 0.0], [2400.0, 300.0, 100.0]])
        s.done()
        s.run_sync()
        s.add_member(s.accept(), ["c"])
        self.assertEqual(s.undo_last()["object_ids"], ["c"])
        self.assertIs(s.current, first)
        self.assertEqual(s.tally, (1, 30.9))
        self.assertEqual(s.undo_last()["object_ids"], ["a", "b"])
        self.assertFalse(s.current["accepted"])


def with_outlines(body):
    """A fixture body with the two billet outlines per piece that core main b514e62 sends (the fixture
    predates them): each a closed loop, in the plate's frame, core mm."""
    out = json.loads(json.dumps(body))
    f = out["form"]
    pieces = f.get("pieces") or []
    for i, b in enumerate([p["billet"] for p in pieces] or [f["billet"]]):
        x0 = 1200.0 * i
        loop = [[x0, -300.0, 0.0], [x0 + 1200.0, -300.0, 0.0], [x0 + 1200.0, -300.0, 190.0], [x0, -300.0, 190.0],
                [x0, -300.0, 0.0]]
        b["outline"] = [loop, [[p[0], 300.0, p[2]] for p in loop]]
    return out


class Billets(unittest.TestCase):
    """Daniel, 2026-11-15: each piece's billet as a box, like the pink boxes in his reference image.
    Sizes are the core's, never computed here."""

    def test_one_box_per_piece_labelled_with_the_core_sizes(self):
        form = with_outlines(BODIES["twist_50_splits"])["form"]
        boxes = core.billet_boxes(form)
        self.assertEqual([b["id"] for b in boxes], ["B1", "B2"])
        self.assertEqual(boxes[0]["label"], "B1 1204 x 595 x 190 mm")   # 1203.8 x 594.8 x 190.0 as sent
        self.assertEqual(boxes[1]["outline"], form["pieces"][1]["billet"]["outline"])

    def test_one_billet_without_pieces(self):
        form = with_outlines(BODIES["path_too_tight"])["form"]
        b = form["billet"]
        boxes = core.billet_boxes(form)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["label"], "B1 %d x %d x %d mm" % tuple(
            core.jround(b[k]) for k in ("length_mm", "width_mm", "depth_mm")))

    def test_no_outline_no_box(self):
        self.assertEqual(core.billet_boxes(BODIES["twist_50_splits"]["form"]), [])   # sizes but no outline
        self.assertEqual(core.billet_boxes({}), [])
        self.assertEqual(core.billet_boxes(None), [])
        form = with_outlines(BODIES["twist_50_splits"])["form"]
        form["pieces"][0]["billet"]["outline"] = [form["pieces"][0]["billet"]["outline"][0]]   # one loop only
        self.assertEqual([b["id"] for b in core.billet_boxes(form)], ["B2"])

    def test_a_billet_outline_splits_into_its_four_sides(self):
        """Two sampled arcs and two straight ends, as the core sends a billet face: four runs, so the
        box has four smooth sides (the first take drew one face per sample, a pink hatch)."""
        import math
        inner = [[2000.0 * math.sin(t / 32.0 - 0.5), 0.0, 2000.0 * math.cos(t / 32.0 - 0.5)] for t in range(33)]
        outer = [[2190.0 * math.sin(t / 32.0 - 0.5), 0.0, 2190.0 * math.cos(t / 32.0 - 0.5)] for t in range(33)][::-1]
        loop = inner + outer + [inner[0]]
        runs = core.loop_runs(loop)
        self.assertEqual(sorted(len(r) for r in runs), [2, 2, 33, 33])
        self.assertEqual([r[-1] for r in runs], [runs[(k + 1) % 4][0] for k in range(4)])   # they close
        square = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]]
        self.assertEqual(core.loop_runs(square), [[0, 1], [1, 2], [2, 3], [3, 0]])

    def test_member_user_text_is_the_answer_as_sent(self):
        s = core.Session(Canned([with_outlines(BODIES["twist_50_splits"])]))
        s.begin_drawing("end")
        s.end_drawing("end", [[2400.0, -300.0, 0.0], [2400.0, 300.0, 100.0]])
        s.done()
        s.run_sync()
        mid = s.next_member_id()
        text = dict(core.member_user_text(mid, s.result))
        form = s.result["sent"]["form"]
        grains = [p["checks"]["grain"]["angle_deg"] for p in form["pieces"]] + [form["checks"]["grain"]["angle_deg"]]
        self.assertEqual(text, {"gnj.id": "M1", "gnj.pieces": "2",
                                "gnj.layers": "%g" % form["n_lamellas"], "gnj.layer_mm": "%g" % form["lamella_mm"],
                                "gnj.waste_pct": "%g" % form["checks"]["waste_pct"], "gnj.grain_deg": "%g" % max(grains)})
        row = s.add_member(s.accept(), ["a"])
        self.assertEqual(row["id"], mid)
        self.assertEqual(s.next_member_id(), "M2")


@unittest.skipUnless(sys.version_info[0] == 3 and os.path.isdir(os.path.join(CORE_DIR, "gnj_nudge")),
                     "core main export not present")
class RoundTripWithTheCore(unittest.TestCase):
    """The core itself, in this process (no server): what this client sends after an Accept."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, CORE_DIR)
        from gnj_nudge.plate import PlateIntent, solve_plate
        from gnj_nudge.intent import Holds
        cls.solve = staticmethod(lambda d: solve_plate(PlateIntent.from_dict(d), Holds()).as_dict())

    def test_an_accepted_plate_sent_again_comes_back_the_same(self):
        first = self.solve(core.plate_intent({"path": arc(rise=150.0),
                                              "end": [[2400.0, -150.0, -40.0], [2400.0, 150.0, 40.0]]},
                                             core.straight_member()))
        form = core.nudge_response(first, {"kind": "plate"})["form"]
        again = self.solve(core.plate_intent({}, core.member_from_form(form)))
        g0, g1 = first["form"]["grid"], again["form"]["grid"]
        worst = max(abs(a - b) for r0, r1 in zip(g0, g1) for p, q in zip(r0, r1) for a, b in zip(p, q))
        self.assertLess(worst, 0.05)
        self.assertEqual(again["deviation_mm"], 0.0)

    def test_a_start_drawn_on_the_accepted_plate_keeps_its_shape_there(self):
        first = self.solve(core.plate_intent({"path": arc(rise=300.0)}, core.straight_member()))
        form = core.nudge_response(first, {"kind": "plate"})["form"]
        cur = core.member_from_form(form)
        f = cur["end_frames"]["start"]
        drawn = [[f["origin"][k] + w * f["across"][k] for k in range(3)] for w in (-200.0, 200.0)]
        out = self.solve(core.plate_intent({"start": drawn}, cur))
        row = out["form"]["grid"][0]
        width = sum((a - b) ** 2 for a, b in zip(row[0], row[-1])) ** 0.5
        self.assertAlmostEqual(width, 400.0, delta=0.5)   # not shortened by the leaning end plane

    def test_a_path_in_plan_and_elevation_comes_back_doubly_curved_in_pieces(self):
        s = core.Session(core.OfflineClient())
        draw(s, plan_stroke(), "flat")
        draw(s, elevation_stroke(), "upright")
        s.done()
        out = self.solve(s.plate)
        rows = core.row_means(out["form"]["grid"])
        self.assertEqual((out["status"], out["deviation_mm"]), ("proposed", 0.0))
        self.assertGreater(len(out["form"]["pieces"]), 1)
        self.assertGreater(max(abs(p[1]) for p in rows), 140.0)   # the S in plan
        self.assertGreater(max(p[2] for p in rows), 290.0)        # the arch in elevation


if __name__ == "__main__":
    unittest.main()


class SayOnAPart(unittest.TestCase):
    """Regression (v9 smoke, 2026-11-15): words said while a part's plan was proposed raised KeyError
    'radius_mm' in formal_reject (a part plan has no radius), the card stayed on 'Working out what you
    meant.' and Accept then judged the stale one-billet plan while the core held the 4-piece one."""

    PLAN = {"status": "proposed", "sentence": "Buildable as modelled.", "steps": [], "deviation_mm": 0.0,
            "form": {"kind": "part_plan", "n_pieces": 1, "pieces": [{"n_lamellas": 7, "lamella_mm": 17.0}],
                     "cuts": [], "billet": {"outline": []}, "axis": {"length_mm": 2380.0}}}

    def test_words_on_a_proposed_part_decline_it_and_show_the_new_plan(self):
        split = json.loads(json.dumps(self.PLAN))
        split["form"]["n_pieces"] = 4
        split["form"]["cuts"] = [{"at_mm": 595.0, "line": [[595.0, 0.0, 0.0], [595.0, 89.0, 0.0]]}]
        split["sentence"] = "Buildable as modelled, in 4 pieces joined end to end."
        reply = {"understood": True, "heard": "Shorter pieces are fine.", "source": "keywords",
                 "actions": [{"op": "hold", "name": "split_ok"}, {"op": "hold", "name": "less_waste"}], "nudge": split}
        s = core.Session(Canned([self.PLAN]))
        s.check_part(core.part_intent([[0.0, 0.0, 0.0]] * 300, 1000.0))
        s.run_sync()
        gen, text, intent = s.begin_say("shorter pieces are fine and waste less")
        self.assertTrue(s.finish_say(gen, core.say_response(reply, intent)))
        self.assertEqual((s.phase, s.result["form"]["n_pieces"], s.held()), ("proposed", 4, ["less_waste", "split_ok"]))
        self.assertTrue(s.record[0]["text"].startswith("Proposal declined: your own part, in one piece."))
        self.assertFalse(s.saying)
