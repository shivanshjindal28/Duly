"""Stores posts GR/SES; waiting invoices are re-matched automatically (scenario 4)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.ratelimit import limiter
from app.samples.invoice_pdf import Line, render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

STORES = "imran.shaikh@plantx.example"
NAVRANG = "accounts@navrang-pack.example"
CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def po_line_id(client, po_number, idx=0):
    po = next(p for p in client.get("/api/stores/open-pos").json() if p["po_number"] == po_number)
    return po["lines"][idx]["id"], po


def test_s4_missing_gr_auto_released_when_stores_posts_gr(client, db):
    # Supplier invoices FFS bags before the goods arrive.
    spec = seeded_invoice(db, "Navrang Packaging Works", invoice_number="NPW-411", invoice_date=date(2026, 11, 10),
                          po_number="4500001004",
                          lines=[Line("PKG-FFS-25", "FFS bag 25 kg PE", "3923", D(20000), "NOS", D("14.50"), D(18))])
    from app.core.crypto import decrypt_str
    from app.models import Supplier
    from sqlalchemy import select
    s = db.scalar(select(Supplier).where(Supplier.code == "V100102"))
    spec.bank_account, spec.bank_ifsc = decrypt_str(s.bank_account_enc), s.bank_ifsc
    h = login(client, NAVRANG)
    inv = client.post("/api/invoices/upload", headers=h,
                      files={"file": ("npw.pdf", render_invoice_pdf(spec), "application/pdf")}).json()
    assert inv["decision"] == "BLOCK" and [r["code"] for r in inv["match"]["reasons"]] == ["MISSING_GR"]
    assert inv["rail"] == 1  # ordered, not yet received

    # Stores receives the goods.
    h = login(client, STORES)
    line_id, po = po_line_id(client, "4500001004")
    assert D(po["lines"][0]["received"]) == 0 and D(po["lines"][0]["open"]) == 20000
    r = client.post("/api/stores/goods-receipts", headers=h,
                    json={"po_number": "4500001004", "lines": [{"po_line_id": line_id, "qty": "20000"}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["rechecked"] == 1 and body["released"] == 1
    assert "released" in body["message"] and "NPW-411" not in body["message"]  # stores never sees invoices

    # The invoice was released without anyone touching it.
    login(client, CLERK)
    after = client.get(f"/api/invoices/{inv['id']}").json()
    assert after["decision"] == "APPROVE" and after["status"] == "pending_approval"
    assert after["match"]["trigger"] == f"gr_posted:{body['number']}"
    assert after["rail"] == 3


def test_over_receipt_rejected(client):
    h = login(client, STORES)
    line_id, po = po_line_id(client, "4500001002")  # 2000 KG ordered, 2000 already received
    r = client.post("/api/stores/goods-receipts", headers=h,
                    json={"po_number": "4500001002", "lines": [{"po_line_id": line_id, "qty": "1"}]})
    assert r.status_code == 422 and "exceed the ordered" in r.json()["detail"]


def test_goods_receipt_on_service_po_rejected_and_ses_posted(client):
    h = login(client, STORES)
    line_id, po = po_line_id(client, "4500001007")  # freight: 10 trips x 38,000, 152,000 accepted
    r = client.post("/api/stores/goods-receipts", headers=h,
                    json={"po_number": "4500001007", "lines": [{"po_line_id": line_id, "qty": "1"}]})
    assert r.status_code == 422 and "service entry sheet" in r.json()["detail"]
    r = client.post("/api/stores/service-entries", headers=h,
                    json={"po_number": "4500001007", "po_line_id": line_id, "value": "38000.00",
                          "description": "Trip 5 delivered"})
    assert r.status_code == 201 and r.json()["kind"] == "SES"
    line = po_line_id(client, "4500001007")[1]["lines"][0]
    assert D(line["received"]) == D("190000.00")


def test_closed_po_and_roles(client):
    h = login(client, STORES)
    r = client.post("/api/stores/goods-receipts", headers=h,
                    json={"po_number": "4500000990", "lines": [{"po_line_id": 1, "qty": "1"}]})
    assert r.status_code == 422 and "closed" in r.json()["detail"]
    assert client.get("/api/invoices").status_code == 403  # stores never touches invoices
    login(client, CLERK)
    assert client.get("/api/stores/open-pos").status_code == 403
