# Impact model

The in-app **Impact** page (`/impact`, staff roles) has two halves. This document is the same model in words.
Code: `backend/app/reports/impact.py` (measured metrics, default assumptions with reasons) and
`frontend/src/pages/ImpactPage.tsx` (projection formulas, editable inputs).

## 1. Measured on Duly's data (live)
Computed on every page load from the database. The data is synthetic (seeded 90-day history plus whatever was
uploaded in the demo), so these figures prove the mechanism, not Plant X's real performance.

| Metric | Definition |
|---|---|
| Touchless rate | Approved or paid invoices approved by policy P-01 with zero human touches (no field review, no override), divided by all approved or paid invoices |
| First-pass match rate | Invoices whose first engine run returned APPROVE, divided by all matched invoices |
| Cycle time, average and P90 | Upload to final approval step, approved or paid invoices |
| Exceptions by root cause | Invoices that ever had a FLAG or BLOCK reason, grouped: price, quantity, missing receipt, duplicate, tax/compliance, fraud/security, PO data |
| Duplicates caught | Unpaid invoices blocked as DUPLICATE / POSSIBLE_DUPLICATE, count and value |
| MSME on-time % | Paid MSME invoices paid on or before the statutory due date, divided by paid MSME invoices |
| AI fields needing review % / corrected % | Extracted fields below the confidence threshold / fields a human changed, over all extracted fields |

## 2. Projected for Plant X
Every input is an **assumption**, conservative on purpose, editable on the page (edits stay in that browser).
Inputs marked *measured* default to the figure measured in half 1.

| Assumption | Default | Why |
|---|---|---|
| Invoices per month | 3,000 | Scenario assumption (spec section 3) |
| Manual minutes per invoice | 12 | Keying, 3-way match and filing for a clean invoice; exceptions excluded |
| Duly minutes per touchless invoice | 1 | A glance at the decision card |
| Touchless rate | measured | Only small clean invoices are approved by policy |
| Loaded cost per AP hour | ₹600 | Shared-services AP clerk in India, rough |
| Duplicates slipping through without Duly | 0.1% | Well below what the demo data shows, on purpose |
| Average invoice value | measured | |
| MSME share of value | measured | |
| MSME value paid late without a guardian | 5% | Invoices stuck in exceptions past day 45 |
| Average days late | 20 | About one payment cycle |
| MSMED interest rate | 3 x RBI bank rate (policy) | Verify the current bank rate |
| Corporate tax rate | policy (25.17%) | Sizing only; confirm with the tax team |
| Cost of funds | policy (9%) | Values the deduction moving a year |
| Value offering an early-payment discount | 5% | Few suppliers offer one |
| Discount | 1% | Common "1% 10 days" term |
| Extra discounts captured | 50% | Discounts missed today because approval is slower than the window |
| AI extraction cost per invoice | ₹0 | Our setup reads invoices with local OCR (AI mode offline). With a paid AI API, roughly ₹3 (verify current pricing) |

Formulas (value per year = invoices per month x 12 x average invoice value):

- **AP hours saved a month** = invoices per month x touchless rate x (manual minutes - Duly minutes) / 60  *(headline)*
- **AP cost saved a year** = hours saved a month x 12 x cost per AP hour
- **Duplicate leakage prevented a year** = invoices per year x duplicate rate x average invoice value
- **MSME interest avoided a year** = value per year x MSME share x late share x (interest rate x days late / 365)
- **Tax-deduction timing effect avoided** = the same late value x tax rate x cost of funds (the deduction for a late MSME payment moves to the year it is paid: s.43B(h) / s.37(2)(g))
- **Early-payment discounts captured** = value per year x eligible share x discount x capture gain
- **Less AI cost** = invoices per year x AI cost per invoice

Headline indicators for the pitch: **touchless rate and AP hours saved a month**, then **MSME on-time %**.

Not counted (so the real figure is higher): time spent on exceptions, supplier disputes and calls, audit effort,
fraud prevented by the bank-detail and signed-QR checks.

Limits: the measured half runs on synthetic data; the projection is only as good as its assumptions, which is why
each one is visible, explained and editable.
