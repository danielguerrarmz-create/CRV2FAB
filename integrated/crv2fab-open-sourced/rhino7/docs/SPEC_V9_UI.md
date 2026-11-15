# SPEC V9 UI: the Rhino 7 card and System panel

Approved direction, Daniel, 2026-11-14. Core contract: `gnj-nudge-core` `docs/SPEC_V9.md` and README. Copy rules: no em or en dashes, no comma tails, no colon reveals, no scare quotes, plain words. Units mm in, metres shown past 1000 mm as today (`gnj_tech._m`).

## Rules

- Blue (38,104,214) is the ghost only. Never on text, headers, links, bullets or strokes. Links are plain text, underline on hover.
- Strokes: thin dark (30,30,30), 1 px; the one being drawn 3 px. Layer GNJ::Gesture. All strokes are deleted after Done. After an answer, the dashed dark `intent_grid` outline shows what was read (1 px).
- Accepted members bake in `TIMBER_COLOR` (common.py:40). Cut lines `CUT_COLOR`. Conflict text `CONFLICT_TEXT`.
- Only `deviation_mm` appears as a "how far it moved" number: "Largest move N mm", shown only when above 0. Eased scales (`eased.path/drift/twist/profiles`) appear only as words in Why?, never as numbers.
- After Reject nothing is sent until a stroke is redrawn, a hold changes, or Say returns.

## Card (Mode 1), 280 px wide, one column, height fits content

Every state ends with the links row `Why?   System`. Why? lists the core `steps` as today.

| State | Headline (bold) | Sub (muted) | Controls |
|---|---|---|---|
| idle | Draw the shape you want. | Path, start and end. Skip any you do not need. | stroke row (below), then `Photo` and `My solid` links (My solid only with a closed solid selected) |
| drawing a stroke | Path / Start / End status per below | Drag in any view. Press Esc to cancel the stroke. | stroke row, Done disabled until one stroke is drawn |
| thinking | Finding the closest buildable shape. | none | none, links only |
| proposed | core `sentence` | `Waste N% of the billet.` then `Largest move N mm.` on the same line | `Reject` (secondary) `Accept` (primary: filled dark, never blue), stroke row collapsed to one `Redraw` link |
| conflict | core `sentence`, red | Release a hold, redraw a stroke, or say what to change. | holds row if any, Say box, stroke row |
| rejected | Rejected. I will not guess again. | Redraw a stroke, or say what to keep. | `Keep my shape` `Keep it as one solid piece` (hold `shape`, hold `solid`), Say box and `Say`, stroke row |
| accepted | Accepted and recorded. | Draw again to change this member. | stroke row |
| saying / reading photo | Working out what you meant. / Reading your photo. | photo adds: Your photo is sent to Claude to be read. | none |

**Stroke row** (replaces single Draw): three equal buttons `Path` `Start` `End`, each with a status line beneath: `not drawn`, `drawn`, or `kept as is` once Done has sent with it skipped. Below them `Done` (primary) and `Cancel` link. Pressing a drawn stroke redraws it (last one counts). Done sends `POST /nudge` kind `plate`. Cancel discards undrawn strokes and returns to the last state.

**Holds row** while a hold is on: `Keeping: my shape   release` or `Keeping: one solid piece   release`. Release re-sends. Hold `shape` and `solid` go in `holds`.

**Fields read:** `sentence`, `waste_pct`, `deviation_mm`, `steps`, `status`, `form.checks`.

## Panel (Mode 2), docked tab "CRV2FAB"

Designed for 300 px. No page scroll. Only Members and Record scroll, inside themselves. Section header: plain bold text with a small chevron (right closed, down open), whole row clickable, no blue, no underline. Open by default: Inputs, This proposal, Members. Closed: Settings, Show, Record. State kept for the Rhino session.

Real docked width is about 170 px. Below 250 px: label sits above its value; check lines wrap to two lines; values wrap and are never cut with an ellipsis; Members shows `Member` and `Waste` only; Settings boxes take the full width; Show checkboxes wrap. A number is never truncated.

**1 Inputs**
- `Drawing`: `Path drawn, Start kept as is, End drawn` (from the last sent strokes) or `none yet`. `Redraw` link opens the card stroke row.
- `Model`: scene name or the checked part's name (`part` kind).
- `Photo`: file name or `none`; `Open` link runs the photo dialog (JPEG or PNG, 8 MB), sends `POST /photo` with bytes.
- `Say`: text box and `Say` button, `POST /say`. Same behaviour as the card box.

**2 This proposal** (`No proposal on screen.` when none). Lines from `form.checks`:
- `Bend` `Pass` or `Fail`, then `tightest layer N m, limit N m` (`checks.bend.tightest_radius_mm`, `limit` x `lamella_mm`).
- `Machine` `Pass` or `Fail`, `N x N mm in N x N mm` (`checks.machine.need_mm`, `opening_mm`).
- `Grain` `Pass` or `Fail`, `N degrees, limit N` (`checks.grain.angle_deg`, `limit`). Plate kind only.
- `Made as` `stock board`, `one straight piece`, `pressed in one curve from N layers of N mm`, or `N pieces` (`billet.mode`, `n_lamellas`, `lamella_mm`, `pieces`).
- `Waste` `N%` (`checks.waste_pct`); `Pieces` `N` (count of `pieces`, else 1); `Largest move` `N mm` (`deviation_mm`, hidden at 0).
- Part and surface kinds use their own forms; show the same lines that exist and hide the rest.

**3 Members**: grid `Member, Kind, Length, Layers, Waste` (as `OUTPUT_COLUMNS`), selecting a row selects that member in Rhino, view unmoved. Under it `Accepted so far: N members, N% waste.` The grid has no fixed empty floor; it grows to its rows, then scrolls.

