# -*- coding: utf-8 -*-
"""CRV2FAB for Rhino: the Rhino 7 side, split by concern. Entry: gnj_nudge.py."""
MODULES = ['common', 'doc', 'gesture', 'geometry', 'scenes', 'conduit', 'coreproc', 'part', 'system', 'card']  # dependency order: reload in this order

VERSION = "0.9.0"   # spec v9: the plate
# Credits to the creators, in Daniel's words and order (2026-11-15). CREDITS.md at the repo root says the same.
CREDITS = {
    "product": "CRV2FAB",
    "creators": ("Aaryan Dalal", "Daniel Guerra", "Keven Zhao", "Christopher Bergeron", "Adnan Agha"),
    "event": "Done at the AEC Tech Hackathon NYC 2026.",
    "version": VERSION,
    "licence": "MIT",
}


def credits_line():
    """The one line the command line shows when CRV2FAB starts."""
    c = CREDITS
    return "%s %s by %s. %s %s licence." % (c["product"], c["version"], ", ".join(c["creators"]), c["event"],
                                            c["licence"])
