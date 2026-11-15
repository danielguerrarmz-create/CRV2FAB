# -*- coding: utf-8 -*-
"""Pure tests for gnj_core. Run: python -m unittest discover -s tests (CPython 3),
or under IronPython 2.7 with tests/run_ipy.ps1. No Rhino needed."""
from __future__ import division

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gnj_core as core  # noqa: E402


def intent(radius, angle=0.0):
    return {"member_id": "M1", "chord_mm": 2400.0, "radius_mm": radius, "direction": "up", "bend_angle_deg": angle}


class FakeClient(core.OfflineClient):
    """Local solver, but records judge calls and can pretend a result came via the core."""

    def __init__(self, via_core=False):
        core.OfflineClient.__init__(self)
        self.via_core = via_core
        self.judged = []

    def nudge(self, intent_, holds):
        out = core.OfflineClient.nudge(self, intent_, holds)
        out["via_core"] = self.via_core
        return out

    def judge(self, verdict, hold=None):
        self.judged.append((verdict, hold))
        return "CORE " + verdict if self.via_core else None


class SolverMatchesMock(unittest.TestCase):
    def test_2450_laminates_four_layers_no_deviation(self):
        r = core.local_solve(intent(2450.0), [])
        self.assertEqual(r["status"], "proposed")
        self.assertEqual(r["form"]["n_lamellas"], 4)
        self.assertAlmostEqual(r["form"]["lamella_mm"], 9.5)
        self.assertAlmostEqual(r["form"]["radius_mm"], 2450.0)
        self.assertEqual(r["deviation_mm"], 0)

    def test_2450_holding_solid_eases_to_7600(self):
        r = core.local_solve(intent(2450.0), ["solid"])
        self.assertEqual(r["status"], "proposed")
        self.assertEqual(r["form"]["n_lamellas"], 1)
        self.assertAlmostEqual(r["form"]["radius_mm"], 7600.0)
        self.assertGreater(r["deviation_mm"], 200)  # 314 - 95 = about 219 mm at mid-span

    def test_solid_and_shape_conflict(self):
        r = core.local_solve(intent(2450.0), ["solid", "shape"])
        self.assertEqual(r["status"], "conflict")
        self.assertIsNone(r["form"])
        self.assertEqual(r["sentence"], "Solid and this curve cannot both be built.")

    def test_wide_radius_passes_solid(self):
        r = core.local_solve(intent(8000.0), [])
        self.assertEqual((r["form"]["n_lamellas"], r["deviation_mm"]), (1, 0))
        self.assertEqual(r["sentence"], "Buildable as drawn, in one solid piece.")

    def test_boundary_7600_is_solid(self):
        self.assertEqual(core.local_solve(intent(7600.0), [])["form"]["n_lamellas"], 1)
        self.assertEqual(core.local_solve(intent(7599.0), [])["form"]["n_lamellas"], 2)

    def test_too_tight_eases_to_thinnest_layer(self):
        r = core.local_solve(intent(1500.0), [])
        self.assertEqual(r["form"]["n_lamellas"], 4)
        self.assertAlmostEqual(r["form"]["radius_mm"], 1900.0)
        self.assertEqual(core.local_solve(intent(1500.0), ["shape"])["status"], "conflict")

    def test_every_proposal_passes_the_limits(self):
        for radius in range(1300, 9000, 37):
            for holds in ([], ["solid"], ["shape"]):
                r = core.local_solve(intent(float(radius)), holds)
                if r["status"] != "proposed":
                    continue
                f = r["form"]
                self.assertGreaterEqual(f["radius_mm"] / f["lamella_mm"], core.BEND_RATIO - 1e-9)
                self.assertGreaterEqual(f["lamella_mm"], core.MIN_LAMELLA_MM)
                self.assertAlmostEqual(f["n_lamellas"] * f["lamella_mm"], core.STOCK_MM)
                if "solid" in holds:
                    self.assertEqual(f["n_lamellas"], 1)
                if "shape" in holds:
                    self.assertAlmostEqual(r["deviation_mm"], 0)


