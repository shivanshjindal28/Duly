"""Exceptions dashboard and work queue (spec C5), computed live from the database.

Every number here is derived from stored invoices, match results and approval steps; nothing
is hard-coded. "Open exception" = an invoice that is blocked, flagged or waiting for human
review. Ages use the business clock (so the demo clock moves them too).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import get_db
from app.core.enums import InvoiceStatus, Role, Severity, StepStatus
from app.core.security import require_roles
from app.engine.catalog import info
from app.models import ApprovalStep, Invoice, MatchResult, ReasonCode, Supplier
from app.models.base import as_utc

router = APIRouter(prefix="/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])

OPEN_EXCEPTION = (InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED, InvoiceStatus.NEEDS_REVIEW)
IN_QUEUE = (*OPEN_EXCEPTION, InvoiceStatus.RECEIVED, InvoiceStatus.PENDING_APPROVAL)
AGE_BUCKETS = [("0-7", 0, 7), ("8-15", 8, 15), ("16-30", 16, 30), ("31-45", 31, 45), ("45+", 46, 10_000)]


class Kpis(BaseModel):
    in_queue: int
    value_on_hold: Decimal
    touchless_rate: float | None  # share of approved invoices approved by policy (no human)
    approved_count: int
    avg_cycle_hours: float | None  # upload -> final approval
    msme_due_7d: int
    msme_overdue: int
    duplicates_prevented: int
    duplicates_value: Decimal


class TypeRow(BaseModel):
    code: str
    title: str
    severity: str
    count: int
    value: Decimal


class SupplierRow(BaseModel):
    supplier_id: int
    supplier_name: str
    msme: str
    open_exceptions: int
    value_at_risk: Decimal
    oldest_days: int


class AgeRow(BaseModel):
    bucket: str
    count: int
    value: Decimal


class DueDay(BaseModel):
    day: date
    count: int
    value: Decimal


class Summary(BaseModel):
    as_of: datetime
    kpis: Kpis
    by_type: list[TypeRow]
    by_supplier: list[SupplierRow]
    by_age: list[AgeRow]
    msme_due: list[DueDay]


class QueueRow(BaseModel):
    id: int
    invoice_number: str
    supplier_id: int | None
    supplier_name: str | None
    total: Decimal
    status: str
    decision: str | None
    reasons: list[str]
    top_reason: str | None
    age_days: int
    current_owner: str
    msme_due_date: date | None
    received_at: datetime


def latest_reasons(db: Session) -> dict[int, list[tuple[str, str]]]:
    """invoice_id -> [(code, severity)] of its latest match."""
    latest = select(func.max(MatchResult.id).label("mid")).group_by(MatchResult.invoice_id).subquery()
    out: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for inv_id, code, sev in db.execute(
        select(MatchResult.invoice_id, ReasonCode.code, ReasonCode.severity)
        .join(latest, latest.c.mid == MatchResult.id)
        .join(ReasonCode, ReasonCode.match_result_id == MatchResult.id)
    ):
        out[inv_id].append((code, sev))
    return out


def _age_days(inv: Invoice, now: datetime) -> int:
    return max(0, (now - as_utc(inv.received_at)).days)


def _bucket(days: int) -> str:
    return next(b for b, lo, hi in AGE_BUCKETS if lo <= days <= hi)


def _actionable(reasons: list[tuple[str, str]]) -> list[tuple[str, str]]:
    order = {Severity.BLOCK: 0, Severity.FLAG: 1}
    return sorted([r for r in reasons if r[1] in (Severity.BLOCK, Severity.FLAG)], key=lambda r: order[r[1]])


@router.get("/summary", response_model=Summary)
def summary(db: Session = Depends(get_db)) -> Summary:
    now, today = clock.now(), clock.today()
    invoices = db.scalars(select(Invoice)).all()
    suppliers = {s.id: s for s in db.scalars(select(Supplier))}
    reasons = latest_reasons(db)
    open_exc = [i for i in invoices if i.status in OPEN_EXCEPTION]

    # Touchless rate and cycle time from approval steps.
    final_steps: dict[int, list[ApprovalStep]] = defaultdict(list)
    for s in db.scalars(select(ApprovalStep).where(ApprovalStep.status == StepStatus.APPROVED)):
        final_steps[s.invoice_id].append(s)
    approved = [i for i in invoices if i.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID)]
    touchless = [i for i in approved if any(s.by_policy for s in final_steps[i.id])]
    cycles = [(max(as_utc(s.decided_at) for s in final_steps[i.id]) - as_utc(i.received_at)).total_seconds() / 3600
              for i in approved if final_steps[i.id]]
    unpaid_msme = [i for i in invoices if i.msme_due_date and i.status not in (InvoiceStatus.PAID, InvoiceStatus.REJECTED)]
    dup = [i for i in invoices if any(c in ("DUPLICATE", "POSSIBLE_DUPLICATE") for c, _ in reasons.get(i.id, []))]

    kpis = Kpis(
        in_queue=sum(i.status in IN_QUEUE for i in invoices),
        value_on_hold=sum((i.total for i in open_exc), Decimal(0)),
        touchless_rate=round(len(touchless) / len(approved), 3) if approved else None,
        approved_count=len(approved),
        avg_cycle_hours=round(sum(cycles) / len(cycles), 1) if cycles else None,
        msme_due_7d=sum(today <= i.msme_due_date <= today + timedelta(days=7) for i in unpaid_msme),
        msme_overdue=sum(i.msme_due_date < today for i in unpaid_msme),
        duplicates_prevented=len(dup),
        duplicates_value=sum((i.total for i in dup), Decimal(0)),
    )

    by_type: dict[str, TypeRow] = {}
    for inv in open_exc:
        for code, sev in {c: s for c, s in _actionable(reasons.get(inv.id, []))}.items():
            row = by_type.setdefault(code, TypeRow(code=code, title=info(code).title, severity=sev, count=0, value=0))
            row.count += 1
            row.value += inv.total
            if sev == Severity.BLOCK:
                row.severity = sev
    if any(i.status == InvoiceStatus.NEEDS_REVIEW for i in open_exc):
        n = [i for i in open_exc if i.status == InvoiceStatus.NEEDS_REVIEW]
        by_type["NEEDS_REVIEW"] = TypeRow(code="NEEDS_REVIEW", title="Low-confidence fields to review",
                                          severity="flag", count=len(n), value=sum((i.total for i in n), Decimal(0)))

    by_sup: dict[int, SupplierRow] = {}
    for inv in open_exc:
        s = suppliers.get(inv.supplier_id)
        if s is None:
            continue
        row = by_sup.setdefault(s.id, SupplierRow(supplier_id=s.id, supplier_name=s.name, msme=s.msme_category,
                                                  open_exceptions=0, value_at_risk=0, oldest_days=0))
        row.open_exceptions += 1
        row.value_at_risk += inv.total
        row.oldest_days = max(row.oldest_days, _age_days(inv, now))

    by_age = {b: AgeRow(bucket=b, count=0, value=0) for b, _, _ in AGE_BUCKETS}
    for inv in open_exc:
        r = by_age[_bucket(_age_days(inv, now))]
        r.count += 1
        r.value += inv.total

    due = {today + timedelta(days=d): DueDay(day=today + timedelta(days=d), count=0, value=0) for d in range(-7, 31)}
    for inv in unpaid_msme:
        if inv.msme_due_date in due:
            due[inv.msme_due_date].count += 1
            due[inv.msme_due_date].value += inv.total

    return Summary(as_of=now, kpis=kpis, by_type=sorted(by_type.values(), key=lambda r: (-r.count, r.code)),
                   by_supplier=sorted(by_sup.values(), key=lambda r: -r.value_at_risk),
                   by_age=list(by_age.values()), msme_due=list(due.values()))


@router.get("/queue", response_model=list[QueueRow])
def queue(
    status: str | None = Query(None, description="status, or 'open' for open exceptions, 'all' for everything"),
    reason: str | None = None,
    supplier_id: int | None = None,
    age: str | None = Query(None, description="age bucket, e.g. 8-15"),
    msme_due_within: int | None = Query(None, ge=0, le=60),
    db: Session = Depends(get_db),
) -> list[QueueRow]:
    now, today = clock.now(), clock.today()
    q = select(Invoice).order_by(Invoice.received_at)
    if status in (None, "open"):
        q = q.where(Invoice.status.in_(OPEN_EXCEPTION if status == "open" else IN_QUEUE))
    elif status != "all":
        q = q.where(Invoice.status == status)
    if supplier_id:
        q = q.where(Invoice.supplier_id == supplier_id)
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    reasons = latest_reasons(db)
    rows = []
    for inv in db.scalars(q):
        codes = _actionable(reasons.get(inv.id, []))
        all_codes = [c for c, _ in codes]
        if inv.status == InvoiceStatus.NEEDS_REVIEW:
            all_codes.append("NEEDS_REVIEW")
        if reason and reason not in all_codes:
            continue
        days = _age_days(inv, now)
        if age and _bucket(days) != age:
            continue
        if msme_due_within is not None and not (
            inv.msme_due_date and inv.msme_due_date <= today + timedelta(days=msme_due_within)
            and inv.status not in (InvoiceStatus.PAID, InvoiceStatus.REJECTED)
        ):
            continue
        rows.append(QueueRow(
            id=inv.id, invoice_number=inv.invoice_number, supplier_id=inv.supplier_id,
            supplier_name=names.get(inv.supplier_id), total=inv.total, status=inv.status, decision=inv.decision,
            reasons=all_codes, top_reason=all_codes[0] if all_codes else None, age_days=days,
            current_owner=inv.current_owner, msme_due_date=inv.msme_due_date, received_at=inv.received_at,
        ))
    return rows
