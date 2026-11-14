# Demo script (10 minutes: about 7 minutes of demo, 3 minutes of buffer)

Presenters (fill in names): **A** product and AP story · **B** security (cybersecurity background) ·
**C** SAP and finance (SAP background). Every file is in `demo/invoices/`; `demo/manifest.json` has the expected
result and story for each.

## 4-minute demo on https://www.duly.website (final round)

The hosted site runs on Render's free plan: it sleeps after ~15 min idle (first request then takes about a minute)
and photo OCR is too slow there, so the photo scenario (S05) is already loaded. Every live upload below is a PDF
(~7 s each).

**Before presenting (10 minutes earlier, same browser you will present from)**
1. Open https://www.duly.website and wait for the login page (this wakes the server).
2. Sign in as **Sanjay Patil** (admin) → Demo controls → **Reset demo data** (about a second): back to the staged
   state (90-day history + S02 S03 S05 S09a/b S10 S11 S12). Check the top bar says "AI: offline (OCR)".
3. MFA: sign in as **Rohan Mehta** and **Kavita Desai**; scan each Overview QR into an authenticator app (only after a
   new deploy; a reset keeps the same codes).
4. Download `S01_catalyst_clean_einvoice.pdf`, `S04_packaging_missing_gr.pdf`, `S06_impellers_bank_mismatch.pdf`,
   `S07_pallets_prompt_injection.pdf` and `S08_catalyst_edited_total_qr_mismatch.pdf` from `demo/invoices/` to the
   desktop. Browser zoom 90-100%.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Login page | Plant X AP clerks chase mismatches by hand; wrong invoices get paid, MSMEs get paid late. Duly: every invoice duly checked, every payment duly on time. |
| 0:20 | **Asha Kulkarni** → Upload `S04` (Identify from the document) | Billed before the goods arrived: **BLOCK MISSING_GR**. Point at the Duly rail, reasons, "AI does not make this decision", **Explain**. |
| 0:50 | **Imran Shaikh** (stores) → Receiving → type `1004` → Post goods receipt | "1 released from block": Duly re-checked by itself. |
| 1:10 | **Asha** → Upload `S06`, then `S07`, then `S08` | New bank account → **BLOCK** + security alert. Hidden white text telling the AI to approve → **FLAG**, AI output quarantined. Edited PDF total vs signed e-invoice QR → **BLOCK QR_MISMATCH**. |
| 2:00 | Ctrl+K → `INV-42` → **Compare** | A WhatsApp photo of an invoice already paid, renumbered: **BLOCK DUPLICATE**, side by side. |
| 2:20 | Ctrl+K → `NPW-311` (the S04 invoice) → **SAP posting preview** | The exact S/4HANA payload; SAP stays the system of record. |
| 2:40 | **Rohan Mehta** → Approvals → NPW-305 → Approve; Payments | MSME invoice first in the run (4 days left of 45); contractor TDS ₹8,400; discounts only if they beat the cost of funds. |
| 3:15 | **Dinesh Patel** (Kesar) → Payment assistant: "When will I get paid for INV/0042?", then "Show me Navrang's invoices" | Precise answer from his own data; the other-supplier question is refused and logged. Works offline. |
| 3:40 | **Meera Iyer** (auditor) → Controls report → Audit chain → Verify | 10 controls tested on live data; every action in a signed hash chain. Close: every invoice, duly done. |

If time is short, drop S07 or the SAP preview. S01 (₹15 lakh, L1 + L2 with MFA) is the 10-minute version below.
After rehearsing, run **Reset demo data** again so the stage starts clean.

## Before going on stage (15 minutes earlier)
1. `python run.py`, open http://localhost:5173 (full-screen browser, zoom 90-100%).
2. Admin (Sanjay Patil) → **Demo controls** → check AI mode is **Offline** (our setup: no API key or network
   needed). The top-bar badge must say "AI: offline (OCR)".
3. In a terminal: `python scripts/demo_prestage.py --reset` (about a minute). Resets with the 90-day history and
   uploads the background scenarios S02, S03, S09a, S09b, S10, S11, S12. Every line must say OK.
4. **MFA:** sign in as Rohan Mehta (L1) and Kavita Desai (L2); on each Overview page scan the QR code into an
   authenticator app on a phone. Secrets change on every reset: delete old entries and scan again after any reset.
5. `python scripts/demo_check.py` the evening before (isolated database, 25/25 green). Do not run it on the stage
   database.
6. Keep the files ready to drag in: S01, S04, S05, S06, S07, S08. Switch personas by **Sign out** and a click on
   the persona on the login page (two clicks), or keep a second (private) browser window signed in as a supplier.

## Run sheet

