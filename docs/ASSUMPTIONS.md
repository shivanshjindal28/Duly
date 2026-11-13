# Scenario and assumptions

Everything here is fictional or an assumption. The in-app **Scenario & assumptions** page (`/assumptions`) shows
the same values, read live from the active policy and the supplier master (the app is the source of truth if
the two ever differ). Defined in code:
`backend/app/core/policy_defaults.py` (policy v1), `backend/app/seed.py` (master data),
`backend/app/validation/hsn.py` (HSN table), `backend/app/reports/impact.py` (impact assumptions).

## Plant X
- **Plant X Polymers Pvt Ltd**: a fictional polypropylene and polyethylene plant at Dahej, Gujarat (GST state
  code 24). Currency INR. Financial year April to March. Synthetic GSTIN and PAN with valid check digits.
- Accounts payable is a small shared-services team in Mumbai serving the plant.
- **Focus user:** the AP clerk, who spends most of the day chasing mismatches by hand.
- **Focus problem:** wrong, duplicated or fraudulent invoices get paid, while honest MSME suppliers get paid late.
- Why polymers: bulk raw materials in MT with quantity tolerances, packaging from MSMEs, spares with partial
  deliveries, maintenance services with no goods receipt, freight, and both intra-state and inter-state GST.
- Plant X runs SAP S/4HANA (assumption); Duly is a side-car, SAP stays the system of record.

## Suppliers (fictional)

| Code | Supplier | Category | State | MSME | e-invoice QR | Terms | TDS section |
|---|---|---|---|---|---|---|---|
| V100101 | Sahyadri Catalysts & Additives Ltd | Catalysts & additives | Maharashtra (27): IGST | No | Yes (signed) | 60 days; 1% discount in 10 days | goods |
| V100102 | Navrang Packaging Works | Packaging | Gujarat (24): CGST+SGST | Micro, manufacturer | No | 45 days | goods |
| V100103 | Kesar Engineering Spares | MRO spares | Gujarat | Small, manufacturer | No | 45 days | goods |
| V100104 | Tapti Turnaround Services | Maintenance services | Gujarat | Small, services | No | 45 days | contractor |
| V100105 | Konkan Bulk Carriers | Freight | Maharashtra: IGST | No | No | 30 days | contractor |
| V100106 | Dakshin Calibration Labs | Lab & QC calibration | Karnataka (29): IGST | Micro, services, **no written agreement** | No | 30 days (MSME cap 15 days) | technical |

Bank names and IFSC prefixes are invented (Sahyog Bank, Narmada Co-operative Bank, Kaveri Gramin Bank); e-mail
domains are `.example`. Every master record is flagged `is_synthetic`.

## Policy v1 (rule values; all assumptions, editable as versioned data)

**Matching tolerances** (modelled on SAP tolerance keys)

| Key | Value |
|---|---|
| PP price variance | Information only while within 1% **and** within ₹500 on the line; above either, flag; above 5%, block |
| DQ quantity | 0% for goods, 0.5% for bulk lines in MT; flag up to 5% of received, block above |
| BD small difference | Up to ₹10 auto-accepted |
| Field confidence | Below 85%, a person confirms or corrects the field |

**Delegation of authority** (invoice value incl. GST)

| Value | Approval |
|---|---|
| Clean invoice up to ₹50,000 | Policy P-01, touchless |
| Up to ₹10 lakh | L1 Finance Manager |
| Up to ₹1 crore | L1 then L2 Plant Head |
| Above ₹1 crore | L1, L2, then L3 CFO |
| FLAG routed with an override | At least L1 and L2, written justification of 15+ characters |
| MFA | Required above ₹10 lakh |
| SLA | 48 hours per step, then the next level may act (escalation) |
| Bank detail change | Call-back checklist, maker-checker, 72-hour cooling period |

**MSME and payments**

| Item | Value |
|---|---|
| MSME payment term | Agreed term capped at 45 days from acceptance (GR / SES date); 15 days without a written agreement (MSMED Act s.15). Traders are excluded |
| Late interest | 3 x RBI bank rate, compound with monthly rests (MSMED Act s.16); bank rate assumed 5.75%, verify before use |
| Tax deduction at risk | Unpaid MSME dues past the due date are not deductible until paid (s.43B(h) of the Income-tax Act 1961 to FY 2025-26; s.37(2)(g) of the Income-tax Act 2025 from FY 2026-27). Corporate tax rate assumed 25.17%, only to size the effect. A tax professional should confirm |
| Payment run | Every 7 days; MSME invoices due before the next run plus a 7-day buffer are paid first |
| Early-payment discount | Taken only if its annualised return beats the 9% cost of funds |

