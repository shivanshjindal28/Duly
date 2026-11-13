"""Smart payment run (D5) and the MSME guardian report (D4).

Proposal rules (deterministic, explained per invoice):
  1. MSME invoices by statutory due date first: paid in this run if the due date falls before
     the next run plus a safety buffer (or is already past).
  2. Early-payment discount: paid now if the discount window is open and the annualised return
     of taking it beats the cost-of-funds assumption.
  3. Everyone else on contract terms, not early: paid in this run only if the contract due date
     falls before the next run; otherwise deferred (cash kept).
Releasing a run is a finance (approver) action; each payment gets a simulated UTR, TDS is
withheld per supplier section, and the invoice becomes "Duly paid" in the supplier view and chatbot.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.enums import InvoiceStatus, Role
from app.models import CreditNote, Invoice, Payment, Policy, Supplier, User
from app.models.base import as_utc
from app.payments import msme as m
from app.workflow.credit_notes import net_amounts
from app.payments import tds as tds_mod

TWO = Decimal("0.01")


class PaymentError(ValueError):
    pass


def _policy(db: Session) -> dict:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True))).data


def fy_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


@dataclass
class Proposal:
    invoice_id: int
    invoice_number: str
    supplier_id: int
    supplier_name: str
    msme: bool
    invoice_date: date | None
    due_date: date | None
    msme_due_date: date | None
    days_left: int | None  # to the binding due date
    pay: bool
    rule: str  # msme | discount | terms | overdue | defer
    reason: str
    gross: Decimal
    taxable: Decimal
    discount: Decimal
    discount_apr_pct: Decimal | None
    tds_section: str
    tds_label: str
    tds_rate_pct: Decimal
    tds: Decimal
    net: Decimal
    interest_if_late: Decimal  # MSMED s.16 interest accrued so far (overdue MSME only)
    # Amounts above are in `currency` (the invoice's). INR equivalents at the invoice's FX rate:
    currency: str = "INR"
    fx_rate: Decimal = Decimal(1)
    gross_inr: Decimal = Decimal(0)
    net_inr: Decimal = Decimal(0)


@dataclass
class RunPlan:
    run_date: date
    next_run: date
    cost_of_funds_pct: Decimal
    items: list[Proposal] = field(default_factory=list)


def _discount(s: Supplier, inv: Invoice, today: date, due: date | None, cof: Decimal,
              total: Decimal) -> tuple[Decimal, Decimal | None, bool]:
    """(discount amount, annualised return %, worth taking)."""
    pct = Decimal(str(s.early_discount_pct or 0))
    if pct <= 0 or not inv.invoice_date or not s.early_discount_days:
        return Decimal(0), None, False
    if today > inv.invoice_date + timedelta(days=s.early_discount_days):
        return Decimal(0), None, False
    days_early = max(1, ((due or today) - today).days)
    apr = (pct / (100 - pct) * Decimal(365) / Decimal(days_early) * 100).quantize(TWO)
    amount = (total * pct / 100).quantize(TWO, rounding=ROUND_HALF_UP)
    return amount, apr, apr > cof


def _paid_this_fy(db: Session, supplier_id: int, today: date) -> Decimal:
    start = datetime.combine(fy_start(today), datetime.min.time(), tzinfo=clock.IST)
    total = db.scalar(select(func.coalesce(func.sum(Invoice.taxable_total), 0))
                      .join(Payment, Payment.invoice_id == Invoice.id)
                      .where(Invoice.supplier_id == supplier_id, Payment.paid_at >= start))
    credited = db.scalar(select(func.coalesce(func.sum(CreditNote.taxable), 0))
                         .join(Payment, Payment.invoice_id == CreditNote.invoice_id)
                         .where(CreditNote.supplier_id == supplier_id, Payment.paid_at >= start))
    return Decimal(str(total or 0)) - Decimal(str(credited or 0))


def plan(db: Session) -> RunPlan:
    policy = _policy(db)
    p = policy.get("payments", {})
    cof = Decimal(str(p.get("cost_of_funds_pct", 9.0)))
    interval = int(p.get("run_interval_days", 7))
    buffer = int(p.get("msme_buffer_days", 7))
    bank_rate = Decimal(str(policy.get("msme", {}).get("rbi_bank_rate_pct", 5.75)))
    table = policy.get("tds")
    today = clock.today()
    nxt = today + timedelta(days=interval)
    out = RunPlan(today, nxt, cof)
    paid_ids = set(db.scalars(select(Payment.invoice_id)))
    fy_paid: dict[int, Decimal] = {}
    invoices = db.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.APPROVED)).all()
    net = net_amounts(db, invoices)  # net of credit notes: what Plant X actually owes
    for inv in invoices:
        if inv.id in paid_ids:
            continue
        taxable, total = net[inv.id]
        s = db.get(Supplier, inv.supplier_id)
        is_msme = inv.msme_due_date is not None
        binding = min(d for d in (inv.due_date, inv.msme_due_date) if d) if (inv.due_date or inv.msme_due_date) else None
        days_left = (binding - today).days if binding else None
        disc, apr, worth = _discount(s, inv, today, inv.due_date, cof, total)
        interest = Decimal(0)
        if binding and binding < today:
            rule, pay = "overdue", True
            reason = f"Overdue since {binding:%d %b %Y}: pay now."
            if is_msme:
                interest = m.interest(total, inv.msme_due_date, today, bank_rate)
                reason = (f"MSME payment overdue since {inv.msme_due_date:%d %b %Y}: pay now. "
                          f"Interest under MSMED s.16 so far: Rs {interest:,.2f}.")
        elif is_msme and inv.msme_due_date <= nxt + timedelta(days=buffer):
            rule, pay = "msme", True
            reason = (f"MSME statutory due date {inv.msme_due_date:%d %b %Y} ({days_left} days left) is before the "
                      f"next run on {nxt:%d %b} plus a {buffer}-day buffer: pay in this run.")
        elif worth:
            rule, pay = "discount", True
            reason = (f"{s.early_discount_pct}% early-payment discount = {apr}% a year, above the {cof}% cost of funds: "
                      f"take it (saves Rs {disc:,.2f}).")
        elif binding and binding <= nxt:
            rule, pay = "terms", True
            reason = f"Due on contract terms on {binding:%d %b %Y}, before the next run: pay in this run."
        else:
            rule, pay = "defer", False
            reason = (f"Due {binding:%d %b %Y}: pay on terms in a later run, not early." if binding
                      else "No due date yet (acceptance pending).")
            if apr is not None:
                reason += f" Discount of {s.early_discount_pct}% = {apr}% a year does not beat the {cof}% cost of funds."
        if rule != "discount":
            disc = Decimal(0)
        if s.id not in fy_paid:
            fy_paid[s.id] = _paid_this_fy(db, s.id, today)
        t = tds_mod.compute(s.tds_section or "none", s.pan or "", taxable, fy_paid[s.id], table)
        if pay:
            fy_paid[s.id] += taxable
        out.items.append(Proposal(
            inv.id, inv.invoice_number, s.id, s.name, is_msme, inv.invoice_date, inv.due_date, inv.msme_due_date,
            days_left, pay, rule, reason, total, taxable, disc, apr, t.section, t.label, t.rate_pct,
            t.amount, total - disc - t.amount, interest,
            inv.currency, inv.fx_rate or Decimal(1), _inr(total, inv), _inr(total - disc - t.amount, inv)))
    order = {"overdue": 0, "msme": 1, "discount": 2, "terms": 3, "defer": 4}
    out.items.sort(key=lambda x: (order[x.rule], x.msme_due_date or x.due_date or date.max, x.invoice_number))
    return out


def _inr(amount: Decimal, inv: Invoice) -> Decimal:
    return (amount * (inv.fx_rate or Decimal(1))).quantize(TWO)


def summary(pl: RunPlan) -> dict:
    """Cash and days-payable effect of the proposed run."""
    pay = [i for i in pl.items if i.pay]
    defer = [i for i in pl.items if not i.pay]

    def wdays(items: list[Proposal], when) -> Decimal | None:
        rows = [(i.gross_inr, (when(i) - i.invoice_date).days) for i in items if i.invoice_date]
        tot = sum((g for g, _ in rows), Decimal(0))
        return (sum((g * d for g, d in rows), Decimal(0)) / tot).quantize(Decimal("0.1")) if tot else None

    kept = sum((i.gross_inr for i in defer), Decimal(0))
    kept_days = [(i.gross_inr, ((i.msme_due_date or i.due_date) - pl.run_date).days) for i in defer
                 if (i.msme_due_date or i.due_date)]
    kept_tot = sum((g for g, _ in kept_days), Decimal(0))
    return {
        "invoices_to_pay": len(pay),
        # All totals in INR (each invoice at its FX rate).
        "gross": sum((i.gross_inr for i in pay), Decimal(0)),
        "discounts": sum(((i.discount * i.fx_rate).quantize(TWO) for i in pay), Decimal(0)),
        "tds": sum(((i.tds * i.fx_rate).quantize(TWO) for i in pay), Decimal(0)),
        "cash_out": sum((i.net_inr for i in pay), Decimal(0)),
        "currencies": sorted({i.currency for i in pay}),
        "msme_in_run": sum(1 for i in pay if i.msme),
        "deferred_count": len(defer),
        "cash_kept": kept,
        "cash_kept_avg_days": (sum((g * d for g, d in kept_days), Decimal(0)) / kept_tot).quantize(Decimal("0.1")) if kept_tot else None,
        # Days payable (invoice date to payment) for this run vs paying every approved invoice today.
        "dpo_this_run_days": wdays(pay, lambda i: pl.run_date),
        "dpo_if_all_paid_today_days": wdays(pl.items, lambda i: pl.run_date),
        "dpo_on_plan_days": wdays(pl.items, lambda i: pl.run_date if i.pay else (i.msme_due_date or i.due_date or pl.run_date)),
    }


def _utr(today: date) -> str:
    """Simulated NEFT-style UTR (fictional bank code DULY)."""
    return f"DULYN{today:%y%j}{secrets.randbelow(10**8):08d}"


def release(db: Session, user: User, invoice_ids: list[int]) -> tuple[str, list[Payment]]:
    """Finance releases the selected invoices: TDS withheld, simulated UTR, invoice -> paid."""
    if user.role != Role.APPROVER:
        raise PaymentError("Only a finance approver can release a payment run.")
    if not invoice_ids:
        raise PaymentError("Select at least one invoice.")
    pl = plan(db)
    by_id = {i.invoice_id: i for i in pl.items}
    missing = [i for i in invoice_ids if i not in by_id]
    if missing:
        raise PaymentError(f"Not payable (not approved, or already paid): invoice ids {missing}.")
    today = clock.today()
    count = db.scalar(select(func.count(func.distinct(Payment.payment_run_id)))
                      .where(Payment.payment_run_id.like(f"PR-{today:%Y%m%d}-%"))) or 0
    run_id = f"PR-{today:%Y%m%d}-{count + 1:02d}"
    now = clock.now()
    # Recompute TDS in order so the yearly threshold accumulates across this run.
    table = _policy(db).get("tds")
    fy_paid: dict[int, Decimal] = {}
    payments = []
    for iid in invoice_ids:
        item = by_id[iid]
        inv = db.get(Invoice, iid)
        s = db.get(Supplier, inv.supplier_id)
        if s.id not in fy_paid:
            fy_paid[s.id] = _paid_this_fy(db, s.id, today)
        t = tds_mod.compute(s.tds_section or "none", s.pan or "", item.taxable, fy_paid[s.id], table)
        fy_paid[s.id] += item.taxable
        disc = item.discount if item.rule == "discount" else Decimal(0)
        p = Payment(invoice_id=iid, payment_run_id=run_id, gross_amount=item.gross, tds_amount=t.amount,
                    tds_section=t.section, tds_rate_pct=t.rate_pct, discount_amount=disc,
                    net_amount=item.gross - disc - t.amount, utr=_utr(today), released_by_user_id=user.id,
                    reason=item.reason[:200], paid_at=now, currency=item.currency, fx_rate=item.fx_rate,
                    net_inr=((item.gross - disc - t.amount) * item.fx_rate).quantize(TWO))
        db.add(p)
        inv.status = InvoiceStatus.PAID
        inv.current_owner = "Paid"
        payments.append(p)
        late = inv.msme_due_date is not None and today > inv.msme_due_date
        audit.queue(db, "payment.released", "invoice", iid, after={
            "run": run_id, "utr": p.utr, "gross": str(item.gross), "tds": str(t.amount), "tds_section": t.section,
            "discount": str(disc), "net": str(p.net_amount), "rule": item.rule, "msme_late": late})
    db.commit()
    return run_id, payments


# ---------------------------------------------------------------- MSME guardian (D4)

@dataclass
class MsmeRow:
    invoice_id: int
    invoice_number: str
    supplier_name: str
    udyam_no: str | None
    msme_category: str
    amount: Decimal
    accepted_on: date | None
    due_date: date
    paid_on: date | None
    status: str  # on_time | paid_late | open | overdue
    days_left: int | None
    days_late: int
    interest: Decimal
    deduction_at_risk: Decimal
    tax_effect: Decimal


def msme_rows(db: Session) -> list[MsmeRow]:
    policy = _policy(db)
    bank_rate = Decimal(str(policy.get("msme", {}).get("rbi_bank_rate_pct", 5.75)))
    tax_rate = Decimal(str(policy.get("corporate_tax_rate_pct", 25.17)))
    today = clock.today()
    pays = {p.invoice_id: p for p in db.scalars(select(Payment))}
    rows = []
    msme_invoices = db.scalars(select(Invoice).where(Invoice.msme_due_date.is_not(None),
                                                     Invoice.status != InvoiceStatus.REJECTED)).all()
    net = net_amounts(db, msme_invoices)
    for inv in msme_invoices:
        amount = net[inv.id][1]
        s = db.get(Supplier, inv.supplier_id)
        p = pays.get(inv.id)
        paid_on = as_utc(p.paid_at).astimezone(clock.IST).date() if p else None
        end = paid_on or today
        late = max(0, (end - inv.msme_due_date).days)
        if paid_on:
            status = "paid_late" if late else "on_time"
            risk, effect = Decimal(0), Decimal(0)
        else:
            status = "overdue" if late else "open"
            risk, effect = m.deduction_at_risk(amount, inv.msme_due_date, today, tax_rate)
        rows.append(MsmeRow(
            inv.id, inv.invoice_number, s.name, s.udyam_no, s.msme_category, amount,
            as_utc(inv.accepted_at).astimezone(clock.IST).date() if inv.accepted_at else None,
            inv.msme_due_date, paid_on, status, None if paid_on else (inv.msme_due_date - today).days, late,
            m.interest(amount, inv.msme_due_date, end, bank_rate), risk, effect))
    rows.sort(key=lambda r: (r.status not in ("overdue", "open"), r.due_date))
    return rows


def form1_summary(db: Session, on: date | None = None) -> dict:
    """Half-yearly 'MSME dues outstanding beyond 45 days' (data for MSME Form I).

    For the half year containing `on`: every MSME invoice whose statutory due date fell in or
    before the period and which was unpaid past it (still unpaid, or paid late within the period).
    """
    on = on or clock.today()
    start, end, label = m.half_year(on)
    cutoff = min(end, clock.today())
    rows = []
    for r in msme_rows(db):
        if r.due_date >= cutoff:
            continue
        outstanding = r.paid_on is None or r.paid_on > r.due_date
        if not outstanding or (r.paid_on and r.paid_on < start):
            continue
        rows.append({"supplier_name": r.supplier_name, "udyam_no": r.udyam_no, "invoice_number": r.invoice_number,
                     "amount_due": r.amount, "due_since": r.due_date, "paid_on": r.paid_on,
                     "days_beyond": (min(r.paid_on or cutoff, cutoff) - r.due_date).days,
                     "reason_for_delay": "Paid late" if r.paid_on else "Unpaid at period end / today"})
    return {"period": label, "from": start, "to": end, "as_of": cutoff, "rows": rows,
            "total_outstanding": sum((x["amount_due"] for x in rows), Decimal(0))}
