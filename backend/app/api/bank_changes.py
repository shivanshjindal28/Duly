"""Bank detail change requests (D3). Suppliers see and create only their own; staff see all."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import SupplierScope, get_scope, require_roles
from app.models import BankChangeRequest, Supplier, User
from app.models.base import as_utc
from app.workflow import bank_changes as bc

router = APIRouter(prefix="/bank-changes", tags=["bank changes"],
                   dependencies=[Depends(require_roles(Role.SUPPLIER, Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


class RequestIn(BaseModel):
    account: str = Field(max_length=30)
    ifsc: str = Field(max_length=11)
    bank_name: str = Field(max_length=100)
    reason: str = Field(max_length=300)


class ProposeIn(BaseModel):
    checklist: dict[str, bool] = Field(max_length=20)
    contact: str = Field(max_length=100)
    notes: str = Field("", max_length=300)


class NoteIn(BaseModel):
    note: str = Field("", max_length=300)


class ChangeOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    current_account: str
    current_ifsc: str
    new_account: str
    new_ifsc: str
    new_bank_name: str
    reason: str
    status: str
    requested_at: datetime
    requested_by: str | None
    proposed_by: str | None
    approved_by: str | None
    callback: dict | None
    cooling_until: datetime | None
    cooling_hours_left: float | None
    decision_note: str | None
    can_propose: bool
    can_approve: bool
    can_reject: bool


def _out(db: Session, r: BankChangeRequest, user: User) -> ChangeOut:
    s = db.get(Supplier, r.supplier_id)
    names = {u.id: u.full_name for u in db.scalars(select(User))}
    left = (as_utc(r.cooling_until) - clock.now()).total_seconds() / 3600 if r.cooling_until else None
    return ChangeOut(
        id=r.id, supplier_id=s.id, supplier_name=s.name, current_account=bc.mask(s.bank_account_last4),
        current_ifsc=s.bank_ifsc, new_account=bc.mask(r.new_account_last4), new_ifsc=r.new_ifsc,
        new_bank_name=r.new_bank_name, reason=r.reason, status=r.status, requested_at=r.requested_at,
        requested_by=names.get(r.requested_by_user_id), proposed_by=names.get(r.proposed_by_user_id),
        approved_by=names.get(r.approved_by_user_id), callback=r.callback, cooling_until=r.cooling_until,
        cooling_hours_left=round(max(left, 0), 1) if left is not None else None, decision_note=r.decision_note,
        can_propose=user.role == Role.CLERK and r.status == "requested",
        can_approve=user.role == Role.APPROVER and r.status == "cooling" and (left or 0) <= 0
        and user.id not in (r.proposed_by_user_id, r.requested_by_user_id),
        can_reject=user.role in (Role.CLERK, Role.APPROVER) and r.status in ("requested", "cooling"),
    )


def _get(db: Session, request_id: int, scope: SupplierScope) -> BankChangeRequest:
    r = db.get(BankChangeRequest, request_id)
    if r is None or not scope.allows(r.supplier_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return r


def _fail(db: Session, e: bc.BankChangeError) -> HTTPException:
    db.rollback()
    return HTTPException(status.HTTP_403_FORBIDDEN if e.sod else status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))


@router.get("/checklist")
def checklist() -> dict[str, str]:
    return bc.CHECKLIST


@router.get("", response_model=list[ChangeOut])
def list_changes(scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> list[ChangeOut]:
    q = select(BankChangeRequest).order_by(BankChangeRequest.id.desc())
    if scope.supplier_id is not None:
        q = q.where(BankChangeRequest.supplier_id == scope.supplier_id)
    return [_out(db, r, scope.user) for r in db.scalars(q)]


@router.post("", response_model=ChangeOut, status_code=status.HTTP_201_CREATED)
def create(body: RequestIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> ChangeOut:
    try:
        r = bc.request_change(db, scope.user, body.account, body.ifsc, body.bank_name, body.reason)
    except bc.BankChangeError as e:
        raise _fail(db, e) from e
    return _out(db, r, scope.user)


@router.post("/{request_id}/propose", response_model=ChangeOut)
def propose(request_id: int, body: ProposeIn, scope: SupplierScope = Depends(get_scope),
            db: Session = Depends(get_db)) -> ChangeOut:
    r = _get(db, request_id, scope)
    try:
        bc.propose(db, r, scope.user, body.checklist, body.contact, body.notes)
    except bc.BankChangeError as e:
        raise _fail(db, e) from e
    return _out(db, r, scope.user)


@router.post("/{request_id}/approve", response_model=ChangeOut)
def approve(request_id: int, body: NoteIn, scope: SupplierScope = Depends(get_scope),
            db: Session = Depends(get_db)) -> ChangeOut:
    r = _get(db, request_id, scope)
    try:
        bc.approve(db, r, scope.user, body.note)
    except bc.BankChangeError as e:
        raise _fail(db, e) from e
    return _out(db, r, scope.user)


@router.post("/{request_id}/reject", response_model=ChangeOut)
def reject(request_id: int, body: NoteIn, scope: SupplierScope = Depends(get_scope),
           db: Session = Depends(get_db)) -> ChangeOut:
    r = _get(db, request_id, scope)
    try:
        bc.reject(db, r, scope.user, body.note)
    except bc.BankChangeError as e:
        raise _fail(db, e) from e
    return _out(db, r, scope.user)
