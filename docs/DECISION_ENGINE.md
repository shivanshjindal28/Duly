# Duly decision engine

Code: `backend/app/engine/decide.py` (rules), `engine/policy.py` (tolerances), `engine/catalog.py` (titles and SAP equivalents), `validation/rules.py` (document checks). Tests: `backend/tests/test_engine.py`, `test_validation.py`.

## Principles
- **Deterministic and pure.** No I/O, no database, no AI. A unit test fails if anything under `app/engine/` imports `app.ai`, the ORM or SQLAlchemy.
- **AI never decides.** AI only extracts fields (and powers the supplier chatbot). The decision is always this engine.
- **Outcome.** Any BLOCK reason means **BLOCK** (cannot be paid until the cause is fixed; BLOCKs cannot be overridden). Otherwise any FLAG reason means **FLAG** (an AP clerk must review; overriding needs a written justification and a second approver). Otherwise the outcome is **APPROVE**, and the invoice goes to the approval workflow (small clean invoices are approved by policy P-01).
- **Every reason carries evidence.** That means the values compared, the tolerance used, the line number, and the SAP-style payment block and transaction.
- **Versioned.** Every match result stores `engine_version`, `policy_version`, what triggered it (upload, GR posted, correction) and a snapshot of the match matrix.

## Inputs
Invoice (after extraction and human corrections), PO with lines, goods receipts (GR) and service entry sheets (SES) per PO line, quantities already invoiced on accepted invoices (pending approval, approved or paid), supplier master (GSTIN, terms, bank), active policy.

## Reason codes

| Code | Severity | Rule | Default tolerance | SAP equivalent |
|---|---|---|---|---|
| NO_PO | block | No PO number, or PO not found. "No PO, no pay." | none | Block A · ME23N |
| PO_CLOSED | block | PO status is not open | none | Block A · ME23N |
| SUPPLIER_MISMATCH | block | Invoice GSTIN differs from the PO supplier's GSTIN | none | Block A · XK03 |
| BILL_TO_MISMATCH | block | Buyer GSTIN is not Plant X | none | Block A · MIRO |
| CURRENCY_MISMATCH | block | Invoice currency differs from PO | none | Block A · ME23N |
| GSTIN_INVALID | block | Supplier GSTIN fails format or mod-36 check digit | none | Block A · XK03 |
| BANK_MISMATCH | block | Bank account or IFSC on invoice differs from vendor master (possible BEC fraud). Accounts are masked in messages. | none | Block A · XK03 |
| NO_LINES | block | No line items could be read; nothing to match, so never approve | none | Block R · MIRO items |
| LINE_NOT_ON_PO | block | Invoice line matches no PO line (by item code, then fuzzy description ≥ 85), or its unit cannot be converted | none | Block R · ME23N |
| MISSING_GR | block | Goods line with no goods receipt yet. Re-checked automatically when stores posts a GR. | none | Block R · MIGO 101 |
| MISSING_SES | block | Service line with no service entry sheet | none | Block R · ML81N |
| PRICE_VARIANCE | info / flag / block | Unit price (in PO unit) above PO price. Within tolerance: info. Above tolerance up to the hard limit: flag. Above the hard limit: block. Below PO: info. | PP: 1% or ₹500, whichever is lower; hard limit 5% | Block R · MIRO (key PP) |
| SMALL_DIFFERENCE | info | Total price difference on a line ≤ BD amount, auto-accepted | BD: ₹10 | MIRO small differences (key BD) |
| QTY_EXCEEDS_GR | info / flag / block | Invoiced qty > received minus already invoiced (cumulative, supports partial deliveries). Excess within DQ: info. Up to 5% of received: flag. Above: block. | DQ: 0% (0.5% for MT bulk); block above 5% | Block R · MIGO/MIRO (key DQ) |
| SES_VALUE_EXCEEDED | flag / block | Service value billed > accepted SES value minus already invoiced | flag up to 5%, block above | Block R · ML81N |
| UOM_CONVERTED | info | kg↔MT, g↔kg, L↔KL converted to the PO unit before comparing | none | MIRO order unit |
| LINE_MAPPED | info | Line matched to the PO by description, not item code | fuzzy ≥ 85 | ME23N |
| TAX_MISMATCH | flag | Same state charged IGST, or different state charged CGST/SGST; GST rate not valid for HSN; line tax ≠ rate × value; GST rate differs from PO | ₹1 rounding | Block R · MIRO tax |
| MATH_ERROR | flag | qty × price ≠ line value; lines ≠ taxable total; taxable + tax ≠ total | ₹1 rounding | Block R · MIRO balance |
| PAYMENT_TERMS_MISMATCH | flag | PO payment terms differ from vendor master terms | none | Block R · ME23N / XK03 |
| INVOICE_NO_INVALID | flag | Invoice number not 1 to 16 chars of letters, digits, `/` and `-` (GST rule) | none | MIRO reference |
| DATE_INVALID | flag | Invoice date missing, in the future, or before the previous financial year | none | MIRO date |

### Reasons computed outside the engine
These come from modules that need other data (earlier invoices, the signed QR, the injection scan). They are
passed into `decide(..., extra_reasons)` so the engine itself stays pure, and they count like any other reason.

