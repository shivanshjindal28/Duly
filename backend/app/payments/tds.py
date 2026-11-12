"""TDS (tax deducted at source) on supplier payments. Pure functions.

Income-tax Act 2025, section 393 (which carries forward the old sections 194C contractors,
194J professional / technical fees and 194Q purchase of goods). Rates and thresholds come
from policy data labelled "verify with tax team": they are assumptions for the demo, not
tax advice. TDS is computed on the value excluding GST when GST is shown separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")

# Default table (policy data overrides it). ASSUMPTION: verify with the tax team.
DEFAULT_TDS = {
    "contractor": {"label": "Contractor (s.393; formerly 194C)", "rate_individual_pct": 1, "rate_other_pct": 2,
                   "single_threshold_inr": 30000, "annual_threshold_inr": 100000},
    "technical": {"label": "Fees for technical services (s.393; formerly 194J)", "rate_pct": 2,
                  "annual_threshold_inr": 50000},
    "professional": {"label": "Professional fees (s.393; formerly 194J)", "rate_pct": 10,
                     "annual_threshold_inr": 50000},
    "goods": {"label": "Purchase of goods (s.393; formerly 194Q)", "rate_pct": 0.1,
              "annual_threshold_inr": 5000000},
}


@dataclass(frozen=True)
class Tds:
    section: str  # contractor | technical | professional | goods | none
    label: str
    rate_pct: Decimal
    base: Decimal  # amount TDS is computed on (taxable value, excl. GST)
    amount: Decimal
    note: str


def compute(section: str, pan: str, taxable_value: Decimal, paid_this_fy: Decimal, table: dict | None = None) -> Tds:
    """TDS for one invoice. `paid_this_fy` = taxable value already paid to this supplier this FY."""
    t = (table or DEFAULT_TDS).get(section)
    if not section or section == "none" or t is None:
        return Tds("none", "No TDS", Decimal(0), taxable_value, Decimal(0), "No TDS section applies to this supplier.")
    if section == "contractor":
        individual = len(pan) >= 4 and pan[3] in "PH"  # PAN 4th character: P person, H HUF
        rate = Decimal(str(t["rate_individual_pct"] if individual else t["rate_other_pct"]))
        over = taxable_value > Decimal(str(t["single_threshold_inr"])) or \
            paid_this_fy + taxable_value > Decimal(str(t["annual_threshold_inr"]))
        base = taxable_value if over else Decimal(0)
        note = ("Single payment or yearly total above the threshold." if over
                else "Below both thresholds: no TDS on this payment.")
    elif section == "goods":
        rate = Decimal(str(t["rate_pct"]))
        threshold = Decimal(str(t["annual_threshold_inr"]))
        base = max(Decimal(0), paid_this_fy + taxable_value - max(threshold, paid_this_fy))
        note = "TDS only on purchases from this seller above the yearly threshold."
    else:
        rate = Decimal(str(t["rate_pct"]))
        over = paid_this_fy + taxable_value > Decimal(str(t["annual_threshold_inr"]))
        base = taxable_value if over else Decimal(0)
        note = "Yearly total above the threshold." if over else "Below the yearly threshold: no TDS yet."
    amount = (base * rate / 100).quantize(TWO, rounding=ROUND_HALF_UP)
    return Tds(section, t["label"], rate, base, amount, note + " Assumption: verify rates with the tax team.")
