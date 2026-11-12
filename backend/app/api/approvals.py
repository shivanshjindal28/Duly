"""Approval workflow endpoints: approver queue, approve / reject / send back / request info,
clerk override of a FLAG, and delegations. All rules live in app.workflow.approvals."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import SupplierScope, get_scope, require_roles
from app.models import Supplier, User
from app.models.base import as_utc
from app.workflow import approvals as wf

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ActionIn(BaseModel):
    comment: str = Field("", max_length=500)
    totp: str | None = Field(None, max_length=8)


class QueueItem(BaseModel):
    invoice_id: int
    invoice_number: str
    supplier_name: str | None
    invoice_date: date | None
    total: Decimal
    decision: str | None
    override: bool
    step_level: int
    step_title: str
    due_at: datetime | None
    overdue: bool
    escalated: bool
    can_act: bool
    reason: str | None
    via_delegation: bool
    mfa_required: bool


class DelegationIn(BaseModel):
    to_user_id: int
    days: int = Field(ge=1, le=30)
    reason: str = Field(max_length=200)


class DelegationOut(BaseModel):
    id: int
    from_name: str
    to_name: str
    starts_at: datetime
    ends_at: datetime
    reason: str
    active: bool


class ApproverOut(BaseModel):
    id: int
    full_name: str
    level: int


def _refuse(e: wf.ApprovalError) -> HTTPException:
    code = status.HTTP_403_FORBIDDEN if e.sod else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, {"message": str(e), "sod": e.sod, "mfa": e.mfa})


def _invoice(invoice_id: int, scope: SupplierScope, db: Session):
    from app.api.invoices import get_invoice_in_scope

    return get_invoice_in_scope(invoice_id, scope, db)


@router.get("/queue", response_model=list[QueueItem])
def queue(user: User = Depends(require_roles(Role.APPROVER)), db: Session = Depends(get_db)) -> list[QueueItem]:
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    now = clock.now()
    return [
        QueueItem(
            invoice_id=inv.id, invoice_number=inv.invoice_number, supplier_name=names.get(inv.supplier_id),
            invoice_date=inv.invoice_date, total=inv.total, decision=inv.decision,
            override=inv.override_justification is not None, step_level=step.level,
            step_title=wf.LEVEL_TITLE[step.level], due_at=step.due_at,
            overdue=bool(step.due_at and as_utc(step.due_at) < now), escalated=step.escalated_at is not None,
            can_act=auth.allowed, reason=auth.reason, via_delegation=auth.via_delegation_from is not None,
            mfa_required=wf.mfa_required(db, inv),
        )
        for inv, step, auth in wf.approver_queue(db, user)
    ]


def _act(fn, invoice_id: int, scope: SupplierScope, db: Session, *args):
    inv = _invoice(invoice_id, scope, db)
    try:
        fn(db, inv, scope.user, *args)
    except wf.ApprovalError as e:
        db.rollback()
        if e.sod:  # segregation-of-duties refusals are security events
            audit.queue(db, "security.sod_refused", "invoice", inv.id,
                        after={"action": fn.__name__, "reason": str(e)})
            db.commit()
        raise _refuse(e) from e
    return {"status": inv.status, "current_owner": inv.current_owner}


_approver = Depends(require_roles(Role.APPROVER, Role.CLERK))  # clerks get a clear SoD refusal, not a bare 403


@router.post("/invoices/{invoice_id}/approve", dependencies=[_approver])
def approve(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)):
    return _act(wf.approve, invoice_id, scope, db, body.comment, body.totp)


@router.post("/invoices/{invoice_id}/reject", dependencies=[Depends(require_roles(Role.APPROVER))])
def reject(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)):
    return _act(wf.reject, invoice_id, scope, db, body.comment)


@router.post("/invoices/{invoice_id}/clerk-reject", dependencies=[Depends(require_roles(Role.CLERK))])
def clerk_reject(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)):
    return _act(wf.clerk_reject, invoice_id, scope, db, body.comment)


@router.post("/invoices/{invoice_id}/send-back", dependencies=[Depends(require_roles(Role.APPROVER))])
def send_back(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)):
    return _act(wf.send_back, invoice_id, scope, db, body.comment)


@router.post("/invoices/{invoice_id}/request-info", dependencies=[Depends(require_roles(Role.APPROVER))])
def request_info(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    return _act(wf.request_info, invoice_id, scope, db, body.comment)


@router.post("/invoices/{invoice_id}/override", dependencies=[Depends(require_roles(Role.CLERK))])
def override(invoice_id: int, body: ActionIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)):
    return _act(wf.override_flag, invoice_id, scope, db, body.comment)


@router.get("/approvers", response_model=list[ApproverOut], dependencies=[Depends(require_roles(Role.APPROVER))])
def approvers(db: Session = Depends(get_db)) -> list[ApproverOut]:
    return [ApproverOut(id=u.id, full_name=u.full_name, level=u.approver_level)
            for u in db.scalars(select(User).where(User.role == Role.APPROVER).order_by(User.approver_level))]


@router.get("/delegations", response_model=list[DelegationOut])
def delegations(user: User = Depends(require_roles(Role.APPROVER)), db: Session = Depends(get_db)) -> list[DelegationOut]:
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.role == Role.APPROVER))}
    now = clock.now()
    return [DelegationOut(id=d.id, from_name=names[d.from_user_id], to_name=names[d.to_user_id], starts_at=d.starts_at,
                          ends_at=d.ends_at, reason=d.reason,
                          active=not d.revoked and as_utc(d.starts_at) <= now <= as_utc(d.ends_at))
            for d in wf.delegations_for(db, user)]


@router.post("/delegations", response_model=DelegationOut, status_code=status.HTTP_201_CREATED)
def create_delegation(body: DelegationIn, user: User = Depends(require_roles(Role.APPROVER)),
                      db: Session = Depends(get_db)) -> DelegationOut:
    try:
        d = wf.add_delegation(db, user, body.to_user_id, body.days, body.reason)
    except wf.ApprovalError as e:
        db.rollback()
        raise _refuse(e) from e
    return DelegationOut(id=d.id, from_name=user.full_name, to_name=db.get(User, d.to_user_id).full_name,
                         starts_at=d.starts_at, ends_at=d.ends_at, reason=d.reason, active=True)
