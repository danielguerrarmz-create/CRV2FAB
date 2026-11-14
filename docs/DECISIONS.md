# Decisions

Choices the team made, so nobody re-argues them and every agent can follow them.

| # | Date | Decision | Why | Who |
|---|---|---|---|---|
| 1 | 2026-11-14 | Code lands untouched in `incoming/<handle>/` and moves to `integrated/` only by pull request | Uncoordinated code merges safely only when each drop has one writer and the merge is visible | Daniel |
| 2 | 2026-11-14 | Repo slug is `CRV2FAB` | GitHub slugs cannot hold "²" | Daniel |
| 3 | 2026-11-14 | No direct pushes to `main`, admins included. Every change is a pull request with one approving review. This replaces the earlier allowance for direct commits to your own `incoming/<handle>/` folder | A reviewed pull request is the only place a second person sees a change before it lands | Daniel |
