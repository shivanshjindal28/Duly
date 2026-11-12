"""Admin demo controls (only when DEMO_MODE=true): the business clock used for SLA timers,
escalation, cooling periods and MSME countdowns."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.workflow.approvals import escalate_overdue


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(_demo_only), Depends(require_roles(Role.ADMIN))])


class ClockOut(BaseModel):
    now: datetime
    offset_hours: float
    escalated: int = 0


class AdvanceIn(BaseModel):
    hours: float = Field(gt=0, le=24 * 120)


def _out(escalated: int = 0) -> ClockOut:
    return ClockOut(now=clock.now(), offset_hours=clock.offset().total_seconds() / 3600, escalated=escalated)


@router.get("/clock", response_model=ClockOut)
def get_clock() -> ClockOut:
    return _out()


@router.post("/clock/advance", response_model=ClockOut)
def advance(body: AdvanceIn, db: Session = Depends(get_db)) -> ClockOut:
    clock.set_offset(db, clock.offset() + timedelta(hours=body.hours))
    return _out(escalate_overdue(db))


@router.post("/clock/reset", response_model=ClockOut)
def reset(db: Session = Depends(get_db)) -> ClockOut:
    clock.set_offset(db, timedelta(0))
    return _out()
