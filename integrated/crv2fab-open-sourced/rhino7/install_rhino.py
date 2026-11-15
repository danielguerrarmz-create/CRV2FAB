# -*- coding: utf-8 -*-
"""CRV2FAB: one-time setup inside Rhino 7 (Rhino 8 is expected to work, untested).

    _-RunPythonScript "<this folder>\\install_rhino.py"

Adds the command alias CRV2FAB, which runs gnj_nudge.py from this folder. Rhino keeps aliases in the
scheme it is running, so run this in the Rhino you use. Run it again after moving the folder.
There is no toolbar button: a Rhino 7 toolbar needs its own .rui file, which this setup does not write.
"""
import os

import Rhino

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.getcwd()
ALIAS = "CRV2FAB"
SCRIPT = os.path.join(HERE, "gnj_nudge.py")


def macro():
    return '_-RunPythonScript "%s"' % SCRIPT


def install():
    """Add or update the alias. Returns its macro."""
    aliases = Rhino.ApplicationSettings.CommandAliasList
    m = macro()
    if aliases.IsAlias(ALIAS):
        aliases.SetMacro(ALIAS, m)
    else:
        aliases.Add(ALIAS, m)
    Rhino.RhinoApp.WriteLine("CRV2FAB: type CRV2FAB to open the card. It runs %s" % SCRIPT)
    return m


if __name__ == "__main__":
    install()
