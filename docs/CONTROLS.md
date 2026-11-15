# Responsible AI, security and data controls

The in-app **Trust & controls** page (`/trust`) shows each control below with live evidence from the database and
the audit chain. The auditor's **Controls report** (`/controls`, PDF too) tests controls C-01 to C-10 on the data for
a period. This file says how each control works, where it lives in the code, and which test proves it.

## 1. AI never decides
- The rules engine (`backend/app/engine/decide.py`) decides APPROVE / FLAG / BLOCK. It is pure: no I/O, no
  database, no AI. `tests/test_engine.py` fails if anything under `app/engine/` imports `app.ai`, the ORM or SQLAlchemy.
- AI does two things only: extract fields from the invoice (`app/ai/`) and answer supplier questions through
  read-only tools (`app/chat/`).
- Every match is audited with `ai_decided: false` and actor `system`; the Trust page counts decisions made by AI
  (always 0).

## 2. Confidence and human review
- Every extracted field has a confidence, the page and the bounding box it came from, and its source (PDF text,
  OCR, AI, rule). Fields below the policy threshold (85%), unread key fields and unread HSN codes go to review
  (`pending_review` in `app/ingestion/pipeline.py`); the decision is held until review is done.
- When AI and the PDF text layer disagree, the text layer wins and the field goes to review (`app/ai/extract.py`).
- Reviews are append-only: a correction adds a row with the old value, old confidence, reviewer and reason
  (`app/workflow/review.py`). Bank account numbers are masked even in the review log. Tests: `test_review.py`.

## 3. Prompt-injection defence (D2)
- Before any AI reads a PDF, `app/ingestion/injection.py` finds white or near-white, tiny (< 3.5 pt) and off-page
  text, PDF metadata, and instruction-like phrasing. Hidden words never reach the parser.
- If anything is found, the AI's reading is quarantined: stored and shown to the clerk next to the hidden text,
  never used. The AI's own `suspicious_text` report also quarantines. Engine reason `INJECTION_ATTEMPT` (FLAG).
- Extraction uses a fixed system prompt, a strict JSON schema output and no tools.
- Chatbot: the supplier id comes from the session, never from the model; other suppliers named in a question are
  refused before any model call and logged (`security.chat_cross_tenant_refused`); injection phrases are stripped
  and logged (`app/chat/guardrails.py`). Tests: `test_injection.py`, `test_chat.py`.

