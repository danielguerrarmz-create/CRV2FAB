# -*- coding: utf-8 -*-
"""Spec v3, pure parts: the saddle grid, the stroke, the response mapping, the session. No Rhino."""
from __future__ import division

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gnj_core as core  # noqa: E402


def saddle_member_body(n_lam=3, n_str=1, count=65, status="proposed"):
    """A core-shaped v3 answer along the saddle's x axis (v = 0.5), with exact normals."""
    stations, normals = [], []
    for i in range(count):
        u = 0.15 + 0.7 * i / (count - 1.0)
        x, y, z = core.saddle_point(u, 0.5)
        stations.append([x, y, z])
        nx, ny, nz = -2 * x / core.SADDLE_K, 2 * y / core.SADDLE_K, 1.0
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        normals.append([nx / ln, ny / ln, nz / ln])
    form = {"kind": "surface_member", "stations": stations, "normals": normals,
            "uv": [[0.15 + 0.7 * i / (count - 1.0), 0.5] for i in range(count)], "intent_stations": stations,
            "n_lamellas": n_lam, "lamella_mm": 38.0 / n_lam, "n_strips": n_str, "strip_mm": 89.0 / n_str,
            "min_radius_normal_mm": 3000.0, "min_radius_side_mm": None, "max_twist_deg_per_m": 0.0,
            "length_mm": 2100.0, "smoothing_passes": 0}
    return {"status": status, "source": "fallback", "sentence": "Your line holds. Made from 3 glued layers.",
            "steps": [{"tag": "Heard", "text": "x", "limit_id": None}], "deviation_mm": 0.0, "trimmed": False,
            "form": form if status == "proposed" else None, "conflict": None}


class CannedCore(core.CoreClient):
    """Answers /nudge with a canned body and records /judge, through the real mapping code."""

    def __init__(self, body):
        core.CoreClient.__init__(self, "http://canned")
        self.body, self.posts = body, []

    def _post(self, path, body, timeout):
        self.posts.append((path, body))
        if path == "/judge":
            return {"formal": "CORE " + body["verdict"]}
        return self.body


def stroke_intent():
    grid = core.grid_from(core.saddle_point)
    return core.surface_intent(grid, core.clean_stroke_uv([(0.15 + 0.07 * i, 0.5) for i in range(11)]))


class Grid(unittest.TestCase):
    def test_saddle_grid_row_major_u_outer(self):
        g = core.grid_from(core.saddle_point)
        self.assertEqual((g["nu"], g["nv"], len(g["points"])), (21, 21, 441))
        self.assertEqual(g["points"][0], [-1500.0, -1500.0, 800.0])
        self.assertEqual(g["points"][1][:2], [-1500.0, -1350.0])      # v moves fastest
        self.assertEqual(g["points"][21][:2], [-1350.0, -1500.0])     # next u row
        self.assertEqual(g["points"][220], [0.0, 0.0, 800.0])         # the saddle point
        self.assertAlmostEqual(g["points"][10][2], 800 + 1500 ** 2 / 6000.0)  # x = -1500, y = 0: ridge

    def test_request_fits_the_core_body_cap(self):
        import json
        body = core.nudge_request(stroke_intent(), [])
        self.assertLess(len(json.dumps(body)), 64 * 1024)
        self.assertEqual(body["intent"]["kind"], "surface_stroke")


class Stroke(unittest.TestCase):
    def test_clamps_dedupes_and_needs_two(self):
        self.assertEqual(core.clean_stroke_uv([(-0.1, 0.5), (-0.2, 0.5), (1.3, 0.5)]), [[0.0, 0.5], [1.0, 0.5]])
        self.assertIsNone(core.clean_stroke_uv([(0.3, 0.3), (0.3, 0.3)]))

    def test_thins_to_400_keeping_ends(self):
        pts = [(i / 999.0, 0.5) for i in range(1000)]
        out = core.clean_stroke_uv(pts)
        self.assertEqual(len(out), 400)
        self.assertEqual((out[0], out[-1]), ([0.0, 0.5], [1.0, 0.5]))


