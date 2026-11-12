"""Supplier portal: own data only, plain-language to-dos with exact credit amounts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.ratelimit import limiter
from app.samples.invoice_pdf import Line, render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

KESAR = "invoices@kesar-spares.example"
NAVRANG = "accounts@navrang-pack.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def test_supplier_sees_what_to_do_with_credit_amount(client, db):
    h = login(client, KESAR)
    spec = seeded_invoice(db, invoice_number="KES/26-27/0099", invoice_date=date(2026, 11, 10), po_number="4500001003",
                          lines=[Line("BRG-6205", "Ball bearing 6205 2RS", "8482", D(100), "NOS", D("450.00"), D(18))])
    inv = client.post("/api/invoices/upload", headers=h,
                      files={"file": ("k.pdf", render_invoice_pdf(spec), "application/pdf")}).json()
    p = client.get("/api/portal").json()
    assert p["supplier_name"] == "Kesar Engineering Spares" and p["msme_eligible"] is True
    mine = next(i for i in p["invoices"] if i["id"] == inv["id"])
    assert mine["stage"] == "stage.on_hold" and mine["expected_payment"] is None
    todo = next(t for t in mine["todos"] if t["code"] == "QTY_EXCEEDS_GR")
    # Excess beyond received/open quantity, credited at the PO price plus 18% GST.
    excess = D(todo["params"]["excess"])
    assert todo["you_act"] and D(todo["params"]["credit"]) == (excess * D("450") * D("1.18")).quantize(D("0.01"))
    assert mine["msme_due_date"] and mine["msme_days_left"] is not None


def test_portal_is_supplier_only_and_scoped(client):
    login(client, NAVRANG)
    p = client.get("/api/portal").json()
    assert all("KES" not in i["invoice_number"] for i in p["invoices"])
    login(client, "asha.kulkarni@plantx.example")
    assert client.get("/api/portal").status_code == 403
