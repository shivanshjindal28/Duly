"""Abuse protection for the public demo: body size, trusted client IP, upload limits, attachment count."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.seed import DEMO_PASSWORD

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


def _clerk(client) -> dict:
    assert client.post("/api/auth/login", json={"email": CLERK, "password": DEMO_PASSWORD}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def test_oversized_body_is_refused_before_it_is_read(client, monkeypatch):
    h = _clerk(client)
    monkeypatch.setattr(get_settings(), "max_request_bytes", 2048)
    r = client.post("/api/invoices/upload", headers=h, files={"file": ("big.pdf", b"%PDF-" + b"0" * 10_000, "application/pdf")})
    assert r.status_code == 413
    assert "larger than" in r.json()["detail"]


def test_client_ip_comes_from_our_proxy_hop_not_the_callers_header(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "debug_proxy_chain", True)
    monkeypatch.setattr(s, "trusted_proxy_hops", 2)
    # The caller typed 6.6.6.6; our proxy recorded the real 1.2.3.4 and our edge appended 10.0.0.1.
    r = client.get("/api/health/chain", headers={"X-Forwarded-For": "6.6.6.6, 1.2.3.4, 10.0.0.1"})
    assert r.json()["client"] == "1.2.3.4"
    monkeypatch.setattr(s, "debug_proxy_chain", False)
    assert client.get("/api/health/chain").status_code == 404  # off by default


def test_uploads_are_rate_limited_per_client(client, monkeypatch):
    h = _clerk(client)
    monkeypatch.setattr(get_settings(), "upload_rate_limit", "2/minute")
    send = lambda: client.post("/api/invoices/upload", headers=h, files={"file": ("x.txt", b"not an invoice", "text/plain")})
    assert send().status_code == 422  # refused file, but it counts
    assert send().status_code == 422
    assert send().status_code == 429


def test_compose_takes_at_most_five_attachments(client):
    h = _clerk(client)
    files = [("files", (f"a{i}.pdf", b"%PDF-1.4", "application/pdf")) for i in range(6)]
    r = client.post("/api/inbox/compose", headers=h, data={"from_addr": "x@example.com"}, files=files)
    assert r.status_code == 422 and "at most 5" in r.json()["detail"]


def test_api_docs_can_be_switched_off(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "api_docs", False)
    c = TestClient(create_app())
    assert c.get("/api/docs").status_code == 404
    assert c.get("/api/openapi.json").status_code == 404


def test_health_reports_the_demo_reset_interval(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_auto_reset_minutes", 60)
    assert client.get("/api/health").json()["demo_reset_minutes"] == 60