class Mapping(unittest.TestCase):
    def test_proposed_member_is_read(self):
        r = core.nudge_response(saddle_member_body(3, 2), stroke_intent())
        f = r["form"]
        self.assertEqual((r["status"], f["kind"], f["n_lamellas"], f["n_strips"], len(f["stations"])),
                         ("proposed", "surface_member", 3, 2, 65))

    def test_bad_member_is_refused(self):
        b = saddle_member_body()
        b["form"]["normals"] = b["form"]["normals"][:10]
        self.assertRaises(ValueError, core.nudge_response, b, stroke_intent())
        b = saddle_member_body()
        b["form"]["stations"][3] = [float("nan"), 0, 0]
        self.assertRaises(ValueError, core.nudge_response, b, stroke_intent())
        b = saddle_member_body()
        b["form"]["n_strips"] = 12
        self.assertRaises(ValueError, core.nudge_response, b, stroke_intent())

    def test_no_core_means_no_answer_never_a_fake_one(self):
        r = core.CoreClient("http://127.0.0.1:9").nudge(stroke_intent(), [])
        self.assertEqual((r["status"], r["form"], r["sentence"]), ("unavailable", None, core.HELPER_DOWN))

    def test_core_refusal_is_said_plainly(self):
        class Refusing(core.CoreClient):
            def _post(self, path, body, timeout):
                raise IOError("core answered 400: intent.kind must be bend or surface_stroke")
        r = Refusing().nudge(stroke_intent(), [])
        self.assertEqual(r["sentence"], core.HELPER_REFUSED)


class SurfaceSession(unittest.TestCase):
    def test_propose_reject_hold_accept(self):
        c = CannedCore(saddle_member_body(3, 1))
        s = core.Session(c)
        s.idle_text = "Draw a line on the surface."
        self.assertEqual(s.headline(), "Draw a line on the surface.")
        self.assertTrue(s.stroke_on_surface(stroke_intent()))
        s.run_sync()
        self.assertEqual(s.phase, "proposed")
        self.assertTrue(s.can_judge())
        self.assertEqual(s.result["steps"][0]["text"], "x")  # no bend snap wording on a surface
        s.reject()
        self.assertEqual(s.phase, "rejected")
        self.assertTrue(s.add_hold("shape"))
        s.run_sync()
        self.assertEqual(c.posts[-1][1]["holds"], ["shape"])
        s.accept()
        self.assertEqual((s.phase, s.record[0]["text"]), ("accepted", "CORE accepted"))

    def test_unavailable_offers_nothing_to_judge(self):
        s = core.Session(core.CoreClient("http://127.0.0.1:9"))
        s.stroke_on_surface(stroke_intent())
        s.run_sync()
        self.assertEqual((s.phase, s.headline(), s.can_judge()), ("unavailable", "No answer yet.", False))
        self.assertEqual(s.subline(), "The helper is not running.")

    def test_a_new_bend_gesture_leaves_surface_mode(self):
        s = core.Session(core.OfflineClient())
        s.stroke_on_surface(stroke_intent())
        s.gesture(core.sag_of(2450.0), 0.0)
        self.assertEqual(s.intent()["radius_mm"], 2450.0)

    def test_surface_words_after_reject(self):
        s = core.Session(CannedCore(saddle_member_body()))
        s.redraw_text, s.shape_word = "Redraw on the surface, or say what to keep.", "line"
        s.stroke_on_surface(stroke_intent())
        s.run_sync()
        s.reject()
        self.assertEqual(s.subline(), "I will not guess again. Redraw on the surface, or say what to keep.")
        self.assertIsNone(s.begin_say(""))   # nothing typed: nothing sent



