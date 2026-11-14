# Curved Member Fabrication Loop

Browser tool for a closed-loop doubly curved timber workflow (LC hackathon). **Whatever you load is treated as ONE member.**

- **Input:** a Rhino `.3dm` holding one of these:
  - a surface: read as a curved plate, thickened to the member thickness
  - a closed solid: the member as modelled
  - a curve: read as a centreline with a rectangular section
- **Curvature analysis** of the member: Gaussian, mean, minimum radius and type maps, plus a lamination check.
- **Fabrication check:** one singly curved glulam billet (pressed in one plane at one radius, then CNC-milled to the member).
  - Billet fit: bending plane by PCA + Nelder-Mead, minimum-area annular sector, depth rounded to whole laminations.
  - Pass means all of these: the billet fits the CNC opening, waste is within the target, and lam R/t is at or above the limit.
- **Design loop** when it fails:
  - **Ask Claude:** the artifact `sample` capability. Claude gets the shape, the limits and the failure reasons, can call an `evaluate_member` tool that runs the same check, and returns a new centreline, cross-curvature scale and twist scale with its reasoning.
  - **Sketch:** a pen stroke over the 3D view becomes the new centreline. It is checked first; if it fails, Claude gets the sketch image and keeps its shape.
  - **Auto-relax (no AI):** the smallest morph toward the best-fit billet arc that passes.
  - **Manual edit:** across-width curvature and twist sliders.
- **Laminations:** layer count and lengths, boards across the width, and how many 2× boards to buy.
- **Exports:** PDF member report; `.3dm` with one layer per iteration (centreline, member, billet); PNG.

## Layout
```
src/page.html   UI + viewer + member model + loop (three.js, jsPDF, fflate from CDN)
src/core.js     curvature analysis + lamination check (pure JS)
src/billet.js   singly curved billet fit (pure JS)
vendor/         rhino3dm.js + wasm (McNeel, MIT)
tests/          node tests for the maths
build.py        inlines src/*.js into dist/index.html
```

## Build and test
```
node tests/test_core.js
python3 build.py && python3 -m http.server 8000 -d dist
```

## Placeholders
- Lam R/t >= 125 (confirm with the supplier).
- CNC opening 1200 x 280 mm and 18 m max length: enter your machine.
- Springback is not modelled.
