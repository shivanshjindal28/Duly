"""Tamper-evident audit chain: events recorded, chain verifies, edits and truncation detected."""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.core import audit, tamper
from app.core.ratelimit import limiter
from app.models import AuditEvent

CLERK = "asha.kulkarni@plantx.example"
AUDITOR = "meera.iyer@plantx.example"
KESAR = "invoices@kesar-spares.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def actions(db) -> list[str]:
    db.expire_all()
    return [a for (a,) in db.execute(select(AuditEvent.action).order_by(AuditEvent.id))]


def test_chain_records_and_verifies(client, db):
    login(client, CLERK)
    client.post("/api/auth/login", json={"email": CLERK, "password": "wrong"})
    acts = actions(db)
    assert "system.seeded" in acts and "auth.login" in acts and "auth.login_failed" in acts
    r = audit.verify(db)
    assert r.ok and r.head_signature_ok and r.events == len(acts)


def test_verify_endpoint_for_auditor_only(client):
    login(client, AUDITOR)
    body = client.get("/api/audit/verify").json()
    assert body["ok"] is True and body["head_signature_ok"] is True and body["public_key"]
    login(client, CLERK)
    assert client.get("/api/audit/verify").status_code == 403
    assert client.get("/api/audit/events").status_code == 403  # clerks only see one invoice's events
    login(client, KESAR)
    assert client.get("/api/audit/events?entity_type=invoice&entity_id=1").status_code == 403


def test_tamper_detected_then_restored(client, db):
    h = login(client, CLERK)  # make sure there is a matched-invoice event to tamper with
    from app.samples.invoice_pdf import render_invoice_pdf
    from tests.fixtures.invoices import seeded_invoice
    client.post("/api/invoices/upload", headers=h,
                files={"file": ("a.pdf", render_invoice_pdf(seeded_invoice(db, invoice_number="AUD-1")), "application/pdf")})

    result = tamper.tamper(db)
    r = audit.verify(db)
    assert not r.ok and r.broken_at_id == result["event_id"]
    assert "edited" in r.problem and r.expected_hash != r.stored_hash

    tamper.restore(db)
    assert audit.verify(db).ok


def test_truncation_detected_by_signed_head(db):
    last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    row = db.execute(text("SELECT * FROM audit_events WHERE id = :id"), {"id": last.id}).mappings().one()
    db.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": last.id})
    db.commit()
    try:
        r = audit.verify(db)
        assert not r.ok and "signed head" in r.problem
    finally:
        cols = ", ".join(row.keys())
        db.execute(text(f"INSERT INTO audit_events ({cols}) VALUES ({', '.join(':' + k for k in row.keys())})"),
                   dict(row))
        db.commit()
    assert audit.verify(db).ok


def test_rolled_back_action_leaves_no_event(client, db):
    h = login(client, CLERK)
    before = actions(db).count("field.reviewed")
    r = client.post("/api/invoices/1/review", headers=h, json={"field": "total", "value": "abc", "reason": "typo"})
    assert r.status_code == 422
    assert actions(db).count("field.reviewed") == before


def test_match_events_state_ai_did_not_decide(db):
    db.expire_all()
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "invoice.matched")).all()
    assert ev and all(e.after["ai_decided"] is False for e in ev)