class Maths(unittest.TestCase):
    def test_radius_and_sag_invert(self):
        for radius in (1300.0, 2450.0, 7600.0, 20000.0):
            self.assertAlmostEqual(core.radius_of(core.sag_of(radius)), radius, places=6)

    def test_read_bend_takes_farthest_point_and_its_direction(self):
        sag, a, why = core.read_bend([(0, 5), (0, -40), (0, 30)])
        self.assertEqual((sag, a, why), (40, 180.0, None))
        sag, a, _ = core.read_bend([(100, 0), (0, 30)])
        self.assertEqual((sag, a), (100, 90.0))
        sag, a, _ = core.read_bend([(-30, 30)])
        self.assertAlmostEqual(a, 315.0)

    def test_read_bend_rejects_small_gesture_at_boundary(self):
        self.assertEqual(core.read_bend([(0, 19.9), (19.9, 0)])[2], core.TOO_SMALL)
        self.assertEqual(core.read_bend([(0, 20.0)])[0], 20.0)

    def test_read_bend_clamps_like_the_mock(self):
        self.assertAlmostEqual(core.read_bend([(0, 5000.0)])[0], 230 / 0.35)
        self.assertAlmostEqual(core.read_bend([(-5000.0, 0)])[1], 270.0)

    def test_n1_and_m(self):
        self.assertEqual(core.n1(9.5), "9.5")
        self.assertEqual(core.n1(12.0), "12")
        self.assertEqual(core.m(2450.0), "2.45 m")

    def test_no_local_keyword_matcher(self):
        self.assertFalse(hasattr(core, "parse_say"))  # v5: the core owns reading words


class Contract(unittest.TestCase):
    def test_request_shape(self):
        body = core.nudge_request(intent(2450.0), ["solid", "shape"])
        self.assertEqual(set(body), {"intent", "holds"})
        self.assertEqual(set(body["intent"]), {"member_id", "chord_mm", "radius_mm", "direction", "bend_angle_deg"})

    def test_response_reads_core_body(self):
        body = {"status": "proposed", "sentence": u"Fine \u2014 really", "steps": [{"tag": "Heard", "text": "x", "limit_id": None}],
                "form": {"radius_mm": 2450.0, "n_lamellas": 4, "lamella_mm": 9.5, "chord_mm": 2400.0, "direction": "down"},
                "deviation_mm": 0.0, "source": "model", "conflict": None, "governing": ["bend_ratio"]}
        r = core.nudge_response(body, intent(2450.0, 180.0))
        self.assertEqual(r["form"]["direction"], "down")
        self.assertEqual(r["sentence"], u"Fine, really")  # dashes stripped from untrusted text

    def test_response_rejects_garbage(self):
        self.assertRaises(ValueError, core.nudge_response, {"status": "maybe"}, intent(2450.0))
        self.assertRaises(ValueError, core.nudge_response, {"status": "proposed", "form": None}, intent(2450.0))

    def test_offline_client_falls_back(self):
        r = core.CoreClient("http://127.0.0.1:9").nudge(intent(2450.0), [])
        self.assertEqual((r["source"], r["via_core"]), ("fallback", False))
        self.assertEqual(r["form"]["n_lamellas"], 4)


class SessionFlow(unittest.TestCase):
    def make(self, via_core=False):
        c = FakeClient(via_core)
        s = core.Session(c)
        self.assertTrue(s.gesture(core.sag_of(2450.0)))
        s.run_sync()
        return s, c

    def test_gesture_proposes(self):
        s, _ = self.make()
        self.assertEqual(s.phase, "proposed")
        self.assertTrue(s.can_judge())
        self.assertEqual(s.result["form"]["n_lamellas"], 4)

    def test_reject_waits_and_keeps_holds(self):
        s, _ = self.make()
        s.holds["solid"] = True
        self.assertFalse(s.reject())   # never re-runs by itself
        self.assertEqual(s.phase, "rejected")
        self.assertTrue(s.holds["solid"])
        self.assertIn(core.NO_REASON, s.record[0]["text"])

    def test_hold_after_reject_amends_and_reruns(self):
        s, _ = self.make()
        s.reject()
        self.assertTrue(s.add_hold("solid"))
        self.assertIn("Designer holds: solid section.", s.record[0]["text"])
        s.run_sync()
        self.assertEqual((s.phase, s.result["form"]["radius_mm"]), ("proposed", 7600.0))
        self.assertTrue(s.add_hold("shape"))
        s.run_sync()
        self.assertEqual(s.phase, "conflict")
        self.assertFalse(s.can_judge())

    def test_hold_while_proposed_logs_reject_with_reason(self):
        s, c = self.make(via_core=True)
        self.assertTrue(s.add_hold("solid"))
        self.assertEqual(c.judged, [("rejected", "solid")])

    def test_accept_clears_holds_and_records(self):
        s, c = self.make(via_core=True)
        s.add_hold("shape")
        s.run_sync()
        r = s.accept()
        self.assertEqual(r["form"]["n_lamellas"], 4)
        self.assertEqual(s.phase, "accepted")
        self.assertEqual(s.held(), [])
        self.assertEqual(s.record[0], {"v": "accepted", "text": "CORE accepted"})
        self.assertFalse(s.can_judge())

    def test_offline_accept_writes_local_formal(self):
        s, c = self.make()
        s.accept()
        self.assertEqual(c.judged, [])  # a local proposal is never sent to the core to judge
        self.assertTrue(s.record[0]["text"].startswith("Member M1, softwood 38 x 89 mm"))

    def test_stale_result_is_dropped(self):
        s, c = self.make()
        gen, i, h = s.begin_nudge()
        s.begin_nudge()                       # a newer gesture came in
        self.assertFalse(s.finish_nudge(gen, c.nudge(i, h)))
        self.assertEqual(s.phase, "thinking")

    def test_words_need_the_helper_when_the_core_is_down(self):
        s, _ = self.make()                    # FakeClient: the local solver answered
        self.assertIsNone(s.begin_say("no glue please"))
        self.assertEqual(s.subline(), core.HELPER_FOR_WORDS)
        self.assertEqual(s.phase, "proposed")


