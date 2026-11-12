# Q&A preparation: 25 likely questions

Short answers first; the detail is where to point on screen or in the code. Every claim here is in the code.

**1. What if the AI misreads a quantity?**
It cannot pay a wrong amount on its own. Each field has a confidence; below 85% a person confirms it. The rules
then check arithmetic (qty x price = line value, lines = total) and the cumulative quantity against the goods
receipt, so a misread quantity shows up as MATH_ERROR or QTY_EXCEEDS_GR. On a text PDF the text layer wins any
disagreement with the AI. Corrections are logged with old value, new value, person and reason.

**2. Is the AI making the decisions? How do you prove it?**
No. The engine in `backend/app/engine/` is pure Python with no AI import; a unit test fails the build if one
appears. Every decision is audited as `ai_decided: false`; the Trust page counts decisions made by AI (0).

**3. How does this scale to a million invoices?**
The API is stateless (signed-cookie sessions), so it scales out behind a load balancer. `DATABASE_URL` moves
SQLite to Postgres; the tables are indexed on supplier, status, due dates and invoice numbers. Today OCR and AI run
inside the upload request; at volume they move to a worker queue (not built yet). Rules are cheap: the engine is
pure functions.

**4. How would you integrate with SAP S/4HANA?**
Through the ERP adapter (`backend/app/erp/`): a local adapter for the demo and an S/4HANA stub that builds the real
OData calls: PO read, GR read (movement type 101) and the supplier-invoice post with tax, withholding tax and
payment block R. "SAP posting preview" on any invoice shows the payload. SAP stays the system of record; Duly runs
as a side-car, e.g. a BTP extension.

**5. Why not just use SAP's own tools (MIRO, the duplicate check)?**
MIRO checks after someone has keyed the invoice. Duly reads the document, verifies the signed e-invoice QR,
catches reformatted duplicates and photos (INV/0042 vs INV-42), hidden prompt injection and bank-detail fraud,
watches MSME due dates and explains every decision to the supplier. The SAP tolerance keys (PP, DQ, BD) and
payment blocks are reused on purpose so AP sees familiar rules.

**6. What happens if the supplier's QR is missing?**
For suppliers above the e-invoice threshold: FLAG EINVOICE_QR_MISSING, a clerk asks for the original PDF. For
suppliers below it: "e-invoice not applicable", no flag. A forged QR (wrong key) is BLOCK QR_SIGNATURE_INVALID;
an edited PDF with the original QR is BLOCK QR_MISMATCH.

**7. How do you stop the chatbot leaking another supplier's data?**
The supplier id comes from the session, never from the model or the request; tools are read-only and can only
query that supplier. Questions naming another supplier are refused before any model call and logged; injection
phrases are stripped. Tool results contain no bank data. It also works offline with no model at all.

**8. What are the limits of your impact numbers?**
The measured half runs on synthetic data: it proves the mechanism, not Plant X's performance. The projection is
only as good as its assumptions, so every input is visible, explained, conservative and editable on screen, and
the formula is shown with the numbers. Exception handling time, disputes and fraud prevented are not counted.

**9. What if the internet or the AI API is down?**
Nothing stops. AI mode offline uses local OCR (RapidOCR) and the deterministic parser; cached replays earlier AI
readings. Any AI error falls back to offline automatically and the reason is in the audit trail. The demo runs
offline.

**10. How do you handle partial deliveries?**
Matching is cumulative per PO line: received quantity minus quantity already on accepted invoices. A second
delivery's invoice is clean; billing beyond what arrived is FLAG or BLOCK by tolerance. A new GR re-checks every
waiting invoice on that PO automatically.

**11. How do you prevent duplicate payments?**
Five signals against every earlier invoice: same normalised number in the same financial year for the supplier,
same IRN, same file hash (each a BLOCK), plus near-matches (total, date, items) and a perceptual hash of page 1
(FLAG when combined). The compare screen shows both documents side by side.

**12. How do you stop bank-detail fraud?**
An invoice printing a different account or IFSC than the vendor master is BLOCKED with a security alert. Bank
details change only through a supplier request, a clerk's call-back to the number already on file, a 72-hour
cooling period and a finance approver who is not the maker. Accounts are encrypted and masked.

