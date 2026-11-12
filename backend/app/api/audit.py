"""Audit trail endpoints: verify the hash chain, list events. Auditors and admins see all
events; clerks and approvers may read the events of one invoice (its timeline)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.models import AuditEvent, User

router = APIRouter(prefix="/audit", tags=["audit"])


class VerifyOut(BaseModel):
    ok: bool
    events: int
    head_id: int | None
    head_hash: str | None
    head_signature_ok: bool
    broken_at_id: int | None
    problem: str | None
    expected_hash: str | None
    stored_hash: str | None
    verified_at: datetime | None
    public_key: str
    algorithm: str = "SHA-256 hash chain, head signed with Ed25519"


class EventOut(BaseModel):
    id: int
    ts: datetime
    actor: str | None
    actor_role: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    before: dict | None
    after: dict | None
    ip: str | None
    prev_hash: str
    hash: str


@router.get("/verify", response_model=VerifyOut)
def verify(user: User = Depends(require_roles(Role.AUDITOR, Role.ADMIN)), db: Session = Depends(get_db)) -> VerifyOut:
    r = audit.verify(db)
    audit.queue(db, "audit.chain_verified", "audit", r.head_id, after={"ok": r.ok, "events": r.events,
                                                                         "broken_at": r.broken_at_id})
    db.commit()
    return VerifyOut(**r.__dict__, public_key=audit.public_key_b64())


@router.get("/events", response_model=list[EventOut])
def events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = Query(None, max_length=60),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_roles(Role.AUDITOR, Role.ADMIN, Role.CLERK, Role.APPROVER)),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    if user.role in (Role.CLERK, Role.APPROVER) and not (entity_type == "invoice" and entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only auditors and admins can browse the full audit trail")
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    rows = db.scalars(q).all()
    names = {u.id: u.full_name for u in db.scalars(select(User))}
    return [EventOut(id=e.id, ts=e.ts, actor=names.get(e.actor_user_id), actor_role=e.actor_role, action=e.action,
                     entity_type=e.entity_type, entity_id=e.entity_id, before=e.before, after=e.after, ip=e.ip,
                     prev_hash=e.prev_hash, hash=e.hash) for e in rows]
