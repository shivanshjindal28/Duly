"""Impact model (spec section 11): what Duly measured on its own data, and the projection for
Plant X with every input an editable, labelled assumption.

Measured numbers are computed live from invoices, match results, approval steps, extraction
rows and payments; nothing is stored or hard-coded. The projection formulas are evaluated in
the browser so the viewer can change assumptions; defaults and their reasons live here (and in
docs/IMPACT.md).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import Decision, InvoiceStatus, Severity, StepStatus
from app.engine.catalog import info
from app.models import ApprovalStep, ExtractionResult, Invoice, MatchResult, Policy, ReasonCode, Supplier
from app.models.base import as_utc
from app.payments import run as payrun

ROOT_CAUSES: list[tuple[str, str, tuple[str, ...]]] = [
    ("price", "Price differs from the PO", ("PRICE_VARIANCE",)),
    ("quantity", "Billed more than received or accepted", ("QTY_EXCEEDS_GR", "SES_VALUE_EXCEEDED")),
    ("receipt", "Missing goods receipt or service entry", ("MISSING_GR", "MISSING_SES")),
    ("duplicate", "Duplicate or possible duplicate", ("DUPLICATE", "POSSIBLE_DUPLICATE")),
    ("tax", "Tax, GSTIN or e-invoice compliance", ("TAX_MISMATCH", "GSTIN_INVALID", "MATH_ERROR", "EINVOICE_QR_MISSING",
                                                  "INVOICE_NO_INVALID", "DATE_INVALID", "BILL_TO_MISMATCH")),
    ("fraud", "Fraud and security signals", ("BANK_MISMATCH", "BANK_ACCOUNT_SHARED", "QR_MISMATCH",
                                             "QR_SIGNATURE_INVALID", "INJECTION_ATTEMPT", "SUPPLIER_MISMATCH")),
    ("po", "PO or line data problems", ("NO_PO", "PO_CLOSED", "LINE_NOT_ON_PO", "NO_LINES", "CURRENCY_MISMATCH",
                                        "PAYMENT_TERMS_MISMATCH")),
]

# Projection inputs. Every value is an ASSUMPTION, deliberately conservative, with the reason shown
# next to it in the app. `measured`: taken from Duly's own data when there is any, else the default.
ASSUMPTIONS: list[dict] = [
    {"key": "invoices_per_month", "label": "Invoices per month at Plant X", "unit": "invoices", "default": 3000,
     "reason": "Scenario assumption for a polymer plant's AP volume (spec section 3)."},
    {"key": "manual_minutes", "label": "Manual handling time per invoice", "unit": "minutes", "default": 12,
     "reason": "Keying, 3-way match and filing for a clean invoice; exceptions take far longer and are not counted."},
    {"key": "duly_minutes", "label": "Duly handling time per touchless invoice", "unit": "minutes", "default": 1,
     "reason": "A glance at the decision card; set higher if your team double-checks every touchless invoice."},
    {"key": "touchless_rate", "label": "Touchless rate", "unit": "%", "default": 25, "measured": "touchless_rate",
     "reason": "Defaults to the rate measured on Duly's data (only small, clean invoices are approved by policy)."},
    {"key": "cost_per_hour", "label": "Loaded cost per AP hour", "unit": "₹", "default": 600,
     "reason": "Salary, benefits and overheads for a shared-services AP clerk in India (rough)."},
    {"key": "duplicate_rate", "label": "Duplicates that would slip through without Duly", "unit": "%", "default": 0.1,
     "reason": "Far below the duplicate rate seen in Duly's data, on purpose; most get caught somewhere manually."},
    {"key": "avg_invoice_value", "label": "Average invoice value", "unit": "₹", "default": 150000,
     "measured": "avg_invoice_value", "reason": "Defaults to the average measured on Duly's data."},
    {"key": "msme_share", "label": "Share of invoice value from MSME suppliers", "unit": "%", "default": 20,
     "measured": "msme_value_share", "reason": "Defaults to the share measured on Duly's data."},
    {"key": "msme_late_share", "label": "MSME value paid late without a due-date guardian", "unit": "%", "default": 5,
     "reason": "Invoices that sit in exceptions or approval queues past day 45 without anyone watching the date."},
    {"key": "days_late", "label": "Average days late when it happens", "unit": "days", "default": 20,
     "reason": "About one payment cycle missed."},
    {"key": "msme_interest_pct", "label": "MSMED Act interest rate (3 x RBI bank rate)", "unit": "% a year",
     "default": 17.25, "measured": "msme_interest_pct", "reason": "From the policy's RBI bank rate (verify the current rate)."},
    {"key": "tax_rate_pct", "label": "Corporate tax rate", "unit": "%", "default": 25.17, "measured": "tax_rate_pct",
     "reason": "From the policy; used only to size the tax-deduction timing effect. Confirm with the tax team."},
    {"key": "cost_of_funds_pct", "label": "Cost of funds", "unit": "% a year", "default": 9,
     "measured": "cost_of_funds_pct", "reason": "From the payment-run policy; values the tax deduction moving a year later."},
    {"key": "discount_eligible_share", "label": "Invoice value offering an early-payment discount", "unit": "%",
     "default": 5, "reason": "Few suppliers offer one; in the demo data only one does."},
    {"key": "discount_pct", "label": "Typical early-payment discount", "unit": "%", "default": 1,
     "reason": "1% in 10 days is a common term (the demo supplier offers exactly this)."},
    {"key": "capture_gain", "label": "Extra discounts captured thanks to faster approval", "unit": "%", "default": 50,
     "reason": "Share of offered discounts missed today because approval takes longer than the window."},
    {"key": "ai_cost_per_invoice", "label": "AI extraction cost per invoice", "unit": "₹", "default": 0,
     "reason": "Zero: our setup reads invoices with local OCR (AI mode offline). If a paid AI API is switched on, "
               "use pages x tokens x price (roughly ₹3 for 1.5 pages; verify current pricing)."},
]

FORMULAS = {
    "hours_saved_month": "invoices_per_month × touchless_rate × (manual_minutes − duly_minutes) / 60",
    "cost_saved_year": "hours_saved_month × 12 × cost_per_hour",
    "duplicates_prevented_year": "invoices_per_month × 12 × duplicate_rate × avg_invoice_value",
    "msme_exposure_avoided_year": ("value_per_year × msme_share × msme_late_share × (msme_interest_pct × days_late / 365) "
                                   "+ the same late value × tax_rate_pct × cost_of_funds_pct (deduction moves a year)"),
    "discounts_captured_year": "value_per_year × discount_eligible_share × discount_pct × capture_gain",
    "ai_cost_year": "invoices_per_month × 12 × ai_cost_per_invoice",
}


def _pct(n: int | float, d: int | float) -> float | None:
    return round(n / d, 4) if d else None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def measured(db: Session) -> dict:
    invoices = db.scalars(select(Invoice)).all()
    by_id = {i.id: i for i in invoices}
    suppliers = {s.id: s for s in db.scalars(select(Supplier))}
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True))).data

    # First match per invoice (first-pass rate) and every flag/block reason ever raised (root causes).
    first: dict[int, str] = {}
    for inv_id, decision in db.execute(select(MatchResult.invoice_id, MatchResult.decision).order_by(MatchResult.id)):
        first.setdefault(inv_id, decision)
    ever: dict[int, set[str]] = defaultdict(set)
    for inv_id, code in db.execute(
        select(MatchResult.invoice_id, ReasonCode.code).join(ReasonCode, ReasonCode.match_result_id == MatchResult.id)
        .where(ReasonCode.severity.in_((Severity.FLAG, Severity.BLOCK)))
    ):
        ever[inv_id].add(code)

    steps: dict[int, list[ApprovalStep]] = defaultdict(list)
    for s in db.scalars(select(ApprovalStep).where(ApprovalStep.status == StepStatus.APPROVED)):
        steps[s.invoice_id].append(s)
    manual = set(db.scalars(select(ExtractionResult.invoice_id).where(ExtractionResult.source == "manual")))
    approved = [i for i in invoices if i.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID)]
    touchless = [i for i in approved if any(s.by_policy for s in steps[i.id]) and i.id not in manual
                 and not i.override_by_user_id]
    cycles = [(max(as_utc(s.decided_at) for s in steps[i.id]) - as_utc(i.received_at)).total_seconds() / 3600
              for i in approved if steps[i.id]]

    causes = []
    for key, title, codes in ROOT_CAUSES:
        hit = [i for i, c in ever.items() if c & set(codes)]
        if hit:
            causes.append({"key": key, "title": title, "count": len(hit),
                           "value": sum((by_id[i].total for i in hit), Decimal(0)),
                           "codes": [{"code": c, "title": info(c).title} for c in codes]})
    causes.sort(key=lambda r: -r["count"])

    dup_ids = [i.id for i in invoices if i.status != InvoiceStatus.PAID
               and ({"DUPLICATE", "POSSIBLE_DUPLICATE"} & ever[i.id]) and i.decision == Decision.BLOCK]
    rows = payrun.msme_rows(db)
    paid_msme = [r for r in rows if r.paid_on]
    on_time = [r for r in paid_msme if r.status == "on_time"]

    fields = db.execute(select(ExtractionResult.confidence, ExtractionResult.value)
                        .where(ExtractionResult.source.not_in(("manual", "ers")))).all()  # ERS: not read from a document
    threshold = float(policy.get("confidence_threshold", 0.85))
    needs_review = sum(1 for c, v in fields if v is not None and c < threshold)
    corrections = db.scalar(select(func.count()).select_from(ExtractionResult).where(
        ExtractionResult.source == "manual", ExtractionResult.previous_value.is_not(None),
        ExtractionResult.value != ExtractionResult.previous_value)) or 0

    total_value = sum((i.total for i in invoices), Decimal(0))
    msme_value = sum((i.total for i in invoices if suppliers.get(i.supplier_id) is not None
                      and suppliers[i.supplier_id].msme_category in ("micro", "small")), Decimal(0))
    bank_rate = float(policy.get("msme", {}).get("rbi_bank_rate_pct", 5.75))
    received = [as_utc(i.received_at) for i in invoices]
    days = max(1, (max(received) - min(received)).days) if received else 0
    return {
        "invoices": len(invoices),
        "days": days,
        "value": total_value,
        "touchless_rate": _pct(len(touchless), len(approved)),
        "touchless": len(touchless),
        "approved": len(approved),
        "first_pass_rate": _pct(sum(1 for d in first.values() if d == Decision.APPROVE), len(first)),
        "avg_cycle_hours": round(sum(cycles) / len(cycles), 1) if cycles else None,
        "p90_cycle_hours": _percentile(cycles, 0.9),
        "root_causes": causes,
        "exceptions": sum(1 for c in ever.values() if c),
        "duplicates_caught": len(dup_ids),
        "duplicates_value": sum((by_id[i].total for i in dup_ids), Decimal(0)),
        "msme_paid": len(paid_msme),
        "msme_on_time_rate": _pct(len(on_time), len(paid_msme)),
        "msme_open": sum(1 for r in rows if r.status in ("open", "overdue")),
        "ai_fields": len(fields),
        "ai_review_rate": _pct(needs_review, len(fields)),
        "ai_corrected_rate": _pct(corrections, len(fields)),
        # Defaults for assumptions marked "measured".
        "avg_invoice_value": (total_value / len(invoices)).quantize(Decimal("1")) if invoices else None,
        "msme_value_share": _pct(float(msme_value), float(total_value)),
        "msme_interest_pct": round(3 * bank_rate, 2),
        "tax_rate_pct": float(policy.get("corporate_tax_rate_pct", 25.17)),
        "cost_of_funds_pct": float(policy.get("payments", {}).get("cost_of_funds_pct", 9.0)),
    }


def impact(db: Session) -> dict:
    m = measured(db)
    pct_keys = {"touchless_rate", "msme_share"}
    assumptions = []
    for a in ASSUMPTIONS:
        value = a["default"]
        if a.get("measured"):
            v = m.get(a["measured"])
            value = (round(v * 100, 1) if a["key"] in pct_keys else v) if v is not None else value
        assumptions.append({**{k: v for k, v in a.items() if k != "default"}, "value": value})
    return {"measured": m, "assumptions": assumptions, "formulas": FORMULAS}
