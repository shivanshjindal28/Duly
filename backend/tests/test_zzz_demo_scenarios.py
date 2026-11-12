"""The demo as it will be shown: seeded history + the 12 git-tracked scenario files (demo/manifest.json).

Runs last (it reseeds the shared test database with the 90-day history, as `seed.py --reset`
does), then uploads every scenario file in manifest order and checks the expected decision,
status and reason codes, plus each scenario's follow-up (GR release, approvals with MFA,
review, payment run with MSME first and TDS).
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal as D
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import func, select

from app.core.crypto import decrypt_str
from app.core.ratelimit import limiter
from app.models import ApprovalStep, Invoice, Payment, PurchaseOrder, ReasonCode, User
from app.seed import reset_and_seed

DEMO = Path(__file__).resolve().parents[2] / "demo"
MANIFEST = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
CLERK, STORES, AUDITOR = "asha.kulkarni@plantx.example", "imran.shaikh@plantx.example", "meera.iyer@plantx.example"
L1, L2 = "rohan.mehta@plantx.example", "kavita.desai@plantx.example"


@pytest.fixture(scope="module", autouse=True)
def history_db():
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        reset_and_seed(db, history=True)
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    limiter.reset()
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def totp(db, email):
    u = db.scalar(select(User).where(User.email == email))
    return pyotp.TOTP(decrypt_str(u.mfa_secret_enc)).now()


# ---------------------------------------------------------------- history

def test_history_is_realistic_and_produced_by_the_engine(client, db):
    invoices = db.scalars(select(Invoice)).all()
    assert 200 <= len(invoices) <= 300
    status = Counter(i.status for i in invoices)
    assert status["paid"] > 100 and status["approved"] > 20
    for s in ("pending_approval", "flagged", "blocked", "rejected"):
        assert status[s] >= 1, s
    assert db.scalar(select(func.count()).select_from(PurchaseOrder)) >= 55
    # Every invoice went through the rules engine; payments carry simulated UTRs.
    assert all(i.decision for i in invoices)
    assert all(p.utr.startswith("DULYN") for p in db.scalars(select(Payment)))
    # History never contains a bank-mismatch block (the bank change happened before it).
    assert db.scalar(select(func.count()).select_from(ReasonCode).where(ReasonCode.code == "BANK_MISMATCH")) == 0
    # Scenario 5's original: touchless, awaiting payment.
    s5 = db.scalar(select(Invoice).where(Invoice.invoice_number == "INV/0042"))
    assert s5.status == "approved"
    assert db.scalars(select(ApprovalStep).where(ApprovalStep.invoice_id == s5.id)).one().by_policy == "P-01"

    login(client, CLERK)
    k = client.get("/api/dashboard/summary").json()["kpis"]
    assert 0.15 <= k["touchless_rate"] <= 0.5 and k["avg_cycle_hours"] > 0
    assert k["duplicates_prevented"] >= 1 and k["in_queue"] >= 5
    login(client, AUDITOR)
    assert client.get("/api/audit/verify").json()["ok"] is True
    rep = client.get("/api/reports/controls?from=2026-01-01&to=2027-12-31").json()
    results = {c["id"]: c["result"] for c in rep["controls"]}
    assert "no_activity" not in results.values()  # bank changes (C-06) and payments (C-08) have history too


# ---------------------------------------------------------------- the 12 scenarios

def _upload(client, sc) -> dict:
    h = login(client, sc["upload_as"])
    path = DEMO / sc["file"]
    r = client.post("/api/invoices/upload", headers=h, files={"file": (path.name, path.read_bytes(), sc["mime"])})
    assert r.status_code == 201, f"{sc['id']}: {r.text}"
    return r.json()


def test_every_demo_scenario_file_gives_the_expected_result(client, db):
    got = {}
    for sc in MANIFEST["scenarios"]:
        inv = _upload(client, sc)
        exp = sc["expected"]
        codes = {r["code"] for r in inv["match"]["reasons"]}
        if exp["decision"]:
            assert inv["decision"] == exp["decision"], (sc["id"], inv["match"]["reasons"])
        assert inv["status"] == exp["status"], (sc["id"], inv["status"])
        assert set(exp["reason_codes"]) <= codes, (sc["id"], codes)
        assert "POSSIBLE_DUPLICATE" not in codes, sc["id"]  # the demo files never look like history
        got[sc["id"]] = inv

    s1 = got["S01"]
    assert D(s1["total"]) == D("1504500.00") and [s["level"] for s in s1["workflow"]["steps"]] == [1, 2]
    assert s1["workflow"]["mfa_required"]
    pv = next(r for r in got["S02"]["match"]["reasons"] if r["code"] == "PRICE_VARIANCE")
    assert D(pv["evidence"]["variance_amount"]) == D("39680.00")
    dup = next(r for r in got["S05"]["match"]["reasons"] if r["code"] == "DUPLICATE")
    assert dup["evidence"]["duplicate_of"] == "INV/0042"
    qr = next(r for r in got["S08"]["match"]["reasons"] if r["code"] == "QR_MISMATCH")
    assert any(d["field"] == "total" for d in qr["evidence"]["differences"])

    # S04: stores posts the GR live; the automatic re-match releases the invoice.
    h = login(client, STORES)
    po = next(p for p in client.get("/api/stores/open-pos").json() if p["po_number"] == "4500001004")
    r = client.post("/api/stores/goods-receipts", headers=h,
                    json={"po_number": "4500001004", "lines": [{"po_line_id": po["lines"][0]["id"], "qty": "20000"}]})
    assert r.status_code == 201, r.text
    login(client, CLERK)
    s4 = client.get(f"/api/invoices/{got['S04']['id']}").json()
    assert s4["decision"] == "APPROVE" and s4["status"] == "pending_approval"

    # S12: the clerk enters what OCR could not read; the invoice is then matched.
    h = login(client, CLERK)
    s12 = got["S12"]
    for path in s12["pending_review"]:
        body = {"field": path, "reason": "Checked against the photo"}
        if path.endswith("hsn_sac"):
            body = {"field": path, "value": "3923", "reason": "HSN not legible; taken from the PO"}
        assert client.post(f"/api/invoices/{s12['id']}/review", headers=h, json=body).status_code == 200
    s12 = client.get(f"/api/invoices/{s12['id']}").json()
    assert s12["pending_review"] == [] and s12["decision"] == "APPROVE"

    # S01: L1 then L2, both with MFA.
    for email in (L1, L2):
        h = login(client, email)
        r = client.post(f"/api/approvals/invoices/{s1['id']}/approve", headers=h, json={"totp": totp(db, email)})
        assert r.status_code == 200, r.text

    # S10 and S11: L1 approves; the payment run puts the MSME invoice first and withholds TDS.
    for key in ("S10", "S11"):
        h = login(client, L1)
        r = client.post(f"/api/approvals/invoices/{got[key]['id']}/approve", headers=h, json={})
        assert r.status_code == 200, r.text
    login(client, CLERK)
    run = client.get("/api/payments/run").json()
    items = {i["invoice_id"]: i for i in run["items"]}
    s10 = items[got["S10"]["id"]]
    assert s10["rule"] == "msme" and s10["days_left"] == 4 and s10["pay"]
    assert run["items"][0]["invoice_id"] == got["S10"]["id"], [i["invoice_number"] for i in run["items"][:3]]
    assert D(items[got["S11"]["id"]]["tds"]) == D("8400.00")

    login(client, AUDITOR)
    assert client.get("/api/audit/verify").json()["ok"] is True
