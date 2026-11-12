# CLAUDE.md (Duly)

Three people build this repo in a relay, one at a time, each on their own laptop with their own Claude Code. Git carries the code, PROGRESS.md carries the context. Follow these rules in every session.

## Source of truth
- The full spec is `docs/MASTER_PROMPT.md`. Read it fully once at the start of a session, then only the sections you need for the current step.
- `PROGRESS.md` is the live status. Read it before doing anything.
- The original problem-statement slides are in `docs/brief/` (images). If anything in the spec seems to conflict with the slides, the slides win; note the conflict in PROGRESS.md.

## Start of every session
1. `git pull --rebase` (the code may have changed while you were away).
2. Read CLAUDE.md, PROGRESS.md, then the relevant part of docs/MASTER_PROMPT.md.
3. Run the app and the tests once to confirm the state matches PROGRESS.md before writing new code.
4. Continue from "Next" in PROGRESS.md unless the person tells you otherwise.

## After every completed step (mandatory)
After every completed step: update PROGRESS.md, commit with a clear message, and push to GitHub. PROGRESS.md must always have: what's done, what's in progress, what's next, key decisions, known bugs, and how to run the app.

- Keep steps small (roughly 20 to 40 minutes of work each) so a usage cutoff loses at most one small step.
- Run the backend tests (and the demo check once it exists) before committing. Do not push a broken main.
- If you must save half-finished work, commit with a `WIP:` prefix and say exactly what is unfinished in PROGRESS.md under "In progress".
- Commit messages: `feat(matching): ...`, `fix(auth): ...`, `docs: ...`, `test: ...`, `chore: ...`.

## Handoff
When the person says they are near their limit, or asks for a handoff:
1. Finish or cleanly stop the current step.
2. Update PROGRESS.md with everything the next person needs: exact state, half-done work, the next 3 concrete steps, any gotchas, commands to run.
3. Commit and push. Confirm the push succeeded.

## Rules that do not change without recording a decision
- Stack, folder layout, design tokens and the decision engine rules are fixed by the spec. If you change any of them, add a line under "Key decisions" in PROGRESS.md with the reason.
- AI never makes the final approve/block decision. The deterministic rules engine decides; AI extracts, suggests and explains.
- Fictional data only. Never add real company, personal or confidential data. No real GSTINs, PANs, bank accounts or people.
- Never commit secrets. `.env` is git-ignored; keep `.env.example` updated.
- The app must keep working with no internet (demo mode). Do not add a feature that breaks offline mode.
- Must run on Windows and macOS with only `pip` and `npm` installs. No system packages (no Tesseract, no zbar, no Docker requirement).

## PROGRESS.md format (keep these headings)
```
# PROGRESS
Last updated: <date time> by <name>
## How to run
## Done
## In progress
## Next (in order)
## Key decisions
## Known bugs
## Demo status (which demo scenarios work end to end)
```
