# DROP: Aaryan (`dalalaaryan`)

Timber Surface Curvature Analyzer. A browser tool that turns a Rhino surface into timber members and checks whether they can be built. Live version: https://claude.ai/artifact/7BTasUAafmhq4utL5XvMVW

| Field | Answer |
|---|---|
| What it does (one sentence) | Loads a Rhino `.3dm` surface, analyses its curvature, maps either dry-bent 2× boards or laminated glulam billets (pressed singly curved, then CNC'd) onto it, checks each member, and exports PDF / PNG / `.3dm` / CSV. |
| Language, runtime, versions | JavaScript (browser, ES modules). three.js 0.160.0, jsPDF 2.5.1 and fflate 0.8.2 from CDN. rhino3dm 8.35.0 (`.js` + `.wasm`) vendored in `vendor/`. Node ≥ 18 for the tests. Python 3 for `build.py`. |
| Entry point (file or command) | `python3 build.py`, then serve `dist/` over HTTP and open `index.html`. Source lives in `src/page.html`, `src/core.js` and `src/billet.js`. |
| Inputs (format, units, up-axis) | `.3dm` with surfaces, polysurfaces or extrusions (meshes and SubD are skipped). Units are read from the file (override in the UI). Z-up, as in Rhino. Built-in sample surfaces are in mm. |
| Outputs (format, units, up-axis) | All internal geometry is in **mm, Z-up**. `.3dm` in mm, with layers: analysis surface, members OK / fail, billets. CSVs: positions in mm, curvature in 1/m and 1/m², radii in m (stated in the column headers). A3 PDF sheet. PNG. |
| Dependencies | Browser with WebGL and WebAssembly. Internet access for the three CDN libraries. |
| Hardcoded things (paths, keys, machine names) | No keys or paths. Placeholder material and fabrication values are listed in DEBT: E/forming limit per species, R/t ≥ 125, CNC opening 1200 × 280 mm / 18 m, fit tolerance 2 mm, lam options 38 / 17 / 11 mm from 2× stock, refine limit 240 billets. |
| Large files kept elsewhere (link) | None. The largest file is `vendor/rhino3dm.wasm` (2.7 MB). |
| Known broken or unfinished | Trimmed faces are analysed over the untrimmed surface. No springback model. Billets are constant radius only. Twist and geodesic (edge-wise) bending of boards are not checked. Only tested in headless Chrome. |
| Overlaps with someone else's drop? | The billet fit reimplements the minimum-volume singly curved billet method of a Grasshopper billet toolkit the team has (not in this repo yet). UNKNOWN (ask dalalaaryan) who owns it. |

## How to run it from a fresh clone

```
cd incoming/dalalaaryan
node tests/test_core.js          # maths tests: sphere, cylinder, saddle, arc billet
python3 build.py                 # writes dist/index.html + rhino3dm files (dist/ is gitignored)
python3 -m http.server 8000 -d dist
# open http://localhost:8000 → "Large shell" sample → Production route → Preview timber mapping
```

Outside claude.ai, exports download directly through the browser. Inside the claude.ai artifact they go through the artifact's download prompt.
