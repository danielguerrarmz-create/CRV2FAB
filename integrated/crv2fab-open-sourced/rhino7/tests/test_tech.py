# -*- coding: utf-8 -*-
"""The Technical view's content (gnj_tech.py): pure, no Rhino. Responses as the core sends them today."""
from __future__ import division

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gnj_tech as tech  # noqa: E402

SURFACE_SENT = {
    "status": "proposed", "deviation_mm": 0.0, "source": "rules",
    "form": {"kind": "surface_member", "n_lamellas": 3, "lamella_mm": 19.0, "straight_billet": False,
             "billet": {"mode": "arc", "length_mm": 2142.5, "width_mm": 89.0, "depth_mm": 57.0, "radius_mm": 3091.2},
             "checks": {"bend": {"ok": True, "tightest_radius_mm": 3062.7, "ratio": 161.2, "limit": 125.0, "applies": True},
                        "machine": {"ok": True, "name": "INTERNAL MACHINE NAME", "need_mm": [239.1, 89.0],
                                    "opening_mm": [1200.0, 280.0], "orientation": "flat"},
                        "waste_pct": 33.3, "waste_rounding_pct": 30.9},
             "max_twist_deg_per_m": 0.0}}
BEND_SENT = {
    "status": "proposed", "deviation_mm": 0.0,
    "form": {"radius_mm": 2450, "n_lamellas": 4, "lamella_mm": 9.5, "n_strips": 1, "strip_mm": 89.0,
             "checks": {"waste_pct": 0.0, "waste_rounding_pct": 0.0},
             "billet": {"mode": "arc", "length_mm": 2508.1, "width_mm": 89.0, "depth_mm": 38.0, "radius_mm": 2450.0}}}


def plate(name):
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fixtures", "plate_bodies.json")) as fh:
        return json.load(fh)["bodies"][name]


class CheckLines(unittest.TestCase):
    """SPEC_V9_UI 'This proposal', now 'This member' (SPEC_V9_CARD_SLOTS words). Replaces the v6 readout: no Twist row, no 'Moved from your line'
    (deviation_mm is 'Largest move', hidden at 0), no 'inputs in force' fallback."""

    def test_an_eased_plate(self):
        self.assertEqual(tech.check_lines({"sent": plate("path_too_tight")}), [
            ("Bend", "Pass, layers bend to 1.38 m, limit 1.38 m"),
            ("Machine", "Pass, billet 725 x 89 mm, opening 1200 x 280 mm"),
            ("Grain", "Pass, 0 degrees off the path, limit 10"),
            ("Made as", "pressed in one curve from 5 layers of 11 mm"),
            ("Waste", "31%"), ("Largest move", "331 mm")])

    def test_stock_and_pieces(self):
        rows = dict(tech.check_lines({"sent": plate("no_strokes")}))
        self.assertEqual((rows["Made as"], rows["Bend"], rows["Machine"]), ("one piece as it comes", "Pass, no pressing", "Pass, no milling"))
        self.assertNotIn("Largest move", rows)   # hidden at 0
        rows = dict(tech.check_lines({"sent": plate("twist_50_splits")}))
        self.assertEqual(rows["Made as"], "2 pieces joined end to end")
        self.assertNotIn("Pieces", rows)   # it lives in Made as
        self.assertTrue(rows["Machine"].startswith("Pass, billet 595 x 193 mm, opening 1200 x 280 mm"))

    def test_a_surface_shows_the_lines_it_has(self):
        rows = dict(tech.check_lines({"sent": SURFACE_SENT}))
        self.assertEqual(rows["Bend"], "Pass, layers bend to 3.06 m, limit 2.38 m")
        self.assertEqual(rows["Machine"], "Pass, billet 239 x 89 mm, opening 1200 x 280 mm")
        self.assertEqual(rows["Made as"], "pressed in one curve from 3 layers of 19 mm")
        self.assertNotIn("Grain", rows)   # plate kind only
        for gone in ("Twist", "Moved from your line", "Opening needed", "Tightest layer bends to"):
            self.assertNotIn(gone, rows)
        self.assertFalse(hasattr(tech, "inputs_in_force") or hasattr(tech, "readout"))

    def test_members_kind_uses_the_glossary(self):
        for old, new in (("plate", "drawn"), ("plate, 2 pieces", "drawn, 2 pieces"), ("surface", "on surface"),
                         ("part", "own solid"), ("part, 3 pieces", "own solid, 3 pieces"), ("bend", "bend")):
            self.assertEqual(tech.member_kind(old), new)

    def test_the_machine_name_is_never_shown(self):
        self.assertNotIn("INTERNAL", repr(tech.check_lines({"sent": SURFACE_SENT})))

    def test_bend_shows_only_what_it_has(self):
        rows = dict(tech.check_lines({"sent": BEND_SENT}))
        self.assertEqual(rows["Made as"], "pressed in one curve from 4 layers of 9.5 mm")
        self.assertNotIn("Bend", rows)   # the bend kind does not send a bend check: not computed here
        self.assertNotIn("Machine", rows)

    def test_nothing_sent_nothing_shown(self):
        self.assertEqual(tech.check_lines(None), [])
        self.assertEqual(tech.check_lines({"sent": {"status": "conflict", "form": None}}), [])


