# -*- coding: utf-8 -*-
"""Shared imports, look and constants, and small Eto helpers."""
import math
import os
import sys
import threading
import time

import System
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Eto.Drawing as drawing
import Eto.Forms as forms

import gnj_core as core
import gnj_slots as slots
import gnj_tech as tech


# ---------------------------------------------------------------- look
GHOST_COLOR = System.Drawing.Color.FromArgb(38, 104, 214)    # the proposal blue: the ghost's edges
# The ghost reads as a ghost (Daniel, 2026-11-15): a light translucent fill, crisp blue edges, and the
# member under it and the dashed drawing over it both stay visible. Accepted timber stays opaque.
GHOST_FILL = System.Drawing.Color.FromArgb(70, 130, 230)
GHOST_TRANSPARENCY = 0.80                                     # 0 opaque, 1 invisible
GHOST_EDGE_PX = 2
INTENT_PX = 2                                                 # the dashed drawing, over the ghost
GHOST_EDGE_COLOR = System.Drawing.Color.FromArgb(20, 28, 40)  # glue lines and the billet outline: dark
EXISTING_COLOR = System.Drawing.Color.FromArgb(160, 160, 160)
CONFLICT_TEXT = drawing.Color.FromArgb(169, 54, 38, 255)

# Display only: the ghost is drawn 0.5 mm wider each side so its side faces do not
# flicker against the grey member's coplanar faces. Accept bakes the exact 89 mm.
GHOST_DISPLAY_INFLATE_MM = 0.5
GLUE_DISPLAY_INFLATE_MM = 0.8

LIFT_MM = 800.0  # the demo member sits this far above the world XY plane

LAYER_ROOT = "GNJ"
LAYER_EXISTING = "GNJ::Existing"
LAYER_REFERENCE = "GNJ::Reference"
LAYER_GESTURE = "GNJ::Gesture"
LAYER_BUILDABLE = "GNJ::Buildable"
LAYER_BILLETS = "GNJ::Buildable::Billets"
# Billets, one per piece, like the pink boxes of Daniel's reference image (2026-11-15). Rhino 7 conduit
# lines are whole pixels, so the 1.5 px asked for is drawn at 1: the ghost's 2 px edges stay on top.
BILLET_FILL = System.Drawing.Color.FromArgb(230, 80, 130)
BILLET_TRANSPARENCY = 0.75
BILLET_EDGE = System.Drawing.Color.FromArgb(200, 50, 100)
BILLET_EDGE_PX = 1
# A baked billet is its edges only, thin pink, in every view mode (Shaded, Rendered...): the accepted
# timber reads fully inside it, as in Daniel's reference (2026-11-15; Ghosted swallowed the member).
BILLET_DISPLAY_MODE = "Wireframe"
TIMBER_COLOR = System.Drawing.Color.FromArgb(196, 164, 112)   # accepted members; blue is the proposal only
CUT_COLOR = System.Drawing.Color.FromArgb(20, 28, 40)
STROKE_COLOR = System.Drawing.Color.FromArgb(30, 30, 30)     # strokes and the read outline: thin, dark, never blue
PRIMARY_FILL = drawing.Color.FromArgb(30, 30, 30, 255)       # primary buttons: filled dark, never blue
PRIMARY_OFF = drawing.Color.FromArgb(214, 214, 214, 255)     # ...and light grey with grey text when disabled
STICKY_KEY = "gnj_nudge_panel"
PANEL_WIDTH = 280
END_PLANE_GRID_MM = 25.0     # the end plane's grid while a profile is drawn: 25 mm squares,
END_PLANE_GRID_LINES = 12    # 12 each way from the end (300 mm), about a profile's size
TECH_MAX_HEIGHT = 420     # the Technical section scrolls inside itself past this
CURVATURE_SAMPLES = 40    # per direction, for the curvature colouring
OVERLAY_OPACITY = 0.55    # the colour maps, drawn shaded over the surface
OVERLAY_LIFT_MM = 6.0     # ...and lifted clear of its render mesh
# The core's folder and the Python that runs it: GNJ_CORE_DIR, the config install.ps1 writes beside
# gnj_nudge.py, or the layout (gnj_core.core_location). None when it is not found: the card says so.
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(PACKAGE_DIR)
CORE_DIR, CORE_PYTHON, CORE_FOUND = core.core_location(os.environ, REPO_DIR, core.read_config(REPO_DIR))

# The logo: one asset folder; swapping the art is a file replacement (crv2fab.ico: 16, 24, 32, 48 px;
# crv2fab.png). A missing or unreadable file falls back to Rhino's default icon, never an error.
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")
ICON_FILE = os.path.join(ASSETS_DIR, "crv2fab.ico")


def app_icon():
    """System.Drawing.Icon for the docked panel's tab."""
    try:
        if os.path.isfile(ICON_FILE):
            return System.Drawing.Icon(ICON_FILE)
    except Exception:
        pass
    return System.Drawing.SystemIcons.Application


def window_icon():
    """Eto icon for a window's title bar, or None to keep the default."""
    try:
        if os.path.isfile(ICON_FILE):
            return drawing.Icon(ICON_FILE)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- panel

def _label(text="", bold=False, size=None, muted=False):
    lbl = forms.Label()
    lbl.Text = text
    lbl.Wrap = forms.WrapMode.Word
    if bold or size:
        lbl.Font = drawing.Font(drawing.SystemFont.Bold if bold else drawing.SystemFont.Default, size or 9)
    if muted:
        lbl.TextColor = drawing.Colors.Gray
    return lbl


def _button(text, handler, height=None):
    b = forms.Button()
    b.Text = text
    b.Click += handler
    if height:
        b.Height = height
    return b


class PlainLink(forms.Label):
    """A link as SPEC_V9_UI asks: plain text in the body colour, underlined only on hover, never blue.
    click() does what a click does (tests and other views call it)."""

    def __new__(cls, *args, **kwargs):
        return forms.Label.__new__(cls)

    def __init__(self, text, handler):
        self.Text = text
        self.handler = handler
        self.Cursor = forms.Cursors.Pointer
        self.Wrap = forms.WrapMode.Word
        self.normal = drawing.Font(drawing.SystemFont.Default, 9)
        self.hover = drawing.Font(drawing.SystemFont.Default, 9, drawing.FontDecoration.Underline)
        self.Font = self.normal
        self.MouseEnter += lambda s, e: setattr(self, "Font", self.hover if self.Enabled else self.normal)
        self.MouseLeave += lambda s, e: setattr(self, "Font", self.normal)
        self.MouseDown += lambda s, e: self.click()
        self.set_enabled(True)

    def set_enabled(self, on):
        self.Enabled = bool(on)
        self.TextColor = drawing.SystemColors.ControlText if on else drawing.Colors.Gray

    def click(self):
        if self.Enabled:
            self.handler(self, None)


def _row(*controls):
    t = forms.TableLayout()
    t.Spacing = drawing.Size(6, 0)
    t.Rows.Add(forms.TableRow(*[forms.TableCell(c, True) for c in controls]))
    return t

__all__ = [_n for _n in dir() if not _n.startswith("__")]  # every name, underscores too
