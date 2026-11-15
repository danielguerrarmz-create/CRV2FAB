# CRV2FAB for Rhino

CRV2FAB lets a designer draw a curved timber member in Rhino and get back the closest member that can
actually be made from glued laminated timber. You draw a path and the two end profiles over a straight
2x4. A local helper, the nudge core, checks the shape against the limits of pressing and milling. It
answers with one blue ghost and one plain sentence: your shape holds, or how it was eased so it can be
built, and by how much. You accept it or reject it. It never guesses again after a reject; it waits
for a new stroke or for words that say what to keep.

## What you see

- **The card**, a small floating window titled "CRV2FAB - Nudge". It has the sentence, the waste line,
  the Path, Start and End buttons with Done, and Accept and Reject while a proposal is on screen.
  After a reject it offers Keep my shape, Keep it as one piece and a Say box.
- **The CRV2FAB panel**, a tab beside Layers. Its sections are Inputs, This proposal (bend, machine,
  grain, how it is made, waste, pieces), Members (accepted members; selecting a row selects the member),
  Settings, Show (billets, billet outline, cut lines) and Record (newest first, Undo last accept,
  Start over, and About CRV2FAB).
- **In the viewport**, the proposal is a translucent blue ghost with your drawing dashed over it, and
  each piece's billet is a translucent pink box around it.

## Install

Rhino 7 on Windows is tested. Rhino 8 is expected to work but is untested.

You need the Python the core declares in its `pyproject.toml`, today 3.13 or later (we have run it on
3.14 only), and the nudge core: the `core` folder beside this one in the published layout, or a
`gnj-nudge-core` checkout beside this folder.

1. In PowerShell, from this folder, run
   `powershell -ExecutionPolicy Bypass -File install.ps1`.
   It finds the core, checks the Python version, makes a virtual environment in the core's `.venv`
   folder, installs numpy, pillow and anthropic into it, and writes `crv2fab.config.json` here. The
   core needs the anthropic package to start, but calls the Anthropic API with it only when
   `GNJ_BACKEND=api` and a key are set. Pass `-Core <folder>` if the core is
   somewhere else, or `-Python <python.exe>` to choose the Python.
2. Once, in Rhino, run `_-RunPythonScript "<this folder>\install_rhino.py"`. It adds the command
   `CRV2FAB`. Rhino keeps the command in the scheme you run it in.
3. Type `CRV2FAB` in Rhino. The command line shows one line of credits, and the card opens.

The Rhino side finds the core from `GNJ_CORE_DIR` if you set it, then from `crv2fab.config.json`,
then beside this folder. If nothing answers on port 8742, it starts the core itself and stops it when
the card closes.

## First run

1. Open a new document. CRV2FAB adds a straight 2x4 on the `GNJ::Existing` layer.
2. Press **Path** and draw over the member. Draw it in Top for the plan and again in Front for the
   elevation, and the two make one curve that bends both ways. Press **Start** and **End** to draw the
   profile at each end, on the end's own plane. Skip any you do not need.
3. Press **Done**. The ghost and the sentence arrive in a few seconds.
4. **Accept** bakes the member. **Reject** waits: draw again, or press Keep my shape or Keep it as one
   piece, or type in the Say box, for example "shorter pieces are fine".
5. **Photo** on the card, or Open a photo in the panel, reads a hand sketch into a member.
6. Select your own closed solid and press **My solid** on the card. The core says how it would be made
   and never moves your geometry.

## What it outputs

- Each accepted member is a closed polysurface on `GNJ::Buildable` in timber colour. Its user text
  holds its id, layer count, layer thickness, waste, grain angle and piece count.
- Each piece's billet is a closed box on `GNJ::Buildable::Billets`, drawn as thin pink edges, with a
  label giving its size, for example "B1 1204 x 595 x 190 mm". The sizes are the core's.
- The core keeps a record of every proposal and decision in `gnj-record.jsonl`, in the core's folder
  unless `GNJ_RECORD` names another file.

## Limits are placeholders

The fabrication limits stand in for a real shop's and are meant to be replaced. Today they are:

- a layer bends to no less than 125 times its thickness (R/t 125);
- layer thicknesses of 38, 17 and 11 mm;
- a machine opening of 1200 x 280 mm;
- the grain runs within 10 degrees of the member's path;
- at most 4 pieces joined end to end.

Every sentence and number on screen is the core's answer under these limits.

## How words and photos reach Claude

Typed words and photos are read by Claude through Claude Code, already signed in on this machine. No
API key is needed or used. The core runs Claude Code headless, with no tools, no MCP servers and none
of your settings. If Claude Code is not there, typed words fall back to a keyword reading, and photos
cannot be read. Set `GNJ_SAY=keywords` to always use the keyword reading.

## Privacy

- What goes to Claude is the words you type with the holds now set, or a photo you choose to open.
  Your model's geometry never goes into a prompt.
- No machine data leaves the core: answers show the opening you set, never a machine's name.
- Claude Code attaches the signed-in account's email to every request. The core refuses any answer
  that contains an email address.

## Credits

Credits to the creators: Aaryan Dalal, Daniel Guerra, Keven Zhao, Christopher Bergeron, Adnan Agha.
Done at the AEC Tech Hackathon NYC 2026. See `CREDITS.md`.

## Licence

MIT.

## For developers

`gnj_nudge.py` is the entry. The Rhino side is in `gnj_rhino/`; the state and the core client are in
`gnj_core.py`. The logo is in `gnj_rhino/assets/`; replace the files to change it. Tests:
`python -m unittest discover -s tests -p "test_*.py"` (CPython) and `powershell -File tests\run_ipy.ps1`
(Rhino 7's IronPython). The Rhino smokes run in a separate scheme on their own port:
`tests\run_smoke_v9.ps1` and `tests\run_install_smoke.ps1`.
