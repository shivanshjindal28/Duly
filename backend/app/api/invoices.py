"""Invoice endpoints with row-level supplier scoping.

Every query goes through `get_scope`: a supplier only ever sees its own invoices, and a
request for another supplier's invoice returns 404 (not 403) so existence is not revealed.
Stores users cannot touch invoices. Upload is open to suppliers (own invoices) and AP
clerks (on behalf of a supplier, e.g. invoices received by email).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import SupplierScope, get_scope, require_roles
from app.ingestion.hardening import MAX_BYTES, UploadRejected
from app.ingestion.pages import page_png
from app.ingestion.pipeline import UploadError, confidence_threshold, process_upload
from app.ingestion.storage import path_of
from app.models import Document, ExtractionResult, Invoice, Supplier, User
from app.models.enums import Role
from app.workflow.matching import validate_invoice

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(require_roles(Role.SUPPLIER, Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))],
)


class InvoiceSummary(BaseModel):
    id: int
    supplier_id: int | None
    supplier_name: str | None
    invoice_number: str
    invoice_date: date | None
    po_number: str | None
    total: Decimal
    status: str
    decision: str | None
    current_owner: str
    received_at: datetime


class LineOut(BaseModel):
    line_no: int
    item_code: str | None
    description: str
    hsn_sac: str | None
    qty: Decimal
    uom: str
    unit_price: Decimal
    taxable_value: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


class FieldOut(BaseModel):
    field: str
    value: str | None
    confidence: float
    page: int | None
    bbox: list[float] | None
    source: str
    needs_review: bool


class ReasonOut(BaseModel):
    code: str
    severity: str
    message: str
    evidence: dict
    line_no: int | None


class DocumentOut(BaseModel):
    original_filename: str
    mime_type: str
    pages: int
    sha256: str
    size_bytes: int


class InvoiceDetail(InvoiceSummary):
    supplier_gstin: str | None
    buyer_gstin: str | None
    place_of_supply: str | None
    currency: str
    taxable_total: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    bank_account_masked: str | None
    bank_ifsc: str | None
    irn: str | None
    ai_mode: str | None
    lines: list[LineOut]
    document: DocumentOut | None
    fields: list[FieldOut]
    confidence_threshold: float
    validation: list[ReasonOut]


def _summary_kwargs(inv: Invoice, supplier_name: str | None) -> dict:
    return dict(
        id=inv.id, supplier_id=inv.supplier_id, supplier_name=supplier_name, invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date, po_number=inv.po_number_text, total=inv.total, status=inv.status,
        decision=inv.decision, current_owner=inv.current_owner, received_at=inv.received_at,
    )


def get_invoice_in_scope(invoice_id: int, scope: SupplierScope, db: Session) -> Invoice:
    """Load an invoice or 404 if it does not exist or is outside the caller's scope."""
    inv = db.get(Invoice, invoice_id)
    if inv is None or not scope.allows(inv.supplier_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


def _detail(db: Session, inv: Invoice) -> InvoiceDetail:
    supplier = db.get(Supplier, inv.supplier_id) if inv.supplier_id else None
    doc = db.get(Document, inv.document_id) if inv.document_id else None
    threshold = confidence_threshold(db)
    results = db.scalars(select(ExtractionResult).where(ExtractionResult.invoice_id == inv.id)
                         .order_by(ExtractionResult.id)).all()
    # Latest result per field wins (human corrections are appended, never overwritten).
    latest: dict[str, ExtractionResult] = {}
    for r in results:
        latest[r.field] = r
    return InvoiceDetail(
        **_summary_kwargs(inv, supplier.name if supplier else None),
        supplier_gstin=inv.supplier_gstin, buyer_gstin=inv.buyer_gstin, place_of_supply=inv.place_of_supply,
        currency=inv.currency, taxable_total=inv.taxable_total, cgst=inv.cgst, sgst=inv.sgst, igst=inv.igst,
        bank_account_masked=("XXXXXX" + inv.bank_account_last4) if inv.bank_account_last4 else None,
        bank_ifsc=inv.bank_ifsc, irn=inv.irn, ai_mode=inv.ai_mode,
        lines=[LineOut.model_validate(ln, from_attributes=True) for ln in inv.lines],
        document=DocumentOut.model_validate(doc, from_attributes=True) if doc else None,
        fields=[FieldOut(field=r.field, value=r.value, confidence=r.confidence, page=r.page, bbox=r.bbox,
                         source=r.source, needs_review=r.source != "manual" and r.value is not None
                         and r.confidence < threshold)
                for r in latest.values()],
        confidence_threshold=threshold,
        validation=[ReasonOut(code=r.code, severity=r.severity, message=r.message, evidence=r.evidence,
                              line_no=r.line_no) for r in validate_invoice(db, inv)],
    )


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> list[InvoiceSummary]:
    q = select(Invoice).order_by(Invoice.received_at.desc())
    if scope.supplier_id is not None:
        q = q.where(Invoice.supplier_id == scope.supplier_id)
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    return [InvoiceSummary(**_summary_kwargs(i, names.get(i.supplier_id))) for i in db.scalars(q)]


@router.post("/upload", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def upload_invoice(
    file: UploadFile = File(...),
    supplier_id: int | None = Form(None),
    user: User = Depends(require_roles(Role.SUPPLIER, Role.CLERK)),
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    data = file.file.read(MAX_BYTES + 1)
    try:
        inv = process_upload(db, user, file.filename or "upload", data, supplier_id)
    except (UploadRejected, UploadError) as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _detail(db, inv)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> InvoiceDetail:
    return _detail(db, get_invoice_in_scope(invoice_id, scope, db))


def _document(invoice_id: int, scope: SupplierScope, db: Session) -> Document:
    inv = get_invoice_in_scope(invoice_id, scope, db)
    doc = db.get(Document, inv.document_id) if inv.document_id else None
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No document for this invoice")
    return doc


@router.get("/{invoice_id}/document")
def get_document(invoice_id: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> FileResponse:
    doc = _document(invoice_id, scope, db)
    return FileResponse(path_of(doc.stored_name), media_type=doc.mime_type,
                        filename=f"invoice-{invoice_id}.{doc.stored_name.rsplit('.', 1)[-1]}")


@router.get("/{invoice_id}/pages/{page}.png")
def get_page(invoice_id: int, page: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> Response:
    doc = _document(invoice_id, scope, db)
    if not 1 <= page <= doc.pages:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such page")
    return Response(page_png(doc.stored_name, page), media_type="image/png")
