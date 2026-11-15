# Contributing to CRV²FAB

CRV²FAB is open source under MIT. Contributions from people and from their coding agents are welcome.
This page is the map. [`AGENTS.md`](../AGENTS.md) is the rulebook every agent follows, and people
should read it too.

> GitHub slugs cannot hold the character "²", so the repo address is `CRV2FAB`.

## Where things live

| Path | What it is | Status |
|---|---|---|
| `integrated/crv2fab-open-sourced/` | The CRV²FAB Rhino plugin (`rhino7/`) and its rules core (`core/`) | Working; Rhino 7 tested, Rhino 8 untested |
| `integrated/crv2fab-glulam-slicer/` | Grasshopper glulam slicer: fabrication pieces, raw blocks, reports, render meshes | Standalone on Rhino 8, **pending integration** (read its `INTEGRATION.md`) |
| `incoming/<handle>/` | A contributor's own code, as delivered, with a `DROP.md` | Not yet integrated |
| `docs/INVENTORY.md` | One row per drop or module: what it does, how to run it | Append only |
| `docs/INTERFACES.md` | Data formats, units and axes shared between pieces | Changed by pull request |
| `docs/DEBT.md` | Every shortcut taken, and how it will be undone | In the same commit as the shortcut |
| `docs/DECISIONS.md` | Choices made, and why | Whoever makes the call |

Before touching the plugin, read `integrated/crv2fab-open-sourced/ARCHITECTURE.md`. It covers the
parts, one request start to finish, where each rule lives, and how to test.

## How a change gets in

1. **Fork or branch.** Name branches `<your-github-handle>/<short-topic>`.
2. **Keep one purpose per pull request.** Commit messages read `<area>: <what changed>`, for example
   `rhino7: pick an existing curve as the Path`.
3. **Run the tests for what you touched,** and say in the PR what you ran and what you saw.
   - Core: `python -m pytest -q -m "not slow"` in `integrated/crv2fab-open-sourced/core/`
   - Plugin: `python -m unittest discover -s tests -p "test_*.py"` in `.../rhino7/`
   - Inside Rhino: `tests\run_smoke_v9.ps1` (its own Rhino scheme and port; never your own settings)
4. **Open a pull request.** `main` takes no direct pushes, admins included, and every PR needs one
   approving review from a maintainer.
5. **Log your shortcuts** in `docs/DEBT.md`, and units at any new boundary in `docs/INTERFACES.md`.

## Standards the code keeps

- **Units: millimetres, Z up,** at every boundary. Convert at the edge, never inside someone else's
  code.
- **One home for each rule.** The core is the only place that decides buildability. The plugin
  shows what the core sent and never computes its own numbers. The billet maths
  (`core/vendor/sc_glulam/`) stays unmodified.
- **Words people read:** plain, short, no em or en dashes. Card text follows
  `rhino7/docs/SPEC_V9_CARD_SLOTS.md`.
- **Tests that can fail.** A bug fix comes with a test that fails before the fix.

## Public repo: what must never be committed

- Secrets: keys, tokens, passwords, `.env` files. Run `gitleaks protect --staged` before you push.
- Company or client data: machine tables, client drawings, site data, anything under NDA. The
  core reads a private machine table only from a git-ignored `private/` folder.
- Personal details hidden in files. Rhino `.3dm` files store the author's computer and paths, so
  save examples from a neutral location or generate them with a script.
- Files over 50 MB.

## Where help is wanted

| Item | Where to start |
|---|---|
| Connect the glulam slicer to the plugin | `integrated/crv2fab-glulam-slicer/INTEGRATION.md`, DEBT D-022 |
| Test on Rhino 8 | DEBT D-021 |
| Pick an existing curve, or draw with Polyline, Curve or Arc, as a stroke | `rhino7/gnj_rhino/card.py` (`on_stroke`, `end_stroke`) |
| Real shop limits instead of placeholders (R/t, layers, opening, grain) | DEBT D-016, `core/gnj_nudge/settings.py` |

## If you are an agent

Read [`AGENTS.md`](../AGENTS.md) before you change anything. Then read this page, the top-level
`README.md`, and the `ARCHITECTURE.md` or `INTEGRATION.md` of the folder you will touch. Never push to
`main`, never approve or merge a pull request, and stop and ask your human whenever a change would
touch someone else's folder.
