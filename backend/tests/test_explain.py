"""Explain: plain-language explanation from reason codes only; never changes the decision."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import delete, select

from app.core.enums import InvoiceStatus
from app.core.ratelimit import limiter
from app.engine.catalog import CATALOG
from app.models import Invoice, MatchResult, PurchaseOrder, ReasonCode
from app.workflow.explain import GUIDE, ReasonFact, explain

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def test_every_actionable_code_has_guidance():
    info_only = {"LINE_MAPPED", "UOM_CONVERTED", "SMALL_DIFFERENCE", "EINVOICE_VERIFIED", "EINVOICE_NOT_APPLICABLE",
                 "ERS_SETTLEMENT", "EMAIL_RECEIVED", "CREDIT_NOTE_APPLIED"}
    assert set(CATALOG) - info_only <= set(GUIDE)


def test_block_explanation_names_who_acts_and_keeps_engine_sentences():
    facts = [ReasonFact("MISSING_GR", "block", "No goods receipt for PO line 10 (FFS bag).", 1),
             ReasonFact("PRICE_VARIANCE", "flag", "Unit price Rs 640 vs PO Rs 620 (+3.2%).", 1),
             ReasonFact("EINVOICE_NOT_APPLICABLE", "info", "Supplier below the e-invoice threshold.")]
    e = explain("BLOCK", "blocked", facts, "engine-1.4", 2)
    assert e.headline.startswith("Blocked") and "1 problem is fixed" in e.headline and "override" in e.headline
    assert [p.code for p in e.points] == ["MISSING_GR", "PRICE_VARIANCE"]  # blocks first, then flags
    gr = e.points[0]
    assert gr.what == facts[0].message and gr.who == "Plant X stores" and "(line 1)" in gr.title
    assert "Plant X stores" in e.next_step and "automatically" in e.next_step
    assert len(e.notes) == 1 and "engine engine-1.4, policy v2" in e.footer and "cannot change it" in e.footer
    assert e.inputs == ["EINVOICE_NOT_APPLICABLE", "MISSING_GR", "PRICE_VARIANCE"]


def test_flag_approve_and_review_wording():
    f = explain("FLAG", "flagged", [ReasonFact("INJECTION_ATTEMPT", "flag", "Hidden white text found.")])
    assert f.headline.startswith("Flagged: 1 point needs") and "two approval levels" in f.next_step
    a = explain("APPROVE", "pending_approval", [])
    assert a.headline.startswith("Approved by the checks") and not a.points and "delegation of authority" in a.next_step
    assert "Paid" in explain("APPROVE", "paid", []).next_step
    r = explain("BLOCK", "needs_review", [ReasonFact("NO_LINES", "block", "No lines.")])
    assert r.next_step.startswith("First a clerk confirms")
    unknown = explain("FLAG", "flagged", [ReasonFact("SOMETHING_NEW", "flag", "x")])
    assert unknown.points[0].who == "AP clerk"


def test_explain_endpoint_and_access(client, db):
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "4500001004"))
    inv = Invoice(supplier_id=po.supplier_id, po_id=po.id, invoice_number="NPW/EXPLAIN/1", invoice_number_norm="NPWEXPLAIN1",
                  invoice_date=date(2026, 11, 9), status=InvoiceStatus.BLOCKED, total=D("100"), current_owner="x")
    db.add(inv)
    db.flush()
    m = MatchResult(invoice_id=inv.id, decision="BLOCK", policy_version=1, engine_version="engine-test", trigger="upload")
    db.add(m)
    db.flush()
    db.add(ReasonCode(match_result_id=m.id, code="MISSING_GR", severity="block", message="No goods receipt yet.",
                      evidence={}, line_no=None))
    db.commit()
    try:
        assert client.post("/api/auth/demo-login", json={"email": CLERK}).status_code == 200
        r = client.get(f"/api/invoices/{inv.id}/explain")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["decision"] == "BLOCK" and j["points"][0]["who"] == "Plant X stores" and j["source"] == "template"
        assert j["supplier_view"][0]["code"] == "MISSING_GR" and j["supplier_view"][0]["you_act"] is False
        db.expire_all()
        assert db.get(Invoice, inv.id).status == InvoiceStatus.BLOCKED  # explaining changes nothing
        assert client.post("/api/auth/demo-login", json={"email": "accounts@navrang-pack.example"}).status_code == 200
        assert client.get(f"/api/invoices/{inv.id}/explain").status_code == 403
    finally:
        db.rollback()
        db.execute(delete(ReasonCode).where(ReasonCode.match_result_id == m.id))
        db.execute(delete(MatchResult).where(MatchResult.id == m.id))
        db.execute(delete(Invoice).where(Invoice.id == inv.id))
        db.commit()


def test_do_not_pay_blocks_say_reject_not_fix():
    e = explain("BLOCK", "blocked", [ReasonFact("DUPLICATE", "block", "Duplicate of INV/0042.")])
    assert e.next_step.startswith("Do not pay") and "rejects" in e.next_step
    mixed = explain("BLOCK", "blocked", [ReasonFact("DUPLICATE", "block", "x"), ReasonFact("MISSING_GR", "block", "y")])
    assert mixed.next_step.startswith("Waiting for")


def test_every_actionable_code_has_supplier_text_in_english_and_hindi():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"
    for lang in ("en", "hi"):
        todo = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))["todo"]
        missing = sorted(set(GUIDE) - set(todo))
        assert not missing, f"{lang}.json todo is missing {missing}"
