# -*- coding: utf-8 -*-
"""Run under Rhino 7's own IronPython 2.7 engine, outside Rhino (see run_ipy.ps1).

1. Compiles every .py in the repo as IronPython 2.7 (catches Python 3 only syntax).
2. Runs tests/test_core.py and tests/test_surface_v3.py.
Writes to the log path given in GNJ_LOG.
"""
import os
import sys
import unittest

REPO = os.environ["GNJ_REPO"]
LOG = os.environ["GNJ_LOG"]
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

out = open(LOG, "w")
out.write("IronPython %s\n" % sys.version)
bad = 0
for folder in (REPO, os.path.join(REPO, "tests"), os.path.join(REPO, "gnj_rhino")):
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            path = os.path.join(folder, name)
            try:
                compile(open(path).read(), path, "exec")
                out.write("compiles: %s\n" % name)
            except SyntaxError as e:
                bad += 1
                out.write("SYNTAX ERROR: %s: %s\n" % (name, e))

import test_core  # noqa: E402
import test_surface_v3  # noqa: E402
import test_tech  # noqa: E402
import test_photo  # noqa: E402
import test_plate  # noqa: E402
import test_slots  # noqa: E402
import test_plugin  # noqa: E402
suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_core, test_surface_v3, test_tech, test_photo, test_plate, test_slots, test_plugin)])
result = unittest.TextTestRunner(stream=out, verbosity=1).run(suite)
out.write("\nRESULT syntax_errors=%d tests=%d failures=%d errors=%d\n"
          % (bad, result.testsRun, len(result.failures), len(result.errors)))
out.close()
