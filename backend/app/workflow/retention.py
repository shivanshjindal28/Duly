"""Data retention (spec 12, privacy and data minimisation): delete what Duly no longer needs.

Periods come from the active policy (`retention`), editable by an admin on the Policy page.

  Invoice documents  the original file and its rendered page images are deleted once every invoice
                     using the file is closed (paid or rejected) and the file is older than
                     `documents_years`. The Document row stays with its SHA-256 and pHash, so a
                     resubmitted copy is still caught as a duplicate, and the invoice data (the books
                     of account) stays.
  Chat transcripts   payment-assistant sessions older than `chat_days` are deleted.
  Email text         the body of AP-mailbox emails older than `email_body_days` is replaced by a
                     note; sender, subject and the resulting invoices stay.

Never deleted here: the audit trail (it is the evidence that all this happened), invoices, payments,
extraction results. Open invoices keep their documents whatever their age. Every run is audited
with counts only (no content).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.enums import InvoiceStatus
from app.ingestion.pages import PAGE_DIR
from app.ingestion.storage import path_of
from app.models import ChatSession, Document, InboundEmail, Invoice, Policy
from app.models.base import as_utc

DEFAULTS = {"documents_years": 8, "chat_days": 180, "email_body_days": 365}
CLOSED = {InvoiceStatus.PAID, InvoiceStatus.REJECTED}
PURGED_BODY = "[Message text deleted under the data retention policy.]"


@dataclass
class Cutoffs:
    documents_before: datetime
    chats_before: datetime
    email_bodies_before: datetime
    settings: dict


@dataclass
class Plan:
    cutoffs: Cutoffs
    document_ids: list[int]
    documents_kept_open: int  # old enough, but an invoice using the file is still open
    chat_ids: list[int]
    email_ids: list[int]


def cutoffs(db: Session) -> Cutoffs:
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True))).data
    r = {**DEFAULTS, **(policy.get("retention") or {})}
    now = clock.now()
    return Cutoffs(now - timedelta(days=round(365.25 * r["documents_years"])), now - timedelta(days=r["chat_days"]),
                   now - timedelta(days=r["email_body_days"]), r)


def plan(db: Session) -> Plan:
    c = cutoffs(db)
    open_by_doc: dict[int, bool] = {}
    for doc_id, status in db.execute(select(Invoice.document_id, Invoice.status).where(Invoice.document_id.is_not(None))):
        open_by_doc[doc_id] = open_by_doc.get(doc_id, False) or status not in CLOSED
    docs, kept = [], 0
    for d in db.scalars(select(Document).where(Document.purged_at.is_(None))):
        if as_utc(d.uploaded_at) >= c.documents_before:
            continue
        if open_by_doc.get(d.id, False):
            kept += 1
        else:
            docs.append(d.id)
    chats = [s.id for s in db.scalars(select(ChatSession)) if as_utc(s.started_at) < c.chats_before]
    emails = [e.id for e in db.scalars(select(InboundEmail).where(InboundEmail.body != PURGED_BODY))
              if as_utc(e.received_at) < c.email_bodies_before]
    return Plan(c, docs, kept, chats, emails)


def _delete_files(stored_name: str, pages: int) -> None:
    stem = stored_name.rsplit(".", 1)[0]
    try:
        path_of(stored_name).unlink(missing_ok=True)
    except ValueError:
        pass
    for n in range(1, max(pages, 1) + 1):
        (PAGE_DIR / f"{stem}-{n}.png").unlink(missing_ok=True)


def run(db: Session, actor_note: str = "manual") -> dict:
    """Apply the retention policy now. Returns the counts (also written to the audit trail)."""
    p = plan(db)
    now = clock.now()
    for d in db.scalars(select(Document).where(Document.id.in_(p.document_ids))):
        _delete_files(d.stored_name, d.pages)
        d.purged_at = now
    for s in db.scalars(select(ChatSession).where(ChatSession.id.in_(p.chat_ids))):
        db.delete(s)
    for e in db.scalars(select(InboundEmail).where(InboundEmail.id.in_(p.email_ids))):
        e.body = PURGED_BODY
    out = {"documents_deleted": len(p.document_ids), "documents_kept_open_invoice": p.documents_kept_open,
           "chats_deleted": len(p.chat_ids), "email_texts_deleted": len(p.email_ids),
           "settings": p.cutoffs.settings, "trigger": actor_note}
    audit.queue(db, "retention.run", "retention", None, after=out)
    db.commit()
    return out
