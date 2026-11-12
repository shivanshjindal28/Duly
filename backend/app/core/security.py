"""Sessions, CSRF and the authentication / RBAC / supplier-scoping dependencies.

Session: a JWT (HS256, server secret) in the httpOnly, SameSite=strict cookie `duly_session`.
It carries the user id, role, the user's token_version (bumped on logout to revoke) and a
random CSRF token. The same CSRF token is set in the readable cookie `duly_csrf`; every
state-changing request must echo it in the `X-CSRF-Token` header (signed double submit).
Sessions expire after SESSION_MINUTES of inactivity and slide forward on use.
"""
from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.models import User
from app.core.enums import Role

SESSION_COOKIE = "duly_session"
CSRF_COOKIE = "duly_csrf"
CSRF_HEADER = "X-CSRF-Token"
_ALG = "HS256"
_REFRESH_AFTER = timedelta(minutes=5)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _now() -> datetime:
    return datetime.now(UTC)


def issue_session(response: Response, user: User, request: Request, csrf: str | None = None) -> None:
    """Set the session and CSRF cookies for `user`."""
    settings = get_settings()
    csrf = csrf or secrets.token_urlsafe(32)
    now = _now()
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "tv": user.token_version,
        "csrf": csrf,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_minutes)).timestamp()),
    }
    token = jwt.encode(claims, settings.resolved_secret_key, algorithm=_ALG)
    secure = request.url.scheme == "https"
    max_age = settings.session_minutes * 60
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="strict",
                        secure=secure, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="strict",
                        secure=secure, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _unauthorized(detail: str = "Not signed in") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail)


def get_current_user(request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    """Authenticate the request from the session cookie; enforce CSRF on unsafe methods."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()
    try:
        claims = jwt.decode(token, get_settings().resolved_secret_key, algorithms=[_ALG])
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("Session expired, please sign in again") from e
    except jwt.InvalidTokenError as e:
        raise _unauthorized() from e

    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active or user.token_version != claims.get("tv"):
        raise _unauthorized()

    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, claims["csrf"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")

    audit.set_actor(db, user.id, user.role, request.client.host if request.client else None)

    # Sliding expiry: re-issue the cookie when the token is older than a few minutes.
    issued = datetime.fromtimestamp(claims["iat"], UTC)
    if _now() - issued > _REFRESH_AFTER:
        issue_session(response, user, request, csrf=claims["csrf"])
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Dependency factory: allow only the given roles (server-side RBAC)."""
    allowed = set(roles)

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not allowed to do this")
        return user

    return _dep


@dataclass(frozen=True)
class SupplierScope:
    """Row-level scope for the current user. supplier_id=None means all suppliers (staff)."""

    user: User
    supplier_id: int | None

    def allows(self, supplier_id: int | None) -> bool:
        return self.supplier_id is None or supplier_id == self.supplier_id


def get_scope(user: User = Depends(get_current_user)) -> SupplierScope:
    """The single place supplier row scoping is decided. Suppliers see only their own rows."""
    if user.role == Role.SUPPLIER:
        if user.supplier_id is None:  # misconfigured supplier account: see nothing
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Supplier account is not linked to a supplier")
        return SupplierScope(user, user.supplier_id)
    return SupplierScope(user, None)
