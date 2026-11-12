"""Email-in (simulated): invoices that suppliers send to the AP mailbox.

No mail server is involved (the demo must run offline). Messages are real RFC 5322 emails
(built with the standard `email` package) that Duly "fetches" from a simulated mailbox or that a
clerk composes in the app. For each message Duly:

1. checks the sender against the vendor master: the domain of a supplier's registered addresses
   (verified), Plant X's own domain (internal: a buyer forwarding an invoice), a domain that imitates
   a supplier's (lookalike: a classic payment-fraud trick, raises a security alert), or anything else;
2. sends every PDF / JPG / PNG attachment through the normal upload pipeline (hardening, OCR / text,
   GSTIN-based supplier identification, rules engine), as the clerk who fetched the mail;
3. records what happened to each attachment (invoice and decision, or why it was rejected).

The rules engine then sees EMAIL_SENDER_UNVERIFIED (flag) when the sender is not a registered
address of the supplier the invoice belongs to. The email never decides anything by itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, formataddr, make_msgid, parseaddr

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock, jobs
from app.core.enums import Role, Severity
from app.engine.types import Reason
from app.models import InboundEmail, Invoice, Supplier, User

AP_MAILBOX = "ap@plantx.example"
INVOICE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
LOOKALIKE_MIN = 85  # rapidfuzz ratio between two different domains that counts as imitation
MAX_ATTACHMENTS = 10
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class EmailError(ValueError):
    """User-facing problem with a composed email."""


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class Parsed:
    message_id: str
    from_addr: str
    from_name: str | None
    to_addr: str
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


def build_message(from_addr: str, from_name: str | None, subject: str, body: str,
                  attachments: list[Attachment], message_id: str | None = None) -> bytes:
    """A real MIME email, as a mail server would hand it over."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr  # quotes names with commas
    msg["To"] = AP_MAILBOX
    msg["Subject"] = subject
    msg["Date"] = format_datetime(clock.now())
    msg["Message-ID"] = message_id or make_msgid(domain=domain_of(from_addr) or "duly.local")
    msg.set_content(body or "")
    for a in attachments:
        maintype, _, subtype = (a.content_type or "application/octet-stream").partition("/")
        msg.add_attachment(a.data, maintype=maintype, subtype=subtype or "octet-stream", filename=a.filename)
    return msg.as_bytes()


def parse(raw: bytes) -> Parsed:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    name, addr = parseaddr(str(msg.get("From", "")))
    body_part = msg.get_body(preferencelist=("plain",))
    attachments = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        attachments.append(Attachment(part.get_filename() or "attachment", part.get_content_type(), data))
    return Parsed(
        message_id=str(msg.get("Message-ID", "")).strip() or make_msgid(domain="duly.local"),
        from_addr=addr.lower(), from_name=name or None, to_addr=parseaddr(str(msg.get("To", "")))[1].lower(),
        subject=str(msg.get("Subject", ""))[:300], body=(body_part.get_content() if body_part else "")[:4000],
        attachments=attachments,
    )


def domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def _supplier_domains(db: Session) -> dict[str, Supplier]:
    """Registered email domains per supplier: vendor master contact plus its portal users."""
    out: dict[str, Supplier] = {}
    suppliers = {s.id: s for s in db.scalars(select(Supplier))}
    for s in suppliers.values():
        out.setdefault(domain_of(s.contact_email), s)
    for u in db.scalars(select(User).where(User.role == Role.SUPPLIER)):
        if u.supplier_id in suppliers:
            out.setdefault(domain_of(u.email), suppliers[u.supplier_id])
    out.pop("", None)
    return out


def _internal_domains(db: Session) -> set[str]:
    return {domain_of(u.email) for u in db.scalars(select(User).where(User.role != Role.SUPPLIER))} - {""}


@dataclass
class SenderCheck:
    status: str  # verified | internal | lookalike | unknown
    supplier: Supplier | None  # matched supplier, or the one a lookalike imitates
    detail: str


def check_sender(db: Session, addr: str) -> SenderCheck:
    dom = domain_of(addr)
    known = _supplier_domains(db)
    if dom in known:
        return SenderCheck("verified", known[dom], f"{dom} is registered for {known[dom].name}")
    if dom in _internal_domains(db):
        return SenderCheck("internal", None, f"{dom} is Plant X's own domain (forwarded by a colleague)")
    best = max(known.items(), key=lambda kv: fuzz.ratio(dom, kv[0]), default=None)
    if best and fuzz.ratio(dom, best[0]) >= LOOKALIKE_MIN:
        return SenderCheck("lookalike", best[1], f"{dom} imitates {best[0]}, registered for {best[1].name}")
    return SenderCheck("unknown", None, f"{dom or 'no domain'} is not on the vendor master")


