# Tech debt ledger

Every shortcut, duplicate, hardcode, stub and open question, recorded in the same commit that created it.
Types: `shortcut`, `duplicate`, `hardcode`, `stub`, `untested`, `question`.

| ID | Type | Where | What and why | Fix plan | Owner | Status |
|---|---|---|---|---|---|---|
| D-001 | question | `docs/INTERFACES.md` | No shared unit, axis or exchange convention yet; every drop uses its own | Agree conventions once phase 1 maps the drops | team | open |
| D-002 | stub | `incoming/dalalaaryan/src/page.html` (SPECIES) | Material values (SPF E 9650 / 30 MPa, DF-L 11000 / 35, SYP 11000 / 38) are textbook placeholders, not test data | Replace with the team's bending test results (closed loop) | dalalaaryan | open |
| D-003 | question | `incoming/dalalaaryan/src/page.html` (rt) | Lam R/t ≥ 125 default is unconfirmed | Confirm with the glulam supplier | dalalaaryan | open |
| D-004 | hardcode | `incoming/dalalaaryan/src/page.html` (mW, mH, mL) | CNC opening default 1200 × 280 mm, 18 m max length is a neutral placeholder | Enter the real machine opening per project | dalalaaryan | open |
| D-005 | shortcut | `incoming/dalalaaryan/src/core.js` | Trimmed Brep faces are sampled over their untrimmed domain | Sample within trims, or mesh faces via rhino3dm | dalalaaryan | open |
| D-006 | shortcut | `incoming/dalalaaryan/src/page.html` (startBilletJob) | Billet refinement is skipped above 240 pieces to keep the UI responsive; those keep the quick (conservative) fit | Move fitting to a Web Worker | dalalaaryan | open |
| D-007 | untested | `incoming/dalalaaryan/` | Only tested in headless Chrome (swiftshader) and on sample surfaces; not yet on teammates' Rhino files | Run on real project surfaces | dalalaaryan | open |
| D-008 | duplicate | `incoming/dalalaaryan/src/billet.js` | Reimplements the team's Grasshopper billet-fit method in JS (matches it within ~0.6% on test parts) | Pick one implementation in DECISIONS once both drops are in | dalalaaryan | open |
