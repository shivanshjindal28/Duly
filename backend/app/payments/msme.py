"""MSME statutory due dates and the cost of missing them (D4). Pure functions.

Due date (MSMED Act s.15): Udyam-registered micro and small manufacturers and service providers
(traders excluded) must be paid within the agreed term, capped at 45 days from acceptance
(GR / SES); 15 days if there is no written agreement.

If paid late (s.16): compound interest with monthly rests at three times the RBI bank rate
(the bank rate is an editable assumption in policy).

Tax deduction at risk: an amount owed to a micro/small enterprise that is still unpaid past
the due date is not deductible in that year (Income-tax Act 1961 s.43B(h) up to FY 2025-26;
carried into s.37(2)(g) of the Income-tax Act 2025 from FY 2026-27). Shown as "deduction at
risk" with an assumed tax rate; a tax professional should confirm.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import EnterpriseType, MsmeCategory

MAX_TERM_DAYS = 45
NO_AGREEMENT_DAYS = 15
TWO = Decimal("0.01")
TAX_RULE = ("Income-tax Act 1961 s.43B(h) (to FY 2025-26) / Income-tax Act 2025 s.37(2)(g) (from FY 2026-27): "
            "amounts owed to micro and small enterprises are deductible only when paid, if paid after the MSMED "
            "Act due date. Confirm with a tax professional.")


def msme_eligible(msme_category: str, enterprise_type: str) -> bool:
    return msme_category in (MsmeCategory.MICRO, MsmeCategory.SMALL) and enterprise_type != EnterpriseType.TRADER


def statutory_due_date(accepted: date, terms_days: int, written_agreement: bool,
                       max_term: int = MAX_TERM_DAYS, no_agreement: int = NO_AGREEMENT_DAYS) -> date:
    days = min(terms_days, max_term) if written_agreement else no_agreement
    return accepted + timedelta(days=days)


def interest(principal: Decimal, due: date, paid_on: date, bank_rate_pct: Decimal) -> Decimal:
    """MSMED s.16 interest: monthly compounding at 3x the RBI bank rate, for the days late."""
    days_late = (paid_on - due).days
    if days_late <= 0:
        return Decimal(0)
    monthly = Decimal(3) * Decimal(str(bank_rate_pct)) / 100 / 12
    months = Decimal(days_late) / Decimal(30)
    factor = Decimal(str(float(1 + monthly) ** float(months)))
    return (principal * (factor - 1)).quantize(TWO, rounding=ROUND_HALF_UP)


def deduction_at_risk(amount: Decimal, due: date, on: date, tax_rate_pct: Decimal) -> tuple[Decimal, Decimal]:
    """(expense deduction at risk, tax effect) if still unpaid after the due date on `on`."""
    if on <= due:
        return Decimal(0), Decimal(0)
    return amount, (amount * Decimal(str(tax_rate_pct)) / 100).quantize(TWO, rounding=ROUND_HALF_UP)


def half_year(d: date) -> tuple[date, date, str]:
    """MSME Form I half years: April-September and October-March."""
    if 4 <= d.month <= 9:
        return date(d.year, 4, 1), date(d.year, 9, 30), f"Apr-Sep {d.year}"
    start_year = d.year if d.month >= 10 else d.year - 1
    return date(start_year, 10, 1), date(start_year + 1, 3, 31), f"Oct {start_year}-Mar {start_year + 1}"