**TDS** (Income-tax Act 2025 s.393, formerly 194C / 194J / 194Q; verify with the tax team)

| Section | Rate | Threshold |
|---|---|---|
| Contractor | 1% individual / HUF, 2% others | Single bill above ₹30,000 or year above ₹1 lakh |
| Technical fees | 2% | Year above ₹50,000 |
| Professional fees | 10% | Year above ₹50,000 |
| Purchase of goods | 0.1% | On the part of the year above ₹50 lakh |

TDS is computed on the taxable value (excluding GST). PAN 4th character P or H is treated as individual / HUF.

## Currencies and units
- **Exchange rates** (policy `fx`, INR per one unit; fictional round values as of 2026-11-01): USD 84, EUR 90, GBP 107,
  JPY 0.56, CNY 11.60, SGD 63, AED 22.90. Assumption: update from the RBI / FBIL reference rate or the treasury rate
  table (SAP OB08). Editable on the Policy page; each invoice keeps the rate it was matched at.
- **Import supplier** (fictional): Nordwerk Polymer Additives GmbH, Germany, VAT ID DE-FICT-447101, bills in EUR, 60
  days, no MSME, no TDS (non-resident withholding is left to the tax team), IBAN / SWIFT fictional. Import invoices carry
  no Indian GST; IGST is paid at customs (bill of entry, not modelled).
- **Units**: standard conversions (mass, volume, length, count) built in; pack sizes are item master data
  (`item_units`): BRG-6205 BOX = 10 NOS, BRG-6310 BOX = 5 NOS, SEAL-M40 SET = 4 NOS, ADD-AO-1010 BAG = 25 KG,
  NUC-AGT-77 BAG = 20 KG, CAT-ZN-01 DRUM = 200 KG, PKG-FFS-25 BUNDLE = 100 NOS, PKG-FFS-50 BUNDLE = 50 NOS,
  PKG-FIBC-1T BALE = 20 NOS.

## HSN / SAC rates used by the tax check (illustrative)
3901 and 3902 polymers 18%; 3812 additives 18%; 3815 catalysts 18%; 3923 plastic sacks 18%; 6305 FIBC 5% or
12%; 4415 wooden pallets 5% or 12%; 8413 pumps and parts 18%; 8482 bearings 18%; 8484 seals and gaskets 18%;
9965 goods transport 5%, 12% or 18%; 9983 technical testing 18%; 9987 maintenance 18%. Rates change with GST
Council notifications: verify before any real use.

## Data and demo assumptions
- Volume for the impact model: 3,000 invoices a month (editable on the Impact page; see docs/IMPACT.md).
- The seeded history (about 250 invoices over 90 days, 71 POs in total) is synthetic, produced by replaying business
  events through Duly's own engine and workflow with the clock set to past dates.
- e-invoice QRs are signed by a local **Sandbox IRP** key. Production would trust the real IRP public key
  (`IRP_PUBLIC_KEY_PATH`).
- **Evaluated receipt settlement (ERS)** is set per PO (as SAP sets the ERS indicator on the PO item); the seeded
  ERS PO is 4500001015 (Konkan, truck freight, 6 trips at ₹22,000, GST 12%). Other Konkan POs are still invoiced on
  paper. GST: in India a registered supplier still issues the tax invoice that gives Plant X its input tax credit;
  the ERS settlement drives the payment, and the supplier's tax invoice would be linked to it for GST returns (not
  built). Verify the GST treatment of freight (GTA forward charge vs reverse charge) with the tax team.
- **Email-in** is simulated: no IMAP / SMTP server. The AP mailbox address, the three sample emails (including the
  lookalike domain `kesar-spare.example`) and every sender are fictional (`.example` domains). A real deployment
  would read the shared mailbox (IMAP or Microsoft Graph) and also check SPF / DKIM / DMARC results, which the
  simulation does not have.
- **Credit notes** (GST s.34) are entered in a form (supplier portal or AP clerk), not read from a PDF. Duly prices
  them from the invoice line, so the GST on the credit note mirrors the invoice. They are accepted at once (they only
  reduce what Plant X owes) and the invoice is re-checked net of them.
- SAP configuration values in the posting preview (company code PX01, plant PX10, tax codes, withholding tax
  types) are fictional.
