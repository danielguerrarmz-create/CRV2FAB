# Contributing to CRV²FAB

How the team works in this repo. The product itself is described in the top-level `README.md`.


AEC Hackathon submission. **This repo is a temporary integration scaffold, and it is messy on purpose.**

Several people are bringing code that was written separately, in different languages, with different
assumptions. Nothing here is coordinated yet. The repo exists to collect all of it in one place, make
the pieces visible to each other, merge them into one working system, and pay down the debt we take on
to get there.

> GitHub slugs cannot hold the character "²", so the repo address is `CRV2FAB`.

## If you are a person

1. Clone the repo.
2. Copy `incoming/_TEMPLATE` to `incoming/<your-github-handle>`.
3. Put your code in that folder exactly as it is. Do not clean it up first.
4. Fill in `DROP.md` in your folder. Ten minutes of writing is what lets everyone else use your code.
5. Commit and push, then point your coding agent at `AGENTS.md`.

## If you are an agent

Read [`AGENTS.md`](AGENTS.md) before you change anything. It is the rulebook for this repo.

## Layout

| Path | What lives there | Who writes it |
|---|---|---|
| `incoming/<handle>/` | Each person's code, as delivered | Only that person and their agent |
| `integrated/` | Merged code with one owner and a written interface | Pull requests only |
| `docs/INVENTORY.md` | One row per drop: what it does, how to run it | Everyone, append only |
| `docs/INTERFACES.md` | Data formats, units and axes shared between pieces | Pull requests only |
| `docs/DEBT.md` | Every shortcut we took, and how we will undo it | Everyone, in the same commit as the shortcut |
| `docs/DECISIONS.md` | Choices the team made, and why | Whoever made the call |

## Phases

| Phase | Goal | Done when |
|---|---|---|
| 0. Collect | Everyone's code is in `incoming/` | Every contributor has a folder with a filled `DROP.md` |
| 1. Map | We know what exists and how it connects | `INVENTORY.md` and `INTERFACES.md` cover every drop |
| 2. Integrate | One pipeline runs end to end | The demo path runs from `integrated/` |
| 3. Pay down | The debt is visible and shrinking | Every `DEBT.md` item is closed or has an owner |

**Current phase: 0. Collect**
