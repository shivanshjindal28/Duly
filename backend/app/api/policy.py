"""Policy (tolerances, approval limits, thresholds): staff read it; an admin changes it as a new version."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import jobs
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.enums import Role
from app.core.security import get_current_user, require_roles
from app.models import User
from app.models.base import as_utc
from app.workflow import policy_admin as pa
from app.workflow import retention as ret

router = APIRouter(prefix="/policy", tags=["policy"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


class ChangeIn(BaseModel):
    changes: dict[str, float] = Field(max_length=60)
    reason: str = Field(max_length=300)


class VersionOut(BaseModel):
    version: int
    reason: str
    active: bool
    created_at: datetime
    created_by: str | None
    changed: dict[str, dict]


def _out(db: Session, user: User) -> dict:
    cur = pa.active(db)
    users = {u.id: u.full_name for u in db.scalars(select(User))}
    return {
        "version": cur.version,
        "can_edit": user.role == Role.ADMIN,
        "fields": [{"path": f.path, "section": f.section, "label": f.label, "unit": f.unit, "min": f.lo, "max": f.hi,
                    "integer": f.integer, "help": f.help} for f in pa.FIELDS],
        "values": pa.values(cur.data),
        "statutory": [{"label": label, "unit": unit, "value": pa._get(cur.data, path)} for path, label, unit in pa.STATUTORY],
        "history": [VersionOut(version=p.version, reason=p.name, active=p.is_active, created_at=p.created_at,
                               created_by=users.get(p.created_by_user_id) if p.created_by_user_id else "System (seed)",
                               changed=changed).model_dump()
                    for p, changed in pa.history(db)],
    }


@router.get("")
def get_policy(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _out(db, user)


@router.post("")
@limiter.limit("30/hour")
def change_policy(request: Request, body: ChangeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        pa.change(db, user, body.changes, body.reason)
    except pa.PolicyError as e:
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN if user.role != Role.ADMIN else status.HTTP_422_UNPROCESSABLE_CONTENT,
                            str(e)) from e
    return _out(db, user)


def _retention_out(db: Session, user: User) -> dict:
    from app.models import Document

    p = ret.plan(db)
    oldest = db.scalar(select(func.min(Document.uploaded_at)).where(Document.purged_at.is_(None)))
    years = p.cutoffs.settings["documents_years"]
    return {
        "settings": p.cutoffs.settings,
        "cutoffs": {"documents_before": p.cutoffs.documents_before, "chats_before": p.cutoffs.chats_before,
                    "email_bodies_before": p.cutoffs.email_bodies_before},
        "due": {"documents": len(p.document_ids), "documents_kept_open_invoice": p.documents_kept_open,
                "chats": len(p.chat_ids), "email_texts": len(p.email_ids)},
        "oldest_document": oldest,
        "oldest_document_due": (as_utc(oldest) + timedelta(days=round(365.25 * years))) if oldest else None,
        "never_deleted": ["Audit trail", "Invoice data and line items", "Payments and UTRs", "Extraction and review log",
                          "File hash and look-alike fingerprint (duplicate detection keeps working)"],
        "last_run": _last_run(db),
        "can_run": user.role == Role.ADMIN,
    }


def _last_run(db: Session) -> dict | None:
    from app.models import AuditEvent

    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "retention.run").order_by(AuditEvent.id.desc()).limit(1))
    return {"at": ev.ts, "counts": ev.after} if ev else None


@router.get("/retention")
def retention(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return _retention_out(db, user)


@router.post("/retention/run")
@limiter.limit("10/hour")
def run_retention(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can run data retention.")
    result = jobs.enqueue("data_retention", ret.run, db, f"run by {user.full_name}").result
    return {"result": result, **_retention_out(db, user)}