class SpecV2AnyDirection(unittest.TestCase):
    def test_vertical_reproduces_v1_numbers(self):
        for a in (0.0, 180.0):
            f = core.local_solve(intent(2450.0, a), [])["form"]
            self.assertEqual((f["n_lamellas"], f["n_strips"]), (4, 1))
            self.assertAlmostEqual(f["lamella_mm"], 9.5)
            self.assertEqual(f["bend_angle_deg"], a)  # the solver never changes the direction
            f = core.local_solve(intent(2450.0, a), ["solid"])["form"]
            self.assertEqual((f["radius_mm"], f["n_lamellas"], f["n_strips"]), (7600.0, 1, 1))
            self.assertEqual(core.local_solve(intent(2450.0, a), ["solid", "shape"])["status"], "conflict")
            self.assertAlmostEqual(core.local_solve(intent(1500.0, a), [])["form"]["radius_mm"], 1900.0)

    def test_sideways_2450_is_eight_strips(self):
        r = core.local_solve(intent(2450.0, 90.0), [])
        f = r["form"]
        self.assertEqual((f["n_lamellas"], f["n_strips"], r["deviation_mm"]), (1, 8, 0))
        self.assertEqual(r["sentence"], "Your curve holds. Made from 8 glued strips side by side in place of one solid piece.")

    def test_sideways_solid_boundary_17800(self):
        self.assertEqual(core.local_solve(intent(17800.0, 90.0), [])["sentence"], "Buildable as drawn, in one solid piece.")
        self.assertEqual(core.local_solve(intent(17799.0, 90.0), [])["form"]["n_strips"], 2)
        self.assertAlmostEqual(core.local_solve(intent(2450.0, 270.0), ["solid"])["form"]["radius_mm"], 17800.0)

    def test_diagonal_glues_both_ways(self):
        r = core.local_solve(intent(2450.0, 45.0), [])
        f = r["form"]
        self.assertGreater(f["n_lamellas"], 1)
        self.assertGreater(f["n_strips"], 1)
        self.assertTrue(r["sentence"].startswith("Your curve holds. Glued both ways"))

    def test_too_tight_sideways_eases_to_thinnest_strip(self):
        r = core.local_solve(intent(1300.0, 90.0), [])
        self.assertAlmostEqual(r["form"]["radius_mm"], 200 * 89.0 / 11)
        self.assertEqual(r["form"]["n_strips"], 11)
        self.assertEqual(core.local_solve(intent(1300.0, 90.0), ["shape"])["sentence"],
                         "This curve is too tight for any strip we can cut.")

    def test_every_direction_passes_the_v2_limits(self):
        for a in range(0, 360, 15):
            c, s = core.dir_factors(a)
            for radius in range(1250, 20000, 113):
                for holds in ([], ["solid"], ["shape"]):
                    r = core.local_solve(intent(float(radius), float(a)), holds)
                    if r["status"] != "proposed":
                        continue
                    f = r["form"]
                    R = f["radius_mm"]
                    self.assertEqual(f["bend_angle_deg"], a)
                    self.assertLessEqual(f["lamella_mm"] * c, R / 200.0 + 1e-6)
                    self.assertLessEqual(f["strip_mm"] * s, R / 200.0 + 1e-6)
                    self.assertGreaterEqual(min(f["lamella_mm"], f["strip_mm"]), 8.0 - 1e-9)
                    if "solid" in holds:
                        self.assertEqual((f["n_lamellas"], f["n_strips"]), (1, 1))
                    if "shape" in holds:
                        self.assertAlmostEqual(r["deviation_mm"], 0)

    def test_v1_core_answer_refused_for_a_sideways_bend(self):
        v1 = {"status": "proposed", "sentence": "x", "steps": [], "deviation_mm": 0, "source": "fallback",
              "form": {"radius_mm": 2450, "n_lamellas": 4, "lamella_mm": 9.5, "chord_mm": 2400, "direction": "up"}}
        self.assertRaises(ValueError, core.nudge_response, v1, intent(2450.0, 90.0))
        self.assertEqual(core.nudge_response(v1, intent(2450.0, 0.0))["form"]["n_strips"], 1)

    def test_core_answer_with_a_changed_direction_is_refused(self):
        body = {"status": "proposed", "sentence": "x", "steps": [], "deviation_mm": 0, "source": "fallback",
                "form": {"radius_mm": 2450, "n_lamellas": 4, "lamella_mm": 9.5, "n_strips": 1, "strip_mm": 89.0,
                         "bend_angle_deg": 0.0, "chord_mm": 2400, "direction": "up"}}
        self.assertRaises(ValueError, core.nudge_response, body, intent(2450.0, 90.0))
        body["form"]["bend_angle_deg"] = 359.8
        self.assertEqual(core.nudge_response(body, intent(2450.0, 0.0))["form"]["n_lamellas"], 4)  # wraps at 360

    def test_session_sends_direction(self):
        s = core.Session(FakeClient())
        s.gesture(core.sag_of(2450.0), 90.0)
        self.assertEqual(s.intent()["bend_angle_deg"], 90.0)
        s.run_sync()
        self.assertEqual(s.result["form"]["n_strips"], 8)
        s.accept()
        self.assertIn("bend direction 90 degrees", s.record[0]["text"])


