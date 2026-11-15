# Status: standalone, pending integration

The glulam slicer works on its own today: Rhino 8 + Grasshopper, axis curves in, CNC-ready glulam
beams, realistic render meshes and quantity reports out (see `README.md` in this folder). It is **not
yet connected** to the CRV²FAB plugin in `integrated/crv2fab-open-sourced/`. It is here for further
development, and for anyone who wants to integrate it.

## How the two fit together

| | CRV²FAB plugin (`crv2fab-open-sourced`) | Glulam slicer (this folder) |
|---|---|---|
| Role | Design intent: draw, get one buildable ghost, accept or reject | Fabrication and visualisation: slice an accepted member into real boards, pieces, blocks and render meshes |
| Runs on | Rhino 7 (tested), IronPython script plus a local Python rules service | Rhino 8, Grasshopper, built-in Python 3 components |
| Input | Strokes, your own model, a photo, words | Axis curves, with per-beam User Text (`W`, `H`, `RotStart`, `RotEnd`, `MaxBlank`, `Wood`, `EndGrain`) |
| Output | An accepted member (closed polysurface) with user text, billet boxes per piece | Pieces labelled B1-L3-P2-S4, raw CNC blocks, a bill of materials and cut list (CSV / JSON), textured meshes |
| Units | mm, Z up | mm (Rhino document units) |

The natural seam is **the plugin's accepted member becomes the slicer's beam**. The plugin's
centreline becomes the axis curve, its section becomes `W` and `H`, and its end profile rotations
become `RotStart` and `RotEnd`, written as User Text on the curve. The slicer needs nothing else to
run.

## Open questions before integrating

1. **Two billet logics.** The plugin decides buildability with the team's `sc_glulam` maths (one pressed
   billet per piece, layer bend R/t 125, a 1200 x 280 mm opening). The slicer lays out real boards and
   splits raw blocks under a maximum waste %. Per `AGENTS.md`, pick which one decides what in
   `docs/DECISIONS.md`. Do not blend them. A likely split is that the plugin decides *whether and how*
   a member is built, and the slicer produces the shop output for the accepted member.
2. **Rhino versions.** The plugin is tested on Rhino 7; the slicer needs Rhino 8. An integration
   either runs on Rhino 8 only or keeps the two as separate steps.
3. **Section model.** The plugin's member is a plate (a profile blended along the path, constant
   thickness). The slicer's beam is a rectangular `W` x `H` section rotated along the axis. Map one to
   the other explicitly, and record that mapping in `docs/INTERFACES.md`.
4. **Limits.** The slicer's curvature check (flatwise bending, R at least ratio x lamella thickness)
   is set by its STEP 1 sliders. Align its ratio with the plugin's R/t setting, or state which one
   governs.

## If you take this on

Read `AGENTS.md` and `docs/CONTRIBUTING.md` first. Work on a branch, keep this folder's files
unchanged unless your PR is about them, write the interface in `docs/INTERFACES.md`, and log every
shortcut in `docs/DEBT.md` (see D-022).

Built by the CRV²FAB team at the AEC Tech Hackathon NYC 2026. MIT, see `LICENSE`.
