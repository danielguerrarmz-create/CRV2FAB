# Inventory

One row per drop in `incoming/`. Append only. Status moves: `dropped` → `documented` → `runs` → `integrated`.

| Drop | Owner | What it does | Language | Entry point | Units in / out | Status |
|---|---|---|---|---|---|---|
| `incoming/dalalaaryan/` | dalalaaryan | Rhino surface → curvature analysis → 2× board or glulam billet mapping with buildability checks; exports PDF/PNG/3DM/CSV | JavaScript (browser) + rhino3dm wasm | `python3 build.py` → serve `dist/` | in: .3dm, file units (Z-up) / out: mm, Z-up | documented |