class SnapToPrincipalDirections(unittest.TestCase):
    def test_pinned_cases(self):
        self.assertEqual(core.snap_angle(29), (0.0, True))
        self.assertEqual(core.snap_angle(31), (31.0, False))
        self.assertEqual(core.snap_angle(61), (90.0, True))
        self.assertEqual(core.snap_angle(209), (180.0, True))

    def test_boundary_is_inclusive_and_wraps(self):
        self.assertEqual(core.snap_angle(30), (0.0, True))
        self.assertEqual(core.snap_angle(0), (0.0, False))     # already principal: nothing was snapped
        self.assertEqual(core.snap_angle(180), (180.0, False))
        self.assertEqual(core.snap_angle(359.6), (0.0, False))  # whole degrees: 360 is 0
        self.assertEqual(core.snap_angle(330), (0.0, True))
        self.assertEqual(core.snap_angle(299), (270.0, True))
        self.assertEqual(core.snap_angle(301), (301.0, False))
        self.assertEqual(core.SNAP_DEG, 30)

    def test_roughly_up_is_not_glued_both_ways(self):
        s = core.Session(FakeClient())
        s.gesture(core.sag_of(2450.0), 20.0)
        self.assertEqual((s.angle, s.snapped, s.intent()["bend_angle_deg"]), (0.0, True, 0.0))
        s.run_sync()
        self.assertEqual((s.result["form"]["n_lamellas"], s.result["form"]["n_strips"]), (4, 1))
        self.assertEqual(s.result["steps"][0]["text"], "Bend the full 2.4 m to a radius of 2.45 m, read as straight up.")

    def test_snap_words_and_a_kept_lean(self):
        s = core.Session(FakeClient())
        s.gesture(core.sag_of(2450.0), 260.0)
        s.run_sync()
        self.assertTrue(s.result["steps"][0]["text"].endswith("read as sideways."))
        s.gesture(core.sag_of(2450.0), 200.0)
        s.run_sync()
        self.assertTrue(s.result["steps"][0]["text"].endswith("read as straight down."))
        s.gesture(core.sag_of(2450.0), 45.0)
        s.run_sync()
        self.assertFalse(s.snapped)
        self.assertTrue(s.result["steps"][0]["text"].endswith("bending 45 degrees from up."))