def process(db: Session, user: User, raw: bytes, source: str = "mailbox") -> InboundEmail | None:
    """Receive one email: sender check, then every attachment through the upload pipeline.
    Returns None if this Message-ID was already received (a mailbox is fetched again and again)."""
    from app.ingestion.hardening import UploadRejected
    from app.ingestion.pipeline import UploadError, process_upload

    p = parse(raw)
    if db.scalar(select(InboundEmail.id).where(InboundEmail.message_id == p.message_id)):
        return None
    sender = check_sender(db, p.from_addr)
    em = InboundEmail(message_id=p.message_id, from_addr=p.from_addr, from_name=p.from_name,
                      to_addr=p.to_addr or AP_MAILBOX, subject=p.subject, body=p.body, source=source,
                      sender_status=sender.status, sender_supplier_id=sender.supplier.id if sender.supplier else None,
                      fetched_by_user_id=user.id, received_at=clock.now())
    db.add(em)
    db.flush()
    if sender.status == "lookalike":
        audit.queue(db, "security.email_lookalike_sender", "inbound_email", em.id, actor=audit.SYSTEM,
                    after={"from": p.from_addr, "imitates": sender.supplier.code, "detail": sender.detail})
    db.commit()  # the email is on record even if an attachment fails

    results = []
    for a in p.attachments[:MAX_ATTACHMENTS]:
        row = {"filename": a.filename[:120], "content_type": a.content_type, "size": len(a.data)}
        if not a.filename.lower().endswith(INVOICE_EXTENSIONS):
            results.append({**row, "outcome": "rejected",
                            "error": "Not an invoice file: Duly reads PDF, JPG and PNG attachments only."})
            continue
        try:
            inv = jobs.enqueue("process_email_attachment", process_upload, db, user, a.filename, a.data, None,
                               source_email_id=em.id).result
        except (UploadRejected, UploadError) as e:
            db.rollback()
            results.append({**row, "outcome": "rejected", "error": str(e)})
            continue
        results.append({**row, "outcome": "invoice", "invoice_id": inv.id, "invoice_number": inv.invoice_number,
                        "decision": inv.decision, "status": inv.status})
    em = db.get(InboundEmail, em.id)
    made = sum(r["outcome"] == "invoice" for r in results)
    em.attachments = results
    em.status = ("no_attachment" if not results else "processed" if made == len(results)
                 else "partly" if made else "rejected")
    audit.queue(db, "email.received", "inbound_email", em.id, after={
        "from": p.from_addr, "subject": p.subject[:120], "sender_status": sender.status, "source": source,
        "attachments": [{k: r.get(k) for k in ("filename", "outcome", "invoice_number", "decision", "error")}
                        for r in results],
    })
    db.commit()
    return em


def compose(db: Session, user: User, from_addr: str, subject: str, body: str, files: list[Attachment]) -> InboundEmail:
    """A clerk 'sends' an email to the AP mailbox (for trying Duly with any file)."""
    from_addr = (from_addr or "").strip().lower()
    if not _EMAIL_RE.match(from_addr):
        raise EmailError("Enter a sender email address, for example accounts@navrang-pack.example.")
    if not files:
        raise EmailError("Attach at least one file.")
    if len(files) > MAX_ATTACHMENTS:
        raise EmailError(f"At most {MAX_ATTACHMENTS} attachments.")
    em = process(db, user, build_message(from_addr, None, subject or "(no subject)", body, files), source="composed")
    assert em is not None  # a fresh Message-ID is never a repeat
    return em


def email_reasons(db: Session, inv: Invoice) -> list[Reason]:
    """Engine input: was an emailed invoice sent from a registered address of its own supplier?"""
    if not inv.source_email_id:
        return []
    em = db.get(InboundEmail, inv.source_email_id)
    if em is None:
        return []
    supplier = db.get(Supplier, inv.supplier_id) if inv.supplier_id else None
    name = supplier.name if supplier else "the supplier"
    ev = {"from": em.from_addr, "sender_status": em.sender_status,
          "registered": supplier.contact_email if supplier else None}
    if em.sender_status == "internal" or (em.sender_status == "verified" and em.sender_supplier_id == inv.supplier_id):
        how = "forwarded internally" if em.sender_status == "internal" else f"a registered address of {name}"
        return [Reason("EMAIL_RECEIVED", Severity.INFO, f"Received by email from {em.from_addr} ({how}).", ev)]
    if em.sender_status == "lookalike":
        imitated = db.get(Supplier, em.sender_supplier_id) if em.sender_supplier_id else None
        msg = (f"Emailed from {em.from_addr}: the domain {domain_of(em.from_addr)} imitates "
               f"{domain_of(imitated.contact_email) if imitated else 'a registered supplier domain'}. "
               "Confirm with the supplier on a known phone number before paying.")
    elif em.sender_status == "verified":
        other = db.get(Supplier, em.sender_supplier_id)
        msg = (f"Emailed from {em.from_addr}, an address of {other.name if other else 'another supplier'}, "
               f"but the invoice is from {name}. Check who really sent it.")
    else:
        msg = (f"Emailed from {em.from_addr}, which is not a registered address of {name} "
               f"({supplier.contact_email if supplier else 'none on file'}). Check who sent it.")
    return [Reason("EMAIL_SENDER_UNVERIFIED", Severity.FLAG, msg, ev)]
