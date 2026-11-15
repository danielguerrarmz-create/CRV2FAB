# GNJ shared spec v9: three strokes, a plate from start profile, end profile and path

Draft, 2026-11-14. Not approved. No code until Daniel marks it up.

Decided by Daniel on 2026-11-14:
- "We'll replace the single stroke with the third stroke mode, and it should function in a similar
  manner to PR #3." (Aaryan's PR #3, `dalalaaryan/single-member-rework`, in CRV2FAB.)
- The rules propose one ghost. Claude still only reads words and photos; it never edits geometry.
- Profiles are drawn on the plane square to the path at each end, not on the view plane.
- From PR #3 we take the drawing method only. Its browser page, its own billet maths (`billet.js`),
  its exports, build script and sliders are not used. The billet logic stays the technical member's
  `sc_glulam`, vendored unmodified.

Units: millimetres, Z up, at every boundary.

## What changes

| Today | v9 |
|---|---|
| One stroke over the straight 2x4 becomes one radius and one direction (kind `bend`) | Three strokes reshape the member (kind `plate`) |
| The bend kind has its own make-up rules (ratio 200, layers and strips) | Every member goes through the `sc_glulam` route (layers 38, 17, 11 mm; ratio 125; machine opening; waste) |
| Sculpting (v7) adds one bend at a time | Retired: redrawing the path does the same job. Branch `sculpt` is not merged |
| A photo's bends feed sculpting (v8) | A photo's bends build a path; the profiles are kept |

Unchanged: the line on a surface (`surface_stroke`), your own solid (`part`), holds, `/say`, taste,
settings, splitting, the record.

## The three strokes

The member starts as the straight 2x4: path 2400 mm along X, both profiles a straight 89 mm line,
thickness 38 mm.

| Stroke | Drawn where | Becomes |
|---|---|---|
| Path | In any view, projected onto the plane facing the camera through the member's middle | The member's centreline. Its ends are pinned to the current member's ends; drawn backwards is flipped |
| Start profile | On the plane square to the path at its start | The cross-section across the width at the start, centred on its midpoint |
| End profile | On the plane square to the path at its end | The same at the end |

- Any stroke may be skipped: the current member's own path or profile is kept. At least one is needed.
- Any stroke may be redrawn before Done; the last one drawn counts.
- The designer orbits freely between strokes. Strokes are fixed in 3D when drawn.
- If the path is redrawn after a profile, the profile moves with its end and keeps its local shape.

## Building the plate (core)

1. Path: resampled to 65 stations by arc length. Frames along it are rotation minimising, so the
   profiles do not spin unless drawn to.
2. Profiles: each resampled to 15 points, expressed in its end frame (across, normal).
3. Between the ends the profile is blended linearly, point by point (PR #3's method). This is the
   plate's mid-surface, a 65 x 15 grid. Twist is the angle between the two profiles' chords.
4. The mid-surface is thickened by `thickness_mm` along its normal, giving the solid's surface
   points and volume. Thickness is a setting (`thickness_mm`, default 38, in the System panel's
   Settings), never drawn (Daniel, 2026-11-14). Built in slice 3: setting `thickness_mm` (GET/POST
   /settings, 1 to 500 mm, default 38). A plate request that sends `thickness_mm` wins for that request
   only; one that does not gets the setting. Record entries carry it in `settings` and in the intent
   summary with `thickness_from` (`request` or `setting`).
5. Width: no limit of its own for the demo (Daniel asked for the option that works for the MVP). A
   profile wider than the machine opening fails the machine check like any other billet, and if no
   easing makes it fit, the answer is the conflict "This billet will not fit through the machine."
   Easing a profile's curve never shrinks its width.
6. Those points go to the same fit every kind already uses: `fit_bending_plane`, `fit_arc_2d`,
   `billet_extents`, `offset_radii`, `min_width_box`. No second billet fit exists.

## Grain follows the path (Daniel, 2026-11-14)

A billet's length axis (the chord of its spine, the way its layers run) lies within `grain_deg` of the
path: for each piece, the chord of its own run of stations. Card `grain_deg`: 10 degrees, source
"placeholder, confirm with the technical member". The check is `checks.grain` (`ok`, `angle_deg`,
`limit`). When the free fit runs off the grain, the same points are fitted again with the bending plane
constrained to hold the path's chord (`fabrication.fit_arc_billet_in_plane`, the existing wrapper; plane
normals: the piece's mean across, its mean normal, and the free fit's normal, each made square to the
chord); every fit's checks are offered, thickest layer first. A piece fails on grain when some billet
would pass bend and machine but none of those runs along the grain. Pieces are tried for a grain
failure as for a machine failure. Nothing passing: a conflict, worded by the rule in "Conflict
wording"; "The billet cannot run along the grain at this width." when the drawn plate's own one-billet
failure is grain. The other kinds have no path and no grain check.