class TasteFromTheCore(unittest.TestCase):
    """A taste-led answer changes radius and make-up, never direction: shown as sent."""

    def body(self):
        return {"status": "proposed", "source": "fallback",
                "sentence": "Kept solid, as you usually do. Curve eased by 219 mm so one piece can bend it.",
                "steps": [{"tag": "Heard", "text": "Bend the full 2.40 m to a radius of 2.45 m.", "limit_id": None},
                          {"tag": "Taste", "text": "You kept it solid in 3 of your last 3 decisions.", "limit_id": None}],
                "form": {"radius_mm": 7600.0, "n_lamellas": 1, "lamella_mm": 38.0, "n_strips": 1, "strip_mm": 89.0,
                         "bend_angle_deg": 0.0, "chord_mm": 2400.0},
                "deviation_mm": 218.7, "conflict": None, "governing": ["bend_ratio"],
                "taste": {"lead": "solid", "because": "You kept it solid in 3 of your last 3 decisions."}}

    def test_taste_answer_passes_the_guards_untouched(self):
        r = core.nudge_response(self.body(), intent(2450.0, 0.0))
        self.assertEqual(r["sentence"], self.body()["sentence"])
        self.assertEqual([s["tag"] for s in r["steps"]], ["Heard", "Taste"])
        self.assertEqual(r["taste"]["lead"], "solid")
        self.assertEqual((r["form"]["radius_mm"], r["form"]["n_lamellas"]), (7600.0, 1))

    def test_session_shows_core_steps_when_not_snapped(self):
        class Canned(core.CoreClient):
            def _post(s, path, body, timeout):
                return self.body()
        s = core.Session(Canned())
        s.gesture(core.sag_of(2450.0), 0.0)   # drawn straight up: nothing to snap
        s.run_sync()
        self.assertEqual((s.headline(), s.subline()), ("Buildable, eased.", self.body()["sentence"][:65] + "..."))
        self.assertEqual(s.result["steps"][0]["text"], "Bend the full 2.40 m to a radius of 2.45 m.")



def _camera(direction):
    """A synthetic view: project world directions onto the screen (right, up) of a camera looking
    along direction, no roll. Returns project(v) -> (x, y)."""
    d = [c / math.sqrt(sum(x * x for x in direction)) for c in direction]
    zup = (0.0, 0.0, 1.0)
    right = (d[1] * zup[2] - d[2] * zup[1], d[2] * zup[0] - d[0] * zup[2], d[0] * zup[1] - d[1] * zup[0])
    if math.sqrt(sum(x * x for x in right)) < 1e-9:  # looking straight down: screen up is +Y
        right = (1.0, 0.0, 0.0)
    lr = math.sqrt(sum(x * x for x in right))
    right = tuple(x / lr for x in right)
    up = (right[1] * d[2] - right[2] * d[1], right[2] * d[0] - right[0] * d[2], right[0] * d[1] - right[1] * d[0])

    def project(v):
        return (sum(a * b for a, b in zip(v, right)), sum(a * b for a, b in zip(v, up)))
    return project


def _view(direction):
    """(up, side) as projected on screen, and across(v): the part of a screen vector across the
    timber's projected axis (a stroke's offset is always across it). The timber runs along world X."""
    project = _camera(direction)
    ax = project((1.0, 0.0, 0.0))
    la = math.hypot(*ax) or 1.0
    ax = (ax[0] / la, ax[1] / la)

    def across(v):
        k = v[0] * ax[0] + v[1] * ax[1]
        return (v[0] - k * ax[0], v[1] - k * ax[1])
    return project((0.0, 0.0, 1.0)), project((0.0, 1.0, 0.0)), across


PERSPECTIVE = (1.0, 1.0, -0.75)   # roughly Rhino 7's default Perspective, looking down about 28 degrees
FRONT = (0.0, 1.0, 0.0)
TOP = (0.0, 0.0, -1.0)


