"""Supplier risk card (D8): pure rules on hand-made facts, plus the API's shape and access."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.enums import BankChangeStatus, MsmeCategory
from app.core.ratelimit import limiter
from app.models import Supplier
from app.reports.supplier_risk import BankChangeFact, Facts, InvoiceFact, PaymentFact, card, sustainability

TODAY = date(2026, 11, 12)


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def _supplier(e_invoice: bool = False, msme: MsmeCategory = MsmeCategory.MICRO) -> Supplier:
    return Supplier(id=1, code="V100102", name="Test Supplier", category="Packaging", msme_category=msme,
                    udyam_no="UDYAM-XX-00-0000000", enterprise_type="manufacturer", e_invoice_applicable=e_invoice,
                    payment_terms_days=45, written_agreement=True)


def _inv(n: int, codes: set[str] = frozenset(), days_ago: int = 10) -> InvoiceFact:
    return InvoiceFact(n, TODAY - timedelta(days=days_ago), "paid", Decimal(1000), set(codes))


def test_clean_supplier_is_low_with_no_reasons():
    facts = Facts(invoices=[_inv(i) for i in range(12)],
                  payments=[PaymentFact(1, TODAY - timedelta(days=5), TODAY - timedelta(days=3), Decimal(1000))])
    c = card(_supplier(), facts, TODAY)
    assert c["level"] == "low" and c["reasons"] == []
    assert c["on_time"]["rate"] == 1.0 and c["disputes"]["rate"] == 0.0
    assert c["msme"]["is_msme"] is True and c["einvoice"]["applicable"] is False


def test_bank_mismatch_or_injection_makes_it_high():
    for code in ("BANK_MISMATCH", "INJECTION_ATTEMPT"):
        c = card(_supplier(), Facts(invoices=[_inv(1, {code}), _inv(2)]), TODAY)
        assert c["level"] == "high", code
        assert c["reasons"][0]["level"] == "high"


def test_dispute_rate_counts_billing_exceptions_not_missing_gr_or_duplicates():
    invs = ([_inv(i, {"PRICE_VARIANCE"}) for i in range(4)] + [_inv(10 + i) for i in range(6)]
            + [_inv(20, {"MISSING_GR"}), _inv(21, {"DUPLICATE"})])
    c = card(_supplier(), Facts(invoices=invs), TODAY)
    assert c["disputes"] == {**c["disputes"], "count": 4, "of": 11}  # the duplicate is not a genuine invoice
    assert c["duplicates"]["blocked"] == 1
    assert c["level"] == "watch" and "billing dispute" in c["reasons"][0]["text"]


def test_small_samples_are_not_judged_and_old_invoices_fall_outside_the_window():
    few = card(_supplier(), Facts(invoices=[_inv(1, {"PRICE_VARIANCE"}), _inv(2)]), TODAY)
    assert few["disputes"]["rate"] == 0.5 and few["level"] == "low"
    old = card(_supplier(), Facts(invoices=[_inv(1, {"BANK_MISMATCH"}, days_ago=400)]), TODAY)
    assert old["invoices_12m"] == 0 and old["level"] == "low"


def test_recent_bank_change_and_repeated_duplicates_are_watch_points():
    facts = Facts(invoices=[_inv(1, {"DUPLICATE"}), _inv(2, {"DUPLICATE"}), _inv(3)],
                  bank_changes=[BankChangeFact(BankChangeStatus.APPROVED, TODAY - timedelta(days=30), TODAY - timedelta(days=35)),
                                BankChangeFact(BankChangeStatus.COOLING, None, TODAY - timedelta(days=1))])
    c = card(_supplier(), facts, TODAY)
    assert c["level"] == "watch"
    assert c["bank_changes"]["approved_12m"] == 1 and c["bank_changes"]["in_progress"] == 1
    texts = " ".join(r["text"] for r in c["reasons"])
    assert "Bank account changed" in texts and "in progress" in texts and "2 duplicate" in texts


def test_einvoice_compliance_and_late_payments():
    invs = [_inv(i, {"EINVOICE_VERIFIED"}) for i in range(9)] + [_inv(9, {"EINVOICE_QR_MISSING"})]
    pays = [PaymentFact(1, TODAY - timedelta(days=2), TODAY - timedelta(days=6), Decimal(500)),
            PaymentFact(2, TODAY - timedelta(days=9), TODAY - timedelta(days=8), Decimal(500))]
    c = card(_supplier(e_invoice=True, msme=MsmeCategory.NONE), Facts(invoices=invs, payments=pays), TODAY)
    assert c["einvoice"]["rate"] == 0.9 and c["level"] == "watch"
    assert c["on_time"] == {**c["on_time"], "paid": 2, "on_time": 1, "rate": 0.5, "avg_days_late": 4.0}
    assert c["spend_paid_12m"] == Decimal(1000)


def test_sustainability_status_follows_the_business_date():
    assert sustainability("V100105", TODAY)["status"] == "overdue"
    assert sustainability("V100102", TODAY)["status"] == "due"
    assert sustainability("V100103", TODAY)["status"] == "not_started"
    assert sustainability("V100101", TODAY)["status"] == "current"
    assert sustainability("V100106", TODAY)["status"] == "not_required"
    assert sustainability("V999999", TODAY)["status"] == "unknown"
    assert all(sustainability(c, TODAY)["fictional"] for c in ("V100101", "V999999"))


def test_risk_api_lists_every_supplier_for_staff(client):
    client.post("/api/auth/demo-login", json={"email": "asha.kulkarni@plantx.example"})
    body = client.get("/api/suppliers/risk").json()
    assert len(body["cards"]) == 7
    assert body["methodology"]["note"].startswith("Information for procurement")
    order = {"high": 0, "watch": 1, "low": 2}
    assert [order[c["level"]] for c in body["cards"]] == sorted(order[c["level"]] for c in body["cards"])
    one = body["cards"][0]
    for key in ("msme", "on_time", "disputes", "duplicates", "bank_changes", "einvoice", "sustainability"):
        assert key in one
    single = client.get(f"/api/suppliers/{one['supplier_id']}/risk").json()
    assert single["code"] == one["code"]
    assert client.get("/api/suppliers/99999/risk").status_code == 404


def test_risk_api_is_staff_only(client):
    for email in ("invoices@kesar-spares.example", "imran.shaikh@plantx.example"):
        client.post("/api/auth/demo-login", json={"email": email})
        assert client.get("/api/suppliers/risk").status_code == 403, email
