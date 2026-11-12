# Duly decision engine

Code: `backend/app/engine/decide.py` (rules), `engine/policy.py` (tolerances), `engine/catalog.py` (titles and SAP equivalents), `validation/rules.py` (document checks). Tests: `backend/tests/test_engine.py`, `test_validation.py`.

## Principles
- **Deterministic and pure.** No I/O, no database, no AI. A unit test fails if anything under `app/engine/` imports `app.ai`, the ORM or SQLAlchemy.
- **AI never decides.** AI (Phase 2) only extracts fields and writes explanations *from* the reason codes. The decision is always this engine.
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

Coming in later phases: `DUPLICATE` / `POSSIBLE_DUPLICATE` (B1), `QR_MISMATCH` (D1), `INJECTION_ATTEMPT` (D2).

All tolerances are policy data (`backend/app/core/policy_defaults.py`, stored versioned in the `policies` table). They are assumptions, editable by admin, and every change is audited.

## Worked examples (from the tests)
- **Scenario 2:** PO price ₹620.00/kg, invoice ₹639.84/kg on 2,000 kg. That is +3.20% and ₹39,680.00 more, which is above the PP tolerance and under the 5% hard limit, so the result is **FLAG PRICE_VARIANCE**.
- **Scenario 3:** 100 bearings billed, 80 received, 0 invoiced before. Excess 20 = 25% of received, so the result is **BLOCK QTY_EXCEEDS_GR**. With 60 already invoiced, a bill for 20 is clean, 21 flags and 25 blocks.
- **Scenario 4:** no GR gives **BLOCK MISSING_GR**. Stores posts the GR, the engine re-runs, and the result is **APPROVE**.
