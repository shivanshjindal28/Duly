"""Authentication, sessions, CSRF, lockout, rate limiting and demo-mode gating."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.models import User
from app.seed import DEMO_PASSWORD

CLERK = "asha.kulkarni@plantx.example"
SUPPLIER = "invoices@kesar-spares.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


def login(client, email, password=DEMO_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def test_login_sets_secure_cookies_and_me_works(client):
    r = login(client, CLERK)
    assert r.status_code == 200
    assert r.json()["role"] == "clerk"
    set_cookie = r.headers.get_list("set-cookie")
    session = next(c for c in set_cookie if c.startswith("duly_session="))
    assert "HttpOnly" in session and "SameSite=strict" in session
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == CLERK
    assert me.json()["permissions"]["cannot"]  # role restrictions are reported


def test_email_is_case_insensitive(client):
    assert login(client, CLERK.upper()).status_code == 200


def test_wrong_password_and_unknown_user_get_same_generic_error(client):
    a = login(client, CLERK, "wrong-password")
    b = login(client, "nobody@plantx.example", "wrong-password")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == "Invalid email or password"


def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_token_rejected(client):
    login(client, CLERK)
    token = client.cookies.get("duly_session")
    client.cookies.set("duly_session", token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
    assert client.get("/api/auth/me").status_code == 401


def test_state_change_without_csrf_header_is_refused(client):
    login(client, CLERK)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 204


def test_logout_revokes_old_token(client):
    login(client, CLERK)
    old = client.cookies.get("duly_session")
    assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 204
    client.cookies.set("duly_session", old)
    assert client.get("/api/auth/me").status_code == 401


def test_lockout_after_five_failures(client, db):
    email = "nikhil.verma@plantx.example"
    try:
        for _ in range(4):
            assert login(client, email, "bad").status_code == 401
        r = login(client, email, "bad")
        assert r.status_code == 423 and "locked" in r.json()["detail"]
        # Even the right password is refused while locked.
        assert login(client, email, DEMO_PASSWORD).status_code == 423
    finally:
        user = db.scalar(select(User).where(User.email == email))
        user.locked_until = None
        user.failed_logins = 0
        db.commit()
    assert login(client, email).status_code == 200


def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit", "3/minute")
    codes = [login(client, "nobody@plantx.example", "x").status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429


def test_demo_personas_and_demo_login(client):
    personas = client.get("/api/auth/demo-personas").json()
    assert len(personas) == 14
    assert {p["role"] for p in personas} == {"supplier", "clerk", "approver", "stores", "auditor", "admin"}
    r = client.post("/api/auth/demo-login", json={"email": SUPPLIER})
    assert r.status_code == 200
    assert r.json()["supplier"]["name"] == "Kesar Engineering Spares"


def test_demo_endpoints_hidden_when_demo_mode_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.get("/api/auth/demo-personas").status_code == 404
    assert client.post("/api/auth/demo-login", json={"email": CLERK}).status_code == 404