class WasteOnThePanel(unittest.TestCase):
    """Spec v4: one quiet line, read from the core; hidden whenever the core sends nothing."""

    def test_hidden_without_v4_fields(self):
        s = core.Session(CannedCore(saddle_member_body()))
        s.stroke_on_surface(stroke_intent())
        s.run_sync()
        self.assertEqual(s.waste_line(), "Needs 3 layers")   # no waste sent: none made up

    def test_proposed_then_accepted_tally(self):
        body = saddle_member_body()
        body["checks"] = {"waste_pct": 60.6}
        del body["form"]["n_strips"], body["form"]["strip_mm"]   # v4 drops strips for this kind

        class TallyCore(CannedCore):
            def tally(self):
                return core.tally_of({"members": 3, "billet_m3": 0.1, "part_m3": 0.042, "waste_pct": 58.2})
        s = core.Session(TallyCore(body))
        s.stroke_on_surface(stroke_intent())
        s.run_sync()
        self.assertEqual((s.phase, s.result["form"]["n_strips"]), ("proposed", 1))
        self.assertEqual(s.waste_line(), "Waste 61%  Needs 3 layers")
        s.accept()
        self.assertEqual(s.waste_line(), "Accepted so far: 3 members, 58% waste.")

    def test_never_a_made_up_number(self):
        self.assertIsNone(core.waste_pct({"checks": {"waste_pct": "61"}}))
        self.assertIsNone(core.waste_pct({"checks": {"waste_pct": 140}}))
        self.assertEqual(core.waste_pct({"form": {"checks": {"waste_pct": 12.4}}}), 12.4)
        self.assertIsNone(core.tally_of({"members": 0, "waste_pct": 10}))
        self.assertEqual(core.tally_of({"tally": {"members": 1, "waste_pct": 9.5}}), (1, 9.5))
        self.assertIsNone(core.OfflineClient().tally())


class StartOver(unittest.TestCase):
    def test_start_over_resets_tally_and_taste_and_clears_the_line(self):
        body = saddle_member_body()
        body["checks"] = {"waste_pct": 33.3}

        class TallyCore(CannedCore):
            def tally(self):
                return core.tally_of({"members": 2, "waste_pct": 41.6})
        c = TallyCore(body)
        s = core.Session(c)
        s.stroke_on_surface(stroke_intent())
        s.run_sync()
        s.again_text = "Draw again to try another line."
        s.accept()
        self.assertEqual(s.waste_line(), "Accepted so far: 2 members, 42% waste.")
        self.assertEqual(s.subline(), "Draw again to try another line.")
        self.assertTrue(s.start_over())
        self.assertEqual([path for path, _ in c.posts][-2:], ["/tally/reset", "/taste/reset"])
        self.assertEqual((s.waste_line(), s.record), ("", []))

    def test_bend_waste_zero_is_shown_not_hidden(self):
        r = core.nudge_response({"status": "proposed", "sentence": "x", "steps": [], "deviation_mm": 0.0,
                                 "form": {"radius_mm": 8000.0, "n_lamellas": 1, "lamella_mm": 38.0, "n_strips": 1,
                                          "strip_mm": 89.0, "bend_angle_deg": 0.0, "chord_mm": 2400.0,
                                          "checks": {"waste_pct": 0.0}}},
                                {"member_id": "M1", "chord_mm": 2400.0, "radius_mm": 8000.0, "bend_angle_deg": 0.0})
        s = core.Session(core.OfflineClient())
        s.phase, s.result = "proposed", r
        self.assertEqual(s.waste_line(), "Waste 0%  Needs 1 layer")
        r["waste_pct"] = None
        self.assertEqual(s.waste_line(), "Needs 1 layer")   # a waste figure the core did not send is never made up


class LessWasteLayers(unittest.TestCase):
    def test_more_than_four_thin_layers_is_a_valid_surface_member(self):
        """Regression: the bend kind's 4-layer cap refused less_waste's 5 layers of 8 mm (demo, beat 5)."""
        body = saddle_member_body(5, 1)
        body["form"]["lamella_mm"] = 8.0
        r = core.nudge_response(body, stroke_intent())
        self.assertEqual((r["form"]["n_lamellas"], r["form"]["lamella_mm"]), (5, 8.0))
        body = saddle_member_body(14, 1)
        self.assertEqual(core.nudge_response(body, stroke_intent())["form"]["n_lamellas"], 14)
        body = saddle_member_body(1, 1)
        body["form"]["n_lamellas"] = 0
        self.assertRaises(ValueError, core.nudge_response, body, stroke_intent())


if __name__ == "__main__":
    unittest.main()
