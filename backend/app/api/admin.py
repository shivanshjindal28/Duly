"""Admin demo controls (only when DEMO_MODE=true): the business clock used for SLA timers,
escalation, cooling periods and MSME countdowns; the AI mode switch; one-click demo reset;
the audit tamper demo."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.core.guard import global_budget
from app.core.ratelimit import limiter
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
    audit.queue(db, "demo.clock_advanced", "clock", None, before={"now": clock.now()}, after={"hours": body.hours})
    clock.set_offset(db, clock.offset() + timedelta(hours=body.hours))
    return _out(escalate_overdue(db))


@router.post("/clock/reset", response_model=ClockOut)
def reset(db: Session = Depends(get_db)) -> ClockOut:
    audit.queue(db, "demo.clock_reset", "clock", None,
                before={"offset_hours": clock.offset().total_seconds() / 3600})
    clock.set_offset(db, timedelta(0))
    return _out()


class AiModeIn(BaseModel):
    mode: str = Field(pattern="^(auto|live|cached|offline|default)$")  # default = back to .env AI_MODE


class AiModeOut(BaseModel):
    configured: str  # what the admin chose (or the environment's AI_MODE)
    effective: str  # live | cached | offline
    overridden: bool
    key_configured: bool
    cached_extractions: int


def _ai_mode_out(db: Session) -> AiModeOut:
    from app.ai.claude_extractor import CACHE_DIR
    from app.ai.extract import ai_mode_setting
    from app.core import runtime

    s = get_settings()
    return AiModeOut(configured=s.ai_mode or "auto", effective=ai_mode_setting(),
                     overridden=runtime.ai_override(db) is not None, key_configured=bool(s.anthropic_api_key),
                     cached_extractions=len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0)


@router.get("/ai-mode", response_model=AiModeOut)
def get_ai_mode(db: Session = Depends(get_db)) -> AiModeOut:
    return _ai_mode_out(db)


@router.post("/ai-mode", response_model=AiModeOut)
def set_ai_mode(body: AiModeIn, db: Session = Depends(get_db)) -> AiModeOut:
    """The AI switch: live (Claude API), cached (replay earlier AI readings, no network), offline
    (kill switch: OCR + rules only) or auto (live if an API key is configured)."""
    from app.ai.extract import ai_mode_setting
    from app.core import runtime

    if body.mode == "live" and not get_settings().anthropic_api_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Live AI needs ANTHROPIC_API_KEY in .env. Use cached or offline.")
    before = ai_mode_setting()
    audit.queue(db, "demo.ai_mode_changed", "settings", "ai_mode", before={"effective": before},
                after={"mode": body.mode})
    runtime.set_ai_mode(db, None if body.mode == "default" else body.mode)  # commits (and writes the event)
    return _ai_mode_out(db)


class ResetOut(BaseModel):
    counts: dict[str, int]
    seconds: float


@router.post("/reset-demo", response_model=ResetOut)
@limiter.limit("10/hour")
def reset_demo(request: Request, db: Session = Depends(get_db)) -> ResetOut:
    global_budget("reset-demo", 12)  # site-wide: one visitor cannot keep wiping everyone else's demo
    """Drop everything and reseed with the 90-day history (about 25 s). Signed-in users stay signed
    in (same ids). The AI mode switch is kept; the demo clock returns to real time."""
    import time

    from app.core import runtime
    from app.seed import reset_and_seed

    from app import demo_snapshot

    started = time.time()
    actor = db.info.get("audit_actor")
    override = runtime.ai_override(db)
    if demo_snapshot.available():  # hosted demo: back to the staged state saved at build time
        db.close()
        demo_snapshot.restore()
        clock.load_offset(db)
        counts = {"restored_snapshot": 1}
    else:
        counts = reset_and_seed(db, history=True)
    if override is not None:
        runtime.set_ai_mode(db, override)
    if actor is not None:
        audit.set_actor(db, *actor)
    audit.queue(db, "demo.reset", "database", None, after={"history": True, **counts})
    db.commit()
    return ResetOut(counts=counts, seconds=round(time.time() - started, 1))


@router.post("/tamper-demo")
@limiter.limit("20/hour")
def tamper_demo(request: Request, db: Session = Depends(get_db)) -> dict:
    global_budget("tamper-demo", 30)
    """Edit one audit row directly in the database (as an insider could), for the verify demo."""
    from app.core import tamper

    try:
        return tamper.tamper(db)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.post("/tamper-restore")
def tamper_restore(db: Session = Depends(get_db)) -> dict:
    from app.core import tamper

    try:
        return tamper.restore(db)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
