"""Evaluated receipt settlement (ERS) on freight PO 4500001015: a service entry settles itself."""
from __future__ import annotations

from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.models import AuditEvent, Invoice, MatchResult, PurchaseOrder, ReasonCode
from app.samples.invoice_pdf import Line
from app.workflow import ers
from tests.test_approvals import login, upload

STORES = "imran.shaikh@plantx.example"
CLERK = "asha.kulkarni@plantx.example"
ERS_PO = "4500001015"  # Konkan: 6 trips x Rs 22,000, GST 12% (inter-state: IGST)


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def post_trip(client, value="22000.00") -> dict:
    h = login(client, STORES)
    po = next(p for p in client.get("/api/stores/open-pos").json() if p["po_number"] == ERS_PO)
    assert po["ers"] is True
    r = client.post("/api/stores/service-entries", headers=h,
                    json={"po_number": ERS_PO, "po_line_id": po["lines"][0]["id"], "value": value,
                          "description": "Trip Dahej to Bhiwandi"})
    assert r.status_code == 201, r.text
    return r.json()


def codes(db, inv_id: int) -> dict[str, str]:
    mid = db.scalar(select(MatchResult.id).where(MatchResult.invoice_id == inv_id).order_by(MatchResult.id.desc()))
    return {c: s for c, s in db.execute(select(ReasonCode.code, ReasonCode.severity)
                                        .where(ReasonCode.match_result_id == mid))}


def test_service_entry_on_ers_po_settles_itself_and_goes_touchless(client, db):
    out = post_trip(client)
    assert out["ers_settled"] is True and "ERS" in out["message"]
    assert "ERS-" not in out["message"]  # stores is told it was settled, never shown the payable itself
    inv = db.scalar(select(Invoice).where(Invoice.invoice_number == f"ERS-{out['number']}"))
    assert inv is not None and inv.origin == "ers" and inv.document_id is None and inv.processed_by_user_id is None
    assert inv.taxable_total == D("22000.00") and inv.igst == D("2640.00") and inv.cgst == 0
    assert inv.total == D("24640.00")
    assert inv.lines[0].qty == D("1.000") and inv.lines[0].unit_price == D("22000.00")
    assert inv.decision == "APPROVE" and inv.status == "approved"  # <= Rs 50,000: policy P-01, no human touch
    c = codes(db, inv.id)
    assert c.get("ERS_SETTLEMENT") == "info" and "POSSIBLE_DUPLICATE" not in c
    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "invoice.ers_settled",
                                            AuditEvent.entity_id == str(inv.id)))
    assert ev is not None and ev.after["receipt"] == f"SES {out['number']}"


def test_second_trip_of_the_same_value_is_not_a_duplicate(client, db):
    out = post_trip(client)
    inv = db.scalar(select(Invoice).where(Invoice.invoice_number == f"ERS-{out['number']}"))
    assert inv.decision == "APPROVE"
    assert "POSSIBLE_DUPLICATE" not in codes(db, inv.id) and "DUPLICATE" not in codes(db, inv.id)


def test_settlement_detail_shows_origin_and_receipt_sourced_fields(client, db):
    inv = db.scalar(select(Invoice).where(Invoice.origin == "ers").order_by(Invoice.id))
    login(client, CLERK)
    d = client.get(f"/api/invoices/{inv.id}").json()
    assert d["origin"] == "ers" and d["document"] is None
    assert {f["source"] for f in d["fields"]} == {"ers"} and all(f["confidence"] == 1.0 for f in d["fields"])
    assert any(r["code"] == "ERS_SETTLEMENT" for r in d["match"]["reasons"])
    sap = client.get(f"/api/invoices/{inv.id}/sap-preview").json()["posting"]
    assert any("MRRL" in w for w in sap["warnings"])
    item = sap["payload"]["to_SuplrInvcItemPurOrdRef"]["results"][0]
    assert item["ServiceEntrySheet"] == inv.invoice_number.removeprefix("ERS-")
    login(client, "freight@konkan-bulk.example")  # the supplier sees its settlement like any invoice
    assert client.get(f"/api/invoices/{inv.id}").status_code == 200


def test_supplier_invoice_for_settled_trips_is_caught(client, db):
    # Two trips (Rs 44,000) are already settled; Konkan bills them again on paper.
    inv = upload(client, db, "Konkan Bulk Carriers", "KBC/FRT/9001", ERS_PO,
                 [Line("FRT-TRK-02", "Truck freight Dahej to Bhiwandi", "996511", D(2), "TRIP", D("22000.00"), D(12))])
    c = codes(db, inv["id"])
    assert c.get("ERS_PO_INVOICE") == "flag"
    assert c.get("SES_VALUE_EXCEEDED") == "block"
    assert inv["decision"] == "BLOCK"


def test_receipt_on_a_normal_po_creates_no_settlement(client, db):
    login(client, STORES)
    pos = {p["po_number"]: p for p in client.get("/api/stores/open-pos").json()}
    assert [n for n, p in pos.items() if p["ers"]] == [ERS_PO]
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "4500001007"))  # freight, invoiced on paper
    assert ers.settle(db, po, "SES", "1999999999", [(po.lines[0], D("38000.00"))]) is None
    db.rollback()


def test_a_receipt_is_never_settled_twice(db):
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == ERS_PO))
    done = db.scalar(select(Invoice).where(Invoice.origin == "ers").order_by(Invoice.id))
    receipt = done.invoice_number.removeprefix("ERS-")
    assert ers.settle(db, po, "SES", receipt, [(po.lines[0], D("22000.00"))]) is None
    db.rollback()
