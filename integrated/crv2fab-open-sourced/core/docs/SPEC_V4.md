# GNJ shared spec v4: the real fabrication route (sc_glulam)

Decided by Daniel on 2026-11-14: go with the teammate's direction. The teammate's package at
`C:\Users\danie\Downloads\sc_glulam\sc_glulam` defines how a doubly-curved timber is actually
made and checked. It replaces the placeholder limits for surface drawing. Read its README.md
first; it is the authority on the method. This spec only says how our agent uses it.

Scope: intent kind `surface_stroke` only. The straight-timber `bend` kind and taste stay exactly
as they are today (still placeholder rules, and said so). Everything in spec v3 about reading the
stroke stays: the surface grid, cleaning, trimming to 2400 mm, the smoothing ladder, nearest-point
deviation, holds, the one-sentence answer.

## The route (theirs)

One **singly curved** glulam billet is pressed: a constant rectangular section swept along a
planar spine, lamellas stacked in the bending plane. The billet is then **CNC milled** down to
the doubly-curved member. So the sideways curve and the twist of the member are not glued in.
They are milled out of a bigger billet. Their cost is waste and billet size.

What v3 called "strips" and "glued both ways" does not exist in this route. Remove it from
surface answers.

## Using their code

- `glulam_math.py` is numpy-only and Rhino-free. Use it as it is. Vendor an unmodified copy in
  the core repo under `vendor/sc_glulam/` with a short NOTICE naming the source path and the
  date copied. Do not edit it. If something in it looks wrong, report it; do not patch it.
- `glulam_billet.py` needs Rhino. Do not import it. Re-express the few Rhino-free pieces we need
  (the machine check, the lam check, the waste figure) in our own module, following its logic
  line for line, and cite the function each one mirrors.
- The machine table (`glulam_billet.MACHINES`) cites the teammate's internal company knowledge
  base. Copy it into a local data file in the core repo, keep its source strings, and never put
  it in the browser mock, a published page, a prompt sent to the model, or any outside service.
  The model sees none of it: no machine name, no opening size, no source string. (Tightened
  2026-11-14 after review: the keyless model path runs under Daniel's personal subscription
  with his account attached, so company-internal data must never enter any prompt. If the
  model-proposes path is switched on, it is told only whether its proposal passed or failed
  and which check failed, in generic words.)

## The check, for one candidate line

1. Build the member: the 38 x 89 section swept along the candidate stations using the surface
   normals (as in v3). Sample its surface as points: the 4 corner curves at all 65 stations.
2. Fit the billet around those points with their functions: `fit_bending_plane`, then
   `fit_arc_2d` (constant radius, their default). Allowance 0 mm unless configured.
3. For a lamella thickness t: `billet_extents` gives depth rounded up to whole lams, width,
   length and lam count; `offset_radii` gives each lam's tightest radius.
4. Bend check: every lam has R / t >= the ratio limit. Default 125 (their default, flagged in
   their README as not yet confirmed). A limit card, source "sc_glulam default, confirm".
5. Machine check: the billet's smallest cross-section (`min_width_box` width of its in-plane
   outline, by the billet width) must fit the selected machine's opening in either orientation,
   mirroring `check_machine`. Default machine: the first in their table. Config picks another.
   Length is reported against the machine maximum, not judged, as in their code.
6. Waste: (billet volume - member volume) / billet volume, reported as a percentage. Not judged.
7. Also report their CSA O86 Kx figure for the tightest lam, as they do. Not judged.

## Solver order (same philosophy as before)

Keep the drawn line. Change the make-up first. Move the line last.

- Lamella ladder, thickest first: [38, 25, 19, 12, 8] mm (placeholder stock list, a card).
  For a given line the billet fit does not depend on t, so fit once and walk the ladder.
- For the drawn line (rung 0): the thickest t that passes the bend check, provided the machine
  check passes. If that works, deviation 0.
- Otherwise straighten along the v3 smoothing ladder. Use bisection over the rungs rather than
  trying every rung, since each rung needs a billet fit. Take the least straightening at which
  some t passes both checks.
- No rung passes: conflict, naming the real cause. Bend: "This bends too tightly for the
  thinnest layer." Machine: "This billet will not fit through the machine."