class Settings(unittest.TestCase):
    def test_round_trip_of_the_boxes(self):
        self.assertEqual(tech.format_setting("opening_mm", [1200, 280]), "1200 x 280")
        self.assertEqual(tech.format_setting("lam_options_mm", [38.0, 17.0, 11.0]), "38, 17, 11")
        self.assertEqual(tech.parse_setting("lam_options_mm", "11, 38 17"), [38.0, 17.0, 11.0])
        self.assertEqual(tech.parse_setting("thickness_mm", "19"), 19.0)
        self.assertEqual(tech.parse_setting("opening_mm", " 1200 X 280 "), [1200.0, 280.0])
        self.assertIsNone(tech.parse_setting("max_waste_pct", "off"))
        self.assertEqual(tech.parse_setting("lam_ratio", "125"), 125.0)

    def test_bad_input_says_why(self):
        self.assertRaises(ValueError, tech.parse_setting, "opening_mm", "1200")
        self.assertRaises(ValueError, tech.parse_setting, "max_waste_pct", "140")
        self.assertRaises(ValueError, tech.parse_setting, "allowance_mm", "-2")
        self.assertRaises(ValueError, tech.parse_setting, "lam_ratio", "abc")
        self.assertRaises(ValueError, tech.parse_setting, "thickness_mm", "0")
        self.assertRaises(ValueError, tech.parse_setting, "lam_options_mm", "38, thin")

    def test_only_changes_are_posted(self):
        current = {"max_waste_pct": None, "allowance_mm": 0, "lam_ratio": 125, "opening_mm": [1200, 280]}
        texts = {"max_waste_pct": "40", "allowance_mm": "0", "lam_ratio": "125", "opening_mm": "1200 x 280"}
        self.assertEqual(tech.changed_settings(current, texts), {"max_waste_pct": 40.0})


class Curvature(unittest.TestCase):
    def test_four_classes_with_the_100_m_rule(self):
        k3m, k200m = 1 / 3000.0, 1 / 200000.0
        self.assertEqual(tech.classify(0.0, 0.0), "flat")
        self.assertEqual(tech.classify(k200m, -k200m), "flat")      # both radii above 100 m
        self.assertEqual(tech.classify(k3m, k200m), "single")
        self.assertEqual(tech.classify(k3m, k3m), "dome")
        self.assertEqual(tech.classify(k3m, -k3m), "saddle")
        self.assertEqual(tech.classify(-k3m, -k3m), "dome")

    def test_boundary_sits_on_100_m(self):
        self.assertEqual(tech.classify(1 / 99999.0, 0.0), "single")
        self.assertEqual(tech.classify(1 / 100001.0, 0.0), "flat")


