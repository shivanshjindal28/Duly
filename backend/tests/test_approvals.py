"""Approval workflow (spec C4): DoA, touchless P-01, MFA step-up, SoD, overrides, SLA, delegation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pyotp
import pytest
from sqlalchemy import select

from app.core.crypto import decrypt_str
from app.core.ratelimit import limiter
from app.models import User
from app.samples.invoice_pdf import Line, render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

CLERK = "asha.kulkarni@plantx.example"
L1 = "rohan.mehta@plantx.example"
L2 = "kavita.desai@plantx.example"
ADMIN = "sanjay.patil@plantx.example"
SUPPLIER_EMAIL = {
    "Sahyadri Catalysts & Additives Ltd": "billing@sahyadri-catalysts.example",
    "Kesar Engineering Spares": "invoices@kesar-spares.example",
    "Konkan Bulk Carriers": "freight@konkan-bulk.example",
    "Dakshin Calibration Labs": "lab@dakshin-cal.example",
}


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def totp(db, email) -> str:
    u = db.scalar(select(User).where(User.email == email))
    return pyotp.TOTP(decrypt_str(u.mfa_secret_enc)).now()


def upload(client, db, supplier: str, number: str, po: str, lines: list[Line], **kw) -> dict:
    spec = seeded_invoice(db, supplier, invoice_number=number, invoice_date=date(2026, 11, 9), po_number=po,
                          lines=lines, **kw)
    h = login(client, SUPPLIER_EMAIL[supplier])
    r = client.post("/api/invoices/upload", headers=h,
                    files={"file": (f"{number}.pdf", render_invoice_pdf(spec), "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def act(client, email, inv_id, action, **body):
    h = login(client, email)
    return client.post(f"/api/approvals/invoices/{inv_id}/{action}", headers=h, json=body)


def detail(client, inv_id, email=CLERK):
    login(client, email)
    return client.get(f"/api/invoices/{inv_id}").json()


def test_touchless_small_clean_invoice_approved_by_policy(client, db):
    inv = upload(client, db, "Dakshin Calibration Labs", "DCL-2026-77", "4500001008",
                 [Line("SRV-CAL-01", "Lab instrument calibration", "998346", D(1), "LS", D("36000.00"), D(18))])
    assert inv["decision"] == "APPROVE" and inv["status"] == "approved"
    steps = inv["workflow"]["steps"]
    assert len(steps) == 1 and steps[0]["by_policy"] == "P-01" and steps[0]["status"] == "approved"
    assert inv["current_owner"].startswith("Approved by policy P-01")
    assert inv["rail"] == 4


def test_s1_fifteen_lakh_needs_l1_then_l2_with_mfa(client, db):
    inv = upload(client, db, "Sahyadri Catalysts & Additives Ltd", "SCA/26-27/0901", "4500001001",
                 [Line("CAT-ZN-01", "Ziegler-Natta catalyst ZN-118", "3815", D("1.5"), "MT", D("850000.00"), D(18))])
    assert inv["decision"] == "APPROVE" and D(inv["total"]) == D("1504500.00")
    assert [s["level"] for s in inv["workflow"]["steps"]] == [1, 2] and inv["workflow"]["mfa_required"]

    # L2 cannot jump the queue.
    r = act(client, L2, inv["id"], "approve", totp=totp(db, L2))
    assert r.status_code == 422 and "L1 Finance Manager" in r.json()["detail"]["message"]
    # L1 without a code: refused, MFA flagged.
    r = act(client, L1, inv["id"], "approve")
    assert r.status_code == 422 and r.json()["detail"]["mfa"] is True
    r = act(client, L1, inv["id"], "approve", totp="000000")
    assert r.status_code == 422
    r = act(client, L1, inv["id"], "approve", totp=totp(db, L1), comment="Within contract price")
    assert r.status_code == 200 and r.json()["current_owner"] == "Awaiting L2 Plant Head"
    # L1 cannot approve the L2 step as well (and SoD says why).
    r = act(client, L1, inv["id"], "approve", totp=totp(db, L1))
    assert r.status_code == 403 and "already approved" in r.json()["detail"]["message"]
    r = act(client, L2, inv["id"], "approve", totp=totp(db, L2))
    assert r.status_code == 200
    d = detail(client, inv["id"])
    assert d["status"] == "approved" and d["rail"] == 4
    assert [(s["approver"], s["mfa_verified"]) for s in d["workflow"]["steps"]] == [
        ("Rohan Mehta", True), ("Kavita Desai", True)]


def test_sod_po_creator_cannot_approve_and_clerk_cannot_approve(client, db):
    # PO 4500001007 (freight) was created by Rohan Mehta (L1).
    inv = upload(client, db, "Konkan Bulk Carriers", "KBC/FRT/3381", "4500001007",
                 [Line("FRT-TNK-01", "Bulk tanker freight Dahej to Taloja", "996511", D(2), "TRIP", D("38000.00"), D(12))])
    assert inv["status"] == "pending_approval" and inv["workflow"]["steps"][0]["level"] == 1
    r = act(client, L1, inv["id"], "approve")
    assert r.status_code == 403 and r.json()["detail"]["sod"] is True
    assert "you created PO 4500001007" in r.json()["detail"]["message"]
    d = detail(client, inv["id"], L1)
    assert d["workflow"]["can_approve"] is False and d["workflow"]["approve_blocked_sod"] is True

    r = act(client, CLERK, inv["id"], "approve")
    assert r.status_code == 403 and "AP clerks process invoices" in r.json()["detail"]["message"]


def test_block_cannot_be_overridden_flag_needs_justification_and_two_approvers(client, db):
    blocked = upload(client, db, "Kesar Engineering Spares", "KES/26-27/0050", "4500001003",
                     [Line("BRG-6205", "Ball bearing 6205 2RS", "8482", D(100), "NOS", D("450.00"), D(18))])
    assert blocked["decision"] == "BLOCK"
    r = act(client, CLERK, blocked["id"], "override", comment="Supplier promised the rest next week")
    assert r.status_code == 422 and "cannot be overridden" in r.json()["detail"]["message"]

    # Intra-state seals invoice charging IGST: FLAG TAX_MISMATCH, total under Rs 10 lakh.
    flagged = upload(client, db, "Kesar Engineering Spares", "KES/26-27/0051", "4500001012",
                     [Line("SEAL-M60", "Mechanical seal 60 mm", "8484", D(6), "NOS", D("9400.00"), D(18))],
                     force_igst=True)
    assert flagged["decision"] == "FLAG" and flagged["status"] == "flagged"
    r = act(client, CLERK, flagged["id"], "override", comment="ok")
    assert r.status_code == 422 and "justification" in r.json()["detail"]["message"]
    r = act(client, CLERK, flagged["id"], "override",
            comment="Supplier will issue a corrected invoice; tax amount is the same, only the head is wrong")
    assert r.status_code == 200
    d = detail(client, flagged["id"])
    assert d["status"] == "pending_approval" and [s["level"] for s in d["workflow"]["steps"]] == [1, 2]
    assert d["workflow"]["override_by"] == "Asha Kulkarni"


def test_sla_escalation_and_delegation(client, db):
    inv = upload(client, db, "Kesar Engineering Spares", "KES/26-27/0060", "4500001009",
                 [Line("PUMP-IMP-50", "Pump impeller 50 mm SS316", "8413", D(10), "NOS", D("6800.00"), D(18))])
    assert inv["status"] == "pending_approval" and inv["workflow"]["steps"][0]["level"] == 1
    # L2 cannot act on an L1 step that is not overdue.
    assert act(client, L2, inv["id"], "approve").status_code == 422
    h = login(client, ADMIN)
    try:
        r = client.post("/api/admin/clock/advance", headers=h, json={"hours": 49})
        assert r.status_code == 200 and r.json()["escalated"] >= 1
        d = detail(client, inv["id"], L2)
        assert d["workflow"]["steps"][0]["escalated_at"] and d["workflow"]["can_approve"]
        assert "escalated to L2" in d["current_owner"]
        assert act(client, L2, inv["id"], "approve", comment="Escalated after 48h").status_code == 200
    finally:
        h = login(client, ADMIN)
        client.post("/api/admin/clock/reset", headers=h)

def test_delegation_send_back_override_and_reject(client, db):
    # Two freight trips (Rs 85,120) need L1. The PO was created by Rohan (L1), so SoD stops him;
    # he delegates to Vikram (L3), who then acts on the L1 step through the delegation.
    inv = upload(client, db, "Konkan Bulk Carriers", "KBC/FRT/3382", "4500001007",
                 [Line("FRT-TNK-01", "Bulk tanker freight Dahej to Taloja", "996511", D(2), "TRIP", D("38000.00"),
                       D(12))])
    assert inv["status"] == "pending_approval"
    h = login(client, L1)
    vikram = db.scalar(select(User).where(User.email == "vikram.rao@plantx.example"))
    r = client.post("/api/approvals/delegations", headers=h,
                    json={"to_user_id": vikram.id, "days": 3, "reason": "On leave"})
    assert r.status_code == 201 and r.json()["active"]

    login(client, "vikram.rao@plantx.example")
    item = next(q for q in client.get("/api/approvals/queue").json() if q["invoice_id"] == inv["id"])
    assert item["can_act"] and item["via_delegation"]

    r = act(client, "vikram.rao@plantx.example", inv["id"], "send-back", comment="Check trip sheets for trip 6")
    assert r.status_code == 200 and r.json()["status"] == "flagged"
    r = act(client, CLERK, inv["id"], "override", comment="Trip sheets checked; both trips delivered on time")
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"

    assert act(client, "vikram.rao@plantx.example", inv["id"], "reject", comment="no").status_code == 422
    r = act(client, "vikram.rao@plantx.example", inv["id"], "reject", comment="Trip already billed on KBC/FRT/3381")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    d = detail(client, inv["id"])
    first = d["workflow"]["steps"][0]
    assert first["status"] == "skipped" and first["comment"].startswith("Sent back to AP clerk")
    rejected = next(s for s in d["workflow"]["steps"] if s["status"] == "rejected")
    assert rejected["approver"] == "Vikram Rao" and rejected["delegated_from"] == "Rohan Mehta"


def test_mfa_setup_only_for_own_approver_account(client):
    login(client, L1)
    r = client.get("/api/auth/mfa-setup")
    assert r.status_code == 200 and r.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert "<svg" in r.json()["qr_svg"]
    login(client, CLERK)
    assert client.get("/api/auth/mfa-setup").status_code == 404
