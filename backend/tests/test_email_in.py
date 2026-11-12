"""Email-in (simulated AP mailbox): sender check, attachments through the pipeline, engine reason."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.ingestion.email_in import Attachment, build_message, check_sender, parse
from app.models import AuditEvent, InboundEmail, Invoice
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice
from tests.test_approvals import login

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def test_build_and_parse_a_real_mime_email():
    raw = build_message("accounts@navrang-pack.example", "Hetal Shah, Navrang", "Invoice", "Hello",
                        [Attachment("a.pdf", "application/pdf", b"%PDF-1.4 x"), Attachment("b.png", "image/png", b"\x89PNG")],
                        message_id="<t1@navrang-pack.example>")
    p = parse(raw)
    assert (p.from_addr, p.from_name, p.to_addr, p.subject) == ("accounts@navrang-pack.example", "Hetal Shah, Navrang",
                                                                "ap@plantx.example", "Invoice")
    assert p.message_id == "<t1@navrang-pack.example>" and p.body.strip() == "Hello"
    assert [(a.filename, a.content_type, a.data) for a in p.attachments] == [
        ("a.pdf", "application/pdf", b"%PDF-1.4 x"), ("b.png", "image/png", b"\x89PNG")]


def test_sender_check_against_the_vendor_master(db):
    assert check_sender(db, "billing@navrang-pack.example").status == "verified"
    assert check_sender(db, "purchase@plantx.example").status == "internal"
    look = check_sender(db, "billing@kesar-spare.example")
    assert look.status == "lookalike" and look.supplier.code == "V100103" and "kesar-spares.example" in look.detail
    assert check_sender(db, "someone@mail.example").status == "unknown"


def test_fetching_the_mailbox_processes_each_email_once(client, db):
    h = login(client, CLERK)
    r = client.post("/api/inbox/fetch", headers=h)
    assert r.status_code == 200 and r.json()["fetched"] == 3, r.text
    assert client.post("/api/inbox/fetch", headers=h).json()["fetched"] == 0  # same Message-IDs: skipped

    emails = {e["subject"]: e for e in client.get("/api/inbox").json()["emails"]}
    clean = emails["Invoice NPW-318 for PO 4500001016"]
    assert clean["sender_status"] == "verified" and clean["status"] == "processed"
    inv = client.get(f"/api/invoices/{clean['attachments'][0]['invoice_id']}").json()
    assert inv["origin"] == "email" and inv["decision"] == "APPROVE" and inv["status"] == "approved"  # touchless
    assert inv["source_email"]["from_addr"] == "accounts@navrang-pack.example"
    assert any(r["code"] == "EMAIL_RECEIVED" for r in inv["match"]["reasons"])

    fake = emails["URGENT: Invoice INV/0081 - please pay today"]
    assert fake["sender_status"] == "lookalike" and fake["sender_supplier"] == "Kesar Engineering Spares"
    inv = client.get(f"/api/invoices/{fake['attachments'][0]['invoice_id']}").json()
    assert inv["decision"] == "FLAG"
    reason = next(r for r in inv["match"]["reasons"] if r["code"] == "EMAIL_SENDER_UNVERIFIED")
    assert "kesar-spare.example" in reason["message"] and "imitates" in reason["message"]
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "security.email_lookalike_sender")) is not None

    soa = emails["Statement of account, October 2026"]
    assert soa["status"] == "rejected" and "PDF, JPG and PNG" in soa["attachments"][0]["error"]


def test_compose_an_email_with_your_own_file(client, db):
    h = login(client, CLERK)
    pdf = render_invoice_pdf(seeded_invoice(db, invoice_number="KES/EM/0099", po_number="4500001003"))
    r = client.post("/api/inbox/compose", headers=h,
                    data={"from_addr": "someone@mail.example", "subject": "inv", "body": "see attached"},
                    files=[("files", ("KES-EM-0099.pdf", pdf, "application/pdf"))])
    assert r.status_code == 201, r.text
    em = r.json()
    assert em["source"] == "composed" and em["sender_status"] == "unknown"
    inv = db.get(Invoice, em["attachments"][0]["invoice_id"])
    assert inv.origin == "email" and inv.supplier_id is not None  # supplier found by the GSTIN on the invoice
    h = login(client, CLERK)  # a new login rotates the CSRF token
    reasons = client.get(f"/api/invoices/{inv.id}").json()["match"]["reasons"]
    assert any(r["code"] == "EMAIL_SENDER_UNVERIFIED" and r["severity"] == "flag" for r in reasons)

    bad = client.post("/api/inbox/compose", headers=h, data={"from_addr": "not-an-address"},
                      files=[("files", ("x.pdf", pdf, "application/pdf"))])
    assert bad.status_code == 422


def test_mailbox_access(client):
    for email, code in (("meera.iyer@plantx.example", 200), ("imran.shaikh@plantx.example", 403),
                        ("invoices@kesar-spares.example", 403)):
        login(client, email)
        assert client.get("/api/inbox").status_code == code, email
    h = login(client, "meera.iyer@plantx.example")
    assert client.post("/api/inbox/fetch", headers=h).status_code == 403  # auditors read, clerks fetch
