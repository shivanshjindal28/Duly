"""Upload -> hardening -> storage -> text layer / OCR -> extraction -> persisted invoice.

Deterministic first, AI second (Phase 2), rules decide (Phase 1 step 5). Every extracted
field is stored with its confidence and location; fields below the policy threshold send
the invoice to human review.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import offline_parser
from app.ai.schema import ExtractedInvoice
from app.core import audit
from app.core.crypto import encrypt_str
from app.ingestion.extract_text import acquire_tokens
from app.ingestion.hardening import harden
from app.ingestion.storage import sha256, store
from app.core.enums import InvoiceStatus, Role
from app.models import Document, ExtractionResult, Invoice, InvoiceLine, Policy, Supplier, User
from app.validation.rules import fiscal_year
from app.workflow.matching import run_match

# Fields that must be read reliably before the rules can run on an invoice.
KEY_FIELDS = ("supplier_gstin", "invoice_number", "invoice_date", "po_number", "total")


class UploadError(ValueError):
    """User-facing problem with an upload that passed hardening (e.g. unknown supplier)."""


def dec(value: str | None) -> Decimal:
    try:
        return Decimal(value) if value not in (None, "") else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def normalise_invoice_number(number: str) -> str:
    """Canonical form for duplicate checks: 'INV/0042' and 'inv-42' both become '42'."""
    s = number.upper().translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    s = "".join(ch for ch in s if ch.isalnum())
    for prefix in ("1NV", "INV", "B1LL", "BILL"):
        if s.startswith(prefix) and len(s) > len(prefix):
            s = s[len(prefix):]
            break
    return s.lstrip("0") or "0"


def confidence_threshold(db: Session) -> float:
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True)))
    return float(policy.data.get("confidence_threshold", 0.85)) if policy else 0.85


def latest_fields(db: Session, invoice_id: int) -> dict[str, ExtractionResult]:
    """Latest extraction row per field (human review rows are appended, never overwritten)."""
    rows = db.scalars(select(ExtractionResult).where(ExtractionResult.invoice_id == invoice_id)
                      .order_by(ExtractionResult.id)).all()
    return {r.field: r for r in rows}


def pending_review(db: Session, invoice_id: int) -> list[str]:
    """The single definition of "needs a human": a field below the confidence threshold that
    nobody has reviewed yet, or a key field that could not be read. (No readable lines at all
    is not a review item: the engine blocks it with NO_LINES.)"""
    threshold = confidence_threshold(db)
    latest = latest_fields(db, invoice_id)
    low = [k for k, r in latest.items() if r.source != "manual" and r.value is not None and r.confidence < threshold]
    missing = [k for k in KEY_FIELDS if k in latest and latest[k].value is None]
    return low + missing


def _resolve_supplier(db: Session, user: User, supplier_id: int | None, extracted: ExtractedInvoice) -> Supplier:
    if user.role == Role.SUPPLIER:
        return db.get(Supplier, user.supplier_id)
    if supplier_id is not None:
        supplier = db.get(Supplier, supplier_id)
        if supplier is None:
            raise UploadError("Unknown supplier.")
        return supplier
    gstin = extracted.get("supplier_gstin")
    supplier = db.scalar(select(Supplier).where(Supplier.gstin == gstin)) if gstin else None
    if supplier is None:
        raise UploadError("Could not identify the supplier from the document. Choose the supplier and upload again.")
    return supplier


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def process_upload(db: Session, user: User, filename: str, data: bytes, supplier_id: int | None = None) -> Invoice:
    clean = harden(filename, data)
    tokens, method = acquire_tokens(clean.data, clean.kind)
    extracted = offline_parser.parse(tokens, method)
    supplier = _resolve_supplier(db, user, supplier_id, extracted)

    doc = Document(
        original_filename=filename[:255], stored_name=store(clean.data, clean.kind), mime_type=clean.mime,
        size_bytes=len(clean.data), sha256=sha256(clean.data), pages=clean.pages, uploaded_by_user_id=user.id,
    )
    db.add(doc)
    db.flush()

    h = extracted.header
    number = h["invoice_number"].value or ""
    inv_date = _date(h["invoice_date"].value)
    po_text = h["po_number"].value
    account = h["bank_account"].value
    invoice = Invoice(
        supplier_id=supplier.id, document_id=doc.id, po_number_text=po_text,
        invoice_number=number, invoice_number_norm=normalise_invoice_number(number) if number else "",
        invoice_date=inv_date, fiscal_year=fiscal_year(inv_date) if inv_date else None,
        irn=h["irn"].value, supplier_gstin=h["supplier_gstin"].value, buyer_gstin=h["buyer_gstin"].value,
        place_of_supply=h["place_of_supply"].value, currency=h["currency"].value or "INR",
        taxable_total=dec(h["taxable_total"].value), cgst=dec(h["cgst"].value), sgst=dec(h["sgst"].value),
        igst=dec(h["igst"].value), total=dec(h["total"].value),
        bank_account_enc=encrypt_str(account) if account else None,
        bank_account_last4=account[-4:] if account else None, bank_ifsc=h["bank_ifsc"].value,
        ai_mode="offline", processed_by_user_id=user.id if user.role == Role.CLERK else None,
    )
    db.add(invoice)
    db.flush()

    for i, ln in enumerate(extracted.lines, start=1):
        db.add(InvoiceLine(
            invoice_id=invoice.id, line_no=i, item_code=ln["item_code"].value,
            description=ln["description"].value or "", hsn_sac=ln["hsn_sac"].value, qty=dec(ln["qty"].value),
            uom=ln["uom"].value or "", unit_price=dec(ln["unit_price"].value),
            taxable_value=dec(ln["taxable_value"].value), gst_rate=dec(ln["gst_rate"].value),
            cgst=dec(ln["cgst"].value), sgst=dec(ln["sgst"].value), igst=dec(ln["igst"].value),
        ))

    for path, f in extracted.all_fields():
        value = f.value
        if path == "bank_account" and value:
            value = "X" * (len(value) - 4) + value[-4:]  # never store the plain account in extraction logs
        db.add(ExtractionResult(
            invoice_id=invoice.id, field=path, value=value, confidence=f.confidence, page=f.page,
            bbox=list(f.bbox) if f.bbox else None, source=f.source, model=extracted.extractor,
            prompt_version=extracted.extractor_version,
        ))

    db.flush()
    if pending_review(db, invoice.id):
        invoice.status, invoice.current_owner = InvoiceStatus.NEEDS_REVIEW, "AP clerk (review)"
    db.flush()
    db.refresh(invoice)  # load lines for the engine
    audit.queue(db, "invoice.uploaded", "invoice", invoice.id, after={
        "invoice_number": number, "supplier": supplier.code, "file": filename[:120], "sha256": doc.sha256,
        "pages": doc.pages, "text_source": extracted.method, "extractor": extracted.extractor_version,
        "ai_mode": "offline", "fields": len(extracted.all_fields()),
        "needs_review": pending_review(db, invoice.id),
    })
    run_match(db, invoice, trigger="upload")
    db.commit()
    db.refresh(invoice)
    return invoice
