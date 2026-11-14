# Interfaces

How the pieces talk to each other. Changes go through pull requests.

## Team conventions

| Convention | Value | Decided in |
|---|---|---|
| Length unit | mm | `integrated/analyzer` (2026-11-14, Daniel's direction for this PR) |
| Up-axis | Z up, as in Rhino | `integrated/analyzer` (2026-11-14) |
| Model tolerance | TBD | |
| Geometry exchange format | `.3dm`, written as a Rhino 7 archive (Daniel has Rhino 7) | `integrated/analyzer` (2026-11-14) |
| Coordinate origin | TBD | |

## Boundaries

Copy this block for every place where one person's output becomes another person's input.

### <producer> → <consumer>

- **Data:** what is passed (curves, meshes, point lists, parameters)
- **Format:** file type or in-memory structure, with an example
- **Units / up-axis / tolerance:**
- **Who owns the contract:**

### Rhino model → `integrated/analyzer`

- **Data:** surfaces, polysurfaces and extrusions (meshes and SubD are skipped; trimmed faces are analysed untrimmed, D-010)
- **Format:** `.3dm` from Rhino 6, 7 or 8
- **Units / up-axis / tolerance:** units read from the file and converted to mm; Z up; tolerance not used
- **Who owns the contract:** `dalalaaryan`

### `integrated/analyzer` → Rhino 7 and downstream tools

- **Data:** analysis surface mesh, member meshes, billet meshes (billet route), on named layers; CSVs; `summary.json`
- **Format:** `.3dm` Rhino 7 archive; CSV with units in the column headers (mm, 1/m, 1/m², m); `summary.json` (in billet mode `stock` describes the billet and `orientation` is `null`)
- **Units / up-axis / tolerance:** mm, Z up
- **Who owns the contract:** `dalalaaryan`
