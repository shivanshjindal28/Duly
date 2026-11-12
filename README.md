# Duly

**Every invoice, duly done.** A smart procure-to-pay assistant for the fictional Plant X Polymers Pvt Ltd.

Duly reads supplier invoices (PDF or image), checks them against purchase orders and goods receipts, and approves, flags or blocks each one with a clear reason. A deterministic rules engine makes every decision; AI only extracts, suggests and explains.

Built for LYB Mumbai Hackathon 2026, Round 2, Problem Statement 4. Plant X is a fictional company and all data in this repo is synthetic.

> Status: early build. See [PROGRESS.md](PROGRESS.md) for what works today. Full spec: [docs/MASTER_PROMPT.md](docs/MASTER_PROMPT.md).

## Requirements
- Python 3.12
- Node.js 20+
- Windows or macOS. No Docker, no system packages.

## Setup
```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS:  source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
python scripts/seed.py --reset
```

## Run
```bash
python run.py
```
- Frontend: http://localhost:5173
- Backend API: http://127.0.0.1:8000 (interactive docs at http://127.0.0.1:8000/api/docs)

## Tests
```bash
cd backend && python -m pytest
```

## Demo accounts
Created by `scripts/seed.py`. With `DEMO_MODE=true` the login page shows one-click persona buttons. The demo password for every seeded user is `Duly@2026` (synthetic demo data only).

## Troubleshooting
- `npm` not found on Windows: reinstall Node.js and reopen the terminal.
- Port already in use: stop other apps on 8000/5173, or run `python run.py --backend` and `python run.py --frontend` separately.
- Reset everything: `python scripts/seed.py --reset`.
