"""Supplier directory for Plant X staff (e.g. the clerk's "upload on behalf of" picker).

Bank details are never returned here, only the masked last four digits.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import get_db
from app.reports import supplier_risk
from app.core.enums import Role
from app.core.security import require_roles
from app.models import Supplier

router = APIRouter(prefix="/suppliers", tags=["suppliers"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    category: str
    gstin: str
    state_code: str
    msme_category: str
    enterprise_type: str
    e_invoice_applicable: bool
    payment_terms_days: int
    bank_account_masked: str
    bank_ifsc: str


@router.get("/risk")
def risk_cards(db: Session = Depends(get_db)) -> dict:
    """Supplier risk cards (spec D8), highest level first. Information only: never feeds a decision."""
    return {"as_of": clock.today(), "cards": supplier_risk.cards(db), "methodology": supplier_risk.methodology()}


@router.get("/{supplier_id}/risk")
def risk_card(supplier_id: int, db: Session = Depends(get_db)) -> dict:
    found = supplier_risk.cards(db, supplier_id)
    if not found:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return found[0]


@router.get("", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)) -> list[SupplierOut]:
    return [
        SupplierOut(id=s.id, code=s.code, name=s.name, category=s.category, gstin=s.gstin, state_code=s.state_code,
                    msme_category=s.msme_category, enterprise_type=s.enterprise_type,
                    e_invoice_applicable=s.e_invoice_applicable, payment_terms_days=s.payment_terms_days,
                    bank_account_masked="XXXXXX" + s.bank_account_last4, bank_ifsc=s.bank_ifsc)
        for s in db.scalars(select(Supplier).order_by(Supplier.name))
    ]
