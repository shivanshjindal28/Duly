"""Server-side RBAC and row-level supplier scoping (spec C1 acceptance)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.models import Invoice, Supplier

KESAR = "invoices@kesar-spares.example"  # supplier A
NAVRANG = "accounts@navrang-pack.example"  # supplier B


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


@pytest.fixture(scope="module")
def two_invoices():
    from app.core.db import SessionLocal

    db = SessionLocal()
    kesar = db.scalar(select(Supplier).where(Supplier.name == "Kesar Engineering Spares"))
    navrang = db.scalar(select(Supplier).where(Supplier.name == "Navrang Packaging Works"))
    a = Invoice(supplier_id=kesar.id, invoice_number="KES-T-001", invoice_number_norm="KEST1", total=Decimal("1180.00"))
    b = Invoice(supplier_id=navrang.id, invoice_number="NAV-T-001", invoice_number_norm="NAVT1", total=Decimal("2360.00"))
    db.add_all([a, b])
    db.commit()
    ids = {"a": a.id, "b": b.id}
    yield ids
    db.delete(db.get(Invoice, ids["a"]))
    db.delete(db.get(Invoice, ids["b"]))
    db.commit()
    db.close()


def as_user(client, email):
    r = client.post("/api/auth/demo-login", json={"email": email})
    assert r.status_code == 200
    return client


def test_supplier_cannot_read_other_suppliers_invoice(client, two_invoices):
    as_user(client, KESAR)
    assert client.get(f"/api/invoices/{two_invoices['a']}").status_code == 200
    # Supplier A asking for supplier B's invoice gets 404, not 403: existence is not revealed.
    r = client.get(f"/api/invoices/{two_invoices['b']}")
    assert r.status_code == 404


def test_supplier_list_contains_only_own_invoices(client, two_invoices):
    as_user(client, KESAR)
    ids = {i["id"] for i in client.get("/api/invoices").json()}
    assert two_invoices["a"] in ids
    assert two_invoices["b"] not in ids


def test_other_supplier_sees_only_theirs(client, two_invoices):
    as_user(client, NAVRANG)
    assert client.get(f"/api/invoices/{two_invoices['a']}").status_code == 404
    assert client.get(f"/api/invoices/{two_invoices['b']}").status_code == 200


@pytest.mark.parametrize("email", ["asha.kulkarni@plantx.example", "meera.iyer@plantx.example", "rohan.mehta@plantx.example"])
def test_staff_see_all_suppliers(client, two_invoices, email):
    as_user(client, email)
    ids = {i["id"] for i in client.get("/api/invoices").json()}
    assert {two_invoices["a"], two_invoices["b"]} <= ids


def test_stores_cannot_touch_invoices(client, two_invoices):
    as_user(client, "imran.shaikh@plantx.example")
    assert client.get("/api/invoices").status_code == 403
    assert client.get(f"/api/invoices/{two_invoices['a']}").status_code == 403


def test_anonymous_gets_401(client):
    assert client.get("/api/invoices").status_code == 401


def test_each_persona_gets_a_different_shell(client):
    roles = set()
    for email in [KESAR, "asha.kulkarni@plantx.example", "rohan.mehta@plantx.example", "meera.iyer@plantx.example"]:
        roles.add(as_user(client, email).get("/api/auth/me").json()["role"])
    assert roles == {"supplier", "clerk", "approver", "auditor"}
