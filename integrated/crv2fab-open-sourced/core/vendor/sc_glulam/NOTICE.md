# Vendored: sc_glulam (teammate's doubly curved glulam billet check)

Copied unmodified on 2026-11-14 from `C:\Users\danie\Downloads\sc_glulam\sc_glulam`.
Do not edit these files. If something in them looks wrong, report it to the author; do not patch it here.

| File | sha256 at copy |
|---|---|
| `glulam_math.py` | `3b1de5632192d9e2bba3ff62bf1a1cfc65586be67f9fed3822b05ab824d7031c` |
| `test_glulam_math.py` | `ed0ad6dc9281958adba9fa6ff85cb1cf4d53f78982ebc0019aec47bf955c8c77` |

`tests/test_v4_fabrication.py` checks these hashes and runs `test_glulam_math.py` against this copy.

Not vendored: `glulam_billet.py` (needs Rhino). The few Rhino-free pieces the core needs (the
machine check, the lamella check, the waste figure) are re-expressed in `gnj_nudge/fabrication.py`,
each citing the function it mirrors. Its machine table (company-internal) is copied to
`gnj_nudge/data/machines.internal.json` and must not leave the core: not to the model, a published
file, the browser mock or any outside service.
