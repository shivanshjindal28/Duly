"""Supplier portal: "where is my invoice and why", answered without calling anyone.

Returns only the signed-in supplier's own data. Block and flag reasons are turned into
plain-language to-dos as message codes + parameters; the frontend renders them in English
or Hindi from i18n files (no machine translation at run time). Internal details (approver
names, SAP references, other suppliers) are never included.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dashboard import latest_reasons
from app.core import clock
from app.core.db import get_db
from app.core.enums import InvoiceStatus, Role, Severity
from app.core.security import SupplierScope, get_scope, require_roles
from app.models import Invoice, MatchResult, Payment, ReasonCode, Supplier
from app.payments.msme import msme_eligible
from app.workflow.lifecycle import rail_progress

router = APIRouter(prefix="/portal", tags=["supplier portal"], dependencies=[Depends(require_roles(Role.SUPPLIER))])

# Supplier-facing stage of each status (message key, rendered by the frontend in en/hi).
STAGE = {
    InvoiceStatus.RECEIVED: "stage.checking",
    InvoiceStatus.NEEDS_REVIEW: "stage.checking_fields",
    InvoiceStatus.FLAGGED: "stage.exception",
    InvoiceStatus.BLOCKED: "stage.on_hold",
    InvoiceStatus.PENDING_APPROVAL: "stage.awaiting_approval",
    InvoiceStatus.APPROVED: "stage.scheduled",
    InvoiceStatus.REJECTED: "stage.rejected",
    InvoiceStatus.PAID: "stage.paid",
}


class Todo(BaseModel):
    code: str  # message key suffix, e.g. "QTY_EXCEEDS_GR"
    severity: str
    you_act: bool  # True = the supplier must do something; False = Plant X is on it
    params: dict[str, str]


class PortalInvoice(BaseModel):
    id: int
    invoice_number: str
    invoice_date: date | None
    po_number: str | None
    total: Decimal
    status: str
    stage: str
    rail: int
    expected_payment: date | None
    msme_due_date: date | None
    msme_days_left: int | None
    todos: list[Todo]


class PortalPayment(BaseModel):
    invoice_number: str
    paid_at: date
    gross: Decimal
    tds: Decimal
    net: Decimal
    utr: str


class PortalOut(BaseModel):
    supplier_name: str
    supplier_code: str
    msme_category: str
    msme_eligible: bool
    udyam_no: str | None
    payment_terms_days: int
    written_agreement: bool
    bank_account_masked: str
    bank_ifsc: str
    today: date
    invoices: list[PortalInvoice]
    payments: list[PortalPayment]


def _money(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _todos(db: Session, inv: Invoice, codes: list[tuple[str, str]]) -> list[Todo]:
    out: list[Todo] = []
    if inv.status == InvoiceStatus.NEEDS_REVIEW:
        out.append(Todo(code="NEEDS_REVIEW", severity="info", you_act=False, params={}))
    if inv.status not in (InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED, InvoiceStatus.NEEDS_REVIEW):
        return out
    m = db.scalar(select(MatchResult).where(MatchResult.invoice_id == inv.id).order_by(MatchResult.id.desc()).limit(1))
    reasons = db.scalars(select(ReasonCode).where(ReasonCode.match_result_id == m.id)).all() if m else []
    lines = {ln.line_no: ln for ln in inv.lines}
    seen: set[str] = set()
    for r in reasons:
        if r.severity not in (Severity.BLOCK, Severity.FLAG) or r.code in seen:
            continue
        seen.add(r.code)
        ev, params = r.evidence or {}, {}
        line = lines.get(r.line_no) if r.line_no else None
        if r.code == "QTY_EXCEEDS_GR" and line is not None:
            excess = Decimal(str(ev.get("excess", "0")))
            credit = excess * line.unit_price * (1 + line.gst_rate / 100)
            params = {"item": line.item_code or line.description, "excess": f"{excess.normalize():f}",
                      "uom": ev.get("uom", line.uom), "credit": _money(credit)}
        elif r.code == "PRICE_VARIANCE" and line is not None:
            amount = Decimal(str(ev.get("variance_amount", "0")))
            params = {"item": line.item_code or line.description, "po_price": ev.get("po_price", ""),
                      "credit": _money(amount * (1 + line.gst_rate / 100))}
        elif r.code in ("MISSING_GR", "MISSING_SES") and line is not None:
            params = {"item": line.item_code or line.description}
        elif r.code in ("DUPLICATE", "POSSIBLE_DUPLICATE"):
            params = {"of": str(ev.get("duplicate_of", ""))}
        you_act = r.code not in ("MISSING_GR", "MISSING_SES", "PAYMENT_TERMS_MISMATCH", "POSSIBLE_DUPLICATE",
                                 "BANK_ACCOUNT_SHARED", "INJECTION_ATTEMPT", "EMAIL_SENDER_UNVERIFIED", "ERS_PO_INVOICE",
                                 "LINE_MAPPED")
        out.append(Todo(code=r.code, severity=r.severity, you_act=you_act, params=params))
    return out


@router.get("", response_model=PortalOut)
def portal(scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> PortalOut:
    return build_portal(db, scope.supplier_id)


def build_portal(db: Session, supplier_id: int) -> PortalOut:
    """One supplier's own portal data (also used by the payment chatbot's tools)."""
    s = db.get(Supplier, supplier_id)
    today = clock.today()
    eligible = msme_eligible(s.msme_category, s.enterprise_type)
    codes = latest_reasons(db)
    invoices = []
    for inv in db.scalars(select(Invoice).where(Invoice.supplier_id == s.id).order_by(Invoice.received_at.desc())):
        inv_codes = codes.get(inv.id, [])
        expected = None
        if inv.status in (InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.APPROVED):
            expected = min(d for d in (inv.due_date, inv.msme_due_date) if d) if (inv.due_date or inv.msme_due_date) else None
        open_msme = inv.msme_due_date and inv.status not in (InvoiceStatus.PAID, InvoiceStatus.REJECTED)
        invoices.append(PortalInvoice(
            id=inv.id, invoice_number=inv.invoice_number, invoice_date=inv.invoice_date, po_number=inv.po_number_text,
            total=inv.total, status=inv.status, stage=STAGE[InvoiceStatus(inv.status)],
            rail=rail_progress(inv, {c for c, _ in inv_codes}), expected_payment=expected,
            msme_due_date=inv.msme_due_date,
            msme_days_left=(inv.msme_due_date - today).days if open_msme else None,
            todos=_todos(db, inv, inv_codes),
        ))
    numbers = {i.id: i.invoice_number for i in invoices}
    payments = [
        PortalPayment(invoice_number=numbers.get(p.invoice_id, str(p.invoice_id)), paid_at=p.paid_at.date(),
                      gross=p.gross_amount, tds=p.tds_amount, net=p.net_amount, utr=p.utr)
        for p in db.scalars(select(Payment).join(Invoice, Invoice.id == Payment.invoice_id)
                            .where(Invoice.supplier_id == s.id).order_by(Payment.paid_at.desc()))
    ]
    return PortalOut(
        supplier_name=s.name, supplier_code=s.code, msme_category=s.msme_category, msme_eligible=eligible,
        udyam_no=s.udyam_no, payment_terms_days=s.payment_terms_days, written_agreement=s.written_agreement,
        bank_account_masked="XXXXXX" + s.bank_account_last4, bank_ifsc=s.bank_ifsc, today=today, invoices=invoices, payments=payments,
    )
