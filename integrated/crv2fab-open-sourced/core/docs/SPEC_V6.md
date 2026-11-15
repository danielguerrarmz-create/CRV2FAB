# GNJ shared spec v6: one source of fabrication logic, user inputs, own geometry

Decided by Daniel on 2026-11-14 after reviewing the CRV2FAB drop (`incoming/dalalaaryan`, the
Timber Surface Curvature Analyzer) and the technical member's Grasshopper package (`sc_glulam`
and its canvas `unnamed.gh`).

## 1. One source of billet logic

Three copies of the billet maths exist: the technical member's `sc_glulam` (Python), the
analyzer drop's `billet.js` (a JavaScript rewrite of the same method), and our core calling the
first. Daniel: simplify, "following the core logic created by our technical member".

- `sc_glulam/glulam_math.py`, vendored unmodified, is the ONLY billet and waste logic the core
  uses. No second implementation, no hand-rolled variant, in any language, in anything we build
  from here on. A client that needs a billet number asks the core.
- The frozen browser sketchpads keep their old stand-in rules and their label. They are not
  extended.
- The analyzer drop belongs to its author; we do not edit it. Its curvature analysis and
  displays are content for our technical view (section 5). Its `billet.js` is not used by us.

## 2. Settings the user sets, and sees

Adopted from the analyzer drop's inputs. `GET /settings`, `POST /settings` (partial update),
kept for the session and written into every record entry they affected.

| Setting | Default | Notes |
|---|---|---|
| `lam_options_mm` | [38, 17, 11] | Adopted from the analyzer drop: 2x stock as is, ripped in two, ripped in three. Replaces [38, 25, 19, 12, 8]. Thinnest piece is therefore 11 mm. |
| `lam_ratio` | 125 | Minimum radius / layer thickness. Their shared default, still to confirm with a supplier. |
| `allowance_mm` | 0 | Machining allowance per face, passed to the billet fit as their functions take it. |
| `max_waste_pct` | null | The waste target. Off until the user sets it. |
| `opening_mm` | [1200, 280] | CNC opening width and height. Generic placeholder from the analyzer drop. |
| `max_length_mm` | 18000 | Reported against, as their code does. |
| `max_pieces` | 4 | Upper limit for splitting (section 4). |
| `billet_curve` | "variable" | Added 2026-11-14 (Daniel: "Use his variable-curvature billet"). "variable": after the constant-radius fit, refine the spine with the vendored `fit_freeform_2d` (their variableCurvature mode, `spine_control_points` default 6), so the pressed billet's curve follows the part. "constant": their default, one radius. Applies to every kind. Reason: a sculpted bend is a hump, not an arc, and a constant-radius billet around one bend wasted 62%. To confirm with the technical member that a shop can press it. |

Machine data: the default opening is the generic placeholder above, so the repo carries no
company-internal data. The technical member's named machine table moves out of the tracked
tree into an optional, git-ignored `private/machines.json`; when that file is present the core
offers those machines by name through `GET /settings` and a setting `machine` selects one. The
earlier `GNJ_SHOW_MACHINE` switch is dropped: an opening the user typed is the user's own input
and is shown plainly; a named private machine shows its name only on the machine that has the
private file. Note in the README that earlier local commits still contain the table, so this
repo's existing history must not be pushed; publishing means a fresh history.

The waste target, when set, is a check like any other, because the user asked for it:
- A proposal over the target tries, in order: a thinner layer option, then splitting
  (section 4). It never moves the designer's line or geometry to save material.
- If nothing meets it: no ghost is withheld. The proposal is shown with the sentence ending
  "Waste N%, over your T% target." and one Why step saying what the best reachable figure is
  and how (for example "3 pieces would reach 41%").
- With no target set the agent reports waste and does nothing about it, as today. The
  chat-only `less_waste` action is unchanged.

## 3. Own geometry: intent kind `part`

"One of the inputs that users should be able to do is input their own geometries to then be
developed into buildable parts", using the technical member's logic.

Request intent: `{ kind: "part", member_id, points: [[x,y,z], ...], volume_mm3 }`, mm, Z up.
`points` are surface samples of the designer's own closed solid (300 to 6000 points; the client
takes them from Rhino's mesh of the object). `volume_mm3` is the solid's own volume from Rhino.

