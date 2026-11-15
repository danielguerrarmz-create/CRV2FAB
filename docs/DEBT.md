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
| D-016 | question | `integrated/crv2fab-open-sourced/core/` (limits, settings) | Lamella bend ratio 125, layer options 38/17/11 mm, opening 1200 x 280 mm and grain within 10 degrees are placeholders | Confirm with the technical member; real stock widths too | danielguerrarmz | open |
| D-017 | stub | `integrated/crv2fab-open-sourced/rhino7/` | The Rhino interface is the v8 one (single stroke); the v9 three-stroke interface is being built | Replace by PR when v9 passes its acceptance checks | danielguerrarmz | closed: v9 interface published in this PR |
| D-018 | hardcode | `integrated/crv2fab-open-sourced/rhino7/` (tests, samples, `gnj_rhino/common.py` CORE_DIR) | Default paths point to the author's machine; each can be overridden by an environment variable | Make defaults relative to the folder | danielguerrarmz | partly closed: code people run finds the core by env var, installer config or folder layout; test and sample scripts still default to the author's paths |
| D-019 | shortcut | `integrated/crv2fab-open-sourced/core/` (plate easing) | Eased twisted plates waste 84 to 86%: easing works on one singly curved billet; easing across pieces and variable-curvature billets are not built | Ease across pieces; `sc_glulam` freeform billets | danielguerrarmz | open |
| D-020 | untested | `integrated/crv2fab-open-sourced/` | No human hand has drawn in the Rhino script; every Rhino check was scripted | A hand test in Rhino 7 | danielguerrarmz | open |
| D-021 | untested | `integrated/crv2fab-open-sourced/rhino7/` (install.ps1, install_rhino.py) | Installed and run on Rhino 7 and Python 3.14 only; Rhino 8 and Python 3.13 untested; no toolbar button (Rhino 7 needs a .rui file) | Test on Rhino 8 with a licence; add a .rui toolbar | danielguerrarmz | open |
