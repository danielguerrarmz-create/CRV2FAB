# AGENTS.md

Instructions for every coding agent working in this repo: Claude Code, Codex, Cursor, Copilot, Gemini,
or anything else. Humans should read it too.

## Context

This is a hackathon repo assembled from code written by several people who did not coordinate. Expect
duplicate utilities, conflicting conventions, mixed languages, hardcoded paths and different unit
systems. That is the starting condition, not a mistake to fix on sight. Your job is to help merge it
**without destroying anyone's work and without hiding the mess**.

The current phase is set at the bottom of `README.md`. Check it before you start.

## Before you change anything

1. Read `README.md`, this file, `docs/INVENTORY.md`, `docs/INTERFACES.md` and `docs/DEBT.md`.
2. Confirm which human you are working for and which `incoming/<handle>/` folder is theirs.
3. Run `git pull --rebase` before you start and again before you push. Teammates push often.

## Ownership

- **Write only in your human's own folder**, `incoming/<handle>/`. Never edit, move, reformat or delete
  another person's drop, even to fix an obvious bug. Add a row to `docs/DEBT.md` or open an issue that
  tags the owner instead.
- `integrated/` and `docs/INTERFACES.md` change only through pull requests.
- `docs/INVENTORY.md`, `docs/DEBT.md` and `docs/DECISIONS.md` are shared logs. Append your rows. Edit
  someone else's row only to mark an item you closed.
- Never delete code because it looks unused. Someone's demo may depend on it. Log it in `DEBT.md`.

## Git

- Never force-push `main`. Never rewrite shared history. (`main` is protected against force pushes.)
- **Nobody pushes to `main`. Not humans, not agents, not repo admins.** GitHub enforces it: every change
  reaches `main` through a pull request with one approving review from another collaborator. That
  includes changes inside your own `incoming/<handle>/` folder and appended rows in the shared logs.
- Work on a branch named `<handle>/<short-topic>` and open a pull request.
- Agents never approve or merge a pull request. A human reviews and merges it.
- One purpose per commit. Message format: `<area>: <what changed>`, for example
  `incoming/alex: add curve offset script`.
- Before committing, run `git status` and `git diff --staged` and confirm you are staging only your own
  files.
- On a merge conflict in someone else's file, stop and ask your human. Never resolve it by taking your
  side.

## Public repo: secrets and size

This repo is **public**. Anything pushed is visible to everyone and stays in history after deletion.

- Never commit API keys, tokens, passwords, `.env` files or paid software licence files. Use
  `.env.example` with placeholder values.
- If `gitleaks` is installed, run `gitleaks protect --staged` before every push.
- No file over 50 MB (GitHub rejects files over 100 MB). Never commit client drawings, site data or
  anything under NDA. Large models live in a shared drive, linked from `DROP.md`.

## Make the mess legible

Every drop needs a `DROP.md` (template: `incoming/_TEMPLATE/DROP.md`). If your human's drop lacks one,
writing it is your first task. It must state:

- what the code does, in one sentence
- language, runtime and versions (Python 3.x, Node, Rhino 8, Grasshopper, TouchDesigner, etc.)
- how to run it, exactly, from a fresh clone
- inputs and outputs, **with units and up-axis**
- dependencies, and everything hardcoded (paths, machine names, keys)

Then add a row to `docs/INVENTORY.md`. If a field is unknown, write `UNKNOWN (ask <handle>)`. Never
guess.

## Geometry and units: the most likely merge bug

AEC code fails silently when units or axes disagree. A curve in millimetres fed to a script that expects
metres still runs; it just builds the wrong thing. For any geometry that crosses from one person's code
to another's:

- Record units (mm, m, in, ft), up-axis (Z-up or Y-up), tolerance and exchange format (JSON point
  lists, 3DM, STEP, DXF, OBJ) in `docs/INTERFACES.md`.
- Until the team fixes a convention in `docs/DECISIONS.md`, convert at the boundary and log the
  conversion in `DEBT.md`. Never change units inside someone else's code.

## Tech debt: record it when you take it

Shortcuts are allowed. Hidden shortcuts are not. Whenever you hardcode a path, copy a function instead
of sharing it, skip a test, stub a value for the demo or wrap code you did not understand, add a row to
`docs/DEBT.md` **in the same commit**, using the next free ID (`D-002`, `D-003`, ...).

## Integration (phase 2 onward)

Moving code from `incoming/` to `integrated/`:

1. One pull request per module. The PR names the module's owner.
2. The module's interface is written in `docs/INTERFACES.md` in the same PR or earlier.
3. The original stays in `incoming/` until the integrated version runs the demo path. Removing it is a
   separate PR approved by its author.
4. When two drops do the same job, do not blend them into a hybrid. Pick one in `docs/DECISIONS.md`,
   adapt the callers, and log the retired one in `DEBT.md`.

## Do not

- Reformat, lint-fix or restructure files you were not asked to touch. Whole-file formatting diffs make
  merging impossible.
- Add a repo-wide build system, framework, monorepo tool or CI pipeline without a team-agreed entry in
  `docs/DECISIONS.md`.
- Upgrade shared dependencies on your own.
- Report anything as working unless you ran it. Say what you ran and what you saw.

## When unsure

Leave the code as it is, add a `question` row to `docs/DEBT.md`, and tell your human.