class SnapOnScreen(unittest.TestCase):
    """Approved 2026-11-14: snap by what is nearest on screen; otherwise a deliberate lean."""

    def test_perspective_up_screen_stroke_reads_up(self):
        up, side, across = _view(PERSPECTIVE)
        self.assertEqual(core.screen_snap(across((0.0, 1.0)), up, side, 34.0), (0.0, True))

    def test_perspective_stroke_along_the_projected_horizontal_reads_sideways(self):
        up, side, across = _view(PERSPECTIVE)
        self.assertEqual(core.screen_snap(side, up, side, 120.0), (90.0, True))
        self.assertEqual(core.screen_snap((-side[0], -side[1]), up, side, 250.0), (270.0, True))

    def test_halfway_between_on_screen_stays_a_lean(self):
        up, side, across = _view(PERSPECTIVE)
        nu, ns = math.hypot(*up), math.hypot(*side)
        half = (up[0] / nu + side[0] / ns, up[1] / nu + side[1] / ns)
        self.assertIsNone(core.screen_snap(half, up, side, 45.0))

    def test_front_reads_up_or_down_only(self):
        up, side, across = _view(FRONT)
        self.assertLess(math.hypot(*side), 1e-9)       # the cross axis points at the eye
        self.assertEqual(core.screen_snap((0.0, 1.0), up, side, 0.0), (0.0, False))
        self.assertEqual(core.screen_snap((0.1, -1.0), up, side, 180.0), (180.0, False))
        self.assertIsNone(core.screen_snap((1.0, 1.0), up, side, 0.0))   # 45 degrees: no sideways here

    def test_top_reads_sideways_only(self):
        up, side, across = _view(TOP)
        self.assertLess(math.hypot(*up), 1e-9)
        self.assertEqual(core.screen_snap((0.0, 1.0), up, side, 90.0)[0], 90.0)
        self.assertEqual(core.screen_snap((0.0, -1.0), up, side, 270.0)[0], 270.0)

    def test_nearly_degenerate_axis_is_not_a_candidate(self):
        self.assertIsNone(core.screen_snap((1.0, 0.1), (0.0, 1.0), (0.1, 0.0), 0.0))  # side is 10% of up
        self.assertEqual(core.screen_snap((1.0, 0.1), (0.0, 1.0), (0.2, 0.0), 0.0), (90.0, True))

    def test_session_takes_a_screen_snap_as_final(self):
        s = core.Session(FakeClient())
        s.gesture(core.sag_of(2450.0), 0.0, True)
        s.run_sync()
        self.assertEqual((s.angle, s.result["form"]["n_lamellas"]), (0.0, 4))
        self.assertTrue(s.result["steps"][0]["text"].endswith("read as straight up."))
        s.gesture(core.sag_of(2450.0), 34.0, False)       # a lean stays as drawn, no world snap
        self.assertEqual((s.angle, s.snapped), (34.0, False))



