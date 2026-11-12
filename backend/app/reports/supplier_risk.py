"""Supplier risk card (spec D8): one card per supplier, computed live from stored data.

Information only: nothing here feeds the decision engine. Every figure says how it was
computed (`basis`), and the overall level is a fixed rule list with the reasons that fired,
so a clerk can see exactly why a supplier shows "watch" or "high".

Window: the last 12 months on the business clock (invoices by received date, payments by
paid date, bank changes by decision date). `card()` is pure so it can be tested with
hand-made facts; `cards()` loads the facts from the database.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.enums import BankChangeStatus, MsmeCategory, Severity
from app.models import BankChangeRequest, Invoice, MatchResult, Payment, ReasonCode, Supplier
from app.models.base import as_utc

WINDOW_DAYS = 365
RECENT_BANK_CHANGE_DAYS = 90

# Exceptions the supplier's invoice caused (what it billed or how), as opposed to ones Plant X
# caused (MISSING_GR / MISSING_SES: stores had not received yet) or Duly's own controls.
DISPUTE_CODES = frozenset({
    "PRICE_VARIANCE", "QTY_EXCEEDS_GR", "SES_VALUE_EXCEEDED", "LINE_NOT_ON_PO", "TAX_MISMATCH",
    "MATH_ERROR", "PAYMENT_TERMS_MISMATCH", "CURRENCY_MISMATCH",
})
EINVOICE_OK = "EINVOICE_VERIFIED"
EINVOICE_BAD = frozenset({"EINVOICE_QR_MISSING", "QR_MISMATCH", "QR_SIGNATURE_INVALID"})

# Thresholds for the overall level: labelled assumptions, shown on the card.
THRESHOLDS = {
    # First-pass exception rates of 20-30% are common in AP; above 30% the supplier's billing
    # needs a conversation. Rates on fewer than `min_invoices` invoices are not judged.
    "dispute_rate_watch": 0.30,
    "min_invoices": 10,
    "duplicate_attempts_watch": 2,
    "einvoice_compliance_watch": 0.95,
}

# Fictional sustainability assessments (an EcoVadis-style questionnaire). Not real data about
# anyone: Plant X and every supplier are fictional. Keyed by vendor code.
SUSTAINABILITY: dict[str, dict] = {
    "V100101": {"scheme": "EcoVadis-style assessment", "last_assessed": date(2026, 3, 18), "score": 62,
                "next_due": date(2027, 3, 18), "note": "Scope 1-2 emissions disclosed; catalyst take-back programme."},
    "V100102": {"scheme": "EcoVadis-style assessment", "last_assessed": date(2025, 12, 2), "score": 41,
                "next_due": date(2026, 12, 2), "note": "Recycled-content declaration for FIBC bags requested."},
    "V100103": {"scheme": "EcoVadis-style assessment", "last_assessed": None, "score": None,
                "next_due": date(2027, 1, 31), "note": "Invited; questionnaire not started."},
    "V100104": {"scheme": "EcoVadis-style assessment", "last_assessed": date(2026, 6, 10), "score": 48,
                "next_due": date(2027, 6, 10), "note": "Contractor safety (LTIFR) reported quarterly."},
    "V100105": {"scheme": "EcoVadis-style assessment", "last_assessed": date(2025, 9, 15), "score": 38,
                "next_due": date(2026, 9, 15), "note": "Fleet emissions questionnaire outstanding."},
    "V100106": {"scheme": "EcoVadis-style assessment", "last_assessed": None, "score": None,
                "next_due": None, "note": "Below the annual spend threshold for assessment."},
}
DUE_SOON_DAYS = 60


@dataclass
class InvoiceFact:
    id: int
    received: date
    status: str
    total: Decimal
    codes: set[str]  # every reason code any match of this invoice ever raised (flag or block only)


@dataclass
class PaymentFact:
    invoice_id: int
    paid_on: date
    due: date | None  # binding due date: the earlier of contract and MSME statutory due date
    amount: Decimal


@dataclass
class BankChangeFact:
    status: str
    decided_on: date | None
    requested_on: date


@dataclass
class Facts:
    invoices: list[InvoiceFact] = field(default_factory=list)
    payments: list[PaymentFact] = field(default_factory=list)
    bank_changes: list[BankChangeFact] = field(default_factory=list)


def sustainability(code: str, today: date) -> dict:
    s = SUSTAINABILITY.get(code)
    if s is None:
        return {"scheme": "EcoVadis-style assessment", "status": "unknown", "label": "No record",
                "last_assessed": None, "score": None, "next_due": None, "note": "", "fictional": True}
    due = s["next_due"]
    if due is None:
        status, label = "not_required", "Not required"
    elif due < today:
        status, label = "overdue", f"Overdue since {due:%d %b %Y}"
    elif due <= today + timedelta(days=DUE_SOON_DAYS):
        status, label = "due", f"Due {due:%d %b %Y}"
    elif s["last_assessed"] is None:
        status, label = "not_started", f"Not started (due {due:%d %b %Y})"
    else:
        status, label = "current", f"Current until {due:%d %b %Y}"
    return {**s, "status": status, "label": label, "fictional": True}


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def card(s: Supplier, facts: Facts, today: date) -> dict:
    """Build one supplier's risk card from plain facts (pure)."""
    start = today - timedelta(days=WINDOW_DAYS)
    invs = [i for i in facts.invoices if i.received >= start]
    dup = [i for i in invs if "DUPLICATE" in i.codes]
    possible_dup = [i for i in invs if "POSSIBLE_DUPLICATE" in i.codes and "DUPLICATE" not in i.codes]
    genuine = [i for i in invs if i not in dup]
    disputed = [i for i in genuine if i.codes & DISPUTE_CODES]
    bank_alerts = [i for i in invs if "BANK_MISMATCH" in i.codes]
    injections = [i for i in invs if "INJECTION_ATTEMPT" in i.codes]

    pays = [p for p in facts.payments if p.paid_on >= start and p.due is not None]
    on_time = [p for p in pays if p.paid_on <= p.due]
    late_days = [(p.paid_on - p.due).days for p in pays if p.paid_on > p.due]

    changes = [b for b in facts.bank_changes
               if b.status == BankChangeStatus.APPROVED and b.decided_on and b.decided_on >= start]
    open_changes = [b for b in facts.bank_changes
                    if b.status not in (BankChangeStatus.APPROVED, BankChangeStatus.REJECTED)]
    recent_change = max((b.decided_on for b in changes), default=None)

    if s.e_invoice_applicable:
        ok = [i for i in genuine if EINVOICE_OK in i.codes]
        bad = [i for i in genuine if i.codes & EINVOICE_BAD]
        einv = {"applicable": True, "verified": len(ok), "failed": len(bad),
                "rate": _rate(len(ok), len(ok) + len(bad)),
                "basis": "Invoices with a verified signed QR / invoices checked for one (QR missing, "
                         "mismatched or unsigned count as failed)."}
    else:
        einv = {"applicable": False, "verified": 0, "failed": 0, "rate": None,
                "basis": "Supplier is below the e-invoicing threshold: no signed QR expected."}

    dispute_rate = _rate(len(disputed), len(genuine))
    reasons: list[dict] = []
    if bank_alerts:
        reasons.append({"level": "high", "text": f"{len(bank_alerts)} invoice(s) with bank details that differ "
                                                 "from the vendor master (possible payment diversion)."})
    if injections:
        reasons.append({"level": "high", "text": f"{len(injections)} invoice(s) with hidden instructions aimed "
                                                 "at an AI reader."})
    if recent_change and recent_change >= today - timedelta(days=RECENT_BANK_CHANGE_DAYS):
        reasons.append({"level": "watch", "text": f"Bank account changed on {recent_change:%d %b %Y} "
                                                  f"(within {RECENT_BANK_CHANGE_DAYS} days): check first payments."})
    if open_changes:
        reasons.append({"level": "watch", "text": f"{len(open_changes)} bank change request(s) in progress."})
    if len(dup) >= THRESHOLDS["duplicate_attempts_watch"]:
        reasons.append({"level": "watch", "text": f"{len(dup)} duplicate submissions blocked in 12 months."})
    if (dispute_rate is not None and len(genuine) >= THRESHOLDS["min_invoices"]
            and dispute_rate >= THRESHOLDS["dispute_rate_watch"]):
        reasons.append({"level": "watch", "text": f"{dispute_rate:.0%} of invoices had a billing dispute "
                                                  f"(threshold {THRESHOLDS['dispute_rate_watch']:.0%})."})
    if einv["rate"] is not None and einv["rate"] < THRESHOLDS["einvoice_compliance_watch"]:
        reasons.append({"level": "watch", "text": f"e-invoice compliance {einv['rate']:.0%} "
                                                  f"(expected {THRESHOLDS['einvoice_compliance_watch']:.0%}+)."})
    level = "high" if any(r["level"] == "high" for r in reasons) else "watch" if reasons else "low"

    return {
        "supplier_id": s.id, "code": s.code, "name": s.name, "category": s.category,
        "msme": {"category": s.msme_category, "udyam_no": s.udyam_no,
                 "is_msme": s.msme_category in (MsmeCategory.MICRO, MsmeCategory.SMALL),
                 "enterprise_type": s.enterprise_type, "terms_days": s.payment_terms_days,
                 "written_agreement": s.written_agreement},
        "level": level, "reasons": reasons,
        "invoices_12m": len(invs),
        "spend_paid_12m": sum((p.amount for p in facts.payments if p.paid_on >= start), Decimal(0)),
        "on_time": {"paid": len(pays), "on_time": len(on_time), "rate": _rate(len(on_time), len(pays)),
                    "avg_days_late": round(sum(late_days) / len(late_days), 1) if late_days else None,
                    "basis": "Payments by Plant X paid on or before the binding due date (the earlier of "
                             "contract terms and the MSME statutory date)."},
        "disputes": {"count": len(disputed), "of": len(genuine), "rate": dispute_rate,
                     "basis": "Invoices (excluding blocked duplicates) where the engine raised a billing "
                              "exception: price, quantity, tax, arithmetic, unordered line, terms or "
                              "currency. Missing GR/SES is Plant X's side and is not counted."},
        "duplicates": {"blocked": len(dup), "possible": len(possible_dup),
                       "value_blocked": sum((i.total for i in dup), Decimal(0)),
                       "basis": "Submissions blocked as DUPLICATE, plus near-matches flagged POSSIBLE_DUPLICATE."},
        "bank_changes": {"approved_12m": len(changes), "in_progress": len(open_changes),
                         "last_changed": recent_change, "mismatch_alerts": len(bank_alerts),
                         "basis": "Maker-checker bank changes approved in 12 months; alerts are invoices "
                                  "blocked BANK_MISMATCH."},
        "einvoice": einv,
        "sustainability": sustainability(s.code, today),
    }


