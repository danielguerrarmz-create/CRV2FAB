# -*- coding: utf-8 -*-
"""Gesture, Nudge, Judge for Rhino 7 (IronPython 2.7).

Run in Rhino 7:  _RunPythonScript, pick this file.
Opens the Nudge card (spec v9): draw the path, the start profile and the end profile
over the 2x4 (any you skip stay as they are), press Done, get ONE blue ghost of the
closest buildable plate, accept or reject it.

Rhino 7 Python cannot register a true docked panel without a compiled plug-in,
so the panel is a modeless Eto form owned by the Rhino main window.
"""
# The code lives in the gnj_rhino package beside this file, split by concern (state and the core
# client in gnj_core.py; doc, gesture, geometry, scenes, conduit, coreproc, card, system in
# gnj_rhino/). This file stays the entry: run it with _RunPythonScript, as before.
import os
import sys

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.getcwd()
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Rhino keeps modules between runs: reload everything, dependencies first, to pick up edits.
import gnj_core
import gnj_slots
import gnj_tech
gnj_slots = reload(gnj_slots)
gnj_core = reload(gnj_core)
gnj_tech = reload(gnj_tech)
import gnj_rhino
gnj_rhino = reload(gnj_rhino)
for _name in gnj_rhino.MODULES:
    _full = "gnj_rhino." + _name
    if _full in sys.modules:
        reload(sys.modules[_full])
    else:
        __import__(_full)

from gnj_rhino.card import *  # noqa: F401,F403  (scripts and tests use gnj_nudge.<name>)


def main():
    old = sc.sticky.get(STICKY_KEY)
    if old is not None:
        try:
            old.Close()
        except Exception:
            pass
    Rhino.RhinoApp.WriteLine(gnj_rhino.credits_line())
    scene = choose_scene()
    child = start_core_child()
    panel = NudgePanel(scene, core_child=child)
    panel.Owner = Rhino.UI.RhinoEtoApp.MainWindow
    sc.sticky[STICKY_KEY] = panel
    panel.Show()
    panel.fit()


if __name__ == "__main__":
    main()
