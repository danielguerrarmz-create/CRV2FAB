# Inventory

One row per drop in `incoming/`. Append only. Status moves: `dropped` → `documented` → `runs` → `integrated`.

| Drop | Owner | What it does | Language | Entry point | Units in / out | Status |
|---|---|---|---|---|---|---|
| `incoming/dalalaaryan/` | dalalaaryan | Rhino surface → curvature analysis → 2× board or glulam billet mapping with buildability checks; exports PDF/PNG/3DM/CSV | JavaScript (browser) + rhino3dm wasm | `python3 build.py` → serve `dist/` | in: .3dm, file units (Z-up) / out: mm, Z-up | documented |
| `integrated/crv2fab-open-sourced/` | danielguerrarmz | Gesture, Nudge, Judge: Rhino 7 script + local rules core; a drawing becomes one buildable glulam billet proposal with waste; MIT | Python 3 (core), IronPython 2.7 (Rhino 7) | `core`: `python -m gnj_nudge.server`; Rhino 7: `_RunPythonScript rhino7/gnj_nudge.py` | in: mm, Z-up / out: mm, Z-up | runs |
| `integrated/crv2fab-glulam-slicer/` | CRV2FAB team | Rhino 8 Grasshopper glulam slicer: axis curves to double-curved glulam of real boards, labelled pieces, raw CNC blocks, BOM / cut list (CSV, JSON), render meshes. Standalone, pending integration with the plugin | Grasshopper + Python 3 (Rhino 8) | Open `CRV2FAB_glulam_slicer.gh` with `crv2fab_lib.py` beside it; example `examples/CRV2FAB_example_axes.3dm` | in: axis curves + User Text, mm / out: Breps, meshes, CSV / JSON, mm | runs standalone |