def load_facts(db: Session) -> dict[int, Facts]:
    out: dict[int, Facts] = defaultdict(Facts)
    codes: dict[int, set[str]] = defaultdict(set)
    for inv_id, code, sev in db.execute(select(MatchResult.invoice_id, ReasonCode.code, ReasonCode.severity)
                                        .join(ReasonCode, ReasonCode.match_result_id == MatchResult.id)):
        if sev != Severity.INFO or code == EINVOICE_OK:
            codes[inv_id].add(code)
    invoices = {}
    for inv in db.scalars(select(Invoice).where(Invoice.supplier_id.is_not(None))):
        invoices[inv.id] = inv
        out[inv.supplier_id].invoices.append(InvoiceFact(
            inv.id, as_utc(inv.received_at).astimezone(clock.IST).date(), inv.status, inv.total, codes[inv.id]))
    for p in db.scalars(select(Payment)):
        inv = invoices.get(p.invoice_id)
        if inv is None:
            continue
        dues = [d for d in (inv.due_date, inv.msme_due_date) if d]
        out[inv.supplier_id].payments.append(PaymentFact(
            inv.id, as_utc(p.paid_at).astimezone(clock.IST).date(), min(dues) if dues else None, p.gross_amount))
    for b in db.scalars(select(BankChangeRequest)):
        out[b.supplier_id].bank_changes.append(BankChangeFact(
            b.status, as_utc(b.decided_at).astimezone(clock.IST).date() if b.decided_at else None,
            as_utc(b.requested_at).astimezone(clock.IST).date()))
    return out


def cards(db: Session, supplier_id: int | None = None) -> list[dict]:
    today = clock.today()
    facts = load_facts(db)
    q = select(Supplier).order_by(Supplier.name)
    if supplier_id is not None:
        q = q.where(Supplier.id == supplier_id)
    order = {"high": 0, "watch": 1, "low": 2}
    result = [card(s, facts.get(s.id, Facts()), today) for s in db.scalars(q)]
    return sorted(result, key=lambda c: (order[c["level"]], c["name"]))


def methodology() -> dict:
    return {"window_days": WINDOW_DAYS, "recent_bank_change_days": RECENT_BANK_CHANGE_DAYS,
            "thresholds": THRESHOLDS, "dispute_codes": sorted(DISPUTE_CODES),
            "levels": {"high": "Any bank-detail mismatch or hidden-instruction attempt in 12 months.",
                       "watch": "Recent or pending bank change, repeated duplicates, dispute rate or "
                                "e-invoice compliance past its threshold.",
                       "low": "None of the above."},
            "note": "Information for procurement and AP only. The risk card never changes an invoice "
                    "decision; the rules engine decides."}
