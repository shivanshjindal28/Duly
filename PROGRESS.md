# PROGRESS
Last updated: 2026-11-12 12:55 IST by Shivansh (Claude Code)

## How to run
Requirements: Python 3.12, Node.js 20+. Windows or macOS.
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env
python scripts/seed.py --reset
python run.py          # backend :8000, frontend :5173
cd backend && python -m pytest
```
(Backend, frontend and seed script arrive in Phase 0 step 2; until then only the repo skeleton exists.)

## Done
- Phase 0 step 1: repo layout, `.gitignore`, `.env.example`, README stub, `docs/MASTER_PROMPT.md`, PROGRESS.md, `run.py`. Slide screenshots are in `docs/brief/` (7 images).

## In progress
- Nothing half-done.

## Next (in order)
1. Phase 0 step 2: backend FastAPI app with `/api/health`, SQLAlchemy models for core entities, `scripts/seed.py` v1 (Plant X, 6 suppliers, users per role). Frontend Vite + React + TS app with theme tokens, layout shell, sidebar, login page.
2. Phase 0 step 3: auth (Argon2id, JWT httpOnly cookie, CSRF, lockout), RBAC dependency, supplier row scoping, demo persona buttons, pytest for cross-tenant 404.
3. Phase 1 step 4: upload + hardening + text layer + OCR + offline parser + validation layer.

## Key decisions
- Spec file moved from repo root to `docs/MASTER_PROMPT.md` as the spec instructs.
- Use a local `.venv` (git-ignored) for Python deps; documented in README. Spec only requires pip.
- `run.py` uses the interpreter it is launched with for uvicorn, and on Windows kills the process tree with `taskkill /T` on exit so no orphan node/uvicorn processes are left.
- Runtime data (`backend/data/*.db`, uploads, keys, ai_cache) is git-ignored; demo invoices under `demo/invoices/` will be tracked.

## Known bugs
- None yet.

## Demo status (which demo scenarios work end to end)
- 0 of 12. Nothing demoable yet.
