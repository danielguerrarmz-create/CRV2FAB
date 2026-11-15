# Inventory

One row per drop in `incoming/`. Append only. Status moves: `dropped` → `documented` → `runs` → `integrated`.

| Drop | Owner | What it does | Language | Entry point | Units in / out | Status |
|---|---|---|---|---|---|---|
| `incoming/dalalaaryan/` | dalalaaryan | Rhino surface → curvature analysis → 2× board or glulam billet mapping with buildability checks; exports PDF/PNG/3DM/CSV | JavaScript (browser) + rhino3dm wasm | `python3 build.py` → serve `dist/` | in: .3dm, file units (Z-up) / out: mm, Z-up | documented |
| `integrated/crv2fab-open-sourced/` | danielguerrarmz | Gesture, Nudge, Judge: Rhino 7 script + local rules core; a drawing becomes one buildable glulam billet proposal with waste; MIT | Python 3 (core), IronPython 2.7 (Rhino 7) | `core`: `python -m gnj_nudge.server`; Rhino 7: `_RunPythonScript rhino7/gnj_nudge.py` | in: mm, Z-up / out: mm, Z-up | runs |
