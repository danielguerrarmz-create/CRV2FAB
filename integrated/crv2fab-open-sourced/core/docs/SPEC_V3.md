# GNJ shared spec v3: draw on a 3D surface, get a doubly-curved member

Decided by Daniel on 2026-11-14. Main goal of the demo: a drawn stroke is formalized into a
doubly-curved timber member. The stroke is drawn on an existing doubly-curved surface, and the
member follows the surface where it was drawn.

The core (`C:\Users\danie\code\gnj-nudge-core`) is the single home of these rules. Clients (the
Rhino 7 script, the browser mock) send the surface and the stroke and draw what comes back.
v1/v2 (bend a straight timber) stay in the core unchanged as intent kind `bend`.

## Scene

- Existing shape, grey: a doubly-curved reference surface. Demo sample is a saddle,
  `z = 800 + (x^2 - y^2) / 6000` for x, y in [-1500, 1500] mm (principal radii about 3 m).
  Any untrimmed surface the designer already has may be used instead.
- Stock: one 2x4, section 38 x 89 mm, at most 2400 mm long.
- Ghost, blue and opaque: the 38 x 89 section swept along the buildable curve, lying flat on the
  surface. The 38 mm thickness points along the surface normal, the 89 mm width lies in the
  surface. Glue lines as before: layer lines on the 38 mm faces, strip lines on the 89 mm faces.
- The drawn stroke stays visible as a thin dashed line on the surface.

## Intent, kind `surface_stroke`

```
{ "kind": "surface_stroke",
  "member_id": "M1",
  "surface": { "nu": 21, "nv": 21, "points": [[x,y,z], ...] },   // row-major, u outer, mm
  "stroke_uv": [[u,v], ...] }                                     // 2 to 400 points, each in [0,1]
```

The client samples its surface on a regular 21 x 21 grid over the surface's own parameter domain
and expresses the stroke in that same normalized (u, v). Because the path lives in (u, v), every
curve the core produces lies on the surface by construction.

## Core maths

1. Surface evaluation: bicubic uniform Catmull-Rom through the grid, edge phantoms by linear
   extrapolation (P[-1] = 2 P[0] - P[1]). Normal N = normalize(Su x Sv) from the analytic
   partials of the same basis.
2. Clean the stroke: map to 3D, resample to 65 stations evenly by 3D arc length (interpolating
   u, v linearly), then 10 Laplacian passes in (u, v), lambda 0.5, endpoints fixed, resampling
   to even arc length after the passes. This is the cleaned intent; hand jitter is not intent.
3. Stock length: if the cleaned intent is longer than 2400 mm, keep the first 2400 mm and set
   `trimmed: true`.
4. At each interior station, from the 3D points (h1, h2 the neighbouring chord lengths):
   T = normalize(p[i+1] - p[i-1]); k = 2 * ((p[i+1]-p[i])/h2 - (p[i]-p[i-1])/h1) / (h1 + h2).
   Normal curvature kn = |k . N|, side curvature kg = |k . (N x T)|.
   Twist rate = |(N[i+1] - N[i]) . (T x N)| / h, reported in degrees per metre.
5. Limits (placeholder cards, same as v2): layer thickness <= 1 / (200 * max kn); strip width
   <= 1 / (200 * max kg); no piece thinner than 8 mm, so at most 4 layers and 11 strips.
   Twist is measured and reported; there is no twist limit yet (waiting on the engineer).