class SayToTheCore(unittest.TestCase):
    """v5: typed words go to POST /say; the core reads them, this client shows what comes back."""

    NOT_HEARD = "I did not catch a change I can make. I can keep it solid, or keep your line."

    def client(self, say_body):
        nudge_body = {"status": "proposed", "source": "rules", "sentence": "Your curve holds. Made from 4 glued layers in place of one solid piece.",
                      "steps": [{"tag": "Heard", "text": "Bend the full 2.40 m to a radius of 2.45 m.", "limit_id": None}],
                      "form": {"radius_mm": 2450.0, "n_lamellas": 4, "lamella_mm": 9.5, "n_strips": 1, "strip_mm": 89.0,
                               "bend_angle_deg": 0.0, "chord_mm": 2400.0}, "deviation_mm": 0.0, "conflict": None}

        class Canned(core.CoreClient):
            posts = []

            def _post(s, path, body, timeout):
                s.posts.append((path, body, timeout))
                if path == "/say":
                    return say_body
                if path == "/judge":
                    return {"formal": "CORE " + body["verdict"]}
                return nudge_body
        return Canned()

    def solid_body(self):
        return {"understood": True, "heard": "Keeping it as one piece.", "actions": [{"op": "hold", "name": "solid"}],
                "source": "claude-code", "model_ms": 2369,
                "nudge": {"status": "proposed", "source": "rules",
                          "sentence": "Kept solid. Curve eased by 219 mm so one piece can bend it.",
                          "steps": [{"tag": "Heard", "text": "Bend the full 2.40 m to a radius of 2.45 m.", "limit_id": None}],
                          "form": {"radius_mm": 7600.0, "n_lamellas": 1, "lamella_mm": 38.0, "n_strips": 1, "strip_mm": 89.0,
                                   "bend_angle_deg": 0.0, "chord_mm": 2400.0, "checks": {"waste_pct": 0.0}},
                          "deviation_mm": 218.7, "conflict": None}}

    def session(self, say_body):
        c = self.client(say_body)
        s = core.Session(c)
        s.gesture(core.sag_of(2450.0), 0.0)
        s.run_sync()
        s.reject()
        return s, c

    def test_understood_holds_solid_and_shows_the_nudge_as_sent(self):
        s, c = self.session(self.solid_body())
        gen, text, intent = s.begin_say("  no glue lines please ")
        self.assertEqual((s.saying, s.headline(), text), (True, core.SAYING, "no glue lines please"))
        reply = c.say(text, intent)
        self.assertEqual(c.posts[-1][0:2], ("/say", {"text": "no glue lines please"}))
        self.assertEqual(c.posts[-1][2], core.SAY_TIMEOUT_S)
        self.assertTrue(s.finish_say(gen, reply))
        self.assertEqual((s.phase, s.held(), s.heard), ("proposed", ["solid"], "Keeping it as one piece."))
        self.assertEqual(s.headline(), "Buildable, eased.")   # from deviation_mm; the bend kind is not in the slot table
        self.assertEqual(s.subline(), "Kept solid. Curve eased by 219 mm so one piece can bend it.")
        self.assertEqual(s.unmapped(), "Kept solid. Curve eased by 219 mm so one piece can bend it.")
        self.assertEqual(s.echo_line(), "Keeping it as one piece.")
        self.assertEqual(s.result["source"], "rules")
        self.assertEqual(s.waste_line(), "Waste 0%  Moved 219 mm  Needs 1 layer")
        self.assertFalse(s.saying)

    def test_not_understood_changes_nothing(self):
        body = {"understood": False, "heard": self.NOT_HEARD, "actions": [], "source": "claude-code", "nudge": None}
        s, c = self.session(body)
        gen, text, intent = s.begin_say("make it blue")
        self.assertTrue(s.finish_say(gen, c.say(text, intent)))
        self.assertEqual((s.phase, s.held(), s.heard), ("rejected", [], self.NOT_HEARD))
        self.assertEqual(s.echo_line(), "I did not catch a change.")   # SPEC_V9_CARD_SLOTS: Echo, not Reason
        self.assertEqual(s.subline(), "I will not guess again. Redraw a stroke, or say what to keep.")

    def test_a_hold_never_seen_before_is_kept_and_labelled(self):
        body = self.solid_body()
        body["actions"] = [{"op": "hold", "name": "less_waste"}, {"op": "release", "name": "solid"}]
        s, c = self.session(body)
        s.holds["solid"] = True
        gen, text, intent = s.begin_say("waste less wood")
        s.finish_say(gen, c.say(text, intent))
        self.assertEqual(s.held(), ["less_waste"])
        self.assertEqual(core.hold_label("less_waste"), "less waste")   # SPEC_V9_UI: "Keeping: less waste"
        self.assertEqual(core.hold_label("keep_grain"), "keep grain")   # a plain label for a new name
        self.assertEqual(core.hold_label("shape", "line"), "my line")
        self.assertEqual((core.hold_label("shape"), core.hold_label("solid")), ("my shape", "one piece"))
        bad = core.say_response({"understood": True, "heard": "x", "actions": [{"op": "hold", "name": "Robert'); DROP"}],
                                 "nudge": self.solid_body()["nudge"]}, s.intent())
        self.assertEqual(bad["actions"], [])

    def test_unreachable_core_says_it_needs_the_helper(self):
        s, c = self.session(self.solid_body())
        gen, text, intent = s.begin_say("no glue")
        self.assertTrue(s.finish_say(gen, None))
        self.assertEqual((s.subline(), s.phase), (core.HELPER_FOR_WORDS, "rejected"))

    def test_a_stale_reply_is_dropped(self):
        s, c = self.session(self.solid_body())
        gen, text, intent = s.begin_say("no glue")
        s.gesture(core.sag_of(3000.0), 0.0)
        s.begin_nudge()                       # a new gesture meanwhile
        self.assertFalse(s.finish_say(gen, c.say(text, intent)))


if __name__ == "__main__":
    unittest.main()