## Stock: one 2x4 as it comes (Daniel, 2026-11-14)

Before any fit: a plate whose two faces lie inside one 38 x 89 mm board, 2400 mm long, within 1 mm on
each extent (measured along the path chord and square to it in the start frame; the section may lie
either way round) is answered "Your shape holds. One stock 2x4, no pressing.", `n_lamellas` 1,
`billet.mode` "stock", waste = board minus plate over board (0% for the straight member). A bend, a
twist or a curved profile shows as a larger extent: 2 mm of sag, 1 degree of twist over 89 mm or a 3 mm
deep profile is no longer stock. A thinner plate inside the board is stock with its waste reported
(confirmed by Daniel, 2026-11-14: stock is stock; a 19 mm plate is one stock 2x4 at 50% waste).

## The nudge: closest buildable

Keep the drawn shape. Change how it is made first. Ease the shape last.

1. Layer option: the thickest that passes (38, 17, 11 mm).
2. Pieces: only under the conditions of v6 section 4 (machine check failed, a waste target set, or
   `split_ok`).
3. Ease the shape, by bisection on one scale at a time (1 = as drawn, 0 = fully eased, 12 steps),
   chosen by the check that failed (order confirmed by Daniel, 2026-11-14):
   - Bend check failed (a layer bends too tightly): ease the path's curvature toward the straight
     line between its pinned ends.
   - Machine check failed (the billet is too big for the opening): ease the twist first, then the
     profiles' curve across the width, then the path's drift out of its best bending plane.
4. Nothing passes even fully eased: a conflict naming the two things that cannot both be true.

- Hold `shape`: step 3 is not allowed; failing is a conflict.
- Hold `solid`: one straight piece milled to shape, no pressing; then steps 2 and 3.
- `less_waste`, `split_ok`: as in v5 and v6. Waste is reported, never optimised unasked.
- `deviation_mm` is the largest distance between the drawn and the eased mid-surface over the
  whole 65 x 15 grid, so easing the twist or a profile counts, not only the centreline.

### As built in slice 2 (2026-11-14)

- Scales reported in `eased`: `path` (toward the straight line between the pinned ends), `drift` (out of
  the path's best plane through its chord, least squares; the billet's own bending plane is not used),
  `twist` (each end turns half, so the twist becomes scale x drawn), `profiles` (each profile toward its
  own chord: its span across never shrinks). `drift` is a fourth key: the machine order names it.
- Grain failure (decided here): treated as a machine failure, after pieces: twist, then profiles, then
  drift. The cause that picks the order is the one-billet failure of the drawn plate.
- Easing works on one billet. Pieces are tried only on the drawn plate, so the order stays layer option,
  pieces, easing, and no eased shape is split.
- Binding (Daniel, 2026-11-15): the sentence and its Why steps name the binding check, which is, among
  the checks the drawn plate failed in one billet, the one with the least margin relative to its limit
  in the eased answer (bend: R/t over its limit, minus 1; machine: the smaller spare dimension over its
  opening; grain: spare angle over its limit). The easing order still follows the first failure.
- A scale whose full easing moves the plate less than 0.5 mm is skipped. A scale whose cheap fit still
  fails fully eased is set to 0 with no full fit, and the next scale is eased.
- Cheap fits hold the bending plane of the drawn one-billet fit that came closest
  (`fabrication.fit_arc_billet_in_plane`, about 0.03 s); 12 bisection steps; at most 3 full one-billet
  plans decide, over all scales (at the bisected scale, half of it, then 0). The caps are counts, not a
  clock, so an answer never depends on the machine's speed.