**4 Settings** (`GET /settings`, `POST /settings` only what changed, then re-solve): `Thickness` mm (`thickness_mm`), `Layer options` mm, `Bend ratio`, `Allowance` mm, `Waste target` %, `Machine opening` mm, `Max length` mm, `Max pieces`. One `Apply`. While the core has not answered, the section says `Loading settings.` and on failure `Settings are not available. Is the helper running?` The source tooltip stays.

**5 Show**: `Billet outline`, `Cut lines` (enabled only with cuts). A `Surface` group (`Curvature type`, `Tightest radius`, legend) appears only when the scene is a surface.

**6 Record**: formal text newest first, as today. Links `Undo last accept` and `Start over`. Undo is enabled only after an Accept.

## Rhino mechanics (decided)

- Strokes run `_Sketch` in the clicked view. Path: send 3D points as drawn; the core projects. Start and End: set the active view's construction plane to `end_frames.start` or `end_frames.end` of the current member (origin, `across`, `normal`) for that stroke, restore the previous plane after, so the document is as it was. Send `profile_start_on` / `profile_end_on` `"member"` when drawn on the current member's end plane.
- Strokes are fixed in 3D when drawn and the designer may orbit between them. Done deletes every stroke object; nothing else is written to the document.
- Ghost: plate form drawn by the conduit from `grid`, `normals`, `thickness_mm`; the dashed `intent_grid` outline in dark. The ghost is never in the document until Accept.
- Accept bakes one group in `TIMBER_COLOR` on GNJ::Buildable, one undo record "GNJ Accept", and the plate becomes the current member (store the answer's `end_frames`).
- Undo last accept: `POST /undo` with body `{}`. On success (`{undone: {member_id, timestamp, kind}, tally}`): delete that member's baked ids, restore the previous current member and its `end_frames`, add a Record line `Undid the last accept.`, return the card to idle, and show the returned `tally` in the card and panel tally lines. Repeated Undo walks back one accept at a time. On 409 the card shows `Nothing to undo.` and nothing else changes.

## Cut list (gnj-rhino7)

| Remove or change | Where |
|---|---|
| Single Draw button, `_Sketch` once, read as one curve | card.py:59, 452-463 (replace with stroke row), 465-481 `use_gesture` (rewrite per stroke) |
| Sculpt branches on Accept, tally reset, photo reset | card.py:193-195, 375-377, 494-507 |
| `undo_bend` | card.py:509-530 (rewrite as Undo last accept); system.py:113-119 |
| Hold labels "Keep it solid", "Keep my <word>" | card.py:66-67 (new labels above); core `hold_label` |
| Bend reading, sag on plane, sculpt reading | gesture.py:13-114, 144-227 (keep `_curve_points` at :9; grep that SurfaceScene does not call the rest first) |
| Bend and sculpt scene | scenes.py:17-32, 34-154 (BendScene becomes the plate scene); keep SurfaceScene :156-290 |
| Sculpt constants, intents, responses, session state | gnj_core.py:38, 55, 364-400, 449-450, 699-720, 772-790, 1012, 1040, 1152-1160, 1176, 1197-1225 |
| Bend-era copy | gnj_core.py:970-995 (`COMMAND_LINE`, `HEADLINE`, `SUBLINE`); use the card table above |
| `Twist` row; `Moved from your line` becomes `Largest move`; readout becomes check lines | gnj_tech.py:115-163 |
| `inputs_in_force` fallback and `SET_IN_CORE` | gnj_tech.py:165-176; system.py:20, 224-231 |
| `gesture_summary` bend wording | gnj_tech.py:252 (three-stroke summary) |
| Panel width 460, `CAPS` and nested scrolls, link headers, glyphs | system.py:13, 17, 137-146, 157-158, 180; section list :31-32 |
| Display keys and legend into a Surface group | system.py:24-26, 104-105, 261-275 |
| Inputs rows | system.py:191-192 |

## Acceptance checks (screen states)

1. Idle: card shows "Draw the shape you want.", three stroke buttons all `not drawn`, Done disabled. `v9-card-idle.png`
2. Press Path, draw, release: a thin dark stroke stays, Path shows `drawn`, Done enabled. Orbit: the stroke stays in place. `v9-card-path-drawn.png`
3. Press Start: construction plane visibly changes to the end plane; after the stroke it is back to the prior plane (check the CPlane name). `v9-start-plane.png`
4. Done: card shows "Finding the closest buildable shape.", strokes gone from the document (object count unchanged from before drawing), then blue ghost plus dashed dark outline. `v9-card-proposed.png`, `v9-persp-ghost.png`
5. Proposed card shows one sentence, waste line, `Largest move N mm` only when above 0, Accept filled dark. `v9-card-proposed-eased.png`
6. Reject: ghost gone, "Rejected. I will not guess again.", two hold buttons, Say. Wait 10 s: no new ghost. `v9-card-rejected.png`
7. Keep my shape on a case that needs easing: red conflict sentence, `Keeping: my shape   release`. `v9-card-conflict.png`
8. Accept: tan member on GNJ::Buildable, "Accepted and recorded.", Members gains one row. Undo last accept removes it and restores the prior state. `v9-accepted.png`, `v9-undone.png`
9. Say, Photo (path appears, no "sculpting" copy), My solid (cut lines, Accept bakes nothing): each leaves a sentence on the card. `v9-say.png`, `v9-photo.png`, `v9-part.png`
10. Panel at 300 px and at about 170 px docked: no ellipsised number, no horizontal bar, page does not scroll, headers plain with chevrons, no blue except the ghost. `v9-panel-300.png`, `v9-panel-docked.png`
11. Text search of every screen: only one "moved" number; no em or en dash.
