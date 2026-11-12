"""Line matches by description need a clerk; a clerk can reject a blocked invoice; the job queue interface."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import delete, select

from app.core import jobs
from app.core.enums import InvoiceStatus
from app.core.ratelimit import limiter
from app.models import (ApprovalStep, AuditEvent, Invoice, InvoiceLine, MatchResult, Organisation, PurchaseOrder,
                        ReasonCode, Supplier)
from app.workflow.matching import run_match

CLERK = "asha.kulkarni@plantx.example"
L1 = "rohan.mehta@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


@pytest.fixture
def made(db):
    """Invoices created here bypass upload: delete them afterwards so they consume no PO quantity."""
    ids: list[int] = []
    yield ids
    db.rollback()
    if ids:
        mids = list(db.scalars(select(MatchResult.id).where(MatchResult.invoice_id.in_(ids))))
        db.execute(delete(ReasonCode).where(ReasonCode.match_result_id.in_(mids)))
        db.execute(delete(MatchResult).where(MatchResult.id.in_(mids)))
        db.execute(delete(ApprovalStep).where(ApprovalStep.invoice_id.in_(ids)))
        db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(ids)))
        db.execute(delete(Invoice).where(Invoice.id.in_(ids)))
        db.commit()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def _bearing_invoice(db, made: list[int], number: str) -> Invoice:
    """10 bearings on PO 4500001003, but printed with the supplier's own item code (so only the description matches)."""
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "4500001003"))
    s = db.get(Supplier, po.supplier_id)
    org = db.scalar(select(Organisation))
    value = D("4500.00")
    half = D("405.00")
    inv = Invoice(supplier_id=s.id, invoice_number=number, invoice_number_norm=number.replace("/", ""),
                  invoice_date=date(2026, 11, 9), po_number_text=po.po_number, supplier_gstin=s.gstin,
                  buyer_gstin=org.gstin, place_of_supply=org.state_code, taxable_total=value, cgst=half, sgst=half,
                  total=value + 2 * half, status=InvoiceStatus.RECEIVED, current_owner="AP clerk")
    db.add(inv)
    db.flush()
    db.add(InvoiceLine(invoice_id=inv.id, line_no=1, item_code="KES-0099", description="Ball Bearing 6205-2RS",
                       hsn_sac="8482", qty=D(10), uom="NOS", unit_price=D("450.00"), taxable_value=value,
                       gst_rate=D(18), cgst=half, sgst=half))
    db.flush()
    made.append(inv.id)
    run_match(db, inv)
    db.commit()
    return inv


def _codes(detail: dict) -> set[tuple[str, str]]:
    return {(r["code"], r["severity"]) for r in detail["match"]["reasons"]}


def test_description_match_flags_until_clerk_confirms(client, db, made):
    inv = _bearing_invoice(db, made, "KES/MAP/0001")
    login(client, CLERK)
    d = client.get(f"/api/invoices/{inv.id}").json()
    assert d["match"]["decision"] == "FLAG" and ("LINE_MAPPED", "flag") in _codes(d)
    ev = next(r for r in d["match"]["reasons"] if r["code"] == "LINE_MAPPED")["evidence"]

    h = login(client, L1)
    assert client.post(f"/api/invoices/{inv.id}/lines/1/mapping", headers=h,
                       json={"po_line_id": ev["po_line_id"], "reason": "same"}).status_code == 403
    h = login(client, CLERK)
    other_po_line = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "4500001004")).lines[0].id
    r = client.post(f"/api/invoices/{inv.id}/lines/1/mapping", headers=h, json={"po_line_id": other_po_line, "reason": "x y z"})
    assert r.status_code == 422 and "not on this invoice's purchase order" in r.json()["detail"]
    r = client.post(f"/api/invoices/{inv.id}/lines/1/mapping", headers=h,
                    json={"po_line_id": ev["po_line_id"], "reason": "Same bearing, supplier's own code"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["match"]["decision"] == "APPROVE" and ("LINE_MAPPED", "info") in _codes(d)
    assert d["match"]["trigger"] == "mapping_confirmed"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "line.mapping_confirmed",
                                              AuditEvent.entity_id == str(inv.id))) is not None


def test_rejected_match_blocks_and_clerk_can_reject_the_invoice(client, db, made):
    inv = _bearing_invoice(db, made, "KES/MAP/0002")
    h = login(client, CLERK)
    r = client.post(f"/api/invoices/{inv.id}/lines/1/mapping", headers=h, json={"po_line_id": None, "reason": "Not ordered"})
    assert r.status_code == 200
    d = r.json()
    assert d["match"]["decision"] == "BLOCK" and ("LINE_NOT_ON_PO", "block") in _codes(d)
    assert d["workflow"]["can_clerk_reject"] is True and d["workflow"]["can_override"] is False

    h = login(client, L1)  # approvers reject their own steps, not from the clerk's exception queue
    assert client.post(f"/api/approvals/invoices/{inv.id}/clerk-reject", headers=h, json={"comment": "Not ours"}).status_code == 403
    h = login(client, CLERK)
    r = client.post(f"/api/approvals/invoices/{inv.id}/clerk-reject", headers=h, json={"comment": "no"})
    assert r.status_code == 422  # reason too short
    r = client.post(f"/api/approvals/invoices/{inv.id}/clerk-reject", headers=h,
                    json={"comment": "Item was never ordered on this PO"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # Once rejected (or approved), a clerk cannot reject it again.
    assert client.post(f"/api/approvals/invoices/{inv.id}/clerk-reject", headers=h,
                       json={"comment": "Again, rejected"}).status_code == 422
    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "invoice.rejected_by_clerk",
                                            AuditEvent.entity_id == str(inv.id)))
    assert ev is not None and ev.after["reason"].startswith("Item was never")


def test_job_queue_records_runs_and_failures():
    job = jobs.enqueue("double", lambda x: x * 2, 21)
    assert job.result == 42 and job.status == "done" and job.duration_ms is not None

    def boom():
        raise RuntimeError("worker fell over")

    with pytest.raises(RuntimeError):
        jobs.enqueue("boom", boom)
    st = jobs.status()
    assert st["queue"] == "in-process"
    assert st["recent"][0]["name"] == "boom" and st["recent"][0]["status"] == "failed"
    assert st["recent"][1]["name"] == "double" and st["recent"][1]["status"] == "done"
