# Interfaces

How the pieces talk to each other. Changes go through pull requests.

## Team conventions

| Convention | Value | Decided in |
|---|---|---|
| Length unit | TBD | |
| Up-axis | TBD | |
| Model tolerance | TBD | |
| Geometry exchange format | TBD | |
| Coordinate origin | TBD | |

## Boundaries

Copy this block for every place where one person's output becomes another person's input.

### <producer> → <consumer>

- **Data:** what is passed (curves, meshes, point lists, parameters)
- **Format:** file type or in-memory structure, with an example
- **Units / up-axis / tolerance:**
- **Who owns the contract:**

### Rhino 7 script → GNJ core (`integrated/crv2fab-open-sourced/`)

- **Data:** the designer's input (three strokes as 3D point lists, a surface grid and a line, a solid's surface points and volume, typed words, a photo's bytes) in; one proposal (form, sentence, Why steps, checks, waste, tally) out.
- **Format:** JSON over HTTP on 127.0.0.1:8742 (`POST /nudge`, `/judge`, `/say`, `/photo`, `/undo`, `GET/POST /settings`, `GET /record`, `/tally`). Example and every field: `integrated/crv2fab-open-sourced/core/README.md`.
- **Units / up-axis / tolerance:** millimetres, Z up; the Rhino script converts from document units at the boundary.
- **Who owns the contract:** danielguerrarmz (`core/docs/SPEC_V9.md`).
