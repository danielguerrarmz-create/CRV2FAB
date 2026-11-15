# Architecture

How CRV²FAB is built, for anyone who will change it. Units are millimetres, Z up, at every boundary.

## Three parts, one direction of authority

| Part | Where | Job | Never does |
|---|---|---|---|
| Rhino plugin | `rhino7/` (IronPython 2.7 inside Rhino) | Captures strokes, draws the ghost and billets, shows the card and panel, bakes accepted members | Compute a number the core did not send, or decide buildability |
| Rules core | `core/` (CPython 3.13+, a local HTTP service on 127.0.0.1:8742) | Builds the member from the strokes, fits billets, checks limits, eases, splits, writes the record | Read geometry from Rhino directly, or send geometry or machine data to a model |
| Claude (optional) | Reached by the core through the signed-in Claude Code, no API key | Reads typed words and photos into a closed list of moves | Propose geometry, write text the user sees, or decide anything |

The checker in the core (`core/gnj_nudge/limits.py` and the plate checks) is the only thing allowed to
call a member buildable. Everything the user reads on the card and panel is the core's own answer.

## One request, start to finish

1. **Strokes.** The card runs Rhino's `_Sketch` for Path, Start or End (`rhino7/gnj_rhino/card.py`,
   `on_stroke`). A Path lands on the member's upright or flat plane, whichever the view faces more.
   Drawn once in plan and once in elevation, the two combine into one 3D path
   (`rhino7/gnj_core.py`, `two_view_path`). Start and End are drawn on each end's own plane.
2. **Send.** The plugin posts `{intent: {kind: "plate", path, profile_start, profile_end,
   thickness_mm}, holds}` to `POST /nudge`, as 3D points in mm.
3. **Build the plate** (`core/gnj_nudge/plate.py`). The path is resampled to 65 stations with its ends
   pinned, rotation-minimising frames are run along it, each profile is read on its end plane, and the
   profile blends between the ends to a mid-surface, thickened to `thickness_mm`.
4. **Fit and check.** The team's `sc_glulam` maths (`core/vendor/sc_glulam/`, unmodified) fits one
   singly curved billet per piece. Then three checks run: layer bend (R/t at least 125), the machine
   opening, and grain within 10 degrees of the path. A plate that fits inside one 38 x 89 board is
   simply stock.
5. **Remedies, in a fixed order.** Thinner layers (38, 17, 11 mm) come first. Shorter pieces come
   next, only for a failed machine or grain check, a waste target, or when the user allows joints.
   Easing the shape comes last, by bisection: a failed bend eases the path, and a failed machine or
   grain check eases the twist, then the profiles, then the path's drift. If nothing passes, the answer
   is a conflict that names the cause.
6. **Answer.** One form, one sentence, Why steps, the checks, waste, and `deviation_mm` (the largest
   move anywhere on the plate). The plugin maps the sentence into the card's fixed slots: Verdict,
   Reason, Facts (`rhino7/gnj_slots.py`).
7. **Judge.** `POST /judge` accepts or rejects. Holds (`solid`, `shape`, `split_ok`, `less_waste`)
   come from buttons or from words through `POST /say`. `POST /undo` walks back an accept. Every
   decision is appended to `gnj-record.jsonl`.

Typical time is 1 to 5 s per answer, under 10 s by design, with the core's process pool on.

## Other inputs

- **A line on a surface** (`kind: "surface_stroke"`), and **your own solid** (`kind: "part"`, which is
  never moved, only planned).
- **A photo** (`POST /photo`). Claude reads it into up to three bends from a closed vocabulary, and the
  core builds a path from them.
- **Words** (`POST /say`). Claude maps them to at most two moves from a closed list. On any failure a
  keyword matcher answers instead.

## Where to change things

| To change | Edit |
|---|---|
| A limit's value (R/t, layers, opening, grain, pieces) | `core/gnj_nudge/settings.py` defaults, or `POST /settings` at run time |
| A check or a remedy | `core/gnj_nudge/plate.py`, then `core/docs/SPEC_V9.md` and the vectors |
| What the card says | `rhino7/gnj_slots.py`, then `rhino7/docs/SPEC_V9_CARD_SLOTS.md` |
| The ghost, billets or colours | `rhino7/gnj_rhino/conduit.py`, `geometry.py`, `common.py` |
| The logo | Replace `rhino7/gnj_rhino/assets/crv2fab.ico` and `crv2fab.png` |
| The model that reads words or photos | `GNJ_MODEL` (see `core/README.md`) |

## Tests

- **Core:** `python -m pytest -q -m "not slow"` in `core/` (about 35 s), then without `-m` for the full
  suite (about 7 min). Shared answer files `core/tests/vectors_*.json` pin every worked case.
- **Plugin:** `python -m unittest discover -s tests -p "test_*.py"` in `rhino7/`, and
  `tests\run_ipy.ps1` for IronPython.
- **Inside Rhino:** `tests\run_smoke_v9.ps1` drives the real plugin through 14 checks from an empty
  document, in its own Rhino scheme and port, and never touches your own settings.

## Privacy rules the code enforces

- No machine data of any kind enters a prompt (`core/tests/test_privacy.py`).
- Prompts carry only the typed words, the current holds and the move list, or the photo. Never
  geometry, settings or file paths.
- Photos are downsized and re-encoded before sending, which drops location data, and are never
  written to disk.

## Glossary

**Member**, the whole timber. **Piece**, one pressed part of a member. **Billet**, the glued blank a
piece is milled from. **Layer**, one lamella in a billet. **Ghost**, the proposal shown before
Accept. **Hold**, something the designer says must be kept.
