# Decisions

Choices the team made, so nobody re-argues them and every agent can follow them.

| # | Date | Decision | Why | Who |
|---|---|---|---|---|
| 1 | 2026-11-14 | Code lands untouched in `incoming/<handle>/` and moves to `integrated/` only by pull request | Uncoordinated code merges safely only when each drop has one writer and the merge is visible | Daniel |
| 2 | 2026-11-14 | Repo slug is `CRV2FAB` | GitHub slugs cannot hold "²" | Daniel |
| 4 | 2026-11-14 | The technical member's sc_glulam Python maths is the single reference for billet and waste logic. The analyzer's billet.js stays in the analyzer only until the analyzer can call that logic; no further copies. | One set of billet and waste rules, so the analyzer and the Rhino tool cannot disagree. Numbered 4 because PR #1 adds decision 3; renumber if that changes | Daniel |
