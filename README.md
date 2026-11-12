# Duly

**Every invoice, duly done.** A smart procure-to-pay assistant for the fictional Plant X Polymers Pvt Ltd.

Duly reads supplier invoices (PDF, scan or phone photo), checks them against purchase orders and goods receipts, and approves, flags or blocks each one with a clear reason. A deterministic rules engine makes every decision; AI only reads documents and answers supplier questions, and the whole product also runs offline.

What it does: separate logins for six roles · extraction with per-field confidence and human review · three-way match with SAP-style tolerances · approvals by delegation of authority with MFA and segregation of duties · tamper-evident audit chain · exceptions dashboard and work queue · supplier portal in English and Hindi · duplicate detection · "Where is my payment?" chatbot · controls report for auditors · signed e-invoice QR verification · prompt-injection shield · bank-detail fraud block · MSME 45-day guardian and smart payment run with TDS · SAP S/4HANA posting preview · supplier risk cards · evaluated receipt settlement (self-billing) for freight · Impact, Trust & controls, Architecture and Assumptions pages.

Built for LYB Mumbai Hackathon 2026, Round 2, Problem Statement 4. Plant X is a fictional company and all data in this repo is synthetic.

> Status: feature-complete for the demo (Phases 0 to 4). Live status: [PROGRESS.md](PROGRESS.md). Full spec: [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md).

## Requirements
- Python 3.12 (3.13 and newer lack wheels for some pinned packages; on Windows: `py -3.12 -m venv .venv`)
- Node.js 20.19+ or 22.12+ (Vite 8 needs it; on 22.11 Windows npm skips rolldown's native binary)
- Windows or macOS. No Docker, no system packages.

## Setup
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS:  source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
python scripts/seed.py --reset   # ~25 s: master data + ~250 historical invoices (add --no-history for a bare DB)
```

## Demo
- The 12 demo scenarios are ready-made files in `demo/invoices/`; `demo/manifest.json` lists each file, whom to upload it as, the expected result and the next step to show. Regenerate them with `python scripts/generate_invoices.py` (synthetic data only).
- Stage preparation: `python scripts/demo_prestage.py --reset` (history plus the background scenarios), then follow [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
- One-click reset and the AI mode switch (live / cached / offline) are on **Demo controls** (admin, `DEMO_MODE=true`).
- AI: our setup runs in AI mode **offline** (local OCR and rules; no API key, no network, no cost). An optional Claude API integration exists in the code (`ANTHROPIC_API_KEY` plus AI mode live or auto); the team does not use it.

## Run
```bash
python run.py
```
- Frontend: http://localhost:5173
- Backend API: http://127.0.0.1:8000 (interactive docs at http://127.0.0.1:8000/api/docs)

## Tests
```bash
cd backend && python -m pytest          # backend tests (~90 s)
python scripts/demo_check.py            # the whole demo through the API: green/red table (~45 s; `make demo-check`)
cd frontend && npx playwright install chromium && npm run e2e   # browser smoke test of the demo path
```
`demo_check.py` uses its own temporary database and offline AI by default (`--live-db`, `--ai` to change that). The Playwright test starts its own backend and frontend on ports 8100/5180 with a fresh database; to use an installed browser instead of downloading Chromium, set `PW_CHANNEL=msedge` (or `chrome`).

## Documentation
| File | What |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, invoice lifecycle and data model (rendered in the app) |
| [docs/DECISION_ENGINE.md](docs/DECISION_ENGINE.md) | Every reason code, rule, tolerance and SAP equivalent |
| [docs/CONTROLS.md](docs/CONTROLS.md) | Responsible AI, security and data controls, where they live, what is not built |
| [docs/IMPACT.md](docs/IMPACT.md) | Impact model: measured metrics, formulas, assumptions |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | Scenario, suppliers, policy values, tax tables |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 10-minute run sheet |
| [docs/QA_PREP.md](docs/QA_PREP.md) | 25 likely judge questions with answers |
| [docs/AI_DECLARATION.md](docs/AI_DECLARATION.md) | How generative AI was used to build Duly and inside it |

## Demo accounts
Created by `scripts/seed.py`. With `DEMO_MODE=true` the login page shows one-click persona buttons. The demo password for every seeded user is `Duly@2026` (synthetic demo data only).

| Role | Email |
|---|---|
| Supplier (one per supplier, 6 total) | e.g. `invoices@kesar-spares.example` (Kesar Engineering Spares) |
| AP Clerk | `asha.kulkarni@plantx.example`, `nikhil.verma@plantx.example` |
| Approver L1 / L2 / L3 | `rohan.mehta@`, `kavita.desai@`, `vikram.rao@plantx.example` |
| Stores | `imran.shaikh@plantx.example` |
| Auditor | `meera.iyer@plantx.example` |
| Admin | `sanjay.patil@plantx.example` |

Five wrong passwords lock an account for 15 minutes; `python scripts/seed.py --reset` clears it.

## Troubleshooting
- `npm` not found on Windows: reinstall Node.js and reopen the terminal.
- `Cannot find module './rolldown-binding.win32-x64-msvc.node'` when Vite starts: npm skipped an optional native package (usually because Node is older than 22.12). Upgrade Node, or run `npm install --no-save @rolldown/binding-win32-x64-msvc@<rolldown version>` in `frontend/`.
- Port already in use: stop other apps on 8000/5173, or run `python run.py --backend` and `python run.py --frontend` separately.
- Reset everything: `python scripts/seed.py --reset` (or Demo controls → Reset demo data).
- `pip install` fails on Python 3.13+: use Python 3.12 for the virtual environment.
- MFA code refused after a reset: approver secrets are regenerated; scan the QR on the approver's Overview page again.
