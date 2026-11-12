# PROGRESS
Last updated: 2026-11-13 00:05 IST by Shivansh (Claude Code)

## How to run
Requirements: Python 3.12, Node.js 20.19+ (Vite 8). Windows or macOS.
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env              # optional: everything has safe demo defaults
python scripts/seed.py --reset
python scripts/tamper_demo.py   # optional: break the audit chain; --restore to undo
python run.py                     # backend :8000, frontend :5173 (Ctrl+C stops both)
cd backend && python -m pytest    # 136 tests (about 20 s; OCR model loads once)
cd frontend && npm run typecheck
```
- Open http://localhost:5173. With `DEMO_MODE=true` (default) the login page lists one-click demo personas.
- Seed: 14 users, demo password `Duly@2026` for all (synthetic). API docs at http://127.0.0.1:8000/api/docs.
- After any model change, re-run `python scripts/seed.py --reset` (no migrations yet).

## Done
- **Phase 0 and Phase 1 complete** (core expectations 1 to 5 working end to end).
- Step 1: repo layout, `.gitignore`, `.gitattributes` (LF), `.env.example`, README, `docs/MASTER_PROMPT.md`, PROGRESS.md, `run.py`. Slides in `docs/brief/` (7 images).
- Step 2 backend: FastAPI app, `/api/health`, SQLAlchemy models for every core entity (spec section 8), AES-GCM field encryption (bank accounts, TOTP secrets), Argon2id hashing, GSTIN check digit + synthetic generator, versioned default policy v1 (`app/core/policy_defaults.py`), `scripts/seed.py --reset` (Plant X, 6 suppliers, 14 users across all 6 roles, approvers L1/L2/L3 with MFA secrets), security headers.
- Step 2 frontend: Vite + React 18 + TS, design tokens (`frontend/src/theme/tokens.ts`, AA-checked), app shell (navy sidebar, top bar with entity, AI mode and role badges, skip link), login page, Duly 5-stop rail component, per-role Overview page (server-reported permissions + system status).
- Step 3 auth: login/logout/me, JWT in httpOnly SameSite=strict cookie, signed double-submit CSRF, sliding 60-min session, logout revokes all tokens (token_version), lockout after 5 failures (15 min), login rate limit (slowapi, 10/min/IP), generic error + dummy-hash timing for unknown emails, `require_roles` RBAC dependency, `get_scope` supplier row scoping (404 for other suppliers' invoices), demo personas + demo-login (404 when DEMO_MODE=false), `/api/invoices` list/detail (scoped; stores gets 403).
- **Phase 1 step 4 (backend)**: `POST /api/invoices/upload` (supplier, or clerk on behalf; supplier resolved by GSTIN), upload hardening (`ingestion/hardening.py`: extension vs magic bytes, 10 MB, 20 pages, rejects PDF JavaScript/Launch/EmbeddedFiles incl. hex-obfuscated names, re-encodes images to strip EXIF), random stored names + SHA-256, text layer (pdfplumber) with OCR fallback (RapidOCR, offline), offline regex parser with per-field confidence + page + bbox (`ai/offline_parser.py`), validation layer (`validation/rules.py`: GSTIN check digit, bill-to = Plant X, invoice no <= 16 chars, date not future / not older than previous FY, line and total arithmetic within Rs 1, CGST+SGST vs IGST by place of supply, GST rate vs HSN table), low-confidence fields mark the invoice `needs_review`. Endpoints for the document file and server-rendered page PNGs (scoped). Sample GST invoice renderer `app/samples/invoice_pdf.py`.
- **Phase 1 step 5**: decision engine `app/engine/decide.py` (pure, deterministic; test proves no `app.ai`/ORM/SQLAlchemy import). All reason codes from spec C3 plus LINE_NOT_ON_PO, SES_VALUE_EXCEEDED, SMALL_DIFFERENCE, LINE_MAPPED; PP/DQ/BD tolerances from versioned policy; cumulative qty check for partial deliveries; kg/MT unit conversion; fuzzy description line mapping (rapidfuzz); SAP block + tcode per code (`engine/catalog.py`). `workflow/matching.run_match` builds PO/GR/SES/invoiced-history views, stores a MatchResult with reasons + matrix snapshot, sets invoice status (blocked / flagged / pending_approval). Runs on every upload. Seed now has 14 scenario POs (4500001001..1013 + closed 4500000990), 10 GRs, 3 SESs (`app/seed.py` PURCHASE_ORDERS lists which scenario each PO serves). `docs/DECISION_ENGINE.md` written.
- **Phase 1 step 6**: invoice screens. `/invoices` list (decision + status chips, owner), `/upload` (drag and drop; clerk can pick a supplier or let Duly identify it by GSTIN), `/invoices/:id` hero screen: header with total, PO, status, owner and the 5-stop Duly rail (computed server-side in `workflow/lifecycle.py`); three panes: document viewer (server-rendered page PNG + clickable field boxes, low-confidence boxes dashed), extracted fields with confidence bars, threshold marker and source (PDF text / OCR / rule), decision card (reasons sorted block > flag > info, SAP block + tcode, engine/policy version, "AI does not make this decision"); three-way match matrix with variance cells coloured by severity. `GET /api/suppliers` (staff only, bank masked). Verified in the browser with 4 uploaded scenarios (S2 flag, S3 block, S4 block, S11 approve).
- **Phase 1 step 7**: human review. `POST /api/invoices/{id}/review` (clerk only, reason required): confirm a field as read or correct it; each action appends a `source=manual` row with previous value, previous confidence, reviewer and reason (bank accounts masked), writes the value onto the invoice/line, re-runs the match (trigger `correction` / `review_completed`) and releases the invoice from `needs_review` when nothing is pending. `pending_review()` in `ingestion/pipeline.py` is the single definition. UI: review banner with "Show next field", Confirm / Correct per field, inline editor, correction history under each field. New engine rule `NO_LINES` (block: never approve an invoice with no readable lines). OCR robustness: deskewed line grouping for tilted photos, rows survive a lost line number / GST % / description (rate derived at low confidence). Scenario 12 verified end to end in the browser (blurry tilted JPEG -> 7 fields to review incl. a real OCR misread HSN 3823 -> corrected -> APPROVE).
- **Phase 1 step 8**: stores receiving. `GET /api/stores/open-pos`, `POST /api/stores/goods-receipts` (MIGO 101; no over-receipt beyond the PO, +0.5% for MT), `POST /api/stores/service-entries` (ML81N; not above PO line value). After each posting `workflow/receipts.rematch_waiting` re-runs the engine for every not-yet-approved invoice on that PO (trigger `gr_posted:<GR>` / `ses_posted:<SES>`); stores only learns how many were re-checked/released, never which invoices. UI: `/receiving` (stores nav) with a card per open PO. Scenario 4 verified live in the browser: NPW-311 BLOCK MISSING_GR -> stores posts GR 5000000111 -> APPROVE, pending approval.
- **Phase 1 step 9**: approval workflow (`workflow/approvals.py`). DoA from policy data: clean match <= Rs 50,000 approved by policy P-01 (touchless), <= Rs 10 lakh L1, <= Rs 1 crore L1 then L2, above L1/L2/L3. Route opens automatically when a match is APPROVE (hook in `run_match`), closes when a re-match turns FLAG/BLOCK. Clerk override of a FLAG with >= 15-char justification (never touchless, always >= 2 approvers); BLOCK cannot be overridden. SoD: no approving an invoice you processed, a PO you created, or two steps of one invoice; clerks get an explicit SoD refusal. MFA step-up (TOTP, pyotp) above Rs 10 lakh; demo-mode QR on the approver's Overview (`GET /api/auth/mfa-setup`, own account only). Approve / reject (reason) / send back (comment) / ask supplier. SLA 48 h per step; overdue steps escalate so the next level can act (`escalate_overdue`, evaluated lazily). Time-boxed delegation. Demo clock with persisted offset (`core/clock.py`, admin `/admin/demo`, `POST /api/admin/clock/advance|reset`, DEMO_MODE only). UI: approval timeline + actions in the invoice decision pane, `/approvals` queue (actionable first, SoD conflicts listed with reason) + delegation card. Verified in the browser: Rohan sees QR, queue shows SoD on freight PO, approves Rs 15 lakh with a real TOTP code -> "Awaiting L2", then sees the SoD note.
- **Phase 1 step 10**: tamper-evident audit trail (`core/audit.py`). `hash = SHA256(prev_hash + canonical_json(event))`, head (id:hash) signed with an Ed25519 key in `backend/data/keys/audit_ed25519.pem`. Events are queued on the request session (`audit.queue`) and written only after that transaction commits (SQLAlchemy after_commit hook, process lock) so rolled-back actions leave no entry. Recorded: logins (ok/failed/locked), logout, upload+extraction summary, every match (actor `system`, `ai_decided: false`), field reviews (before/after, reason), routing, approvals (level, MFA, delegation), rejections, send-backs, info requests, overrides, escalations, SoD refusals (`security.sod_refused`), GR/SES postings, demo clock changes, chain verifications, seeding. `GET /api/audit/verify` pinpoints the first broken event (edited content or broken link) and detects truncation via the signed head. `scripts/tamper_demo.py [--restore]` and admin "Run tamper demo / Restore" edit a row with raw SQL. UI: `/audit` (auditor, admin) with Verify, chain-of-blocks view (broken block highlighted), filterable event table; invoice detail shows that invoice's audit trail for staff. Verified live: tamper -> "Chain broken at event #24" -> restore -> verified.
- **Phase 1 step 11**: exceptions dashboard + work queue (`api/dashboard.py`, all numbers computed live). KPIs: in queue, value on hold, touchless rate (approved by P-01 / all approved), avg cycle time (upload -> final approval), MSME due <= 7 days (+ overdue), duplicates prevented (counts DUPLICATE/POSSIBLE_DUPLICATE reasons; 0 until B1). Open exceptions by type (Recharts bar, block vs flag colour + legend), by age buckets, by supplier (value at risk, oldest), MSME due-date heatmap (-7..+30 days, overdue highlighted). Every chart/tile drills down to `/queue?...`. Queue: URL filters (status, reason, supplier, age, MSME due), sortable columns, saved views (localStorage), CSV export, keyboard J/K/Enter, A approve (approvers, no-MFA invoices), R/F open. Contract and statutory MSME due dates now set at acceptance (GR/SES) in `run_match` via `payments/msme.py`. A test proves each dashboard count equals its drill-down queue length.
- **Phase 1 step 12**: supplier portal (`/portal`, `GET /api/portal`, supplier only, own data). Header with MSME status, Udyam no., terms (MSME: paid within N days of acceptance), masked bank account; tiles (open, need your action, next expected payment, paid so far); a card per invoice with Duly rail, supplier-friendly stage, expected payment date, MSME statutory due date + countdown, "What you need to do" (e.g. exact credit-note amount = excess qty x PO price x (1 + GST)) and "What Plant X is doing" (e.g. waiting for GR, re-checked automatically); payment history table (UTRs appear with the Phase 3 payment run). English / Hindi via i18next with reviewed JSON files (`frontend/src/i18n/en.json`, `hi.json`), IBM Plex Sans Devanagari bundled for offline. Suppliers' nav: My invoices + Upload (generic Invoices list now staff only). Verified in the browser in both languages.
- **Phase 2 step 13**: Claude extraction (`ai/claude_extractor.py`, `ai/extract.py`, prompt `ai/prompts/extraction.py` = `extract-v1`). Page images (150 dpi, max 5 pages) + numbered text lines -> structured output (`output_config.format` JSON schema: value, confidence, cited line id per field; `suspicious_text` for injection signals). Model from `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`, effort medium) with server-side refusal fallback (`fallbacks: "default"`). Merge with the deterministic parser: agree -> max confidence; disagree -> PDF-text value kept (or AI's for OCR) at reduced confidence so a human reviews it; boxes from our tokens on the cited line. Cache by SHA-256 + model + prompt version in `backend/data/ai_cache/`. `AI_MODE` auto | live | cached | offline; any AI failure falls back to offline with the reason in the audit event. Model + prompt version stored per field. Tested with a mocked client (no key on this laptop: the live path has NOT been run against the real API yet).
- **Phase 2 step 14**: duplicate detection (`duplicates/detector.py`, pure). Signals vs every earlier non-rejected invoice: exact normalised number + same supplier + same FY, same IRN, same file SHA-256 (any -> BLOCK `DUPLICATE`); near-match (same supplier, total +-0.5%, date <= 30 days, item/qty Jaccard >= 0.8) and page-1 pHash (corroboration only) combined into a probability (>= 0.6 -> FLAG `POSSIBLE_DUPLICATE`); same bank account on two suppliers -> FLAG `BANK_ACCOUNT_SHARED`. Reasons enter the engine via `decide(..., extra_reasons)` (engine stays pure); runs on upload and every re-match. `GET /api/invoices/{id}/duplicates` + `/invoices/:id/compare` page (both documents, signals, field-by-field same/differs). Scenario 5 verified in tests and live (photo "INV-42" blocked as duplicate of "INV/0042"). Dashboard "duplicates prevented" now counts real cases.
- `run.py` fixed: on Windows the backend runs in its own hidden console (output relayed) so uvicorn hot-reload no longer shuts down the whole dev stack.
- Verified in the browser: password login (wrong + right), persona login for supplier/clerk/stores, role badge and entity change per persona, sign-out returns to login, clerk 200 vs stores 403 on `/api/invoices`.

## In progress
- Nothing half-done.

## Next (in order)
1. Phase 1 step 7: human review flow for low-confidence fields with logged corrections.

2. Phase 1 step 8: stores GR/SES posting + automatic re-match (call `run_match(db, inv, trigger="gr_posted")` for open invoices on that PO).
2. Phase 1 step 9: DoA workflow, approvals, SoD, overrides, MFA step-up, SLA escalation.
2. Phase 1 step 10: audit chain (hash + signed head) + verify endpoint + auditor view; then wire login, upload, review, decision events into it.
2. Phase 1 step 11: exceptions dashboard (type, supplier, age, drill-down) + work queue with keyboard shortcuts.
2. Phase 1 step 12: supplier portal (invoice list with Duly rail, owner, plain-language block reasons, MSME countdown).
2. Phase 2 step 13: Claude extraction with structured output, per-field confidence and boxes, response cache by SHA-256, AI mode badge (offline parser stays the fallback).
2. Phase 2 step 14: duplicate detection (5 signals) + side-by-side compare.
2. Phase 2 step 15: "Where is my payment?" chatbot with scoped tools, guardrails, offline intent fallback, English/Hindi (the portal footer currently says "coming soon"; update it when done).
2. Phase 2 step 16: controls report for auditors (screen + PDF via reportlab).
3. Phase 3 step 17: Sandbox IRP signing + signed-QR verification (D1).

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
- pHash is corroborating only (weight 0.35, below the 0.6 flag threshold) and only within one supplier: measured on our template invoices, a different invoice on the same template has distance ~2 while a phone photo of the same invoice has ~8, so pHash alone cannot identify an invoice. Exact duplicates are caught by normalised number / IRN / SHA-256.
- Duplicates compare only against earlier invoices (lower id), so the original is never flagged as a copy of its resubmission; rejected invoices are ignored.
- AI bounding boxes come from our own positioned tokens on the line Claude cites, not model-estimated coordinates (more reliable highlights). On disagreement with the exact PDF text layer, the PDF text wins and the field goes to review.
- `AI_MODE=cached` lets the team pre-warm `backend/data/ai_cache/` with a key once and then demo with live-quality extraction fully offline.
- Supplier to-dos are message codes + params from the server, rendered from i18n files; no internal data (approver names, SAP refs) is sent to suppliers. Language choice is a per-browser preference (localStorage).
- MSME clock starts at acceptance (GR/SES date) whatever the match outcome; traders excluded; no written agreement = 15 days.
- Dashboard data is sparse until Phase 4 seeds ~250 historical invoices; charts and KPIs are already live queries, not placeholders.
- Recharts 3.10.1 (React 18 compatible, 0 audit findings).
- Audit events are written after commit in their own transaction (not inside the business transaction): guarantees no phantom events; the tiny risk is a crash between the two commits losing an event, acceptable for the demo and noted for production (outbox pattern).
- Audit `ts` uses the business clock (so it lines up with SLA timers in demo mode). Automated decisions (matches, routing, P-01, escalations) are recorded with actor `system`.
- Approver levels are exact: an L2 does not approve an L1 step unless it escalated (SLA missed) or L1 delegated to them. "Second approver" for a FLAG override is read as: at least two approval levels (L1 + L2) even below Rs 10 lakh.
- Approval API errors return `detail: {message, sod, mfa}`; SoD refusals are HTTP 403, other refusals 422. The UI shows SoD in red with a lock icon.
- MFA codes are checked against real time (not the demo clock), window +/- 30 s.
- Confirm is one click (reason "Confirmed against the document", reviewer recorded); Correct requires a typed reason. Missing non-key fields (e.g. a CGST total OCR could not read) are not review items; MATH_ERROR flags them and the clerk can enter them via Correct.
- No readable lines is not a review item; the engine blocks it with NO_LINES.
- Rail stops: ordered = PO found; received = no MISSING_GR/SES; matched = decision APPROVE and review done; approved = status approved/paid; paid = status paid. A stop counts only if all earlier stops are done.
- Engine messages format quantities with `fmt_num` (no "2000.000"); sample PDF amount columns widened so large amounts never touch.
- Enums moved to `app/core/enums.py` so the engine can import them without loading the ORM.
- QTY_EXCEEDS_GR and SES_VALUE_EXCEEDED: excess within DQ tolerance is info, up to 5% of received flags, above 5% blocks (spec said "flag/block by tolerance"; we added `DQ.block_pct` = 5 to the policy).
- Only invoices in pending_approval/approved/paid count as "already invoiced" for the cumulative quantity check (blocked or flagged invoices do not consume GR quantity).
- A match on an invoice in `needs_review` is stored but does not change its status until review is done.
- Validation result types live in `engine/types.py` (shared with the step 5 engine); `workflow/matching.py` maps ORM rows to them.
- Runtime data (`backend/data/*.db`, uploads, keys, ai_cache) is git-ignored; demo invoices under `demo/invoices/` will be tracked.

## Known bugs
- Live Claude extraction is untested against the real API on this laptop (no key). Before the demo: set ANTHROPIC_API_KEY, upload the demo invoices once (fills the cache), then consider AI_MODE=cached.
- The browser pane in this environment is narrower than a laptop screen, so the three-pane layout was checked via DOM measurements at 1600 px (grid 488/390/390 px) and visually only in the stacked narrow layout.
- None known. Visual layout has been checked through the accessibility tree and DOM, not by eye (the browser pane could not take screenshots this session). Have a quick look at the login page and shell on first run.
- Gotcha (fixed): never call `queryClient.clear()` on identity change; it detaches the `me` observer. Use `switchIdentity` in `AuthContext.tsx`.

## Demo status (which demo scenarios work end to end)
Scenario PDFs are not generated into `demo/` yet (Phase 4 step 22); today they are produced by the test fixtures / an ad-hoc script.
- S2 price variance: works (FLAG, exact ₹39,680).
- S3 qty exceeds GR: works (BLOCK, cumulative view).
- S4 missing GR: works end to end (BLOCK, stores posts GR live, auto re-match releases it).
- S11 services with SES: APPROVE works; TDS is Phase 3.
- S12 blurry photo: works end to end (review, logged corrections, APPROVE).
- S1 Rs 15 lakh catalyst: APPROVE -> L1 then L2 with MFA works end to end (tested in API tests and browser).
- S6, S9 decisions are covered by engine tests; generated demo PDFs come in Phase 4.
- Separate logins for all 6 roles, cross-tenant denial: works.
- S5 duplicate photo with reformatted number: works end to end (BLOCK DUPLICATE, side-by-side compare).
- Supplier can see where each invoice is, why, what to do and when it will be paid (en/hi): works.
- Dev DB invoices uploaded before step 11 have no MSME due date; run `python scripts/seed.py --reset` and re-upload to see countdowns.