class SystemPanelContent(unittest.TestCase):
    def test_drawing_summary_in_plain_words(self):
        """SPEC_V9_UI Inputs > Drawing: what the last Done sent, stroke by stroke (the bend wording is gone)."""
        import gnj_core as core
        s = core.Session(core.OfflineClient())
        self.assertEqual(tech.gesture_summary(s), "")
        s.begin_drawing("path")
        s.end_drawing("path", [[0.0, 0.0, 0.0], [2400.0, 0.0, 0.0]])
        # every stroke shows at once, before Done (v9 smoke: the panel said "none yet" beside a drawn path)
        self.assertEqual(tech.gesture_summary(s), "Path drawn, Start not drawn, End not drawn")
        s.begin_drawing("end")
        s.end_drawing("end", [[2400.0, -100.0, 0.0], [2400.0, 100.0, 0.0]])
        s.done()
        self.assertEqual(tech.gesture_summary(s), "Path drawn, Start kept as is, End drawn")
        s.stroke_on_surface(core.surface_intent(core.grid_from(core.saddle_point), [[0.15, 0.5], [0.85, 0.5]]))
        self.assertEqual(tech.gesture_summary(s), "A line across the surface.")
        s.result = {"sent": {"form": {"length_mm": 1830.0}}}
        self.assertEqual(tech.gesture_summary(s), "A line across the surface, 1.83 m long.")
        self.assertFalse(hasattr(tech, "span_words"))

    def test_model_name_without_formula(self):
        self.assertEqual(tech.model_name("Reference saddle, z = 800 + (x^2 - y^2) / 6000 mm"), "Reference saddle")
        self.assertEqual(tech.model_name(""), "none")

    def test_radius_gradient(self):
        self.assertIsNone(tech.tightest_radius_mm(1 / 200000.0, 0.0))
        self.assertAlmostEqual(tech.tightest_radius_mm(1 / 3000.0, -1 / 5000.0), 3000.0)
        last = len(tech.RADIUS_RGB) - 1
        self.assertEqual(tech.radius_bin(900.0, 1375.0), 0)
        self.assertEqual(tech.radius_bin(None, 1375.0), last)
        self.assertEqual(tech.radius_bin(99999.0, 1375.0), last - 1)
        self.assertTrue(0 < tech.radius_bin(3000.0, 1375.0) < last)
        self.assertEqual(len(tech.radius_legend(1375.0)), len(tech.RADIUS_RGB))
        self.assertIn("no limit known yet", tech.radius_legend(None)[0][1])

    def test_a_value_is_never_cut_short(self):
        """SPEC_V9_UI: values wrap, never an ellipsis. The v6 fit_text cutter is gone."""
        self.assertFalse(hasattr(tech, "fit_text"))
        text = repr(tech.check_lines({"sent": plate("path_too_tight")}))
        self.assertNotIn(u"\u2026", text)

    def test_member_rows_from_the_accepted_answer(self):
        import gnj_core as core
        s = core.Session(core.OfflineClient())
        s.stroke_on_surface({"kind": "surface_stroke"})
        s.add_member({"sent": SURFACE_SENT, "waste_pct": 33.3}, ["id-1", "id-2"])
        self.assertEqual(tech.member_cells(s.members[0]), ("M1", "on surface", "", "3 of 19 mm", "33%"))
        self.assertEqual(s.members[0]["object_ids"], ["id-1", "id-2"])
        s.start_over()
        self.assertEqual(s.members, [])


class LiveSettings(unittest.TestCase):
    """The core's GET /settings at main 1983b42: {settings, sources, machines}."""
    BODY = {"settings": {"lam_options_mm": [38.0, 17.0, 11.0], "lam_ratio": 125.0, "allowance_mm": 0.0,
                         "max_waste_pct": None, "opening_mm": [1200.0, 280.0], "max_length_mm": 18000.0,
                         "max_pieces": 4, "machine": None},
            "sources": {"lam_ratio": "sc_glulam default, confirm with a supplier"}, "machines": []}

    def test_values_are_unwrapped(self):
        import gnj_core as core
        test = self

        class Canned(core.CoreClient):
            def _get(self, path, timeout=3.0):
                return test.BODY
        c = Canned("http://canned")
        s = c.settings()
        self.assertEqual((s["lam_ratio"], s["max_pieces"]), (125.0, 4))
        self.assertEqual(c.settings_sources["lam_ratio"], "sc_glulam default, confirm with a supplier")

    def test_only_real_changes_are_posted(self):
        current = self.BODY["settings"]
        texts = {"max_waste_pct": "", "allowance_mm": "0", "lam_ratio": "125", "opening_mm": "1200 x 280",
                 "max_length_mm": "18000", "max_pieces": "4"}
        self.assertEqual(tech.changed_settings(current, texts), {})
        texts["max_waste_pct"], texts["max_pieces"] = "20", "3"
        self.assertEqual(tech.changed_settings(current, texts), {"max_waste_pct": 20.0, "max_pieces": 3})
        self.assertRaises(ValueError, tech.parse_setting, "max_pieces", "2.5")

    def test_the_core_says_why_a_value_is_refused(self):
        self.assertEqual(tech.core_reason("core answered 400: lam_ratio must be between 10 and 1000"),
                         "lam_ratio must be between 10 and 1000")


if __name__ == "__main__":
    unittest.main()
