# PROGRESS
Last updated: 2026-11-12 13:20 IST by Shivansh (Claude Code)

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
Seed: 14 users, demo password `Duly@2026` for all (synthetic). API docs at http://127.0.0.1:8000/api/docs.

## Done
- Phase 0 step 1: repo layout, `.gitignore`, `.env.example`, README stub, `docs/MASTER_PROMPT.md`, PROGRESS.md, `run.py`. Slide screenshots are in `docs/brief/` (7 images).

- Phase 0 step 2 (backend): FastAPI app, `/api/health`, SQLAlchemy models for every core entity, AES-GCM field encryption, Argon2id hashing, GSTIN check digit, default policy v1, `scripts/seed.py --reset` (Plant X, 6 suppliers, 14 users), security headers. 15 pytest tests.
- Phase 0 step 2 (frontend): Vite + React 18 + TS, design tokens (`frontend/src/theme/tokens.ts`, AA-checked), app shell (navy sidebar, top bar with entity, AI mode and role badges), login page with demo persona buttons, Duly 5-stop rail component, role Overview page.

## In progress
- Login UI calls `/api/auth/*`, which arrives in Phase 0 step 3. Until then, sign-in shows a server error.

## Next (in order)
1. Phase 0 step 3: auth (Argon2id, JWT httpOnly cookie, CSRF, lockout), RBAC dependency, supplier row scoping, demo persona buttons, pytest for cross-tenant 404.
2. Phase 1 step 4: upload + hardening + text layer + OCR + offline parser + validation layer.

## Key decisions
- Spec file moved from repo root to `docs/MASTER_PROMPT.md` as the spec instructs.
- Use a local `.venv` (git-ignored) for Python deps; documented in README. Spec only requires pip.
- `run.py` uses the interpreter it is launched with for uvicorn, and on Windows kills the process tree with `taskkill /T` on exit so no orphan node/uvicorn processes are left.
- Roles are a fixed string enum on `users.role` (not a table): the six roles are fixed by the spec. Approver level in `users.approver_level`.
- No Alembic yet: schema is created with `create_all`; `scripts/seed.py --reset` drops and recreates. Add migrations only if we need to keep data across schema changes.
- Empty secrets are auto-generated once into `backend/data/keys/` (git-ignored) so a fresh laptop needs no config and sessions/encrypted fields survive restarts.
- Money stored as `Numeric(16,2)`, quantities `Numeric(16,3)`, handled as `Decimal`.
- Palette AA fixes: bright cyan, green and amber fail AA as text on white, so they are fills/on-navy only; text uses darker variants (cyanText #0A7189, approveText #157A42, flagText #8A5A00, blockText #B0005B). Ratios recorded in tokens.ts.
- Frontend versions: react-router 7.18.5 (supports React 18; v6 and Vite 5 had npm audit advisories), Vite 8, TypeScript 5.9 (not 7). Fonts bundled via @fontsource so the UI works offline.
- Vite dev server proxies `/api` to :8000 so the session cookie is same-origin (SameSite=strict).
- Fictional bank names and IFSC prefixes (SHYG, NRMD, KVRG) and `.example` email domains so no seed value points at a real entity.
- Runtime data (`backend/data/*.db`, uploads, keys, ai_cache) is git-ignored; demo invoices under `demo/invoices/` will be tracked.

## Known bugs
- None yet.

## Demo status (which demo scenarios work end to end)
- 0 of 12. Nothing demoable yet.
