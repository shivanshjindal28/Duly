# PROGRESS
Last updated: 2026-11-12 17:00 IST by Shivansh (Claude Code)

## How to run
Requirements: Python 3.12, Node.js 20.19+ (Vite 8). Windows or macOS.
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env              # optional: everything has safe demo defaults
python scripts/seed.py --reset
python run.py                     # backend :8000, frontend :5173 (Ctrl+C stops both)
cd backend && python -m pytest    # 94 tests (about 10 s; OCR model loads once)
cd frontend && npm run typecheck
```
- Open http://localhost:5173. With `DEMO_MODE=true` (default) the login page lists one-click demo personas.
- Seed: 14 users, demo password `Duly@2026` for all (synthetic). API docs at http://127.0.0.1:8000/api/docs.
- After any model change, re-run `python scripts/seed.py --reset` (no migrations yet).

## Done
- **Phase 0 complete.**
- Step 1: repo layout, `.gitignore`, `.gitattributes` (LF), `.env.example`, README, `docs/MASTER_PROMPT.md`, PROGRESS.md, `run.py`. Slides in `docs/brief/` (7 images).
- Step 2 backend: FastAPI app, `/api/health`, SQLAlchemy models for every core entity (spec section 8), AES-GCM field encryption (bank accounts, TOTP secrets), Argon2id hashing, GSTIN check digit + synthetic generator, versioned default policy v1 (`app/core/policy_defaults.py`), `scripts/seed.py --reset` (Plant X, 6 suppliers, 14 users across all 6 roles, approvers L1/L2/L3 with MFA secrets), security headers.
- Step 2 frontend: Vite + React 18 + TS, design tokens (`frontend/src/theme/tokens.ts`, AA-checked), app shell (navy sidebar, top bar with entity, AI mode and role badges, skip link), login page, Duly 5-stop rail component, per-role Overview page (server-reported permissions + system status).
- Step 3 auth: login/logout/me, JWT in httpOnly SameSite=strict cookie, signed double-submit CSRF, sliding 60-min session, logout revokes all tokens (token_version), lockout after 5 failures (15 min), login rate limit (slowapi, 10/min/IP), generic error + dummy-hash timing for unknown emails, `require_roles` RBAC dependency, `get_scope` supplier row scoping (404 for other suppliers' invoices), demo personas + demo-login (404 when DEMO_MODE=false), `/api/invoices` list/detail (scoped; stores gets 403).
- **Phase 1 step 4 (backend)**: `POST /api/invoices/upload` (supplier, or clerk on behalf; supplier resolved by GSTIN), upload hardening (`ingestion/hardening.py`: extension vs magic bytes, 10 MB, 20 pages, rejects PDF JavaScript/Launch/EmbeddedFiles incl. hex-obfuscated names, re-encodes images to strip EXIF), random stored names + SHA-256, text layer (pdfplumber) with OCR fallback (RapidOCR, offline), offline regex parser with per-field confidence + page + bbox (`ai/offline_parser.py`), validation layer (`validation/rules.py`: GSTIN check digit, bill-to = Plant X, invoice no <= 16 chars, date not future / not older than previous FY, line and total arithmetic within Rs 1, CGST+SGST vs IGST by place of supply, GST rate vs HSN table), low-confidence fields mark the invoice `needs_review`. Endpoints for the document file and server-rendered page PNGs (scoped). Sample GST invoice renderer `app/samples/invoice_pdf.py`.
- **Phase 1 step 5**: decision engine `app/engine/decide.py` (pure, deterministic; test proves no `app.ai`/ORM/SQLAlchemy import). All reason codes from spec C3 plus LINE_NOT_ON_PO, SES_VALUE_EXCEEDED, SMALL_DIFFERENCE, LINE_MAPPED; PP/DQ/BD tolerances from versioned policy; cumulative qty check for partial deliveries; kg/MT unit conversion; fuzzy description line mapping (rapidfuzz); SAP block + tcode per code (`engine/catalog.py`). `workflow/matching.run_match` builds PO/GR/SES/invoiced-history views, stores a MatchResult with reasons + matrix snapshot, sets invoice status (blocked / flagged / pending_approval). Runs on every upload. Seed now has 14 scenario POs (4500001001..1013 + closed 4500000990), 10 GRs, 3 SESs (`app/seed.py` PURCHASE_ORDERS lists which scenario each PO serves). `docs/DECISION_ENGINE.md` written.
- **Phase 1 step 6**: invoice screens. `/invoices` list (decision + status chips, owner), `/upload` (drag and drop; clerk can pick a supplier or let Duly identify it by GSTIN), `/invoices/:id` hero screen: header with total, PO, status, owner and the 5-stop Duly rail (computed server-side in `workflow/lifecycle.py`); three panes: document viewer (server-rendered page PNG + clickable field boxes, low-confidence boxes dashed), extracted fields with confidence bars, threshold marker and source (PDF text / OCR / rule), decision card (reasons sorted block > flag > info, SAP block + tcode, engine/policy version, "AI does not make this decision"); three-way match matrix with variance cells coloured by severity. `GET /api/suppliers` (staff only, bank masked). Verified in the browser with 4 uploaded scenarios (S2 flag, S3 block, S4 block, S11 approve).
- `run.py` fixed: on Windows the backend runs in its own hidden console (output relayed) so uvicorn hot-reload no longer shuts down the whole dev stack.
- Verified in the browser: password login (wrong + right), persona login for supplier/clerk/stores, role badge and entity change per persona, sign-out returns to login, clerk 200 vs stores 403 on `/api/invoices`.

## In progress
- Nothing half-done.

## Next (in order)
1. Phase 1 step 7: human review flow for low-confidence fields with logged corrections.

2. Phase 1 step 8: stores GR/SES posting + automatic re-match (call `run_match(db, inv, trigger="gr_posted")` for open invoices on that PO).
3. Phase 1 step 9: DoA workflow, approvals, SoD, overrides, MFA step-up, SLA escalation.

## Key decisions
- Spec file moved from repo root to `docs/MASTER_PROMPT.md` as the spec instructs. Slides and spec agree (palette, wording); no conflicts found.
- Local `.venv` (git-ignored) for Python deps; spec only requires pip.
- `run.py` uses the interpreter it is launched with; on Windows it kills the process tree with `taskkill /T` so no orphan node/uvicorn processes remain.
- Roles are a fixed string enum on `users.role` (not a table): the six roles are fixed by the spec. Approver level in `users.approver_level`.
- No Alembic yet: schema via `create_all`; `scripts/seed.py --reset` drops and recreates.
- Empty secrets (SECRET_KEY, DATA_ENCRYPTION_KEY) are generated once into `backend/data/keys/` (git-ignored) so a fresh laptop needs no config and sessions/encrypted fields survive restarts. Deleting that folder makes existing encrypted data unreadable: reseed.
- Money `Numeric(16,2)`, quantities `Numeric(16,3)`, handled as `Decimal`.
- Palette AA fixes: bright cyan, green and amber fail AA as text on white, so they are fills/on-navy only; text uses darker variants (cyanText #0A7189, approveText #157A42, flagText #8A5A00, blockText #B0005B). Ratios in tokens.ts.
- Frontend: react-router 7.18.5 (supports React 18; v6 and Vite 5 had npm audit advisories), Vite 8, TypeScript 5.9. Fonts bundled via @fontsource so the UI works offline. Icons: lucide-react.
- Vite dev server proxies `/api` to :8000 so the session cookie is same-origin (SameSite=strict, no CORS in the browser).
- Demo persona login is a server endpoint (`/api/auth/demo-login`) that exists only when DEMO_MODE=true, so no password is embedded in the frontend. It skips password and lockout by design (demo only).
- Cross-tenant access returns 404 (not 403) so a supplier cannot probe which invoice ids exist.
- Login events are not yet in the audit trail: the hash-chained audit log is Phase 1 step 10; wire login/logout events then.
- Fictional bank names and IFSC prefixes (SHYG, NRMD, KVRG) and `.example` email domains so no seed value points at a real entity. RBI bank rate in policy (5.75%) is an editable assumption, to be verified.
- Document viewer uses server-rendered page PNGs (`/api/invoices/{id}/pages/{n}.png`, pdfium, cached in `backend/data/pages/`) instead of pdf.js in the browser: one code path for PDFs and photos, bounding boxes (page fractions) line up exactly, no pdf.js worker to break offline. Deviation from spec section 8 (react-pdf).
- Offline parser targets our generated invoice layout plus label variants; it is the "AI: offline (OCR)" path. Free-text fields (supplier name, descriptions) may lose spaces under OCR; suppliers are identified by GSTIN, never by name.
- Extraction results are append-only: a human correction adds a new row with source=manual; the latest row per field wins.
- Bank account numbers are masked in `extraction_results`; the full number is only stored encrypted on the invoice.
- HSN/SAC rate table (`validation/hsn.py`) is a labelled assumption; ambiguous codes list every allowed rate.
- Rail stops: ordered = PO found; received = no MISSING_GR/SES; matched = decision APPROVE and review done; approved = status approved/paid; paid = status paid. A stop counts only if all earlier stops are done.
- Engine messages format quantities with `fmt_num` (no "2000.000"); sample PDF amount columns widened so large amounts never touch.
- Enums moved to `app/core/enums.py` so the engine can import them without loading the ORM.
- QTY_EXCEEDS_GR and SES_VALUE_EXCEEDED: excess within DQ tolerance is info, up to 5% of received flags, above 5% blocks (spec said "flag/block by tolerance"; we added `DQ.block_pct` = 5 to the policy).
- Only invoices in pending_approval/approved/paid count as "already invoiced" for the cumulative quantity check (blocked or flagged invoices do not consume GR quantity).
- A match on an invoice in `needs_review` is stored but does not change its status until review is done.
- Validation result types live in `engine/types.py` (shared with the step 5 engine); `workflow/matching.py` maps ORM rows to them.
- Runtime data (`backend/data/*.db`, uploads, keys, ai_cache) is git-ignored; demo invoices under `demo/invoices/` will be tracked.

## Known bugs
- The browser pane in this environment is narrower than a laptop screen, so the three-pane layout was checked via DOM measurements at 1600 px (grid 488/390/390 px) and visually only in the stacked narrow layout.
- None known. Visual layout has been checked through the accessibility tree and DOM, not by eye (the browser pane could not take screenshots this session). Have a quick look at the login page and shell on first run.
- Gotcha (fixed): never call `queryClient.clear()` on identity change; it detaches the `me` observer. Use `switchIdentity` in `AuthContext.tsx`.

## Demo status (which demo scenarios work end to end)
- 0 of 12 scenarios (they start in Phase 1). Demoable today: separate logins for all 6 roles with different shells, cross-tenant denial (tests).