## 4. Access
- Six roles with server-side checks on every route (`require_roles`); suppliers see only their own rows
  (`get_scope`; other suppliers' invoices return 404, not 403). Tests: `test_rbac_scoping.py`, `test_auth.py`.
- Segregation of duties (`app/workflow/approvals.py`): no approving an invoice you processed, a PO you created, or
  two steps of one invoice; clerks cannot approve; the bank-change maker cannot be the checker. Refusals are
  audited (`security.sod_refused`).
- MFA (TOTP) for approvals above ₹10 lakh, checked against real time. Overrides of a FLAG need a written
  justification and two approval levels; a BLOCK can never be overridden.
- Sessions: signed JWT in an httpOnly, SameSite=strict cookie, 60 minutes sliding; logout revokes all tokens.
  Double-submit CSRF token. Argon2id password hashes. Five failed logins lock an account for 15 minutes; login
  rate limit 10 per minute per IP; unknown e-mails get the same error and timing.

## 5. Privacy and data minimisation
- **Our setup runs in AI mode offline: nothing is sent to any AI provider.** Invoices are read on the laptop (local
  OCR and the PDF text layer); the chatbot answers from an offline intent matcher.
- If the optional AI integration is switched on: only the invoice itself (page images and the text read from them) goes to the AI provider. Never the vendor
  master or its bank records, never other invoices. Chatbot tool results carry no bank data.
- Vendor and invoice bank accounts are encrypted at rest (AES-GCM, key from the environment) and masked everywhere
  (XXXXXX4417), including logs and audit events. Chat transcripts are stored with digits redacted.
- Synthetic data only; every master record is flagged `is_synthetic`.
- Data retention (`backend/app/workflow/retention.py`, Policy page, test `test_retention.py`): the original file and
  page images of a **paid or rejected** invoice are deleted once older than `retention.documents_years` (default 8,
  minimum 6: assumption based on CGST Act s.36 and Companies Act s.128(5), confirm with legal); payment-assistant
  chats after `chat_days` (180); AP-mailbox email text after `email_body_days` (365). Open invoices keep their files.
  Never deleted: the audit trail, invoice data, payments, the extraction / review log, and the file's SHA-256 and
  pHash (so duplicate detection keeps working). Run by an admin from the Policy page (a scheduler in production);
  each run is audited (`retention.run`, counts only); a deleted file returns HTTP 410 and the invoice says why.
- AI kill switch: AI mode **offline** (admin Demo controls, or `AI_MODE=offline`) runs everything on local OCR and
  rules; **cached** replays earlier AI readings with no network. The demo and judging setup is offline.

## 6. Security
- Upload hardening (`app/ingestion/hardening.py`): extension must match the file's magic bytes; 10 MB and 20
  pages maximum; PDFs with JavaScript, launch actions or embedded files are refused (including hex-obfuscated
  names); images are re-encoded to strip metadata. Files are stored under random names outside any web root and
  fingerprinted (SHA-256). Tests: `test_hardening.py`.
- Tamper-evident audit trail (`app/core/audit.py`): each event's hash covers the previous hash; the head is signed
  with Ed25519; events are written only after the business transaction commits. `GET /api/audit/verify`
  pinpoints an edited row, a broken link or a truncated tail. Tests: `test_audit.py`, `test_zz_chain_integrity.py`.
- Bank-detail fraud (D3): a different account or IFSC on an invoice is BLOCK `BANK_MISMATCH` plus a security
  alert; changes go through a call-back checklist, maker-checker and a 72-hour cooling period.
- Security headers on API responses (CSP `default-src 'none'`, X-Frame-Options DENY, nosniff, no-referrer,
  no-store). Secrets only in environment variables (`.env` is git-ignored; empty secrets are generated into the
  git-ignored `backend/data/keys/`). All dependencies pinned to exact versions; `npm audit` and `pip-audit`
  clean (2026-11-15).
- Web app headers (`frontend/vercel.json`): strict Content-Security-Policy (`'self'` only, no inline or eval
  scripts, `frame-ancestors 'none'`), X-Frame-Options DENY, nosniff, strict referrer, Permissions-Policy
  (no camera, microphone, location or payment APIs), Cross-Origin-Opener-Policy, HSTS (Vercel).
- Abuse protection for the public demo (`app/core/guard.py`, settings in `render.yaml`):
  - request bodies above 12 MB are refused **before** they are read (the file checks only run after parsing);
  - the client IP for rate limits and the audit trail is taken from our own proxy hop
    (`TRUSTED_PROXY_HOPS`), not from the caller-controlled left-most `X-Forwarded-For` entry;
  - per-IP limits on uploads and composed emails (30 an hour, 6 a minute), mailbox fetch, policy changes,
    data retention, demo reset, tamper demo and the PDF report, on top of the login and chat limits;
  - site-wide limits that IP spoofing cannot bypass: one OCR job at a time on the 512 MB host (others get 503
    "busy" instead of crashing it) and an hourly upload ceiling; at most 5 attachments per email;
  - every visitor shares one database, so it goes back to the staged snapshot every hour, which clears
    vandalism, odd uploads and a left-over tamper demo. The login page says so and asks for no real documents;
  - signing out of a shared demo persona no longer revokes every other visitor's session (production keeps the
    revoke-all behaviour); interactive API docs are switched off on the public site.
  - Tests: `test_guard.py`, `test_auth.py`.
- Free-text inputs all have length limits (comments 500, chat 1,000, reasons 300 characters; lists and maps capped).
- CSV export neutralises spreadsheet formulas (`=`, `+`, `-`, `@` prefixes) so a supplier-controlled invoice
  number cannot run as a formula in Excel.

## 7. Transparency
- The AI mode badge is always in the top bar. Each extracted field stores the extractor, model and prompt version;
  each AI fallback to offline is recorded with its reason in the upload's audit event.
- Each decision shows reason codes, evidence values, where on the page each value came from, the policy version
  and the engine version (see docs/DECISION_ENGINE.md), and who did what (approval timeline, audit trail).

## 8. Model card (summary; full text on the Trust page)
- **Does:** reads invoice pages into fields with confidence and the line they came from; answers supplier
  questions with five read-only, supplier-scoped tools.
- **Does not:** approve, flag, block, route or pay; see vendor master data, bank records or other suppliers' data;
  use tools during extraction.
- **Known failure modes:** misreads on blurred or tilted photos (also confident ones; see Known bugs in
  PROGRESS.md), instructions hidden in documents, API outages. Mitigations: confidence threshold, arithmetic and
  GSTIN check-digit rules, the injection shield, automatic offline fallback.
- **Humans in control:** review of low-confidence fields, approvals under delegation of authority with MFA, the
  kill switch.

## 9. Generative AI use
See docs/AI_DECLARATION.md.

## Not built (production path)
- A scheduled (nightly) retention run and legal hold; today retention is applied by an admin on demand.
- Single sign-on via the company identity provider (demo uses local accounts and demo personas).
- Real IRP public key for e-invoice QRs (demo uses a local Sandbox IRP key).
- Penetration test and DPIA; Postgres with backups instead of SQLite; secrets in a vault.
