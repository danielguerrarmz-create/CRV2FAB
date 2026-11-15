# CRV²FAB

**Draw a timber in Rhino. Get the closest one you can build.**

CRV²FAB is a Rhino plugin for freeform glued laminated timber. You draw a curved member in the Rhino
viewport. It answers with ONE buildable ghost of the closest member that can be pressed as glulam
billets and milled to shape, one plain sentence, and the material waste. You accept or reject it.
It directs intent; it reports waste and optimises only when you ask in words.

Built at the AEC Tech Hackathon NYC 2026 by Aaryan Dalal, Daniel Guerra, Keven Zhao, Christopher
Bergeron and Adnan Agha. MIT licence.

**The code:** [`integrated/crv2fab-open-sourced/`](integrated/crv2fab-open-sourced/)

## Demo

A designer draws a doubly curved member, accepts it, pushes a second one further, rejects the eased answer and types "shorter pieces are fine". Recorded in Rhino 7 at real speed with pauses cut, 75 s. Every sentence on screen is the running system's own answer; the cursor and strokes are scripted.

https://github.com/user-attachments/assets/ce1642ec-1233-4498-83ce-f72ac0eeb96a

[Watch the demo](https://github.com/user-attachments/assets/ce1642ec-1233-4498-83ce-f72ac0eeb96a)

## How it works

1. **Input.** A straight timber in Rhino, your own model (a line on a surface, or a solid you
   modelled), a photo of a hand sketch, or words you type.
2. **Gesture.** Three strokes: the path, drawn in plan and again in elevation to make one doubly
   curved line, and the cross-section at each end.
3. **Nudge.** One translucent ghost, never a menu. The rules fit one pressed billet per piece and
   check the layer bend, the press and CNC opening, and grain along the member. If the drawing fails,
   they change how it is made first (thinner layers, then shorter pieces) and move your shape last.
4. **Judge.** Accept keeps the member. Reject means it never guesses again by itself: redraw, hold
   what matters, or say it in words ("shorter pieces are fine").
5. **Output.** A closed solid in Rhino, a billet box per piece with its size, the layers, the grain
   angle and the waste, and a record of every decision.

## Install

Rhino 7 on Windows is tested; Rhino 8 is expected to work but is untested. You need Python 3.13 or
later.

1. Clone this repo.
2. From `integrated/crv2fab-open-sourced/rhino7/`, run
   `powershell -ExecutionPolicy Bypass -File install.ps1`.
3. In Rhino, run `_-RunPythonScript "<repo>\integrated\crv2fab-open-sourced\rhino7\install_rhino.py"`
   once. It adds the command `CRV2FAB`.
4. Type `CRV2FAB` in Rhino.

Full steps: [`rhino7/README.md`](integrated/crv2fab-open-sourced/rhino7/README.md).

## Documentation

| Read | For |
|---|---|
| [`integrated/crv2fab-open-sourced/README.md`](integrated/crv2fab-open-sourced/README.md) | The package: folders, install, what is left out on purpose |
| [`ARCHITECTURE.md`](integrated/crv2fab-open-sourced/ARCHITECTURE.md) | How the parts fit, one request start to finish, where to change things, tests, privacy |
| [`core/README.md`](integrated/crv2fab-open-sourced/core/README.md) | The rules service's HTTP contract, with worked examples |
| [`core/docs/SPEC_V9.md`](integrated/crv2fab-open-sourced/core/docs/SPEC_V9.md) | The three-stroke member and its rules |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md) | How the team works in this repo, for people and coding agents |

## Limits are placeholders

Layer bend R/t 125, layers of 38, 17 and 11 mm, a 1200 x 280 mm opening, grain within 10 degrees, at
most 4 pieces. They stand in for a real shop's and are meant to be replaced.

## Credits

Aaryan Dalal, Daniel Guerra, Keven Zhao, Christopher Bergeron, Adnan Agha. AEC Tech Hackathon NYC
2026. The billet maths in `core/vendor/sc_glulam/` is the team's, included unmodified with its
author's permission. Code written with Claude Code.
