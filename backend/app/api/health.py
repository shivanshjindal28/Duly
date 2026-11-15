"""Health and system-status endpoint (public, no secrets)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import __version__
from app.ai.extract import ai_mode_setting
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
        "ai_mode": ai_mode_setting(),
        "ai_model": settings.anthropic_model if ai_mode_setting() != "offline" else None,
        "policy_version": policy.version if policy else None,
        # Public demo: the shared data is put back to the staged state this often (0 = never).
        "demo_reset_minutes": settings.demo_auto_reset_minutes if settings.demo_mode else 0,
    }


@router.get("/health/chain")
def proxy_chain(request: Request) -> dict:
    """Setup aid (off by default): shows the X-Forwarded-For chain this request arrived with, so
    TRUSTED_PROXY_HOPS can be set for the hosting proxies. Only echoes the caller's own request."""
    if not get_settings().debug_proxy_chain:
        raise HTTPException(404, "Not Found")
    return {"x_forwarded_for": request.headers.get("x-forwarded-for"), "client": request.client.host if request.client else None,
            "x_real_ip": request.headers.get("x-real-ip"), "cf_connecting_ip": request.headers.get("cf-connecting-ip"),
            "true_client_ip": request.headers.get("true-client-ip")}
