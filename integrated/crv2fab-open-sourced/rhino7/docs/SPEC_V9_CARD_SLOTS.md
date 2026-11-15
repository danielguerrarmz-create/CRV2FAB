# SPEC V9 CARD SLOTS: the fixed-slot card and its wording

Approved by Daniel, 2026-11-15, from the synthetic study. Core sentences read from `gnj-nudge-core` main b514e62 (`plate.py`, `part.py`, `surface_solver.py`, `pieces.py`, `say.py`, `photo.py`). This replaces the card table in `SPEC_V9_UI.md`; the panel and mechanics there stand unless noted below. Copy rules apply: no em or en dashes, no colon reveals, no comma tails, plain words.

## Slots (280 px card, fixed order, an empty slot takes no height)

| # | Slot | Rule |
|---|---|---|
| 1 | Echo | muted, optional, 1 line, max 34 chars. What the core heard. Cleared on the next move |
| 2 | Verdict | bold, 1 line, max 28. The state line |
| 3 | Reason | max 2 lines of 34, one clause, no numbers |
| 4 | Facts | muted, 1 line, max 42 chars, order Waste, Moved, Needs |
| 5 | Actions | buttons and the Say box, per state |
| 6 | Links | `Why?   System` |

Glossary for every user-facing word: member, piece, billet, layer. Retired in text a person reads: plate, lamella, stock, "holds" as a verdict. `Hold` stays only as the feature (the Keeping row).

Verdict values for a proposal: `Buildable as drawn.` / `Buildable, eased.` / `Not buildable.` A user's own solid is never drawn, so it reads `Buildable as modelled.` (22 chars). Other states use slot 2 for their state line (idle, thinking, rejected, accepted, no answer).

## Facts (slot 4)

Format `Waste N%` then `Moved N mm` then `Needs N layers` or `Needs N pieces`, two spaces apart. At most 42 chars.

| Part | Reads | Shown when |
|---|---|---|
| Waste | `waste_pct` (top level), else `checks.waste_pct` | always; if over target `Waste N%, over target` |
| Moved | `deviation_mm`, whole mm | 1 or more; the one "how far" number anywhere |
| Needs | `n_pieces` or `len(pieces)` when above 1, else `n_lamellas` | always; `straight_billet` true or `billet.mode` "stock" reads `Needs 1 piece` |

Over target is today a sentence suffix (", over your N% target."). Needs-field `checks.waste_ok` exists on parts only.

## Verdict and Reason by core sentence

Verdict rule for plate and surface: status `proposed` with every `eased` scale at 1 (surface: `smoothing_passes` 0) reads `Buildable as drawn.`; any eased reads `Buildable, eased.`; status `conflict` reads `Not buildable.` Part proposals read `Buildable as modelled.`

**Proposed, kept as drawn** (Facts per table)

| Core sentence (plate, surface, part) | Reason |
|---|---|
| Pressed in one curve from N layers, then milled to shape. | Pressed in one curve, then milled. |
| Glued straight from N layers, then milled to shape. | Glued straight from layers, then milled. |
| Milled from one straight piece, no bending. | Milled from one straight piece. |
| in P pieces joined end to end. Each pressed from layers, then milled. | Made in pieces joined end to end. |
| One stock 2x4, no pressing. (plate) | One piece as it comes, no pressing. |

Prefix "Your shape holds." / "Your line holds." is dropped; "Buildable as modelled." (part) is the Verdict.

**Proposed, eased** (plate). Reason is `{What} eased so it {cause}.` What joins the eased scales in the core's order (Twist, Profiles, Path drift, Path), for example "Twist and profiles eased". Path alone reads "Path straightened". The number in the core sentence ("moving the plate at most N mm") goes to Facts as Moved and never to Reason.

| Core cause phrase | Reason ends |
|---|---|
| so the billet fits the machine | so it fits the machine. |
| so the layers can bend | so the layers can bend. |
| so the billet runs along the grain | so it runs along the grain. |

**Proposed, eased** (surface). Core: "Line straightened by X mm so ...". Reason: "Line straightened so it mills from one straight piece." / "Line straightened so the layers can bend." / "Line straightened so the billet fits the machine." X goes to Moved.

**Over target.** The Verdict is unchanged. Reason is the made-as clause above. Facts shows `Waste N%, over target`.

**Trimmed.** Core suffix "Kept to the 2.4 m stock length." goes to Echo as `Kept to the timber length.` (26 chars).

## Conflicts: Verdict `Not buildable.`, one next action

| Core sentence | Reason | Action (one button) |
|---|---|---|
| This bends too tightly for the thinnest layer. | It bends too tightly for the thinnest layer. | Redraw |
| This billet will not fit through the machine. | The billet is too big for the machine. | Redraw |
| The billet cannot run along the grain at this width. | The billet cannot run along the grain at this width. | Redraw |
| This will not mill from one straight piece on this machine. | One straight piece will not fit the machine. | Release the hold |
| This shape could not be fitted with a billet. | No billet fits this shape. | Redraw |
| This part bends too tightly for the thinnest layer. | Your part bends too tightly for the thinnest layer. | Check another part |
| This part will not fit through the machine (even in P pieces). | Even in pieces your part is too big for the machine. | Check another part |
| This part will not mill from one straight piece on this machine. | Your part will not mill from one straight piece. | Check another part |
| This part could not be fitted with a billet. | No billet fits your part. | Check another part |

