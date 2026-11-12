# Generative AI use declaration

## How we built Duly
We used **Claude (through Claude Code)** to help design and write this code base: the backend, the frontend, the
tests, the synthetic data generators and these documents. Every change went through the team: we read it, ran
the tests (`python -m pytest`, `python scripts/demo_check.py`, `npm run e2e`) and can explain it. The working
method is in `CLAUDE.md`: small steps, tests before every commit, decisions recorded in `PROGRESS.md`.
The build specification we gave it is `docs/MASTER_PROMPT.md`.

## How Duly uses AI inside the product
- **Extraction:** Claude reads the invoice's page images and the text lines read from them, and returns each field
  with a confidence and the line it came from (strict JSON schema, prompt `extract-v1` in
  `backend/app/ai/prompts/`). Model from `ANTHROPIC_MODEL`.
- **Payment assistant:** Claude answers supplier questions ("Where is my payment?") using five read-only tools that
  only ever see the signed-in supplier's own data.

## What AI does not do
- It never approves, flags, blocks, routes or pays an invoice. The deterministic rules engine decides, and people
  approve under delegation of authority.
- It never sees the vendor master, bank records or other suppliers' invoices.
- It is never required: AI mode **offline** (local OCR plus rules) runs the whole product, and **cached** replays
  earlier AI readings without a network.

## Data
All companies, people, invoices and numbers are synthetic. No real company, personal or confidential data was
used to build, test or demonstrate Duly.

See docs/CONTROLS.md for the controls around AI, and the Trust & controls page in the app for live evidence.