6. Solver, same order as always: keep the drawn shape, change the make-up first, move the
   shape last.
   - Pass count m in the ladder [0, 5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120, -1]
     (1280 to 5120 added so a long low wave is eased gently before the full straighten) = extra Laplacian
     passes in (u, v), endpoints fixed, applied to the cleaned intent (re-evened after).
     Passes update all interior points at once from the previous pass (Jacobi), not in place.
     The last rung, written -1 in `smoothing_passes`, is the fully straightened line: the
     straight (u, v) segment between the two fixed ends, re-evened. It exists because smoothing
     alone is slow on long, low waves (found 2026-11-14: a trimmed stroke holding about 1.3
     waves was refused although a straight line between its ends is buildable). Without a hold,
     a side-direction conflict is therefore only possible if even the straight segment fails.
   - Find the smallest m whose curve passes at maximum subdivision (4 layers, 11 strips). On
     that curve take the smallest n_lamellas and n_strips that pass.
   - Deviation = for each station of the chosen curve, its 3D distance to the nearest point on
     the cleaned-intent polyline (point to segment); take the largest. m = 0 means deviation 0.
     (Corrected 2026-11-14: comparing stations of the same index overstated it, because a
     straightened line is shorter and its stations slide along the length. The number must
     mean how far the ghost sits from the drawn line, sideways.)
   - Hold `shape`: only m = 0 is allowed; failing is a conflict.
   - Hold `solid`: n_lamellas = n_strips = 1 required; smallest m that passes, else conflict.
   - No m passes: conflict. Name the governing direction: normal ("The surface curves too
     tightly here for any layer we can cut.") or side ("This line turns too sharply for any
     strip we can cut.").
7. Agent: the model does not write geometry. It proposes
   `{ smoothing_passes (one of the ladder), n_lamellas, n_strips, sentence, steps }`; the core
   builds the curve and checks it. Closeness rule unchanged: accepted only if its deviation is
   no more than the solver's deviation + 0.5 mm.

## Response, status `proposed`

```
{ "status": "proposed", "source": "model" | "fallback",
  "sentence": "...", "steps": [{tag, text, limit_id}],
  "deviation_mm": 0.0, "trimmed": false,
  "form": { "kind": "surface_member",
            "stations": [[x,y,z], ...65], "normals": [[x,y,z], ...65], "uv": [[u,v], ...65],
            "intent_stations": [[x,y,z], ...65],
            "n_lamellas": 3, "lamella_mm": 12.67, "n_strips": 1, "strip_mm": 89.0,
            "min_radius_normal_mm": 3000.0, "min_radius_side_mm": null,
            "max_twist_deg_per_m": 4.2, "length_mm": 2100.0, "smoothing_passes": 0 } }
```

Clients sweep the section using `stations` and `normals` and draw the dashed intent from
`intent_stations`. Conflict responses keep the v1 shape.

## Sentences (one plain sentence, no jargon, no dashes)

- Solid passes: "Buildable as drawn, in one solid piece."
- Layers only: "Your line holds. Made from N glued layers."
- Strips only: "Your line holds. Made from N glued strips side by side."
- Both: "Your line holds. Glued both ways."
- Eased: "Line straightened by X mm so it can be built, in one solid piece." / "..., in N glued
  layers." / "..., in N glued strips side by side." / "..., glued both ways."
- Hold solid with no passing line: "The surface curves too tightly here for one solid piece."
  (The core's wording for these two is the reference; settled 2026-11-14.)
- Trimmed adds a second short sentence: "Kept to the 2.4 m stock length."
Counts for the both-ways case live in the Why steps, not in the sentence.
The formal record sentence carries everything: length, minimum radii both ways, twist, make-up,
governing limit, deviation, what it was chosen over.

## Taste: the record is read back (decided 2026-11-14, built after v3)

Two memories stay apart. Limits say what is true. Taste says what this designer likes. Taste may
choose between forms that already pass the checker. It may never change a limit or pass a form
the checker fails.

- An episode is one gesture from first proposal to Accept. Each record entry gains structured
  fields beside the formal sentence: `episode_id`, `kind` (bend or surface_stroke),
  `first_offer_trade` and `accepted_trade`, each one of `none` (buildable as drawn), `makeup`
  (shape kept, glued) or `solid` (kept solid, shape moved).
- Lead: look at the last 5 accepted episodes whose first offer was not `none`. If at least 3
  ended with `accepted_trade: solid`, the lead is `solid`. Otherwise the lead is `makeup`, the
  default order. Both numbers are named constants.
- Solver takes the lead. Lead `solid` tries the solid answer first, exactly as if "solid" were
  held. If solid is a conflict, it falls back to the makeup order without comment. A hold the
  designer sets always outranks the lead.
- A taste-led answer says so in a few words at the end of its first sentence, for example
  "Kept solid, as you usually do." It adds one Why step tagged Taste: "You kept it solid in 3
  of your last 5 decisions." The response carries `taste: { lead, because }`.
- Rejecting a taste-led answer and holding "shape" ends in `accepted_trade: makeup`, so taste
  moves back by itself.
- Closeness rule, corrected: a model answer is compared with the solver's deviation for the
  same lead, not with the default order.
- `GET /taste` returns the current lead and its reason. `POST /taste/reset` clears episodes for
  a fresh demo. No seeded or invented history.
- Tests: with a record of 3 solid episodes the same gesture that used to return glued layers
  returns solid with the taste wording; with 2 it does not; a taste lead never yields a form
  the checker fails; a designer hold overrides the lead; reset returns the default.

## Reference cases (the core pins these in tests and writes them to `tests/vectors_v3.json`)

On the sample saddle:
- A straight stroke along the x axis (v = 0.5, u from 0.15 to 0.85): layers needed, no strips,
  deviation 0.
- A straight stroke along the diagonal (u = v): normal curvature near zero, solid passes.
- A stroke with a sharp sideways wiggle: strips needed or the line is straightened; with hold
  `shape` and a wiggle too sharp for 11 strips it is a conflict.
- A stroke longer than 2400 mm is trimmed.
