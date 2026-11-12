"""Data retention: closed invoices' old files, old chats and old email text are deleted; nothing else."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.core import clock
from app.core.enums import InvoiceStatus
from app.core.ratelimit import limiter
from app.ingestion.pages import PAGE_DIR
from app.ingestion.storage import path_of, store
from app.models import AuditEvent, ChatSession, Document, InboundEmail, Invoice, Supplier, User
from app.workflow.retention import PURGED_BODY

ADMIN = "sanjay.patil@plantx.example"
CLERK = "asha.kulkarni@plantx.example"
AUDITOR = "meera.iyer@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


@pytest.fixture
def made(db):
    rows: dict[str, list[int]] = {"inv": [], "doc": [], "chat": [], "mail": []}
    yield rows
    db.rollback()
    db.execute(delete(Invoice).where(Invoice.id.in_(rows["inv"])))
    db.execute(delete(Document).where(Document.id.in_(rows["doc"])))
    db.execute(delete(ChatSession).where(ChatSession.id.in_(rows["chat"])))
    db.execute(delete(InboundEmail).where(InboundEmail.id.in_(rows["mail"])))
    db.commit()


def _doc_with_invoice(db, made, number: str, age_days: int, status: InvoiceStatus) -> tuple[Document, Invoice]:
    name = store(b"%PDF-1.4 test file for retention", "pdf")
    stem = name.rsplit(".", 1)[0]
    PAGE_DIR.mkdir(parents=True, exist_ok=True)
    (PAGE_DIR / f"{stem}-1.png").write_bytes(b"png")
    when = clock.now() - timedelta(days=age_days)
    doc = Document(original_filename=f"{number}.pdf", stored_name=name, mime_type="application/pdf", size_bytes=30,
                   sha256=number.ljust(64, "0")[:64], pages=1, uploaded_at=when)
    db.add(doc)
    db.flush()
    s = db.scalar(select(Supplier).where(Supplier.code == "V100103"))
    inv = Invoice(supplier_id=s.id, document_id=doc.id, invoice_number=number, invoice_number_norm=number,
                  invoice_date=date(2017, 1, 1), status=status, current_owner="x", received_at=when)
    db.add(inv)
    db.commit()
    made["doc"].append(doc.id)
    made["inv"].append(inv.id)
    return doc, inv


def test_retention_preview_access_and_policy_limits(client):
    login(client, AUDITOR)
    r = client.get("/api/policy/retention")
    assert r.status_code == 200
    j = r.json()
    assert j["settings"] == {"documents_years": 8, "chat_days": 180, "email_body_days": 365} and j["can_run"] is False
    assert "Audit trail" in j["never_deleted"]
    h = login(client, CLERK)
    assert client.post("/api/policy/retention/run", headers=h).status_code == 403
    login(client, "invoices@kesar-spares.example")
    assert client.get("/api/policy/retention").status_code == 403
    # The legal minimum cannot be undercut in the policy editor.
    h = login(client, ADMIN)
    r = client.post("/api/policy", headers=h, json={"changes": {"retention.documents_years": 5}, "reason": "Shorter retention test"})
    assert r.status_code == 422 and "between 6 and 20" in r.json()["detail"]


def test_run_deletes_only_what_is_due(client, db, made):
    old_paid, old_paid_inv = _doc_with_invoice(db, made, "RET-OLD-PAID", 9 * 366, InvoiceStatus.PAID)
    old_open, _ = _doc_with_invoice(db, made, "RET-OLD-OPEN", 9 * 366, InvoiceStatus.BLOCKED)
    new_paid, _ = _doc_with_invoice(db, made, "RET-NEW-PAID", 30, InvoiceStatus.PAID)
    user = db.scalar(select(User).where(User.email == "invoices@kesar-spares.example"))
    old_chat = ChatSession(user_id=user.id, messages=[{"q": "x"}], started_at=clock.now() - timedelta(days=200))
    new_chat = ChatSession(user_id=user.id, messages=[{"q": "y"}], started_at=clock.now() - timedelta(days=10))
    mail = InboundEmail(message_id="<retention-test@x.example>", from_addr="a@x.example", to_addr="ap@plantx.example",
                        subject="Old invoice", body="Please find attached", sender_status="unknown",
                        received_at=clock.now() - timedelta(days=400), status="processed")
    db.add_all([old_chat, new_chat, mail])
    db.commit()
    old_chat_id, new_chat_id, mail_id = old_chat.id, new_chat.id, mail.id
    made["chat"] += [old_chat_id, new_chat_id]
    made["mail"].append(mail_id)

    login(client, AUDITOR)
    due = client.get("/api/policy/retention").json()["due"]
    assert due["documents"] >= 1 and due["documents_kept_open_invoice"] >= 1 and due["chats"] >= 1 and due["email_texts"] >= 1

    h = login(client, ADMIN)
    r = client.post("/api/policy/retention/run", headers=h)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["documents_deleted"] >= 1 and res["chats_deleted"] >= 1 and res["email_texts_deleted"] >= 1
    assert r.json()["due"]["documents"] == 0

    db.expire_all()
    assert db.get(Document, old_paid.id).purged_at is not None
    assert not path_of(old_paid.stored_name).exists()
    assert not (PAGE_DIR / f"{old_paid.stored_name.rsplit('.', 1)[0]}-1.png").exists()
    assert db.get(Document, old_paid.id).sha256.startswith("RET-OLD-PAID")  # hash kept for duplicate checks
    assert db.get(Document, old_open.id).purged_at is None and path_of(old_open.stored_name).exists()
    assert db.get(Document, new_paid.id).purged_at is None
    assert db.get(ChatSession, old_chat_id) is None and db.get(ChatSession, new_chat_id) is not None
    assert db.get(InboundEmail, mail_id).body == PURGED_BODY and db.get(InboundEmail, mail_id).subject == "Old invoice"
    assert db.get(Invoice, old_paid_inv.id) is not None  # the invoice record stays

    login(client, CLERK)
    assert client.get(f"/api/invoices/{old_paid_inv.id}/document").status_code == 410
    assert client.get(f"/api/invoices/{old_paid_inv.id}/pages/1.png").status_code == 410
    d = client.get(f"/api/invoices/{old_paid_inv.id}").json()
    assert d["document"]["purged_at"] is not None
    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "retention.run").order_by(AuditEvent.id.desc()))
    assert ev.after["documents_deleted"] == res["documents_deleted"] and "Sanjay" in ev.after["trigger"]

    for f in (old_open, new_paid):  # leave no stray files behind
        path_of(f.stored_name).unlink(missing_ok=True)
        (PAGE_DIR / f"{f.stored_name.rsplit('.', 1)[0]}-1.png").unlink(missing_ok=True)
