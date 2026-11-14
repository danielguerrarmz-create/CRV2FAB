# Inventory

One row per drop in `incoming/`. Append only. Status moves: `dropped` → `documented` → `runs` → `integrated`.

| Drop | Owner | What it does | Language | Entry point | Units in / out | Status |
|---|---|---|---|---|---|---|
| `incoming/dalalaaryan/` | dalalaaryan | One member (surface → plate, solid, or curve) → curvature analysis → single glulam billet check → fix-it loop with Claude, sketch and auto-relax; exports PDF/3DM/PNG | JavaScript (browser) + rhino3dm wasm | `python3 build.py` → serve `dist/` | in: .3dm, file units (Z-up) / out: mm, Z-up | documented |
