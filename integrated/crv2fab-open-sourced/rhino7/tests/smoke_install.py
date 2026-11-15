# -*- coding: utf-8 -*-
"""Install smoke, in a GNJSmoke Rhino 7 only (tests/run_install_smoke.ps1): install_rhino.py adds the
CRV2FAB alias with the right macro, the logo assets load, the core is found without a personal path.
The alias is put back as it was afterwards. The alias is never run here: it would open the card, which
starts a core on the user's port when none answers."""
import os
import sys
import traceback

OUT = os.environ.get("GNJ_SMOKE_DIR", os.getcwd())
log = open(os.path.join(OUT, "smoke_install.log"), "w")


def say(*parts):
    log.write(" ".join("%s" % (p,) for p in parts) + "\n")
    log.flush()


try:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    sys.path.insert(0, repo)
    import System
    import Rhino
    import install_rhino
    import gnj_nudge as gn
    aliases = Rhino.ApplicationSettings.CommandAliasList
    had = aliases.IsAlias(install_rhino.ALIAS)
    before = aliases.GetMacro(install_rhino.ALIAS) if had else None
    m = install_rhino.install()
    got = aliases.GetMacro(install_rhino.ALIAS)
    alias_ok = aliases.IsAlias(install_rhino.ALIAS) and got == m and os.path.isfile(install_rhino.SCRIPT) \
        and install_rhino.SCRIPT == os.path.join(repo, "gnj_nudge.py")
    say("alias", install_rhino.ALIAS, "->", got, "| was there before", had, "| ok", alias_ok)
    if had:
        aliases.SetMacro(install_rhino.ALIAS, before)
    else:
        aliases.Delete(install_rhino.ALIAS)
    say("alias put back:", aliases.IsAlias(install_rhino.ALIAS) == had)
    icon = gn.app_icon()
    icon_ok = os.path.isfile(gn.ICON_FILE) and not icon.Equals(System.Drawing.SystemIcons.Application) \
        and gn.window_icon() is not None
    say("icon", gn.ICON_FILE, "| tab icon %dx%d" % (icon.Width, icon.Height), "| window icon", gn.window_icon() is not None,
        "| ok", icon_ok)
    say("core", gn.CORE_DIR, "| python", gn.CORE_PYTHON, "| found by", gn.CORE_FOUND)
    say("credits:", gn.gnj_rhino.credits_line())
    say("INSTALL SMOKE %s" % ("OK" if alias_ok and icon_ok and aliases.IsAlias(install_rhino.ALIAS) == had else "FAILED"))
except Exception:
    say("INSTALL SMOKE FAILED")
    say(traceback.format_exc())
finally:
    log.close()
