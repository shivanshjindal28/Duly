"""Credit notes: an over-billed invoice is resolved by the supplier's credit note, not by an override."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.ratelimit import limiter
from app.models import AuditEvent, GoodsReceipt, GRLine, POLine, PurchaseOrder, Supplier, User
from app.payments.run import plan
from app.samples.invoice_pdf import Line
from tests.test_approvals import login, upload
from tests.test_engine import invoice, line, po, po_line, run

CLERK = "asha.kulkarni@plantx.example"
KESAR = "invoices@kesar-spares.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def make_po(db, po_no: str, gr_no: str, item: str) -> PurchaseOrder:
    """A Kesar PO for 100 bearings where stores received 80 (one PO per test keeps them independent)."""
    kesar = db.scalar(select(Supplier).where(Supplier.code == "V100103"))
    stores = db.scalar(select(User).where(User.email == "imran.shaikh@plantx.example"))
    p = PurchaseOrder(po_number=po_no, supplier_id=kesar.id, po_date=clock.today() - timedelta(days=20),
                      payment_terms_days=45)
    db.add(p)
    db.flush()
    pl = POLine(po_id=p.id, line_no=10, item_code=item, description=f"Ball bearing {item[4:]} 2RS", hsn_sac="8482",
                qty=D(100), uom="NOS", unit_price=D("450.00"), gst_rate=D(18))
    db.add(pl)
    db.flush()
    gr = GoodsReceipt(gr_number=gr_no, po_id=p.id, posted_by_user_id=stores.id,
                      posted_at=clock.now() - timedelta(days=3))
    db.add(gr)
    db.flush()
    db.add(GRLine(gr_id=gr.id, po_line_id=pl.id, qty=D(80), uom="NOS"))
    db.commit()
    return p


def _upload_100(client, db, number, po_no, item):
    make_po(db, po_no, "50" + po_no[2:], item)
    return upload(client, db, "Kesar Engineering Spares", number, po_no,
                  [Line(item, f"Ball bearing {item[4:]} 2RS", "8482", D(100), "NOS", D("450.00"), D(18))])


def _credit(client, inv_id, number="CN/0071", qty="20", note_date=None, who=KESAR):
    h = login(client, who)
    return client.post(f"/api/invoices/{inv_id}/credit-notes", headers=h, json={
        "number": number, "note_date": (note_date or date(2026, 11, 10)).isoformat(),
        "reason": "20 bearings not delivered", "lines": [{"line_no": 1, "qty": qty}]})


def test_engine_matches_net_of_credited_quantity():
    view = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=80)])
    gross, _ = run(invoice([line(1, "BRG-6205", 100, "NOS", "450.00")]), view)
    assert gross.decision == "BLOCK"
    net, _ = run(invoice([replace(line(1, "BRG-6205", 100, "NOS", "450.00"), credited_qty=D(20))]), view)
    assert net.decision == "APPROVE", [r.code for r in net.reasons]
    assert net.matrix[0].invoice_qty == 80


def test_supplier_credit_note_releases_the_block_and_pays_net(client, db):
    inv = _upload_100(client, db, "INV/7101", "4599000101", "BRG-6206")
    assert inv["decision"] == "BLOCK" and any(r["code"] == "QTY_EXCEEDS_GR" for r in inv["match"]["reasons"])
    assert inv["can_issue_credit"] is True
    s = inv["credit_suggestion"]
    assert len(s) == 1 and D(s[0]["qty"]) == 20 and D(s[0]["value"]) == D("9000.00") and D(s[0]["total"]) == D("10620.00")

    r = _credit(client, inv["id"])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["decision"] == "APPROVE"
    assert D(d["total"]) == D("53100.00") and D(d["net_total"]) == D("42480.00")  # the printed invoice is unchanged
    assert d["status"] == "approved"  # net Rs 42,480 is within the touchless limit: policy P-01
    assert any(r["code"] == "CREDIT_NOTE_APPLIED" for r in d["match"]["reasons"])
    assert d["credit_notes"][0]["number"] == "CN/0071" and d["credit_notes"][0]["entered_by"] == "Dinesh Patel"
    assert d["can_issue_credit"] is False
    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "credit_note.applied",
                                            AuditEvent.entity_id == str(d["id"])))
    assert ev is not None and ev.after["net_payable"] == "42480.00"

    item = next(i for i in plan(db).items if i.invoice_id == d["id"])
    assert item.gross == D("42480.00") and item.taxable == D("36000.00")


def test_credit_note_rules(client, db):
    inv = _upload_100(client, db, "INV/7102", "4599000102", "BRG-6207")
    bad = [
        _credit(client, inv["id"], number="CN/0071"),  # number already used by Kesar
        _credit(client, inv["id"], number="CN/0072", qty="101"),  # more than billed
        _credit(client, inv["id"], number="CN/0073", note_date=clock.today() + timedelta(days=2)),  # future
        _credit(client, inv["id"], number="CN/0074", note_date=date(2026, 11, 1)),  # before the invoice date
    ]
    assert [b.status_code for b in bad] == [422, 422, 422, 422]
    assert "already used" in bad[0].json()["detail"] and "cannot credit more" in bad[1].json()["detail"]
    # A partial credit leaves it blocked, with the remaining excess; the clerk can add the rest.
    r = _credit(client, inv["id"], number="CN/0075", qty="5")
    assert r.status_code == 201 and r.json()["decision"] == "BLOCK"
    assert D(r.json()["credit_suggestion"][0]["qty"]) == 15
    r = _credit(client, inv["id"], number="CN/0076", qty="15", who=CLERK)
    assert r.status_code == 201 and r.json()["decision"] == "APPROVE" and len(r.json()["credit_notes"]) == 2
    # Approved now: no more credit notes.
    assert _credit(client, inv["id"], number="CN/0077", qty="1").status_code == 422


def test_other_suppliers_and_staff_roles_cannot_issue(client, db):
    inv = _upload_100(client, db, "INV/7103", "4599000103", "BRG-6208")
    assert _credit(client, inv["id"], number="CN/0081", who="accounts@navrang-pack.example").status_code == 404
    assert _credit(client, inv["id"], number="CN/0082", who="rohan.mehta@plantx.example").status_code == 403


def test_a_blocked_duplicate_gets_no_credit_note(client, db):
    _upload_100(client, db, "INV/7104", "4599000104", "BRG-6209")
    again = upload(client, db, "Kesar Engineering Spares", "INV/7104", "4599000104",
                   [Line("BRG-6209", "Ball bearing 6209 2RS", "8482", D(100), "NOS", D("450.00"), D(18))])
    assert any(r["code"] == "DUPLICATE" for r in again["match"]["reasons"])
    assert again["can_issue_credit"] is False and again["credit_suggestion"] == []
    r = _credit(client, again["id"], number="CN/0091")
    assert r.status_code == 422 and "duplicate" in r.json()["detail"]
