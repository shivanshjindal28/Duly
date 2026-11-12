"""Invoice read endpoints with row-level supplier scoping.

Every query goes through `get_scope`: a supplier only ever sees its own invoices, and a
request for another supplier's invoice returns 404 (not 403) so existence is not revealed.
Stores users cannot touch invoices.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import SupplierScope, get_scope, require_roles
from app.models import Invoice
from app.models.enums import Role

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(require_roles(Role.SUPPLIER, Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))],
)


class InvoiceSummary(BaseModel):
    id: int
    supplier_id: int | None
    invoice_number: str
    invoice_date: date | None
    total: Decimal
    status: str
    decision: str | None
    current_owner: str


def _summary(inv: Invoice) -> InvoiceSummary:
    return InvoiceSummary(
        id=inv.id, supplier_id=inv.supplier_id, invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date, total=inv.total, status=inv.status, decision=inv.decision,
        current_owner=inv.current_owner,
    )


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> list[InvoiceSummary]:
    q = select(Invoice).order_by(Invoice.received_at.desc())
    if scope.supplier_id is not None:
        q = q.where(Invoice.supplier_id == scope.supplier_id)
    return [_summary(i) for i in db.scalars(q)]


def get_invoice_in_scope(invoice_id: int, scope: SupplierScope, db: Session) -> Invoice:
    """Load an invoice or 404 if it does not exist or is outside the caller's scope."""
    inv = db.get(Invoice, invoice_id)
    if inv is None or not scope.allows(inv.supplier_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


@router.get("/{invoice_id}", response_model=InvoiceSummary)
def get_invoice(invoice_id: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> InvoiceSummary:
    return _summary(get_invoice_in_scope(invoice_id, scope, db))
