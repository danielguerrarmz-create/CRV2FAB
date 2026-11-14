# integrated/analyzer

Timber Surface Curvature Analyzer, integrated version. Owner: `dalalaaryan` (Aaryan). Source drop:
[`incoming/dalalaaryan/`](../../incoming/dalalaaryan/), which stays untouched until this copy runs the demo path.

## What it is

A browser tool that loads a Rhino `.3dm` surface, analyses its curvature, and maps timber onto it by one of
two routes:

- **Bent 2× boards (dry):** each board is checked for bending stress (E·h·k/2 against the forming limit) and
  for fit across its width (b²·k/8 against the tolerance), then cut at standard stock lengths.
- **Glulam billet, then CNC:** each member is pressed as a singly curved laminated billet and machined to the
  double curvature. Members are split so every billet fits the CNC opening and the waste target.

It exports an A3 PDF sheet, a PNG, a `.3dm` (Rhino 7 format, mm) and CSVs. The method and the placeholder
material values are described in the drop's [README](../../incoming/dalalaaryan/README.md) and
[DROP.md](../../incoming/dalalaaryan/DROP.md).

## Run it

From a fresh clone, with Node 18 or later and Python 3:

```
cd integrated/analyzer
node tests/test_core.js          # curvature maths and billet fit (from the drop)
node tests/test_integration.js   # regression tests for the fixes below
python build.py                  # writes dist/index.html + rhino3dm files (dist/ is gitignored)
python -m http.server 8000 -d dist
# open http://localhost:8000 , pick a sample or drop a .3dm
```

The page needs internet: three.js, jsPDF and fflate load from CDNs (DEBT D-011). rhino3dm is vendored.

## Layout

```
src/page.html    UI and viewer
src/core.js      curvature analysis and timber checks (from the drop, unchanged)
src/billet.js    singly curved billet fit (from the drop, unchanged; see DECISIONS 4)
src/helpers.js   pure functions pulled out of page.html during integration, tested under node
tests/           node tests
vendor/          rhino3dm 8.35.0 js + wasm (McNeel, MIT)
build.py         inlines src/*.js into dist/index.html
```

## Units and axes

Length in millimetres, Z up, as in `docs/INTERFACES.md`. A loaded file's units are read from the file and
converted to mm on input; everything exported is in mm. The `.3dm` export is a Rhino 7 archive.

## What changed from the drop

Each fix has a regression test in `tests/test_integration.js` (test names in brackets).

| # | Defect in the drop | Fix |
|---|---|---|
| 1 | A CNC max length between 0 and 0.2 m made the piece length zero or negative and the member split loop never ended | The loop moved to `Helpers.segment`; the max length is clamped to at least 100 mm and every step must advance [`cnc_max_length_any_setting_terminates`, `cnc_max_length_drop_loop_never_ends`] |
| 2 | The `.3dm` export was a Rhino 8 archive, which Rhino 7 cannot open | Written with `toByteArrayOptions` at version 7 [`export_3dm_is_rhino7_archive`] |
| 3 | Buy quantities ignored the number of layers stacked through the thickness | Cut list, stat card, PDF and the cut-list CSV (`qty_to_buy` column) multiply by the layers [`buy_quantity_scales_with_layers`] |
| 4 | Board width was measured along the transverse isocurve, so a sheared surface got 31 boards where 22 fit | Measured perpendicular to the member [`sheared_plane_board_count_is_22`] |
| 5 | One shared debounce timer dropped an edit when two inputs changed within 250 ms | One timer per callback [`debounce_two_inputs_both_run`] |
| 6 | Object and layer names from a `.3dm` went into `innerHTML` unescaped | Escaped [`escape_html_blocks_markup_and_attribute_breakout`, `page_object_list_escapes_names`] |
| 7 | `build.py` used the platform text encoding, which fails on some UTF-8 text on Windows | Reads and writes UTF-8, and inlines `src/helpers.js` [`build_py_utf8_round_trip`] |
| 8 | In billet mode, exported object names and `summary.json` said "2x6 on edge" | Named for the billet route; `summary.json` `orientation` is `null` in billet mode [`billet_route_names_not_board_size`, `summary_json_keeps_its_fields`] |

Made honest, not fixed: trimmed faces are still analysed over their untrimmed surface. Each trimmed face is now
marked in the object list, with a note saying so [`trimmed_face_is_flagged`] (DEBT D-010).

Interface change: in billet mode `summary.json` `stock` describes the billet (for example
`glulam billet, 17 mm lams from 2×10`) and `orientation` is `null`. Board mode is unchanged.

## Known debt

D-002 to D-013 in [`docs/DEBT.md`](../../docs/DEBT.md). The ones specific to this copy: D-009 (it duplicates the
drop), D-010 (trimmed faces), D-011 (CDN libraries, jsPDF advisories), D-012 (splitter placeholders),
D-013 (not yet opened in Rhino 7), D-014 (billet.js stays only until the analyzer can call the shared billet logic).
