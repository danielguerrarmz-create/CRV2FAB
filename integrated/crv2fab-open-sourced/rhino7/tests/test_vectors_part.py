# -*- coding: utf-8 -*-
"""Round trip of kind part (spec v6) against the core's own tests/vectors_part.json.

CPython only. Skips when that core or its vectors are not there. The core runs in-process on a
free port, no model, record in a temp folder: never port 8742. GNJ_CORE_PART_DIR picks the core
(the part branch's worktree until it merges into main).
"""
import json
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import gnj_core as core  # noqa: E402
import gnj_tech as tech  # noqa: E402

CORE_DIR = os.environ.get("GNJ_CORE_PART_DIR", r"C:\Users\danie\code\_worktrees\gnj-nudge-core--part")
VECTORS = os.path.join(CORE_DIR, "tests", "vectors_part.json")
# Cases where the core's server disagrees with its own vectors file. Each must STILL disagree: when the
# core is fixed this test goes red, and the entry comes out.
KNOWN_CORE_DISCREPANCY = {
    "v_part_split_ok": "core d3781d3: POST /nudge with holds [split_ok] answers one curve of 42 layers; the file says 2 pieces",
}


@unittest.skipUnless(sys.version_info[0] == 3 and os.path.exists(VECTORS), "core vectors_part.json not present")
class CoreVectorsPart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.dont_write_bytecode = True
        sys.path.insert(0, CORE_DIR)
        for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND"):
            os.environ.pop(k, None)
        for name in [m for m in sys.modules if m == "gnj_nudge" or m.startswith("gnj_nudge.")]:
            del sys.modules[name]   # another test may have loaded a different core
        from gnj_nudge import server
        cls.tmp = tempfile.mkdtemp(prefix="gnj-part-")
        cls.srv = server.make_server(port=0, client=None, record_path=os.path.join(cls.tmp, "record.jsonl"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.client = core.CoreClient("http://127.0.0.1:%d" % cls.srv.server_address[1])
        with open(VECTORS) as f:
            cls.cases = json.load(f)["cases"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        sys.path.remove(CORE_DIR)
        for name in [m for m in sys.modules if m == "gnj_nudge" or m.startswith("gnj_nudge.")]:
            del sys.modules[name]

    def test_each_part_case_round_trips(self):
        for c in self.cases:
            intent = c["request"]["intent"]
            mine = core.part_intent(intent["points"], intent["volume_mm3"], intent.get("member_id", "P1"))
            got = self.client.nudge(mine, c["request"].get("holds") or [])
            want = c["expected"]
            with self.subTest(case=c["name"]):
                self.assertTrue(got["via_core"], self.client.last_error)
                if c["name"] in KNOWN_CORE_DISCREPANCY:
                    self.assertNotEqual(got["sentence"], want["sentence"],
                                        "fixed in the core: remove it from KNOWN_CORE_DISCREPANCY")
                    continue
                self.assertEqual(got["status"], want["status"])
                self.assertEqual(got["sentence"], want["sentence"])
                if want["status"] != "proposed":
                    self.assertIsNone(got["form"])
                    continue
                f = got["form"]
                self.assertEqual(f["n_pieces"], want["n_pieces"])
                self.assertAlmostEqual(got["waste_pct"], want["waste_pct"], delta=0.5)
                self.assertEqual([round(x["at_mm"], 1) for x in f["cuts"]], want["cuts_at_mm"])
                self.assertEqual(len(f["cuts"]), f["n_pieces"] - 1)
                self.assertTrue(f["billet"]["outline"])
                rows = dict(tech.check_lines(got))   # SPEC_V9_UI: a part shows the check lines it has
                self.assertNotIn("Pieces", rows)   # SPEC_V9_CARD_SLOTS: it lives in Made as
                self.assertTrue(rows["Bend"].startswith(("Pass", "Fail")) and rows["Machine"].startswith(("Pass", "Fail")))
                self.assertNotIn("Grain", rows)   # plate kind only
                if f["n_pieces"] > 1:
                    self.assertEqual(rows["Made as"], "%d pieces joined end to end" % f["n_pieces"])


class PartIntent(unittest.TestCase):
    def test_shape_and_rounding(self):
        it = core.part_intent([(1.234, 2.0, 3.0)] * 300, 1234.56)
        self.assertEqual((it["kind"], it["member_id"], it["points"][0], it["volume_mm3"]),
                         ("part", "P1", [1.2, 2.0, 3.0], 1234.6))

    def test_no_core_means_no_answer(self):
        r = core.CoreClient("http://127.0.0.1:9").nudge(core.part_intent([(0, 0, 0)] * 300, 1.0), [])
        self.assertEqual((r["status"], r["sentence"]), ("unavailable", core.HELPER_DOWN))

    def test_a_core_without_parts_says_so(self):
        class Old(core.CoreClient):
            def _post(self, path, body, timeout):
                raise IOError("core answered 400: intent.kind must be bend or surface_stroke")
        r = Old().nudge(core.part_intent([(0, 0, 0)] * 300, 1.0), [])
        self.assertEqual(r["sentence"], core.PART_REFUSED)

    def test_accepting_a_part_bakes_nothing_and_records_its_object(self):
        body = {"status": "proposed", "sentence": "Buildable as modelled.", "steps": [], "source": "rules",
                "form": {"kind": "part_plan", "n_pieces": 1, "cuts": [], "axis": {"length_mm": 6283.0},
                         "pieces": [{"n_lamellas": 11, "lamella_mm": 38.0}],
                         "billet": {"outline": [[[0, 0, 0], [1, 0, 0]]]}, "checks": {"waste_pct": 4.3}}}

        class Canned(core.CoreClient):
            def _post(self, path, body_, timeout):
                return {"formal": "CORE"} if path == "/judge" else body
        s = core.Session(Canned())
        s.check_part(core.part_intent([(0, 0, 0)] * 300, 1.0))
        s.run_sync()
        self.assertEqual((s.phase, s.waste_line()), ("proposed", "Waste 4%  Needs 11 layers"))
        r = s.accept()
        s.add_member(r, ["the-designers-object"])
        self.assertEqual(tech.member_cells(s.members[0]), ("M1", "own solid", "6.28 m", "11 of 38 mm", "4%"))
        self.assertEqual(s.members[0]["object_ids"], ["the-designers-object"])
        self.assertEqual(tech.gesture_summary(s).startswith("Your own part"), True)


if __name__ == "__main__":
    unittest.main()
