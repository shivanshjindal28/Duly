"""Hosted demo: 'Reset demo data' restores the snapshot saved after staging, and the audit chain stays valid."""
from __future__ import annotations

import shutil

import pytest
from sqlalchemy import func, select

from app import demo_snapshot
from app.core.ratelimit import limiter
from app.models import Invoice, Supplier

ADMIN = "sanjay.patil@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def test_reset_restores_snapshot(client, db):
    try:
        demo_snapshot.save()
        assert demo_snapshot.available()
        before = db.scalar(select(func.count()).select_from(Invoice))
        s = db.scalar(select(Supplier))
        db.add(Invoice(supplier_id=s.id, invoice_number="SNAP-1", invoice_number_norm="SNAP1", current_owner="x"))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Invoice)) == before + 1

        h = login(client, ADMIN)
        r = client.post("/api/admin/reset-demo", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["counts"] == {"restored_snapshot": 1}
        db.expire_all()
        assert db.scalar(select(func.count()).select_from(Invoice)) == before
        assert db.scalar(select(Invoice).where(Invoice.invoice_number == "SNAP-1")) is None
        login(client, "meera.iyer@plantx.example")
        v = client.get("/api/audit/verify").json()
        assert v["ok"] is True  # the reset event was appended to the restored chain
    finally:
        shutil.rmtree(demo_snapshot.SNAP_DIR, ignore_errors=True)
    assert not demo_snapshot.available()
