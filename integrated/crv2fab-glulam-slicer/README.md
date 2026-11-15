# CRV²FAB Glulam Slicer

**Curve in, CNC-ready glulam beam out.** A Rhino 8 / Grasshopper definition that turns axis
curves into double-curved glued-laminated (glulam) timber beams made of real dimensional lumber,
ready for CNC fabrication.

Built at the AECtech 2026 NYC Hackathon by the CRV²FAB team.

## What it does

| | |
|---|---|
| **Glulam CNC slicer 3D** | Every lamella of every layer is laid out with real boards (2x4 to 2x10, actual 89 to 235 x 38 mm), cut into pieces that fit a 16' board or a CNC blank, with staggered butt joints. Every piece is labelled (B1-L3-P2-S4). |
| **Realistic materials** | Wood grain follows the curve on the long faces; end grain is mapped on the cuts. Per-beam species and per-lamella colour variation, ready to render. |
| **Raw vs finished** | Oriented raw CNC blocks around each beam, split along the axis to stay under a maximum waste %, compared with the finished lamellae. |
| **Quantity report** | Bill of materials, cut list, raw boards to buy, raw blocks; per beam and for the whole assembly; CSV / JSON export. |

One definition handles any number of beams: one Rhino curve = one beam.

## Requirements

- Rhino 8 (Grasshopper and the built-in Python 3 script components). Developed and tested on Windows.
- No third-party Grasshopper plugin.
- Units: millimetres.

## Files

| File | Role |
|---|---|
| `CRV2FAB_glulam_slicer.gh` | The Grasshopper definition (7 steps, each explained by a note on the canvas). |
| `crv2fab_lib.py` | Shared Python logic. **Keep it in the same folder as the .gh.** |
| `examples/CRV2FAB_example_axes.3dm` | Three demo axis curves with their per-beam settings (User Text). |

## Quick start

1. Download the whole folder; keep `CRV2FAB_glulam_slicer.gh` and `crv2fab_lib.py` side by side.
2. Open `examples/CRV2FAB_example_axes.3dm` in Rhino 8, then open the .gh in Grasshopper.
   The `Beam axis` parameter already points to the three example curves.
   For your own model: right-click `Beam axis` > *Set Multiple Curves*.
3. For the realistic render (STEP 4), add the wood materials to the Rhino document:
   from the Rhino 8 material library (Materials panel > Library), drag in **Pine**, **Douglas Fir**,
   **Cross Laminated Timber (CLT) End Grain** and **Glued Laminated Timber (Glulam) End Grain**
   (any material works: the definition matches materials by words of their name).
4. Turn **Show realistic mesh** on to see the textured beams.

## Settings for each beam (no Grasshopper needed)

Select the axis curve in Rhino, then *Properties > Attribute User Text* (or the `SetUserText`
command) and add any of these keys (case-insensitive):

| Key | Meaning |
|---|---|
| `W`, `H` | Overall width and height of the section (mm) |
| `RotStart`, `RotEnd` | Rotation of the start / end profile around the axis (degrees), twisted linearly in between |
| `TopLayerTrim` | `true` = thinner top layer to hit the exact height |
| `MaxBlank` | Widest raw board or CNC blank (mm) |
| `Wood`, `EndGrain` | Material of the long faces / of the end faces (words of the material name, e.g. `douglas`) |

The curve's *Name* becomes the beam name (otherwise B1, B2, ...).
Priority: sliders of STEP 1 (global defaults) < User Text on the curve < optional *Beam Settings* components.
If the definition does not update after editing User Text, press F5 in Grasshopper.

## The 7 steps on the canvas

1. **Inputs + beam definition**: global defaults, per-beam settings.
2. **Layout**: board mix of the section, perpendicular frames along the axis, lamellae and butt joints, geometry.
3. **Fabrication geometry**: one closed Brep per piece, labels.
4. **Realistic mesh**: materials per beam, per-lamella variation.
5. **Raw blocks**: oriented CNC blocks under a maximum waste %, with a margin on all six faces.
6. **Bake to Rhino**: global layers, one layer tree per beam, or one Rhino block per beam.
7. **Reports**: summary, detailed report, cut list, CSV / JSON export.

Speed: a *Light preview* toggle shows beam envelopes only while you design, and a per-beam cache
re-solves only the beams that changed.

## What the definition writes to your files (safety notes)

- **Rhino document**: objects are added only when you click **BAKE**, on layers under `Glulam` /
  `Glulam_Render`. With **Replace** on, only objects previously baked by this definition are deleted
  (they carry the User Text key `crv2fab_beam`); your own objects are never touched.
- **Materials**: STEP 4 adds copies named `Glulam UV - <material>` to the document; the source
  materials are not modified.
- **Disk**: files are written only when you click **EXPORT**, into the folder you choose
  (default: `CRV2FAB_export` next to the .gh).
- **Code**: the script components load and run `crv2fab_lib.py` from the folder of the .gh.
  Only use a copy of that file you trust, from this repository.
- No network access, no external executable, no third-party plugin.

## Limits

- Glulam made of flat lamellae of standard North American boards; one material family today.
- The curvature check (flatwise bending, R >= ratio x lamella thickness) is a design aid, not a
  structural verification. Have every project checked by a qualified engineer and your fabricator.

## License

MIT, see [LICENSE](LICENSE). © 2026 CRV2FAB team - AECtech 2026 NYC Hackathon.