| Time | Who | On screen | Say (one line each) |
|---|---|---|---|
| 0:00 | A | Login page with personas | Plant X, a fictional polymer plant. AP clerks chase mismatches by hand; wrong invoices get paid while MSME suppliers get paid late. Duly: every invoice duly checked, every payment duly on time. |
| 0:30 | A | **Anil Joshi** (Sahyadri) → Upload `S01_catalyst_clean_einvoice.pdf` | Supplier uploads a ₹15 lakh e-invoice. Duly reads it, verifies the government-signed QR, matches PO and GR: **APPROVE**. Point at the Duly rail, the field highlights and confidence bars, "AI does not make this decision". It needs L1 and L2 with MFA. |
| 1:30 | A | **Asha Kulkarni** (clerk) → Dashboard | 90 days of history: queue, value on hold, touchless rate, MSME due dates. Click a bar to drill into the queue. Press **Ctrl+K**, type `0042`, Enter. |
| 2:15 | C | Asha → Upload `S04_packaging_missing_gr.pdf` (Supplier: Identify from the document) | Packaging billed before the goods arrived: **BLOCK MISSING_GR**. Hover the MIGO 101 tooltip. |
| 2:35 | C | **Imran Shaikh** (stores) → Receiving → PO 4500001004 → 20000 → Post goods receipt | "1 released from block". Back as Asha: the same invoice is now APPROVE, awaiting L1. Open **SAP posting preview**: the exact S/4HANA payload, payment block R until approved. |
| 3:15 | B | Asha → Upload `S05_bearings_duplicate_photo.jpg` | A WhatsApp photo of INV/0042, renumbered INV-42: **BLOCK DUPLICATE**. Open **Compare**: both documents, same total, number normalises the same. |
| 3:45 | B | Asha → Upload `S06_impellers_bank_mismatch.pdf` | New bank account printed on the invoice: **BLOCK BANK_MISMATCH** and a security alert. Bank details change only through call-back, maker-checker and a 72-hour cooling period (Bank changes page). |
| 4:15 | B | Asha → Upload `S07_pallets_prompt_injection.pdf` | White text tells the AI to approve and change the bank account. Found before any AI read it: **FLAG INJECTION_ATTEMPT**, AI output quarantined. Even a fooled AI cannot approve: rules decide. |
| 4:40 | B | Asha → Upload `S08_catalyst_edited_total_qr_mismatch.pdf` | Someone edited the PDF total. Trust the signed QR, not the pixels: **BLOCK QR_MISMATCH**, printed ₹5,19,500 vs signed ₹5,01,500. |
| 5:05 | C | **Rohan Mehta** (L1) → Approvals → S01 → Approve + 6-digit code; **Kavita Desai** (L2) the same | Delegation of authority with MFA above ₹10 lakh; L1 cannot also approve L2 (segregation of duties). Rohan also approves NPW-305 (MSME jumbo bags). |
| 5:50 | C | Rohan → Payments | MSME invoice NPW-305 is first: 4 days left of 45 (miss it and MSMED interest plus a tax-deduction disallowance start; Demo controls +7 days shows them on the MSME tab). Contractor TDS withheld (₹8,400 on the turnaround services). Discounts only if they beat the cost of funds. Release: simulated UTR, visible to the supplier. |
| 6:30 | A | **Dinesh Patel** (Kesar) → My invoices → Payment assistant | "When will I get paid for the bearings?" → it asks which one → "INV/0042" → expected payment date. Then "Show me invoices of Navrang Packaging" → refused, and the refusal is logged. Works offline. |
| 7:00 | B | **Meera Iyer** (auditor) → Controls report (Download PDF) → Audit chain → Verify | 10 controls tested on live data. Every action is in a hash chain with a signed head. |
| 7:30 | B | (optional) **Sanjay Patil** → Demo controls → Run tamper demo; Meera → Verify | "Chain broken at event #N": the exact row edited in the database. Restore. |
| 8:00 | A | Asha → **Impact** | Measured on our data, projected for Plant X: about 155 AP hours a month at the measured touchless rate. Change "invoices per month" live: every formula is on screen. |
| 8:30 | C | **Architecture** (and Trust & controls if time) | The diagram is the same file as docs/ARCHITECTURE.md. SAP stays the system of record; Duly is a side-car (BTP extension). AI never decides: 0 decisions by AI. |
| 9:00 | A | Close | Every invoice, duly done. Questions. |

**If behind schedule, cut in this order:** the tamper demo (7:30), S08 (4:40), Trust page, S06's Bank changes page.
**If asked about currencies or units:** upload `S13_import_eur_nucleating_agent.pdf` as **Lena Brandt** (Nordwerk, Germany): EUR 19,250, no GST, ≈ ₹20.1 lakh → L1 + L2 with MFA; then `S14_bearings_billed_in_boxes.pdf` as **Dinesh Patel**: 12 BOX matched as 120 NOS. Stores can receive in boxes (Receiving → PO 4500001019 → unit BOX). Exchange rates and pack sizes are on the Policy and Scenario & assumptions pages.

**If ahead or asked:** S12 (Asha opens NPW-313, enters HSN 3923 on the highlighted field, logged with a reason →
APPROVE), S02 (exact ₹39,680 price variance), S03 (cumulative received vs invoiced), S09a/b (tax head, GSTIN check
digit), Hindi portal (Hetal Shah → हिन्दी), AI mode switch.

## If something goes wrong
- **An upload is slow:** photos and scans take up to ~7 s (OCR). Keep talking about what it checks.
- **Wrong result on stage:** Demo controls → Reset demo data (about 25 s) restores history; re-run
  `python scripts/demo_prestage.py` (without `--reset`) for the background scenarios, or skip to the next beat.
- **MFA code refused:** codes change every 30 s and the phone clock must be right; if secrets were reset, re-scan the
  QR on the approver's Overview.
- **No network:** nothing changes in Offline mode. The AI badge in the top bar says which mode is on.
- **Browser state odd:** sign out, sign in with the persona button again.
