# CRV²FAB: Gesture, Nudge, Judge

A Rhino plugin for freeform glued laminated timber. A designer draws a curved timber member in the
Rhino viewport. CRV²FAB answers with ONE buildable ghost of the closest member that can be pressed as
glulam billets and milled to shape, one plain sentence, and the material waste. The designer accepts
or rejects it. It directs intent; it reports waste and optimises only when asked in words.

Built at the AEC Tech Hackathon NYC 2026 by Aaryan Dalal, Daniel Guerra, Keven Zhao, Christopher
Bergeron and Adnan Agha. MIT licence.

| Folder | What it is | Runs on |
|---|---|---|
| `rhino7/` | The Rhino plugin: the "CRV2FAB - Nudge" card, the docked CRV2FAB panel, drawing, the ghost | Rhino 7 on Windows (tested); Rhino 8 expected to work, untested |
| `core/` | The rules: a local service on 127.0.0.1:8742 that turns a drawing into one buildable answer. The only place that calls a member buildable | Python 3.13 or later, with numpy and pillow |

## Install

Full steps are in `rhino7/README.md`. In short:

1. Install Python 3.13 or later.
2. From `rhino7/`, run `powershell -ExecutionPolicy Bypass -File install.ps1`. It finds `core/` beside
   it, makes a virtual environment for it and installs what it needs.
3. In Rhino, run `_-RunPythonScript "<path>\rhino7\install_rhino.py"` once. It adds the command `CRV2FAB`.
4. Type `CRV2FAB` in Rhino.

## How it works

1. **Input.** A straight timber in Rhino, your own model (a line on a surface, or a solid you
   modelled), a photo of a hand sketch, or words you type.
2. **Gesture.** Three strokes: the path, drawn in plan and again in elevation to make one doubly
   curved line, and the cross-section at each end.
3. **Nudge.** One translucent ghost, never a menu. The core fits one pressed billet per piece and
   checks the layer bend, the press and CNC opening, and grain along the member. If the drawing fails,
   it changes how it is made first (thinner layers, then shorter pieces) and moves your shape last.
4. **Judge.** Accept keeps the member. Reject means it never guesses again by itself: redraw, hold
   what matters, or say it in words.
5. **Output.** A closed solid in Rhino, a billet box per piece with its size, the layers, the grain
   angle and the waste, and a record of every decision.

## Documentation

| Read | For |
|---|---|
| `ARCHITECTURE.md` | How the pieces fit, the request cycle, where each rule lives, how to test and extend |
| `rhino7/README.md` | Install, first run, outputs, privacy |
| `core/README.md` | The HTTP contract: every endpoint and field, with worked examples |
| `core/docs/SPEC_V9.md` | The three-stroke plate and its rules, the current design |
| `rhino7/docs/SPEC_V9_UI.md`, `rhino7/docs/SPEC_V9_CARD_SLOTS.md` | The card and panel, with their exact words |

## What is not here, on purpose

- **No machine table.** Company-internal machine data never entered this tree. The core reads a
  git-ignored `private/machines.json` only if a computer has one; otherwise the opening is the user's
  own setting.
- **No history.** This is a fresh copy of the source trees.
- **No sample `.3dm`.** Rhino stores the author's computer details inside it;
  `rhino7/samples/make_three_timbers.py` rebuilds it.

## Limits are placeholders

Layer bend R/t 125, layers of 38, 17 and 11 mm, a 1200 x 280 mm opening, grain within 10 degrees, at
most 4 pieces. They stand in for a real shop's and are meant to be replaced.

## Credits

`core/vendor/sc_glulam/` is the team's billet maths, included unmodified with its author's permission
(see its `NOTICE.md`); it is the single source of billet logic. Code written with Claude Code.
