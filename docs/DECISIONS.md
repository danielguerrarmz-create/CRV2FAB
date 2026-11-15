# Decisions

Choices the team made, so nobody re-argues them and every agent can follow them.

| # | Date | Decision | Why | Who |
|---|---|---|---|---|
| 1 | 2026-11-14 | Code lands untouched in `incoming/<handle>/` and moves to `integrated/` only by pull request | Uncoordinated code merges safely only when each drop has one writer and the merge is visible | Daniel |
| 2 | 2026-11-14 | Repo slug is `CRV2FAB` | GitHub slugs cannot hold "²" | Daniel |
| 5 | 2026-11-15 | Our Rhino 7 system is published as `integrated/crv2fab-open-sourced/` under MIT, as a fresh copy without history and without the machine table | Open source for the hackathon; the source history holds company-internal machine data | Daniel |
| 6 | 2026-11-15 | Three strokes (path, start profile, end profile) replace the single stroke; the rules propose one ghost; `sc_glulam` stays the only billet logic | Adopts the drawing method of PR #3 without its browser page or second billet maths | Daniel |
