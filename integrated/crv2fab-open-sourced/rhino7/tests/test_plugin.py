# -*- coding: utf-8 -*-
"""The plug-in around the tool (Daniel, 2026-11-15): where the core is found with no personal path in
the code, and the credits, exactly as Daniel gave them. Pure, no Rhino; runs on CPython and on Rhino 7's
IronPython 2.7."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gnj_core as core  # noqa: E402
import gnj_rhino  # noqa: E402

PUB = os.path.join("X:" + os.sep, "pub", "rhino7")          # the published layout: core\ beside rhino7\
LOCAL = os.path.join("X:" + os.sep, "code", "gnj-rhino7")   # a local checkout: gnj-nudge-core beside it


def disk(*dirs, **kw):
    """Fake isdir / isfile over the given core folders (each holding gnj_nudge) and files."""
    have = set(os.path.normpath(os.path.join(d, "gnj_nudge")) for d in dirs)
    files = set(os.path.normpath(f) for f in kw.get("files", ()))
    return (lambda p: os.path.normpath(p) in have), (lambda p: os.path.normpath(p) in files)


class CoreLocation(unittest.TestCase):
    def find(self, env=None, repo=PUB, config=None, dirs=(), files=()):
        isdir, isfile = disk(*dirs, files=files)
        return core.core_location(env or {}, repo, config or {}, isdir, isfile)

    def test_published_layout_finds_core_beside_rhino7(self):
        where = os.path.join("X:" + os.sep, "pub", "core")
        self.assertEqual(self.find(dirs=[where]), (where, "python", "beside"))

    def test_a_local_checkout_finds_gnj_nudge_core_beside_it(self):
        where = os.path.join("X:" + os.sep, "code", "gnj-nudge-core")
        self.assertEqual(self.find(repo=LOCAL, dirs=[where])[0], where)

    def test_the_environment_wins_then_the_installer_config(self):
        env_dir, cfg_dir = os.path.join("Y:" + os.sep, "env"), os.path.join("Y:" + os.sep, "cfg")
        beside = os.path.join("X:" + os.sep, "pub", "core")
        dirs = [env_dir, cfg_dir, beside]
        self.assertEqual(self.find({"GNJ_CORE_DIR": env_dir}, config={"core_dir": cfg_dir}, dirs=dirs)[:3:2],
                         (env_dir, "GNJ_CORE_DIR"))
        self.assertEqual(self.find(config={"core_dir": cfg_dir}, dirs=dirs)[:3:2], (cfg_dir, "config"))

    def test_a_named_folder_without_the_core_is_passed_over(self):
        beside = os.path.join("X:" + os.sep, "pub", "core")
        self.assertEqual(self.find({"GNJ_CORE_DIR": os.path.join("Y:" + os.sep, "empty")}, dirs=[beside])[0], beside)

    def test_nothing_found_says_so(self):
        self.assertEqual(self.find(), (None, "python", "not found"))

    def test_python_from_config_else_the_core_venv_else_path(self):
        beside = os.path.join("X:" + os.sep, "pub", "core")
        venv = os.path.join(beside, ".venv", "Scripts", "python.exe")
        self.assertEqual(self.find(dirs=[beside], files=[venv])[1], venv)
        self.assertEqual(self.find(config={"python": "Z:\\py\\python.exe"}, dirs=[beside], files=[venv])[1],
                         "Z:\\py\\python.exe")
        self.assertEqual(self.find({"GNJ_CORE_PYTHON": "W:\\p.exe"}, config={"python": "Z:\\py\\python.exe"},
                                   dirs=[beside])[1], "W:\\p.exe")

    def test_no_personal_path_in_code_people_run(self):
        """DEBT D-018: the core's location comes from the environment, the installer's config or the
        layout, never from one person's disk."""
        root = os.path.dirname(HERE)
        files = [os.path.join(root, n) for n in os.listdir(root) if n.endswith(".py")]
        for sub in ("gnj_rhino", "samples"):
            files += [os.path.join(root, sub, n) for n in os.listdir(os.path.join(root, sub)) if n.endswith(".py")]
        offenders = [f for f in files if "\\users\\" in open(f).read().lower()]
        self.assertEqual(offenders, [])


class Credits(unittest.TestCase):
    def test_the_creators_in_daniels_order_and_words(self):
        self.assertEqual(list(gnj_rhino.CREDITS["creators"]),
                         ["Aaryan Dalal", "Daniel Guerra", "Keven Zhao", "Christopher Bergeron", "Adnan Agha"])
        self.assertEqual(gnj_rhino.CREDITS["event"], "Done at the AEC Tech Hackathon NYC 2026.")
        self.assertEqual(gnj_rhino.CREDITS["licence"], "MIT")
        self.assertTrue(gnj_rhino.CREDITS["version"])

    def test_the_banner_is_one_line_with_every_name(self):
        line = gnj_rhino.credits_line()
        self.assertNotIn("\n", line)
        for name in gnj_rhino.CREDITS["creators"]:
            self.assertIn(name, line)
        self.assertIn("AEC Tech Hackathon NYC 2026", line)
        self.assertFalse(any(c in line for c in u"\u2014\u2013"))

    def test_credits_md_matches(self):
        text = open(os.path.join(os.path.dirname(HERE), "CREDITS.md")).read()
        self.assertIn(", ".join(gnj_rhino.CREDITS["creators"]), text)
        self.assertIn(gnj_rhino.CREDITS["event"], text)


if __name__ == "__main__":
    unittest.main()
