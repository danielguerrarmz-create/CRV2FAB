# -*- coding: utf-8 -*-
"""Round trip against the real core, using the core's own tests/vectors_v4.json (spec v4).

CPython only. Skips when the core or its vectors are not there. Starts the core in-process on a free
port with no model (deterministic solver), so it never touches port 8742 or a running core, and
writes its record to a temp folder. Tolerances follow the file's note: billet sizes come from an
optimiser, so a few mm on sizes and half a percent on waste.
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

CORE_DIR = os.environ.get("GNJ_CORE_DIR", r"C:\Users\danie\code\gnj-nudge-core")
VECTORS = os.path.join(CORE_DIR, "tests", "vectors_v4.json")
SIZE_MM, WASTE_PCT, TENTH = 3.0, 0.5, 0.11


def _load():
    with open(VECTORS) as f:
        raw = json.load(f)
    return raw["surface"], raw["cases"]


@unittest.skipUnless(sys.version_info[0] == 3 and os.path.exists(VECTORS), "core vectors_v4.json not present")
class CoreVectorsV4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.dont_write_bytecode = True
        sys.path.insert(0, CORE_DIR)
        for k in ("ANTHROPIC_API_KEY", "GNJ_BACKEND"):
            os.environ.pop(k, None)
        from gnj_nudge import server
        cls.tmp = tempfile.mkdtemp(prefix="gnj-vectors-")
        cls.srv = server.make_server(port=0, client=None, record_path=os.path.join(cls.tmp, "record.jsonl"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.client = core.CoreClient("http://127.0.0.1:%d" % cls.srv.server_address[1])
        cls.surface, cls.vectors = _load()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_our_saddle_grid_is_the_core_reference_grid(self):
        ours = core.grid_from(core.saddle_point)
        self.assertEqual((ours["nu"], ours["nv"]), (self.surface["nu"], self.surface["nv"]))
        for a, b in zip(self.surface["points"], ours["points"]):
            for p, q in zip(a, b):
                self.assertAlmostEqual(p, q, places=2)

    def test_each_vector_round_trips_through_our_mapping(self):
        self.assertTrue(self.vectors)
        for v in self.vectors:
            intent = dict(v["request"]["intent"])
            intent["surface"] = core.grid_from(core.saddle_point)  # ours, not the file's: proven equal above
            want = v["expected"]
            got = self.client.nudge(intent, v["request"].get("holds") or [])
            with self.subTest(case=v["name"]):
                self.assertTrue(got["via_core"], self.client.last_error)
                self.assertEqual(got["status"], want["status"])
                self.assertEqual(got["sentence"], want["sentence"])          # shown verbatim
                self.assertEqual(got["trimmed"], want["trimmed"])
                if want["status"] != "proposed":
                    self.assertIsNone(got["form"])
                    continue
                f = got["form"]
                self.assertEqual(f["n_lamellas"], want["n_lamellas"])
                self.assertEqual(f["n_strips"], 1)                            # v4: no strips on a surface
                self.assertEqual(f["straight_billet"], want["straight_billet"])
                self.assertAlmostEqual(f["length_mm"], want["length_mm"], delta=TENTH)
                self.assertAlmostEqual(got["deviation_mm"], want["deviation_mm"], delta=TENTH)
                self.assertAlmostEqual(got["waste_pct"], want["waste_pct"], delta=WASTE_PCT)
                b, wb = f["billet"], want["billet"]
                self.assertEqual(b["mode"], wb["mode"])
                for k in ("length_mm", "width_mm", "depth_mm"):
                    self.assertAlmostEqual(b[k], wb[k], delta=SIZE_MM)
                if wb["radius_mm"] is None:
                    self.assertIsNone(b["radius_mm"])
                else:
                    self.assertAlmostEqual(b["radius_mm"], wb["radius_mm"], delta=SIZE_MM)
                self.assertTrue(b["outline"], "the billet outline is drawn while Why is open")
                self.assertEqual(len(f["stations"]), len(f["normals"]))


if __name__ == "__main__":
    unittest.main()