Rules. If hold `shape` is on, the action is `Release the hold` for every plate or surface conflict, because easing was blocked. `Redraw` opens the stroke row in place. The Say box is hidden on a conflict (it stays in the panel), which leaves one action. Facts is empty.

## Echo (slot 1) from /say and /photo

The client maps by the reply's `actions` list, not by text, so the core keeps its longer lines for the command line.

| Action or reply | Core line | Echo |
|---|---|---|
| hold solid | Keeping it as one piece. | Keeping it as one piece. |
| hold shape | Keeping your {word} as drawn. | Keeping your {word} as drawn. |
| release solid | Glue is fine again. | Glue is fine again. |
| release shape | Your {word} may move again. | Your {word} may move again. |
| hold less_waste | Using thinner layers to waste less. (35) | Thinner layers, less waste. |
| release less_waste | Back to the thickest layers that bend. (38) | Back to the thickest layers. |
| hold split_ok | Shorter pieces are fine; joints to be designed by the engineer. | Shorter pieces are fine. |
| release split_ok | Keeping it in one length. | Keeping it in one length. |
| nothing to save | Already as little waste as this {word} allows. (45) | Already the least waste. |
| no action | I did not catch a change I can make. ... | I did not catch a change. |
| part, hold shape | Your geometry is never moved. | Your geometry is never moved. |
| photo, N bends | Read from your photo: a strong bend up along the whole length. | Photo read: strong bend up. (N above 1: Photo read: 2 bends.) |
| photo, none | Read from your photo: a straight member, no bends. | Photo read: no bends. |
| photo not read | I could not read a timber shape from this photo. | Photo not read. (Reason carries the full line) |

{word} is shape (plate), line (surface), part. The engineer joint note and the photo span go to the panel (Pieces row, Inputs Photo row).

## Other states

| State | Verdict | Reason | Actions |
|---|---|---|---|
| idle | Draw the shape you want. | Path, start and end. Skip any you do not need. | stroke row, `Photo`, `My solid` |
| thinking | Finding the closest buildable shape. | none | none |
| rejected | Rejected. | I will not guess again. Redraw, or say what to keep. | row A `Redraw`; row B `Keep my shape` `Keep it as one piece`; row C Say box and `Say` |
| accepted | Accepted and recorded. | Draw again to change this member. | stroke row |
| no answer | No answer yet. | The helper is not running. | `Try again` |

**Rejected trim.** The study counted 8 or more controls (3 stroke buttons with stale statuses, Done, 2 holds, Say box, Say, plus links). Now `Redraw` alone stands for the stroke row until pressed (it then expands in place of row A), stale statuses and Done are hidden, and the holds use the glossary ("one piece", not "one solid piece"). Visible at rest: Redraw, two holds, one box with its button, two links. That is five controls and two links, from ten. Pressing a hold or Say leaves the card in the same slots with the new Echo.

## Panel: This proposal, aligned to the glossary

Section title `This member`. Rows in order, from the same mapping as the card so the words match.

| Row | Text | Reads |
|---|---|---|
| Verdict | the card's Verdict and Reason joined | as above |
| Bend | Pass or Fail, "layers bend to N m, limit N m" | `checks.bend.tightest_radius_mm`, `limit` x `lamella_mm` |
| Machine | Pass or Fail, "billet N x N mm, opening N x N mm" | `checks.machine.need_mm`, `opening_mm` |
| Grain | Pass or Fail, "N degrees off the path, limit N" | `checks.grain.angle_deg`, `limit` (plate only) |
| Made as | one piece as it comes / one straight piece / pressed in one curve from N layers of N mm / N pieces joined end to end | `billet.mode`, `straight_billet`, `n_lamellas`, `lamella_mm`, `pieces` |
| Waste | N% | `waste_pct` |
| Largest move | N mm | `deviation_mm`, hidden at 0 |

The old Pieces row goes (it lives in Made as). Members grid Kind column reads `drawn` (plate), `on surface` (surface), `own solid` (part), never "plate". Strips and lamella wording goes (bend-kind leftovers).

## Where the core must change, and where the client maps

| Change | Who | Why |
|---|---|---|
| Replace "Your shape holds." and "Your line holds." with "Buildable as drawn." | core (`plate.py:507-513`, `surface_solver.py:415-420`) | "holds" collides with Hold and reads as strength. The client accepts both forms until it lands |
| Say "member" for "plate" in user text ("moving the plate at most", "The plate sits at most", "A plate from ...") | core (`plate.py:796`, Why step, `heard_text` at 529) | glossary |
| "One stock 2x4, no pressing." becomes "One piece as it comes, no pressing." | core (`plate.py:558`) | stock retired |
| Add a top-level `over_target` boolean | core (`pieces.py:732`) | until then the client matches the exact suffix ", over your N% target." |
| Add `ease_cause` ("bend", "machine" or "grain") | core, optional | until then the client matches the three fixed phrases in `EASE_WHY` |
| Verdict, Reason, Facts, Echo shortening, conflict actions, panel wording | client | pure templates on fields and exact sentences |

Fallback. A sentence the client table does not know shows the core sentence in the Reason slot, cut to 2 lines, and the command line logs "GNJ: unmapped sentence". Test. Every sentence in `tests/vectors_plate.json` and `tests/vectors_part.json` must map to a Reason with no fallback, no number in Reason, and Verdict at most 28 chars, Reason at most 68, Echo at most 34, Facts at most 42.

## Open

- Part Verdict `Buildable as modelled.` is a fourth value. Say yes or ask for `Buildable as drawn.` on parts too.
