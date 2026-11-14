# Tech debt ledger

Every shortcut, duplicate, hardcode, stub and open question, recorded in the same commit that created it.
Types: `shortcut`, `duplicate`, `hardcode`, `stub`, `untested`, `question`.

| ID | Type | Where | What and why | Fix plan | Owner | Status |
|---|---|---|---|---|---|---|
| D-001 | question | `docs/INTERFACES.md` | No shared unit, axis or exchange convention yet; every drop uses its own | Agree conventions once phase 1 maps the drops | team | open |
| D-002 | stub | `incoming/dalalaaryan/src/page.html` (SPECIES) | Material values (SPF E 9650 / 30 MPa, DF-L 11000 / 35, SYP 11000 / 38) are textbook placeholders, not test data | Replace with the team's bending test results (closed loop) | dalalaaryan | closed (removed in the single-member rework) |
| D-003 | question | `incoming/dalalaaryan/src/page.html` (rt) | Lam R/t ≥ 125 default is unconfirmed | Confirm with the glulam supplier | dalalaaryan | open |
| D-004 | hardcode | `incoming/dalalaaryan/src/page.html` (mW, mH, mL) | CNC opening default 1200 × 280 mm, 18 m max length is a neutral placeholder | Enter the real machine opening per project | dalalaaryan | open |
| D-005 | shortcut | `incoming/dalalaaryan/src/core.js` | Trimmed Brep faces are sampled over their untrimmed domain | Sample within trims, or mesh faces via rhino3dm | dalalaaryan | open |
| D-006 | shortcut | `incoming/dalalaaryan/src/page.html` (startBilletJob) | Billet refinement is skipped above 240 pieces to keep the UI responsive; those keep the quick (conservative) fit | Move fitting to a Web Worker | dalalaaryan | closed (removed in the single-member rework) |
| D-007 | untested | `incoming/dalalaaryan/` | Only tested in headless Chrome (swiftshader) and on sample surfaces; not yet on teammates' Rhino files | Run on real project surfaces | dalalaaryan | open |
| D-008 | duplicate | `incoming/dalalaaryan/src/billet.js` | Reimplements the team's Grasshopper billet-fit method in JS (matches it within ~0.6% on test parts) | Pick one implementation in DECISIONS once both drops are in | dalalaaryan | open |
| D-009 | shortcut | `incoming/dalalaaryan/src/page.html` (buildFromDoc) | Only the largest closed solid, else the largest surface face, else the first curve becomes the member; the rest of the file is ignored | Let the user pick the object | dalalaaryan | open |
| D-010 | shortcut | `incoming/dalalaaryan/src/page.html` (deform) | Shape edits carry the member's cross-sections rigidly along a new centreline (plus geometric across-width and twist scales); length can change and there is no bending mechanics | Replace with a physics-based form-finding step once test data exists | dalalaaryan | open |
| D-011 | untested | `incoming/dalalaaryan/src/page.html` (askClaude) | Claude calls (artifact `sample` capability with an `evaluate_member` tool and sketch images) were only tested against a mock; they need the page published in claude.ai | Run in claude.ai and record a real session | dalalaaryan | open |
| D-012 | shortcut | `incoming/dalalaaryan/src/page.html` (applySketch) | A sketch is projected onto the view plane through the member centre (one view, no depth cue) | Allow sketching in two views, or snap to the surface | dalalaaryan | open |