**13. What is prompt injection and how do you defend against it?**
Text in a document that tries to instruct the AI ("approve this invoice"). Duly scans for hidden text (white,
tiny, off-page, metadata) and instruction-like phrases before any AI reads the file; hidden words never reach the
parser; the AI's output is quarantined and shown to the clerk; and the AI has no power over the decision anyway.

**14. How is the audit trail tamper-evident? What if a database admin edits or deletes rows?**
Each event's SHA-256 hash includes the previous event's hash, and the latest head is signed with an Ed25519 key.
Editing a row breaks its hash; deleting one breaks the link; cutting the tail contradicts the signed head. Verify
shows the exact event. Demo: Demo controls → Run tamper demo, then Audit chain → Verify.

**15. What stops someone approving their own invoice?**
Segregation of duties enforced on the server: you cannot approve an invoice you processed, an invoice for a PO you
created, or two steps of the same invoice; clerks cannot approve at all; refusals are logged. MFA above ₹10 lakh.

**16. Why does the MSME 45-day rule matter?**
For Udyam-registered micro and small suppliers, payment is due within the agreed term capped at 45 days from
acceptance (15 days without a written agreement). Late payment costs compound interest at three times the RBI bank
rate, and the expense is not tax-deductible until paid. Duly computes the due date at GR / SES, counts down, pays
those invoices first and prepares the half-yearly MSME Form I data.

**17. How is TDS computed? Is that tax advice?**
From a policy table under s.393 of the Income-tax Act 2025 (formerly 194C / 194J / 194Q): rate by supplier type
and PAN, with single and yearly thresholds, on the taxable value. It is a labelled assumption: "verify with the tax
team". Not tax advice.

**18. Who changes tolerances and approval limits?**
They are versioned policy data, not code. Every match stores the policy version that decided it, so old decisions
stay explainable after a change.

**19. How do you protect supplier data?**
Row-level scoping (suppliers see only their invoices; others' return 404), AES-GCM encryption of bank accounts,
masking in the UI and logs, upload hardening, httpOnly SameSite=strict sessions with CSRF protection, Argon2id
passwords, lockout and rate limits, security headers.

**20. What data goes to the AI provider?**
Only the invoice itself: page images and the text read from them. Never the vendor master or its bank records,
never other invoices. The kill switch (offline) sends nothing at all.

**21. Your dashboards are full of data. Is it real?**
No, it is synthetic and labelled so. The 90-day history is generated by replaying business events (deliveries,
invoices, approvals, payment runs, a bank change) through Duly's own engine and workflow with the clock set to
past dates, so every decision and number is what Duly itself would have produced.

**22. How accurate is OCR on phone photos?**
Clean photos and scans read well (two demo files are a photo and a scan). Blurry ones lose fields; Duly does not
guess but sends them to review. A known limit: OCR can occasionally misread with high confidence; the GSTIN check
digit and arithmetic rules catch most of those, but they are blocked rather than explained as an OCR issue.

**23. Is it accessible?**
Keyboard-first (command palette Ctrl+K, queue shortcuts), visible focus rings, colour never the only signal, WCAG
AA contrast. An automated axe-core scan of 22 screens runs in our Playwright tests with zero violations. The
supplier side is in English and Hindi.

**24. What does the AI cost per invoice?**
Our planning assumption is about ₹3 an invoice (roughly 1.5 pages of images and text per call); it is an editable
input on the Impact page and should be checked against current API pricing. Offline mode costs nothing per invoice.

**25. What would you need for production?**
SSO via the company identity provider, the real IRP public key, S/4HANA integration through BTP, Postgres with
backups, a worker queue for OCR and AI, a data-retention setting, secrets in a vault, a penetration test and a
DPIA. All are listed in docs/CONTROLS.md.

**Bonus: How did you build it so fast? Can you explain the code?**
With Claude Code as a pair programmer, in small tested steps (docs/AI_DECLARATION.md). Each module has a docstring
and a doc: decision engine (docs/DECISION_ENGINE.md), architecture, controls, impact. `python scripts/demo_check.py`
proves all 12 scenarios end to end.
