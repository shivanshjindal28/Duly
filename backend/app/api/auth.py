"""Login, logout, current user, and demo-mode persona login."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.passwords import hash_password, verify_password
from app.core.ratelimit import limiter
from app.core.rbac import PERMISSIONS
from app.core.security import clear_session, get_current_user, issue_session
from app.models import Supplier, User
from app.models.base import as_utc
from app.models.enums import Role

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID = "Invalid email or password"
# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class DemoLoginIn(BaseModel):
    email: str = Field(max_length=200)


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    msme_category: str


class MeOut(BaseModel):
    id: int
    email: str
    full_name: str
    title: str
    role: Role
    approver_level: int | None
    mfa_enabled: bool
    supplier: SupplierOut | None
    permissions: dict[str, list[str]]


class PersonaOut(BaseModel):
    email: str
    full_name: str
    title: str
    role: Role
    approver_level: int | None
    supplier_name: str | None


def _me(user: User) -> MeOut:
    s = user.supplier
    return MeOut(
        id=user.id, email=user.email, full_name=user.full_name, title=user.title, role=user.role,
        approver_level=user.approver_level, mfa_enabled=user.mfa_enabled,
        supplier=SupplierOut(id=s.id, code=s.code, name=s.name, msme_category=s.msme_category) if s else None,
        permissions=PERMISSIONS[Role(user.role)],
    )


def _find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def _require_demo() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.post("/login", response_model=MeOut)
@limiter.limit(lambda: get_settings().login_rate_limit)
def login(request: Request, response: Response, body: LoginIn, db: Session = Depends(get_db)) -> MeOut:
    settings = get_settings()
    now = datetime.now(UTC)
    user = _find_user(db, body.email)

    if user is None or not user.is_active:
        verify_password(_DUMMY_HASH, body.password)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID)

    locked_until = as_utc(user.locked_until)
    if locked_until and locked_until > now:
        minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account locked after {settings.lockout_threshold} failed attempts. Try again in {minutes} min.",
        )

    if not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= settings.lockout_threshold:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_logins = 0
            db.commit()
            raise HTTPException(
                status.HTTP_423_LOCKED,
                f"Account locked after {settings.lockout_threshold} failed attempts. "
                f"Try again in {settings.lockout_minutes} min.",
            )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _INVALID)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    issue_session(response, user, request)
    return _me(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    # get_current_user and this handler share the request's DB session (FastAPI caches get_db).
    user.token_version += 1  # revokes every outstanding session token for this user
    db.commit()
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(out)
    return out


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> MeOut:
    return _me(user)


@router.get("/demo-personas", response_model=list[PersonaOut], dependencies=[Depends(_require_demo)])
def demo_personas(db: Session = Depends(get_db)) -> list[PersonaOut]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    return [
        PersonaOut(email=u.email, full_name=u.full_name, title=u.title, role=u.role,
                   approver_level=u.approver_level, supplier_name=names.get(u.supplier_id))
        for u in users
    ]


@router.post("/demo-login", response_model=MeOut, dependencies=[Depends(_require_demo)])
@limiter.limit(lambda: get_settings().login_rate_limit)
def demo_login(request: Request, response: Response, body: DemoLoginIn, db: Session = Depends(get_db)) -> MeOut:
    """One-click persona login. Exists only when DEMO_MODE=true (404 otherwise)."""
    user = _find_user(db, body.email)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown demo persona")
    user.last_login_at = datetime.now(UTC)
    db.commit()
    issue_session(response, user, request)
    return _me(user)
