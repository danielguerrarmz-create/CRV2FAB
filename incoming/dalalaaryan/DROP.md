# DROP: Aaryan (`dalalaaryan`)

Curved Member Fabrication Loop. A browser tool that treats a Rhino surface, solid or curve as ONE glulam member, checks whether it can be made as a pressed singly curved billet plus CNC, and runs a fix-it loop with Claude, sketches and an automatic relaxer. Live version: https://claude.ai/artifact/7BTasUAafmhq4utL5XvMVW

| Field | Answer |
|---|---|
| What it does (one sentence) | Loads one member (surface → curved plate, closed solid, or curve → centreline + section) from `.3dm`, analyses its curvature, fits one singly curved glulam billet, explains why it fails (CNC opening, waste, lam R/t), and iterates the shape with Claude (artifact `sample` + tool), a three-stroke sketch (start profile, end profile, bending) over the 3D view, or auto-relax; exports PDF / `.3dm` / PNG. |
| Language, runtime, versions | JavaScript (browser, ES modules). three.js 0.160.0, jsPDF 2.5.1 and fflate 0.8.2 from CDN. rhino3dm 8.35.0 (`.js` + `.wasm`) vendored in `vendor/`. Node ≥ 18 for the tests. Python 3 for `build.py`. |
| Entry point (file or command) | `python3 build.py`, then serve `dist/` over HTTP and open `index.html`. Source lives in `src/page.html`, `src/core.js` and `src/billet.js`. |
| Inputs (format, units, up-axis) | `.3dm`: the largest closed solid, else the largest surface face, else the first curve becomes the member. Units are read from the file (override in the UI). Z-up. Samples are in mm. |
| Outputs (format, units, up-axis) | All geometry in **mm, Z-up**. `.3dm`: one layer per iteration (centreline NURBS, member mesh, billet mesh). A4 PDF member report. PNG. |
| Dependencies | Browser with WebGL and WebAssembly. Internet access for the three CDN libraries. |
| Hardcoded things (paths, keys, machine names) | No keys or paths. Placeholders: lam R/t ≥ 125; CNC opening 1200 × 280 mm / 18 m; lam options 38 / 17 / 11 mm from 2× stock; 150 mm trim per lamination. |
| Large files kept elsewhere (link) | None. The largest file is `vendor/rhino3dm.wasm` (2.7 MB). |
| Known broken or unfinished | Only the largest face or solid is used. Trimmed faces are sampled untrimmed. The shape edit carries cross-sections rigidly along the centreline (no bending mechanics). Springback is not modelled. Real Claude calls are untested (they need claude.ai). Only tested in headless Chrome. |
| Overlaps with someone else's drop? | The billet fit reimplements the minimum-volume singly curved billet method of a Grasshopper billet toolkit the team has (not in this repo yet). UNKNOWN (ask dalalaaryan) who owns it. |

## How to run it from a fresh clone

```
cd incoming/dalalaaryan
node tests/test_core.js          # maths tests: sphere, cylinder, saddle, arc billet
python3 build.py                 # writes dist/index.html + rhino3dm files (dist/ is gitignored)
python3 -m http.server 8000 -d dist
# open http://localhost:8000 → "Doubly curved panel" → Auto-relax, or sketch a curve
```

Outside claude.ai, exports download directly through the browser. Inside the claude.ai artifact they go through the artifact's download prompt.
