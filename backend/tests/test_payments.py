"""MSME guardian (D4) and smart payment run with TDS (D5)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.enums import InvoiceStatus, StepStatus
from app.core.ratelimit import limiter
from app.models import ApprovalStep, AuditEvent, Invoice, Payment, Policy, PurchaseOrder, Supplier
from app.payments import msme, tds
from app.workflow.approvals import required_levels

CLERK = "asha.kulkarni@plantx.example"
L1 = "rohan.mehta@plantx.example"
NAVRANG = "accounts@navrang-pack.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


# ---------------------------------------------------------------- pure rules

def test_tds_sections_and_thresholds():
    # Contractor, firm PAN (4th char F): 2% once a single bill is above 30k.
    t = tds.compute("contractor", "AAAFT1234K", D("420000"), D(0))
    assert t.rate_pct == 2 and t.amount == D("8400.00")
    # Contractor below both thresholds: nothing; individual PAN gets 1%.
    assert tds.compute("contractor", "AAAPT1234K", D("20000"), D(0)).amount == 0
    assert tds.compute("contractor", "AAAPT1234K", D("20000"), D("90000")).amount == D("200.00")
    # Technical fees: 2% only once the year crosses 50k.
    assert tds.compute("technical", "AAACD1234K", D("36000"), D(0)).amount == 0
    assert tds.compute("technical", "AAACD1234K", D("36000"), D("20000")).amount == D("720.00")
    # Goods: 0.1% only on the part above 50 lakh for the year.
    assert tds.compute("goods", "AAACS1234K", D("1000000"), D("4500000")).amount == D("500.00")
    assert tds.compute("goods", "AAACS1234K", D("1000000"), D("6000000")).amount == D("1000.00")
    assert tds.compute("none", "AAACS1234K", D("1000"), D(0)).amount == 0


def test_msme_interest_deduction_and_half_year():
    due = date(2026, 10, 1)
    # 3 x 5.75% = 17.25% a year, monthly rests: one 30-day month late = 1.4375%.
    assert msme.interest(D("100000"), due, due + timedelta(days=30), D("5.75")) == D("1437.50")
    assert msme.interest(D("100000"), due, due, D("5.75")) == 0
    assert msme.interest(D("100000"), due, due + timedelta(days=60), D("5.75")) > D("2875.00")  # compounding
    assert msme.deduction_at_risk(D("100000"), due, due + timedelta(days=1), D("25.17")) == (D("100000"), D("25170.00"))
    assert msme.deduction_at_risk(D("100000"), due, due, D("25.17")) == (0, 0)
    assert msme.half_year(date(2026, 11, 12))[2] == "Oct 2026-Mar 2027"
    assert msme.half_year(date(2027, 2, 1))[0] == date(2026, 10, 1)
    assert msme.half_year(date(2026, 5, 1))[2] == "Apr-Sep 2026"


# ---------------------------------------------------------------- payment run

def _approved(db, code: str, number: str, taxable: str, inv_days_ago: int, due_in: int | None,
              msme_due_in: int | None = None, status=InvoiceStatus.APPROVED) -> Invoice:
    s = db.scalar(select(Supplier).where(Supplier.code == code))
    today = clock.today()
    base = D(taxable)
    inv = Invoice(supplier_id=s.id, invoice_number=number, invoice_number_norm=number.replace("/", ""),
                  invoice_date=today - timedelta(days=inv_days_ago), taxable_total=base,
                  igst=(base * D("0.18")).quantize(D("0.01")), total=(base * D("1.18")).quantize(D("0.01")),
                  status=status, current_owner="Approved",
                  accepted_at=datetime.combine(today - timedelta(days=inv_days_ago), time(10), tzinfo=clock.IST),
                  due_date=today + timedelta(days=due_in) if due_in is not None else None,
                  msme_due_date=today + timedelta(days=msme_due_in) if msme_due_in is not None else None)
    # Realistic: backed by the supplier's PO and approved at the levels the DoA requires.
    inv.po_id = db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == s.id).order_by(PurchaseOrder.id))
    db.add(inv)
    db.flush()
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True))).data
    for n, level in enumerate(required_levels(inv.total, policy, override=False), start=1):
        db.add(ApprovalStep(invoice_id=inv.id, sequence=n, level=level, status=StepStatus.APPROVED))
    db.commit()
    return inv


def test_payment_run_proposal_release_and_supplier_view(client, db):
    msme_inv = _approved(db, "V100102", "NPI/PR/0041", "154000", 41, 19, msme_due_in=4)
    late_msme = _approved(db, "V100102", "NPI/PR/0030", "50000", 50, 0, msme_due_in=-5)
    disc = _approved(db, "V100101", "SCA/PR/0101", "300000", 2, 30)  # 1% in 10 days: about 12% a year
    defer = _approved(db, "V100101", "SCA/PR/0102", "300000", 20, 40)  # window closed: pay on terms
    contractor = _approved(db, "V100104", "TTS/PR/0007", "420000", 10, 3, msme_due_in=35)
    blocked = _approved(db, "V100101", "SCA/PR/0103", "1000", 2, 1, status=InvoiceStatus.BLOCKED)

    login(client, CLERK)
    r = client.get("/api/payments/run")
    assert r.status_code == 200
    run = r.json()
    items = {i["invoice_id"]: i for i in run["items"]}
    assert blocked.id not in items
    assert items[late_msme.id]["rule"] == "overdue" and D(items[late_msme.id]["interest_if_late"]) > 0
    assert items[msme_inv.id]["rule"] == "msme" and items[msme_inv.id]["pay"]
    assert items[disc.id]["rule"] == "discount" and D(items[disc.id]["discount"]) == D("3540.00")
    assert items[defer.id]["rule"] == "defer" and not items[defer.id]["pay"]
    assert items[contractor.id]["rule"] == "terms" and D(items[contractor.id]["tds"]) == D("8400.00")
    order = [i["invoice_id"] for i in run["items"]]
    assert order.index(late_msme.id) < order.index(msme_inv.id) < order.index(disc.id) \
        < order.index(contractor.id) < order.index(defer.id)
    assert run["can_release"] is False and D(run["summary"]["cash_kept"]) >= defer.total

    mine = [late_msme.id, msme_inv.id, disc.id, contractor.id]
    h = login(client, CLERK)
    assert client.post("/api/payments/run/release", headers=h, json={"invoice_ids": mine}).status_code == 403
    h = login(client, L1)
    r = client.post("/api/payments/run/release", headers=h, json={"invoice_ids": mine})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["run_id"].startswith("PR-") and len(out["payments"]) == 4
    assert all(p["utr"].startswith("DULYN") and len(p["utr"]) == 18 for p in out["payments"])
    # Paying twice is refused.
    assert client.post("/api/payments/run/release", headers=h, json={"invoice_ids": [disc.id]}).status_code == 409

    db.expire_all()
    p = db.scalar(select(Payment).where(Payment.invoice_id == contractor.id))
    assert p.tds_amount == D("8400.00") and p.tds_section == "contractor"
    assert p.net_amount == contractor.total - D("8400.00")
    assert db.scalar(select(Payment).where(Payment.invoice_id == disc.id)).discount_amount == D("3540.00")
    assert db.get(Invoice, msme_inv.id).status == InvoiceStatus.PAID
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "payment.released",
                                              AuditEvent.entity_id == str(msme_inv.id))) is not None

    # The supplier sees the payment and UTR in the portal (and so in the chatbot schedule).
    login(client, NAVRANG)
    portal = client.get("/api/portal").json()
    utrs = {x["invoice_number"]: x["utr"] for x in portal["payments"]}
    assert utrs["NPI/PR/0041"].startswith("DULYN")

    # MSME guardian: late payment shows interest; the Form I summary lists it.
    login(client, CLERK)
    g = client.get("/api/payments/msme").json()
    rows = {x["invoice_id"]: x for x in g["rows"]}
    assert rows[late_msme.id]["status"] == "paid_late" and D(rows[late_msme.id]["interest"]) > 0
    assert rows[msme_inv.id]["status"] == "on_time"
    assert "43B(h)" in g["tax_rule"]
    assert any(x["invoice_number"] == "NPI/PR/0030" for x in g["form1"]["rows"])
    hist = client.get("/api/payments/history").json()
    assert any(x["invoice_id"] == contractor.id and x["tds_section"] == "contractor" for x in hist)


def test_unpaid_overdue_msme_shows_deduction_at_risk(client, db):
    inv = _approved(db, "V100106", "DCL/PR/0009", "10000", 30, -2, msme_due_in=-2)
    login(client, CLERK)
    g = client.get("/api/payments/msme").json()
    row = next(x for x in g["rows"] if x["invoice_id"] == inv.id)
    assert row["status"] == "overdue" and D(row["deduction_at_risk"]) == inv.total and D(row["tax_effect"]) > 0
    assert D(g["totals"]["deduction_at_risk"]) >= inv.total
    # Suppliers cannot reach payment endpoints.
    login(client, NAVRANG)
    assert client.get("/api/payments/run").status_code == 403
