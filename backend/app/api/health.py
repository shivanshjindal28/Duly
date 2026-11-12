"""Health and system-status endpoint (public, no secrets)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.core.db import get_db
from app.models import Policy

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        policy = db.scalar(select(Policy).where(Policy.is_active.is_(True)))
    except Exception:  # noqa: BLE001 - report, never crash the health check
        db_ok, policy = False, None
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "db": "ok" if db_ok else "error",
        "demo_mode": settings.demo_mode,
        "ai_mode": "live" if settings.anthropic_api_key else "offline",
        "policy_version": policy.version if policy else None,
    }
