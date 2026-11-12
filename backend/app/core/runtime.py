"""Runtime settings an admin can change in demo mode, persisted in app_settings so they survive
a restart: the AI mode override (the AI kill switch). Without an override, AI_MODE from the
environment applies."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings

AI_MODES = ("auto", "live", "cached", "offline")
_KEY = "ai_mode_override"
_env_default: str | None = None


def _remember_env_default() -> str:
    global _env_default
    if _env_default is None:
        _env_default = get_settings().ai_mode or "auto"
    return _env_default


def set_ai_mode(db: Session, mode: str | None) -> None:
    """Override AI_MODE (None = back to the environment's value). Commits."""
    from app.models import AppSetting

    env = _remember_env_default()
    row = db.get(AppSetting, _KEY)
    if mode is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(AppSetting(key=_KEY, value=mode))
    else:
        row.value = mode
    db.commit()
    get_settings().ai_mode = mode or env


def load_ai_mode(db: Session) -> None:
    """Apply a persisted override (called at startup and after a demo reset)."""
    from app.models import AppSetting

    env = _remember_env_default()
    row = db.get(AppSetting, _KEY)
    get_settings().ai_mode = row.value if row is not None and row.value in AI_MODES else env


def ai_override(db: Session) -> str | None:
    from app.models import AppSetting

    row = db.get(AppSetting, _KEY)
    return row.value if row is not None else None
