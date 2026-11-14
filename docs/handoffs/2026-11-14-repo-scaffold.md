# 2026-11-14: Repo scaffold

## What

- Created the public repo `danielguerrarmz-create/CRV2FAB` as the temporary integration point for the
  team's AEC Hackathon code.
- `AGENTS.md` is the single rulebook for every coding agent. `CLAUDE.md` and `GEMINI.md` point to it;
  Codex, Cursor and Copilot read `AGENTS.md` natively.
- Layout: `incoming/<handle>/` (each person's code, untouched, one writer per folder), `integrated/`
  (pull requests only), `incoming/_TEMPLATE/DROP.md` (per-drop description).
- Shared logs in `docs/`: `INVENTORY.md`, `INTERFACES.md` (units, up-axis, tolerance, exchange
  format, all TBD), `DEBT.md` (seeded with D-001, no shared conventions yet), `DECISIONS.md` (seeded
  with the layout and the slug).
- Four phases in `README.md`: Collect, Map, Integrate, Pay down. Current phase: 0, Collect.
- `.gitignore` for secrets, Python, Node and Rhino/Grasshopper/Blender/TouchDesigner backups;
  `.gitattributes` marks CAD and media files as binary; `.github/pull_request_template.md`.
- Branch protection on `main`: force pushes and deletion blocked, admins included. Direct pushes are
  still allowed so people can drop code fast.

## Why

The team's code was written separately, so the first risk is agents overwriting or "cleaning up" each
other's work. One writer per folder removes that. Every later step (inventory, interfaces, debt ledger)
makes the mess visible before anyone merges it. Units and axes get their own section because mismatched
geometry units run without errors and build the wrong thing.

## Verify

- `gitleaks protect --staged` before the first push: no leaks found.
- `gh repo view`: visibility `PUBLIC`. Branch protection API returned `allow_force_pushes: false`,
  `allow_deletions: false`.
- Not verified: no teammate or teammate's agent has used the scaffold yet. The `@AGENTS.md` import in
  `CLAUDE.md` and `GEMINI.md` was not tested by opening a session in the repo.

## Left

| Item | Owner |
|---|---|
| Send teammates' GitHub handles so they can be invited with push access | Daniel |
| Decide whether the hackathon needs an open licence (MIT is the usual choice); none yet, so the code is all rights reserved | Daniel |
| Each teammate copies `incoming/_TEMPLATE` to their own folder and fills `DROP.md` | Each teammate |
| Agree units, up-axis and exchange format once phase 1 maps the drops (closes D-001) | Team |

## Files

`README.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.env.example`, `.gitignore`, `.gitattributes`,
`.github/pull_request_template.md`, `incoming/_TEMPLATE/DROP.md`, `integrated/README.md`, `docs/*.md`.
Commits: `438f4b6` (scaffold) and the commit that adds this handoff.