- Sentences name what eased in words: "Twist and profiles eased so the billet fits the machine, moving
  the plate at most 215 mm."; "Path straightened so the layers can bend, moving the plate at most
  331 mm."; also "path drift", and "so the billet runs along the grain". One Why step per eased scale,
  in words only ("Twist removed, each end turned back by the same amount, so the billet fits the
  machine."), and a Check step with `deviation_mm`.
- Words plus ONE number (Daniel, 2026-11-14): the only number in a sentence or Why step about easing
  is `deviation_mm`, the largest move anywhere on the 65 x 15 plate, worded "moving the plate at most
  X mm" or "sits at most X mm from what you drew". No per-scale figure appears in text: no degrees of
  twist eased, no millimetres of path or profile, no scale. Those stay as fields only (`eased`,
  `twist_deg`). The record's formal sentence, written for the engineer, keeps the scales and twists.
- A conflict's cause: see "Conflict wording" (slice 3).

### Conflict wording (slice 3, Daniel 2026-11-14)

A plate conflict names the cause of the drawn plate's failure at the decisive step: the drawn plate
in one billet, with every layer option and every fit tried (free, and constrained to the grain). The
cause is, in this order: `bend` when no layer bends far enough; `grain` when some billet passes bend
and machine but none runs along the grain; `machine` otherwise; `fit` when no billet could be fitted.
Hold `solid` is the straight-piece conflict. Pieces and easing are remedies: when they do not help, the
sentence still names the drawn plate's cause, and when the pieces met a different limit one Why step
says so ("Tried up to 4 pieces: a billet would fit only across the grain, and the grain must follow
the path."). So the twisted plate held to its shape and the 1400 mm plate both read "This billet will
not fit through the machine." (kind part keeps its own rule: the cause at the last count tried).

## Speed (Daniel, 2026-11-14)

One answer on a plate takes under 10 s. One full `sc_glulam` fit of a 2.4 m plate (1,950 points)
measured about 3.5 s on this machine at full speed (`winpower.keep_full_speed()`), so plain
bisection (12 steps on up to 3 scales, up to 36 fits) would take about 2 minutes. Easing therefore
works as the surface kind does: cheap fits steer the search, at most 3 full fits decide. The fits
for one shape are shared by every layer option. If a full fit falls under 1 s, plain bisection is
allowed.

Measured 2026-11-14 through `/nudge` with the process pool on (as `python -m gnj_nudge.server` runs):
every vector 0.03 to 5.2 s, the slowest the twisted deep U (10 piece fits, then easing). Without the
pool (a host that cannot start processes) the same case takes about 10 s, almost all of it the drawn
plate's piece search before easing starts.

## Build order (Daniel, 2026-11-14)

1. Core plate kind: strokes to plate, fit, checks, no easing; `tests/vectors_plate.json`.
2. Easing inside the speed budget.
3. Wiring: `thickness_mm` setting, record sentence, `/say` templates, photo bends to a path.
4. Daniel's interface, flow and panel redesign.
5. Rhino three-stroke tool and plate ghost, designed inside that redesign.

## Contract

`POST /nudge`:

```
{"intent": {"kind": "plate", "member_id": "M1",
            "path": [[x, y, z], ...] or null,           2 to 400 points, mm
            "profile_start": [[x, y, z], ...] or null,  2 to 100 points, on the start plane
            "profile_end": [[x, y, z], ...] or null,
            "profile_start_on": "member" or "path",          optional, default "member"
            "profile_end_on": "member" or "path",
            "thickness_mm": 38},
 "holds": []}
```

The plane each profile was drawn on (decided 2026-11-14, closes Open 4): `"member"` is the current
member's end plane (the client sets its construction plane from the current member's `end_frames`),
`"path"` the plane square to the drawn path at that end. The core reads the profile's local shape
(across, normal) in that plane's frame and places it at the plate's end in the plate's own frame. So a
profile drawn before the path was redrawn moves with its end and keeps its shape and width, whatever
order the strokes came in; the client only says where it drew. Every plate answer carries `end_frames`
(`start` and `end`: `origin`, `tangent`, `across`, `normal`), the planes for the next strokes once
that plate is accepted.

The client sends 3D points; the core computes every frame and projection, so geometry has one home.
`null` keeps the current member's own (the core holds the current member per episode).

Response form `kind: "plate_member"`: `stations` (65), `grid` (65 x 15 mid-surface), `normals`,
`intent_grid` (as drawn, for the dashed outline), `thickness_mm`, `eased` (`{path, twist, profiles}`,
each a scale from 0 to 1), `twist_deg`, then as `surface_member`: `n_lamellas`, `lamella_mm`,
`billet`, `checks`, `deviation_mm`, and `pieces` and `cuts` when split.

Sentences follow the surface kind's, with "shape" for "line": "Your shape holds. Pressed in one curve
from N layers, then milled to shape."; "Twist eased so the billet fits the machine, moving the plate at most D mm.";
"Path straightened so the layers can bend, moving the plate at most D mm." (D is `deviation_mm`; see
"One distance for people")

## The record (slice 3)

A plate's `formal` sentence states: member, species, thickness and where it came from (request or
setting), the strokes drawn, length along the path, widths, twist (as drawn and, when eased, as built),
the eased scales or "Shape kept as drawn", how it is made (stock, one straight piece, glued straight
or pressed in one curve with its layers, or pieces), every billet with its size, volume and waste,
every joint, the weighted waste and target, billet and part volumes, the grain angle against its limit,
the governing limits and `deviation_mm`. The intent is a summary (which strokes, their numbers), never
the point lists. Taste does not lead a plate, as it does not lead a surface line or a part (spec v3:
taste's trade is defined for the bend kind); plate episodes are recorded but not read back.

## /say on a plate (slice 3)

Every heard and not-understood template says "shape" (never curve or line). Hold `shape` is read from
words such as "keep my shape exactly" (the action's meaning in the list now names "shape" too);
`less_waste` and `split_ok` as for every kind. The prompt is unchanged: the words, the holds and the
closed list, no stroke, plate number, setting or machine fact (`tests/test_privacy.py`).

## A photo builds a path (slice 3)

`photo.path_from_bends` applies the photo card's bends (span t0 to t1, direction, `sag_mm`) in order to
the straight 2400 mm path as spec v7 applies a bend: each station moves `sag_mm` x a raised cosine of
its arc-length fraction over [t0, t1], along the direction made square to the path's chord over that
span, and the path is re-evened to 65 stations. The profiles are the current member's, the thickness the
session setting. The plate kind answers (check, pieces, easing), and that plate is the proposal on
screen in the photo's own episode, so /judge records it with the photo's sha256.

## Undo (slice 3, item 7)

Body `{}` (anything else is a 400). Undoes the most recent accepted decision of this server session
that is not undone yet and comes after the last tally reset; repeated undos walk back one accept at a
time. The record stays append-only: an `undo` marker is appended (`event: "undo"`, `undone_timestamp`,
`undone_episode_id`, `undone_line`), never a rewrite.

- 200: `{"undone": {"member_id", "timestamp", "kind"}, "tally"}`.
- 409: nothing to undo (no accept since the last tally reset in this session). A tally reset stops undo
  from crossing it; a decision from an earlier session is never undone.
- The tally (`GET /tally` and every response's `tally`) and taste ignore undone decisions. `GET /record`
  hides the marker and marks the undone entry `undone: true`.
- The proposal on screen, if any, is not touched.

## Client (Rhino 7)

- Draw shows three buttons, Path, Start, End, and Done. Each runs Rhino's `_Sketch`. For Start and
  End the view's construction plane is set to that end's plane for the stroke and restored after,
  so the document is left as it was.
- Strokes show as thin dark lines, the one being drawn thicker. Blue stays reserved for the ghost.
  Strokes are deleted after Done.
- After Done the card is as today: one sentence, the waste line, Accept, Reject, Why?.
- An accepted plate becomes the current member; the next strokes edit it. Record > Undo goes back one.

## Tests

- `tests/vectors_plate.json`, generated by the core and shared with the Rhino client: no strokes
  (the straight 2x4, buildable as drawn); path only, an arc up; profiles only, 30 degrees of twist;
  a twist too large for the opening (twist eased); hold `shape` on that (conflict); a long plate
  that splits.
- A case where only the twist is eased must report `deviation_mm` above 0.
- Privacy: no geometry or machine data in any model prompt (`tests/test_privacy.py` extended).

## Open

1. Ask the technical member for real stock widths; a width limit may follow (placeholder until then).
2. Before any code: the core's `main` has an unfinished merge of `photo` (3daa02f) to commit or abort.
3. Slice 1 simplification: the current member is always the straight 2x4 (path from (0, 0, 0) to
   (2400, 0, 0), both profiles a straight 89 mm line across Y, 38 mm thick). A skipped stroke means the
   straight member's own stroke. Holding an accepted plate as the current member per episode comes later.
4. Decided (see Contract: `profile_start_on`, `profile_end_on`). Was: which end plane a profile is read on when the path is drawn in the same set of strokes: slice 1 reads
   every profile on the drawn path's end plane (its part along the path is dropped). A profile drawn on
   the old end plane is foreshortened by the cosine of the angle between the two planes (3% at 15
   degrees). "The profile moves with its end and keeps its local shape" needs the client to say which
   plane each profile was drawn on, or to send profiles already in the end frame.
5. Found in slice 1 (both now decided, see Stock and Grain): the straight 2x4 (no strokes) fits as 3 layers of 38 mm on edge, 2400 x 38 x 114 mm,
   22% waste, all of it rounding: before rounding the plane fit sees no difference between the bar's two
   orientations. And a plate wider than the opening (1400 mm) is answered in 3 pieces whose billets run
   across the plate (billet length 1400 mm): the fit does not know the grain direction. Both are the
   sc_glulam fit as every kind uses it; decide whether either needs a rule. Decided (Daniel, 2026-11-14):
   grain follows the path (section above); the 1400 mm plate is now the grain conflict.
6. Speed, measured in slice 1: one full fit of a plate (1,950 points, plane sample 250, 20 evaluations,
   as kind part fits) takes 0.6 to 0.9 s here, not 3.5 s. Under 1 s the speed section allows plain
   bisection for slice 2; confirm the fit settings before relying on it.
