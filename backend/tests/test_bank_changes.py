"""D3 bank-detail fraud: BANK_MISMATCH blocks; maker-checker change with call-back and cooling."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core.crypto import decrypt_str
from app.core.ratelimit import limiter
from app.models import AuditEvent, Supplier
from app.samples.invoice_pdf import Line, render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

NAVRANG = "accounts@navrang-pack.example"
CLERK = "asha.kulkarni@plantx.example"
L1 = "rohan.mehta@plantx.example"
ADMIN = "sanjay.patil@plantx.example"
NEW_ACCOUNT, NEW_IFSC = "77778888999911", "NRMD0777777"
FULL_CHECKLIST = {"called_number_on_file": True, "confirmed_with_known_contact": True, "bank_proof_received": True}


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def test_s6_bank_change_end_to_end(client, db):
    # Scenario 6: an invoice arrives with a bank account that is not the one on record.
    spec = seeded_invoice(db, "Navrang Packaging Works", invoice_number="NPW-606", invoice_date=date(2026, 11, 6),
                          po_number="4500001013",
                          lines=[Line("PKG-FFS-50", "FFS bag 50 kg PE", "3923", D(500), "NOS", D("21.00"), D(18))])
    spec.bank_account, spec.bank_ifsc = NEW_ACCOUNT, NEW_IFSC
    h = login(client, NAVRANG)
    inv = client.post("/api/invoices/upload", headers=h,
                      files={"file": ("npw.pdf", render_invoice_pdf(spec), "application/pdf")}).json()
    bank = next(r for r in inv["match"]["reasons"] if r["code"] == "BANK_MISMATCH")
    assert inv["decision"] == "BLOCK" and NEW_ACCOUNT not in str(inv)  # masked everywhere
    assert bank["evidence"]["invoice_account"] == "XXXXXX9911"
    db.expire_all()
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "security.bank_mismatch_alert",
                                              AuditEvent.entity_id == str(inv["id"])))

    # 1. Supplier requests the change.
    r = client.post("/api/bank-changes", headers=h, json={"account": NEW_ACCOUNT, "ifsc": NEW_IFSC,
                                                          "bank_name": "Narmada Co-operative Bank (fictional)",
                                                          "reason": "Moved our main account to a new branch"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "requested" and req["new_account"] == "XXXXXX9911" and NEW_ACCOUNT not in str(req)
    assert client.post(f"/api/bank-changes/{req['id']}/approve", headers=h, json={}).status_code == 403

    # 2. Clerk (maker) must complete the call-back checklist.
    h = login(client, CLERK)
    bad = client.post(f"/api/bank-changes/{req['id']}/propose", headers=h,
                      json={"checklist": {"called_number_on_file": True}, "contact": "Hetal Shah"})
    assert bad.status_code == 422 and "call-back checklist" in bad.json()["detail"]
    ok = client.post(f"/api/bank-changes/{req['id']}/propose", headers=h,
                     json={"checklist": FULL_CHECKLIST, "contact": "Hetal Shah (owner)", "notes": "Called +91 landline on file"})
    assert ok.status_code == 200 and ok.json()["status"] == "cooling" and ok.json()["cooling_hours_left"] > 71
    assert client.post(f"/api/bank-changes/{req['id']}/approve", headers=h, json={}).status_code == 403  # maker != checker

    # 3. Cooling period: the checker cannot approve yet.
    h = login(client, L1)
    early = client.post(f"/api/bank-changes/{req['id']}/approve", headers=h, json={})
    assert early.status_code == 422 and "Cooling period" in early.json()["detail"]

    # 4. After 72 h the finance manager approves; the master changes and the invoice is re-checked.
    ha = login(client, ADMIN)
    try:
        client.post("/api/admin/clock/advance", headers=ha, json={"hours": 73})
        h = login(client, L1)
        done = client.post(f"/api/bank-changes/{req['id']}/approve", headers=h, json={"note": "Call-back verified"})
        assert done.status_code == 200 and done.json()["status"] == "approved"
        assert done.json()["approved_by"] == "Rohan Mehta" and done.json()["proposed_by"] == "Asha Kulkarni"
    finally:
        ha = login(client, ADMIN)
        client.post("/api/admin/clock/reset", headers=ha)

    db.expire_all()
    s = db.scalar(select(Supplier).where(Supplier.code == "V100102"))
    assert decrypt_str(s.bank_account_enc) == NEW_ACCOUNT and s.bank_ifsc == NEW_IFSC
    login(client, CLERK)
    after = client.get(f"/api/invoices/{inv['id']}").json()
    assert "BANK_MISMATCH" not in {x["code"] for x in after["match"]["reasons"]}
    assert after["match"]["trigger"].startswith("bank_change_approved")

    # Controls report C-06 now has activity and passes.
    login(client, "meera.iyer@plantx.example")
    c06 = next(c for c in client.get("/api/reports/controls").json()["controls"] if c["id"] == "C-06")
    assert c06["result"] == "effective" and c06["population"] >= 1


def test_supplier_sees_only_own_requests_and_validation(client):
    h = login(client, "invoices@kesar-spares.example")
    assert all(r["supplier_name"] == "Kesar Engineering Spares" for r in client.get("/api/bank-changes").json())
    bad = client.post("/api/bank-changes", headers=h, json={"account": "12", "ifsc": "BAD", "bank_name": "X Bank",
                                                            "reason": "testing"})
    assert bad.status_code == 422
    h = login(client, CLERK)
    assert client.post("/api/bank-changes", headers=h, json={"account": "123456789012", "ifsc": "ABCD0123456",
                                                             "bank_name": "X Bank", "reason": "for supplier"}).status_code == 422
