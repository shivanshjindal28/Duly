"""AP mailbox (email-in, simulated): list received emails, fetch the mailbox, compose a test email.

Staff only. Fetching and composing are clerk actions (each attachment is processed as an upload by
that clerk, on the supplier's behalf); auditors and admins can read the mailbox.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import get_db
from app.core.guard import global_budget, heavy_slot
from app.core.ratelimit import limiter
from app.core.enums import Role
from app.core.security import require_roles
from app.ingestion.email_in import AP_MAILBOX, Attachment, EmailError, check_sender, compose, process
from app.ingestion.hardening import MAX_BYTES
from app.models import InboundEmail, Supplier, User
from app.samples.inbox import sample_emails

router = APIRouter(prefix="/inbox", tags=["inbox"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.AUDITOR, Role.ADMIN))])


class EmailOut(BaseModel):
    id: int
    from_addr: str
    from_name: str | None
    subject: str
    body: str
    source: str
    sender_status: str
    sender_detail: str
    sender_supplier: str | None
    status: str
    attachments: list[dict]
    received_at: datetime


class InboxOut(BaseModel):
    mailbox: str
    simulated: bool
    emails: list[EmailOut]


class FetchOut(BaseModel):
    fetched: int
    message: str


def _out(db: Session, em: InboundEmail, names: dict[int, str]) -> EmailOut:
    return EmailOut(id=em.id, from_addr=em.from_addr, from_name=em.from_name, subject=em.subject, body=em.body,
                    source=em.source, sender_status=em.sender_status, sender_detail=check_sender(db, em.from_addr).detail,
                    sender_supplier=names.get(em.sender_supplier_id), status=em.status, attachments=em.attachments or [],
                    received_at=em.received_at)


@router.get("", response_model=InboxOut)
def inbox(db: Session = Depends(get_db)) -> InboxOut:
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    emails = db.scalars(select(InboundEmail).order_by(InboundEmail.id.desc())).all()
    return InboxOut(mailbox=AP_MAILBOX, simulated=True, emails=[_out(db, e, names) for e in emails])


@router.post("/fetch", response_model=FetchOut)
@limiter.limit("20/hour")
def fetch(request: Request, user: User = Depends(require_roles(Role.CLERK)), db: Session = Depends(get_db)) -> FetchOut:
    """Pull new mail from the simulated mailbox (already-received Message-IDs are skipped)."""
    with heavy_slot():
        got = [em for raw in sample_emails(db, clock.today()) if (em := process(db, user, raw)) is not None]
    msg = (f"{len(got)} new email{'s' if len(got) != 1 else ''} received and processed." if got
           else "No new email in the mailbox.")
    return FetchOut(fetched=len(got), message=msg)


@router.post("/compose", response_model=EmailOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(lambda: get_settings().upload_rate_limit)
def compose_email(
    request: Request,
    from_addr: str = Form(..., max_length=200),
    subject: str = Form("", max_length=300),
    body: str = Form("", max_length=4000),
    files: list[UploadFile] = File(...),
    user: User = Depends(require_roles(Role.CLERK)),
    db: Session = Depends(get_db),
) -> EmailOut:
    """Simulate an email to the AP mailbox with your own attachments."""
    if len(files) > 5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Attach at most 5 files.")
    global_budget("upload", get_settings().global_uploads_per_hour)
    atts = []
    for f in files:
        data = f.file.read(MAX_BYTES + 1)
        atts.append(Attachment(f.filename or "attachment", f.content_type or "application/octet-stream", data))
    try:
        em = compose(db, user, from_addr, subject, body, atts)
    except EmailError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    return _out(db, em, names)
