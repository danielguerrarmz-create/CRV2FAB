# Timber Surface Curvature Analyzer

Browser tool for a closed-loop doubly curved timber workflow (LC hackathon). Load a Rhino `.3dm` surface, analyse its curvature, map timber onto it, and check whether it can be built.

## Production routes
- **Bent 2× boards (dry):** 2×4 / 2×6 / 2×8 / 2×10, on edge or flat. Each board is checked for bending stress (E·h·k/2 against the forming limit) and for fit across its width (b²·k/8 against the tolerance). Boards are cut at standard stock lengths (8–24 ft) with staggered butt joints.
- **Glulam billet → CNC:** each member is pressed as a singly curved laminated billet, then machined to the double curvature.
  - The billet fit finds the minimum-volume billet: bending plane by PCA + Nelder-Mead, minimum-area annular sector, depth rounded up to whole lams, CNC section by rotating calipers.
  - Members are split greedily so that each billet fits the CNC opening and the waste target.
  - Laminations are 38 / 17 / 11 mm, cut from 2× stock and checked against R/t.

## Outputs
- 3D viewer with curvature maps (Gaussian, mean, minimum radius, type) and timber or billet status.
- Ghosted member preview with tap-to-inspect.
- Cut lists.
- Exports: A3 PDF sheet, PNG, `.3dm` (surface, members and billets on layers), and CSVs (samples, cut list, billets, lam layers).

## Layout
```
src/page.html   UI + viewer (three.js, jsPDF, fflate from CDN)
src/core.js     curvature analysis + timber checks (pure JS, no DOM)
src/billet.js   singly curved billet fit (pure JS)
vendor/         rhino3dm.js + wasm (McNeel, MIT)
tests/          node tests for the maths
build.py        inlines src/*.js into dist/index.html
```

## Build and test
```
node tests/test_core.js
python3 build.py        # dist/index.html + rhino3dm files; serve dist/ over http
```

## Placeholders (to be replaced by physical tests)
- SPF E = 9,650 MPa with a 30 MPa forming limit.
- Lam R/t ≥ 125 (NDS softwood; confirm with the supplier).
- The CNC opening (width × height, max length) is entered by the user. The defaults (1200 × 280 mm, 18 m) are placeholders.
- Springback is not modelled yet.

