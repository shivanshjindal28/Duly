"""Units and currencies end to end: receiving in pack units, billing in boxes, an EUR import invoice."""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.models import GRLine

DEMO = Path(__file__).resolve().parents[2] / "demo"
MAN = {s["id"]: s for s in json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))["scenarios"]}
CLERK, STORES, L1, L2 = ("asha.kulkarni@plantx.example", "imran.shaikh@plantx.example",
                         "rohan.mehta@plantx.example", "kavita.desai@plantx.example")


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def upload(client, sid):
    s = MAN[sid]
    h = login(client, s["upload_as"])
    r = client.post("/api/invoices/upload", headers=h,
                    files={"file": (Path(s["file"]).name, (DEMO / s["file"]).read_bytes(), s["mime"])})
    assert r.status_code == 201, r.text
    return r.json()


def test_stores_receives_in_boxes_and_s14_bills_in_boxes(client, db):
    h = login(client, STORES)
    po = next(p for p in client.get("/api/stores/open-pos").json() if p["po_number"] == "4500001019")
    ln = po["lines"][0]
    assert {"NOS", "BOX", "DOZ"} <= set(ln["units"]) and "1 BOX = 10 NOS" in ln["packs"]
    r = client.post("/api/stores/goods-receipts", headers=h, json={
        "po_number": "4500001019", "lines": [{"po_line_id": ln["id"], "qty": "3", "uom": "BOX"}]})
    assert r.status_code == 201, r.text
    gr_line = db.scalar(select(GRLine).where(GRLine.po_line_id == ln["id"]).order_by(GRLine.id.desc()))
    assert gr_line.qty == D(30) and gr_line.uom == "NOS" and gr_line.entered_qty == D(3) and gr_line.entered_uom == "BOX"
    bad = client.post("/api/stores/goods-receipts", headers=h, json={
        "po_number": "4500001019", "lines": [{"po_line_id": ln["id"], "qty": "1", "uom": "KG"}]})
    assert bad.status_code == 422 and "cannot be converted" in bad.json()["detail"]

    inv = upload(client, "S14")  # 12 BOX at Rs 4,500 = 120 NOS at Rs 450 (180 received now)
    assert inv["decision"] == "APPROVE" and inv["status"] == "pending_approval"
    row = inv["match"]["matrix"][0]
    assert D(str(row["invoice_qty"])) == 120 and row["uom"] == "NOS" and row["invoice_uom"] == "BOX"
    assert D(str(row["invoice_price"])) == D("450.00")
    login(client, CLERK)
    sap = client.get(f"/api/invoices/{inv['id']}/sap-preview").json()["posting"]["payload"]
    item = sap["to_SuplrInvcItemPurOrdRef"]["results"][0]
    assert item["QuantityInPurchaseOrderUnit"] == "120.000" and item["PurchaseOrderQuantityUnit"] == "NOS"


def _approve(client, email, inv_id):
    h = login(client, email)
    u = client.get("/api/auth/mfa-setup").json()["otpauth_uri"]
    r = client.post(f"/api/approvals/invoices/{inv_id}/approve", headers=h,
                    json={"comment": "ok", "totp": pyotp.parse_uri(u).now()})
    assert r.status_code == 200, r.text


def test_s13_eur_import_inr_limits_payment_and_sap(client, db):
    inv = upload(client, "S13")
    assert inv["currency"] == "EUR" and D(inv["total"]) == D("19250.00")
    assert D(inv["total_inr"]) == D("2006042.50")  # EUR 104.21 per the policy table
    assert [s["level"] for s in inv["workflow"]["steps"]] == [1, 2] and inv["workflow"]["mfa_required"]
    codes = {r["code"] for r in inv["match"]["reasons"]}
    assert not codes & {"GSTIN_INVALID", "TAX_MISMATCH", "BILL_TO_MISMATCH", "INVOICE_NO_INVALID"}

    login(client, CLERK)
    sap = client.get(f"/api/invoices/{inv['id']}/sap-preview").json()["posting"]
    assert sap["payload"]["DocumentCurrency"] == "EUR"
    assert sap["payload"]["to_SuplrInvcItemPurOrdRef"]["results"][0]["TaxCode"] == "M0"
    assert any("OB08" in w for w in sap["warnings"])

    _approve(client, L1, inv["id"])
    _approve(client, L2, inv["id"])
    login(client, L1)
    run = client.get("/api/payments/run").json()
    item = next(i for i in run["items"] if i["invoice_id"] == inv["id"])
    assert item["currency"] == "EUR" and D(item["gross"]) == D("19250.00") and D(item["gross_inr"]) == D("2006042.50")
    assert item["tds_section"] == "none" and not item["msme"]

    # The rate is policy data: a new rate changes the INR value on the next match, not the EUR amounts.
    admin = login(client, "sanjay.patil@plantx.example")
    r = client.post("/api/policy", headers=admin, json={"changes": {"fx.rates.EUR": 92}, "reason": "Treasury rate update test"})
    assert r.status_code == 200, r.text
    r = client.post("/api/policy", headers=admin, json={"changes": {"fx.rates.EUR": 90}, "reason": "Restore the demo rate"})
    assert r.status_code == 200