| Code | Severity | Rule | SAP equivalent |
|---|---|---|---|
| DUPLICATE | block | Same supplier and same normalised invoice number in the same FY (`INV/0042` = `INV-42`), or same IRN, or same file SHA-256, as an earlier non-rejected invoice (`duplicates/detector.py`) | Block A · MIRO duplicate check (M8108) |
| POSSIBLE_DUPLICATE | flag | Combined probability ≥ 0.6 from a near-match (same supplier, total within 0.5%, dated within 30 days, ≥ 80% of items and quantities identical) and the page-1 perceptual hash (corroboration only) | Block R · MIRO duplicate check |
| BANK_ACCOUNT_SHARED | flag | The bank account on the invoice appears on invoices of another supplier | Block A · XK03 / FBL1N |
| QR_MISMATCH | block | Signed e-invoice QR verified, but the printed GSTINs, number, date or total differ from the signed values (`ingestion/qr.py`) | Block A · J1IG / IRP |
| QR_SIGNATURE_INVALID | block | A QR is present but not signed by a trusted IRP key | Block A · J1IG / IRP |
| EINVOICE_QR_MISSING | flag | Supplier is above the e-invoice threshold but no readable signed QR was found | Block R · J1IG |
| EINVOICE_VERIFIED | info | Signed QR verified and matches the printed invoice | J1IG |
| EINVOICE_NOT_APPLICABLE | info | Supplier below the e-invoice threshold | J1IG |
| INJECTION_ATTEMPT | flag | Hidden or instruction-like text found in the document; the AI's reading is quarantined (`ingestion/injection.py`) | None (Duly control) |
| ERS_SETTLEMENT | info | Self-billed settlement created by Duly from a GR / SES on an ERS purchase order, at the PO price (`workflow/ers.py`) | MRRL evaluated receipt settlement |
| ERS_PO_INVOICE | flag | A supplier invoice was uploaded against an ERS purchase order, whose receipts Duly settles itself: check it is not a second bill (if it re-bills settled trips, SES_VALUE_EXCEEDED / QTY_EXCEEDS_GR also blocks it) | Block R · MRRL / ME23N ERS indicator |

| CREDIT_NOTE_APPLIED | info | The match is net of the supplier's credit note(s) against this invoice; message gives the numbers, the amount credited and the net payable (`workflow/credit_notes.py`) | MIRO credit memo / FB60 |

**Credit notes.** A BLOCK cannot be overridden; an over-billed invoice is resolved by the supplier's credit note.
The supplier (own invoice) or the AP clerk enters it against a blocked or flagged invoice; the form is prefilled
with the exact credit that clears the QTY_EXCEEDS_GR (quantity) or SES_VALUE_EXCEEDED (value) exception. Duly prices
it from the invoice line (unit price, GST rate, CGST+SGST or IGST as on the invoice) and re-runs the match. The
engine sees each invoice line net of its credited quantity / value (`DocLine.credited_qty`, `credited_value`), and
earlier invoices count net of their credit notes in the cumulative view. The printed invoice is never changed:
math, tax and e-invoice checks still use the printed values; approval bands, MFA, the payment run (gross, TDS
base) and the DoA control use the net amount. Rules: number 1-16 characters and unused by that supplier, dated on or
after the invoice and not in the future, never more than billed per line. Not built: reading a credit-note PDF,
price-difference credit notes clearing PRICE_VARIANCE (the clerk override covers that FLAG), credit notes after
approval.

**Evaluated receipt settlement (ERS).** POs flagged `ers` (seeded: 4500001015, Konkan freight) need no supplier
invoice. When stores posts a GR or SES on one, Duly creates the payable `ERS-<receipt number>` from the receipt at the
PO price and GST rate (CGST+SGST or IGST by state), logs every field with source `ers`, and runs it through this same
engine and the approval route. One settlement per receipt (the number is unique); ERS settlements are not compared
with each other for near-duplicates (two trips of the same value are not copies), but every uploaded invoice is
compared with them.

All tolerances are policy data (`backend/app/core/policy_defaults.py`, stored versioned in the `policies` table). They are assumptions, editable by admin, and every change is audited.

## Worked examples (from the tests)
- **Scenario 2:** PO price ₹620.00/kg, invoice ₹639.84/kg on 2,000 kg. That is +3.20% and ₹39,680.00 more, which is above the PP tolerance and under the 5% hard limit, so the result is **FLAG PRICE_VARIANCE**.
- **Scenario 3:** 100 bearings billed, 80 received, 0 invoiced before. Excess 20 = 25% of received, so the result is **BLOCK QTY_EXCEEDS_GR**. With 60 already invoiced, a bill for 20 is clean, 21 flags and 25 blocks.
- **Scenario 4:** no GR gives **BLOCK MISSING_GR**. Stores posts the GR, the engine re-runs, and the result is **APPROVE**.
- **Scenario 8:** the signed QR says ₹5,01,500, the edited PDF prints ₹5,19,500: **BLOCK QR_MISMATCH** (and MATH_ERROR, since the printed total no longer adds up).

All 12 scenarios with their expected reason codes: `demo/manifest.json`; checked end to end by `python scripts/demo_check.py`.