- Hold `shape` (keep my line): rung 0 only.
- Hold `solid`: no pressing. A straight billet (their zero-curvature case) of one piece, milled
  to shape. The bend check does not apply; the machine check decides. If it fails, straighten;
  if nothing passes, conflict "This will not mill from one straight piece on this machine."
- Budget: a fallback answer within about 5 seconds worst case on this machine. Measure it. If
  the fit is too slow, reduce the sample or the optimiser's evaluation count in OUR call
  arguments (not by editing their file) and say what you chose.

## The model's part

Unchanged in spirit. The model proposes `{ smoothing_passes, lam_mm, straight_billet, sentence,
steps }`. The core builds, fits and checks. Closeness rule as before, per lead.

## What the designer reads

One sentence, plain, no dashes, no numbers except millimetres moved:
- "Your line holds. Pressed in one curve from N layers, then milled to shape."
- Straightened for bend: "Line straightened by X mm so the layers can bend, N layers, then milled."
- Straightened for machine: "Line straightened by X mm so the billet fits the machine."
- Solid held and passing: "Your line holds. Milled from one straight piece, no bending."
- Trimmed adds: "Kept to the 2.4 m stock length."

Why steps carry the rest, in plain words: billet size (length x width x depth), lam count and
thickness, tightest lam radius against the limit, machine name with needed and available
opening, waste percentage, twist (now described as milled out, no longer "no limit yet").
The formal record sentence carries all of it.

## Waste is on the panel (Daniel, 2026-11-14, after using the Rhino panel)

"With every accepted design decision we should begin to see the material waste per our
teammate's definition." So waste is not hidden under Why. It is the one number the panel shows.

- Every proposed form, of BOTH kinds (surface_stroke and bend), carries
  `checks.waste_pct`, `billet.volume_m3` and `part_volume_m3`, computed the teammate's way:
  billet volume minus part volume, over billet volume, with the share caused by rounding up to
  whole lamellas available separately (`waste_rounding_pct`), mirroring their `wastage`.
  For the bend kind, fit the billet around the bent member with the same vendored functions and
  report waste only; the bend kind's own pass or fail rules do not change today.
- The response also carries a running tally of accepted decisions in this record since the last
  reset: `tally: { members, billet_m3, part_m3, waste_pct }`, volume-weighted. `GET /tally`
  returns the same. `POST /taste/reset` does not clear it; `POST /tally/reset` does.
- Panel, one quiet line under the sentence while a ghost is proposed: "Waste 61% of the billet."
  After Accept the line becomes the tally: "Accepted so far: 3 members, 58% waste." One line,
  no chart, no table. Whole percentages.
- The formal record sentence states billet volume, part volume and waste for the decision.
- If numpy or the billet fit is unavailable, the line is omitted. Never show a made-up number.

## Response additions (form, kind `surface_member`)

Keep every v3 field that still applies (stations, normals, uv, intent_stations, length_mm,
smoothing_passes, deviation_mm, trimmed, max_twist_deg_per_m). Remove n_strips / strip_mm for
this kind. Add:

```
"n_lamellas": 5, "lamella_mm": 19.0,
"billet": { "mode": "arc" | "straight", "length_mm": .., "width_mm": .., "depth_mm": ..,
            "radius_mm": .. | null, "volume_m3": ..,
            "outline": [[[x,y,z], ...], ...] },          // a few closed polylines, world mm
"checks": { "bend":    { "ok": true, "tightest_radius_mm": .., "ratio": .., "limit": 125 },
            "machine": { "ok": true, "name": "..", "need_mm": [w, h], "opening_mm": [w, h],
                         "orientation": "flat" | "on edge" },
            "waste_pct": 61.3, "kx": 0.98 }
```

Clients: the blue ghost is still the member. It carries no glue lines in this kind (where the
glue planes cut the finished part is a later step). The billet `outline` may be drawn as thin
lines only while Why is open; never by default.

## Not in scope

Variable-curvature billets, springback, in-feed handling, their Grasshopper components (they
need Rhino 8, which Daniel does not have), the bend kind, taste.