The core treats it exactly as their Grasshopper flow does: fit the minimum-volume singly curved
billet around the points (`fit_bending_plane`, `fit_arc_2d`, `billet_extents`), walk the layer
options for the bend check (`offset_radii`), check the opening (`min_width_box`), report waste.
The geometry is the designer's and is never altered. What the agent may change is how it is
made: the layer option, and the number of pieces.

Sentences:
- "Buildable as modelled. Pressed in one curve from N layers, then milled to shape."
- With pieces: "Buildable as modelled, in P pieces joined end to end. Each pressed from layers,
  then milled."
- Not buildable: "This part bends too tightly for the thinnest layer." or "This part will not
  fit through the machine, even in P pieces." Stated as a finding, with the tightest radius or
  the overshoot in the Why steps. No ghost of a changed shape is offered for a `part`.
Waste line, tally, holds `solid` (one straight piece, no pressing) and `less_waste` apply.
Hold `shape` is meaningless here and is ignored with the reply "Your geometry is never moved."

Response form `kind: "part_plan"`: per piece the billet (mode, size, radius, lam count and
thickness, outline polylines, waste), the cut positions, totals, and the checks.

## 4. Splitting a member into shorter billets

One singly curved billet must enclose the whole member. Over a long doubly-curved member the
sideways drift and the twist add up, so the block grows wide and deep, the waste climbs and the
block may not fit the machine. Cutting the member into shorter pieces lets each piece have its
own billet, in its own best bending plane, hugging it closely. Waste and block size fall; the
price is a joint at each cut, which is a structural matter for the engineer.

- Pieces are equal lengths along the member (surface_stroke: by station; part: by position
  along the principal length axis). P runs 1, 2, ... `max_pieces`. Each piece is fitted and
  checked on its own; waste is the volume-weighted total.
- Splitting is tried ONLY to satisfy a failed machine check or a waste target the user set, or
  when the designer says so in words (new /say action `hold split_ok`: "split it", "shorter
  pieces are fine", "joints are ok"; then the fewest pieces that satisfy the checks, or with
  `less_waste` also set, the piece count with the least waste). Never to shave waste unasked.
- Order of remedies everywhere: layer option, then pieces, then (surface_stroke only, never
  for waste) straightening the line.
- The sentence states the piece count. Each joint is listed in the Why steps and the record
  with the words "joint to be designed by the engineer".
- Clients draw the cuts as thin lines across the blue ghost.

## 5. Technical view (clients)

Off by default. One small link beside Why and Record: "Technical". When open it shows:
- The settings of section 2 with their current values, editable where a number makes sense
  (waste target, allowance, opening, bend ratio); a change re-solves the current proposal.
- The numbers behind the current proposal: billet size, radius, layers, tightest layer radius
  against the limit, opening needed against available, waste with its rounding share, twist.
- In the viewport, only while it is open: billet outlines, cut lines, and (surface kinds) the
  host surface coloured by curvature type and tightest radius, following the analyzer drop's
  classification (flat, singly curved, dome, saddle). Details of this display wait on the
  review inventory of that drop.
The panel at rest does not change: one sentence, the waste line, Accept, Reject, Draw.

## Tests (core)

Layer list change re-pins the saddle cases (list every number that moves). Settings round trip
and appear in the record. No tracked file contains a named machine (assert by scanning the
tree for every name in the private table when that file exists locally). Waste target: met at
rung 0; met by a thinner layer; met only by splitting; unreachable gives the over-target
sentence and the best-reachable step; never moves the line. Part: the analyzer drop's own
reference (an arc beam, R 6000, 400 deep, 200 wide, 60 degrees, 40 mm lams) returns radius
6000 within 5, depth 400, width 200, 10 lams; a doubly curved part that needs 2 pieces to fit
the opening; a part too tight for 11 mm layers is a finding, not a ghost. Splitting: P pieces
have less total waste than 1 on a twisting member; `split_ok` by words; joints appear in the
record. Speed budgets hold with splitting (measure and report).
