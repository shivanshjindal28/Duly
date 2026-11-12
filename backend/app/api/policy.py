"""Policy (tolerances, approval limits, thresholds): staff read it; an admin changes it as a new version."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import Role
from app.core.security import get_current_user, require_roles
from app.models import User
from app.workflow import policy_admin as pa

router = APIRouter(prefix="/policy", tags=["policy"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


class ChangeIn(BaseModel):
    changes: dict[str, float]
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
def change_policy(body: ChangeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        pa.change(db, user, body.changes, body.reason)
    except pa.PolicyError as e:
        db.rollback()
        raise HTTPException(status.HTTP_403_FORBIDDEN if user.role != Role.ADMIN else status.HTTP_422_UNPROCESSABLE_CONTENT,
                            str(e)) from e
    return _out(db, user)
