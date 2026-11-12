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
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import SupplierScope, get_scope, require_roles
from app.ingestion.hardening import MAX_BYTES, UploadRejected
from app.ingestion.pages import page_png
from app.ingestion.pipeline import UploadError, confidence_threshold, process_upload
from app.ingestion.storage import path_of
from app.core import clock
from app.core.enums import InvoiceStatus, Role
from app.engine.catalog import info
from app.models import Document, Invoice, MatchResult, ReasonCode, Supplier, User
from app.models.base import as_utc
from app.workflow import approvals as wf
from app.workflow.lifecycle import rail_progress
from app.workflow.matching import latest_match
from app.ingestion.pipeline import latest_fields, pending_review
from app.workflow.review import EDITABLE_STATUSES, ReviewError, review_field

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
    rail: int  # completed stops on the Duly rail (0-5)


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
    previous_value: str | None = None
    previous_confidence: float | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    reviewed_at: datetime | None = None


class ReviewIn(BaseModel):
    field: str = Field(max_length=60)
    value: str | None = Field(None, max_length=300)  # None = confirm the value as read
    reason: str = Field(max_length=300)


class ReasonOut(BaseModel):
    code: str
    title: str
    severity: str
    message: str
    evidence: dict
    line_no: int | None
    sap_equivalent: str | None


class MatchOut(BaseModel):
    decision: str
    policy_version: int
    engine_version: str
    trigger: str
    created_at: datetime
    reasons: list[ReasonOut]
    matrix: list[dict]


class DocumentOut(BaseModel):
    original_filename: str
    mime_type: str
    pages: int
    sha256: str
    size_bytes: int


class StepOut(BaseModel):
    sequence: int
    level: int
    title: str
    status: str
    approver: str | None
    delegated_from: str | None
    comment: str | None
    by_policy: str | None
    mfa_verified: bool
    due_at: datetime | None
    escalated_at: datetime | None
    decided_at: datetime | None
    overdue: bool


class WorkflowOut(BaseModel):
    steps: list[StepOut]
    override_by: str | None
    override_at: datetime | None
    override_justification: str | None
    # What the current user may do right now (the server re-checks on every action).
    can_approve: bool
    approve_blocked_reason: str | None
    approve_blocked_sod: bool
    mfa_required: bool
    can_override: bool


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
    pending_review: list[str]
    can_review: bool  # filled per request: clerk and invoice still editable
    match: MatchOut | None
    workflow: WorkflowOut


def _workflow(db: Session, inv: Invoice, user: User) -> WorkflowOut:
    wf.escalate_overdue(db)
    steps = wf.steps_of(db, inv.id)
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.role.in_([Role.APPROVER, Role.CLERK])))}
    now = clock.now()
    step = wf.current_step(db, inv.id)
    auth = wf.authority(db, inv, step, user) if step and inv.status == InvoiceStatus.PENDING_APPROVAL else None
    show_approve = user.role == Role.APPROVER and auth is not None
    return WorkflowOut(
        steps=[StepOut(sequence=s.sequence, level=s.level,
                       title="Policy P-01 (touchless)" if s.by_policy else wf.LEVEL_TITLE[s.level],
                       status=s.status, approver=names.get(s.approver_user_id),
                       delegated_from=names.get(s.delegated_from_user_id), comment=s.comment, by_policy=s.by_policy,
                       mfa_verified=s.mfa_verified, due_at=s.due_at, escalated_at=s.escalated_at,
                       decided_at=s.decided_at,
                       overdue=s.status == "pending" and s.due_at is not None and as_utc(s.due_at) < now)
               for s in steps],
        override_by=names.get(inv.override_by_user_id), override_at=inv.override_at,
        override_justification=inv.override_justification,
        can_approve=bool(show_approve and auth.allowed),
        approve_blocked_reason=auth.reason if show_approve and not auth.allowed else None,
        approve_blocked_sod=bool(show_approve and auth.sod),
        mfa_required=wf.mfa_required(db, inv),
        can_override=user.role == Role.CLERK and inv.status == InvoiceStatus.FLAGGED,
    )


def _summary_kwargs(inv: Invoice, supplier_name: str | None, codes: set[str]) -> dict:
    return dict(
        id=inv.id, supplier_id=inv.supplier_id, supplier_name=supplier_name, invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date, po_number=inv.po_number_text, total=inv.total, status=inv.status,
        decision=inv.decision, current_owner=inv.current_owner, received_at=inv.received_at,
        rail=rail_progress(inv, codes),
    )


def _latest_codes(db: Session, invoice_ids: list[int]) -> dict[int, set[str]]:
    """Reason codes of the latest match per invoice, in one query."""
    if not invoice_ids:
        return {}
    latest = (select(func.max(MatchResult.id).label("mid")).where(MatchResult.invoice_id.in_(invoice_ids))
              .group_by(MatchResult.invoice_id).subquery())
    rows = db.execute(select(MatchResult.invoice_id, ReasonCode.code)
                      .join(latest, latest.c.mid == MatchResult.id)
                      .join(ReasonCode, ReasonCode.match_result_id == MatchResult.id)).all()
    out: dict[int, set[str]] = {}
    for inv_id, code in rows:
        out.setdefault(inv_id, set()).add(code)
    return out


def get_invoice_in_scope(invoice_id: int, scope: SupplierScope, db: Session) -> Invoice:
    """Load an invoice or 404 if it does not exist or is outside the caller's scope."""
    inv = db.get(Invoice, invoice_id)
    if inv is None or not scope.allows(inv.supplier_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


def _detail(db: Session, inv: Invoice, user: User) -> InvoiceDetail:
    supplier = db.get(Supplier, inv.supplier_id) if inv.supplier_id else None
    doc = db.get(Document, inv.document_id) if inv.document_id else None
    threshold = confidence_threshold(db)
    # Latest result per field wins (human corrections are appended, never overwritten).
    latest = latest_fields(db, inv.id)
    reviewers = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({r.reviewed_by_user_id for r in latest.values() if r.reviewed_by_user_id})))}
    match = _match_out(db, inv.id)
    codes = {r.code for r in match.reasons} if match else set()
    return InvoiceDetail(
        **_summary_kwargs(inv, supplier.name if supplier else None, codes),
        supplier_gstin=inv.supplier_gstin, buyer_gstin=inv.buyer_gstin, place_of_supply=inv.place_of_supply,
        currency=inv.currency, taxable_total=inv.taxable_total, cgst=inv.cgst, sgst=inv.sgst, igst=inv.igst,
        bank_account_masked=("XXXXXX" + inv.bank_account_last4) if inv.bank_account_last4 else None,
        bank_ifsc=inv.bank_ifsc, irn=inv.irn, ai_mode=inv.ai_mode,
        lines=[LineOut.model_validate(ln, from_attributes=True) for ln in inv.lines],
        document=DocumentOut.model_validate(doc, from_attributes=True) if doc else None,
        fields=[FieldOut(field=r.field, value=r.value, confidence=r.confidence, page=r.page, bbox=r.bbox,
                         source=r.source, needs_review=r.source != "manual" and r.value is not None
                         and r.confidence < threshold,
                         previous_value=r.previous_value, previous_confidence=r.previous_confidence,
                         reviewed_by=reviewers.get(r.reviewed_by_user_id), review_reason=r.review_reason,
                         reviewed_at=r.created_at if r.source == "manual" else None)
                for r in latest.values()],
        confidence_threshold=threshold,
        pending_review=pending_review(db, inv.id),
        can_review=user.role == Role.CLERK and inv.status in EDITABLE_STATUSES,
        match=match,
        workflow=_workflow(db, inv, user),
    )


def _match_out(db: Session, invoice_id: int) -> MatchOut | None:
    m = latest_match(db, invoice_id)
    if m is None:
        return None
    return MatchOut(
        decision=m.decision, policy_version=m.policy_version, engine_version=m.engine_version, trigger=m.trigger,
        created_at=m.created_at, matrix=m.matrix,
        reasons=[ReasonOut(code=r.code, title=info(r.code).title, severity=r.severity, message=r.message,
                           evidence=r.evidence, line_no=r.line_no, sap_equivalent=r.sap_equivalent)
                 for r in m.reasons],
    )


@router.get("", response_model=list[InvoiceSummary])
def list_invoices(scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> list[InvoiceSummary]:
    q = select(Invoice).order_by(Invoice.received_at.desc())
    if scope.supplier_id is not None:
        q = q.where(Invoice.supplier_id == scope.supplier_id)
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    invoices = db.scalars(q).all()
    codes = _latest_codes(db, [i.id for i in invoices])
    return [InvoiceSummary(**_summary_kwargs(i, names.get(i.supplier_id), codes.get(i.id, set()))) for i in invoices]


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
    return _detail(db, inv, user)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> InvoiceDetail:
    return _detail(db, get_invoice_in_scope(invoice_id, scope, db), scope.user)


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


@router.post("/{invoice_id}/review", response_model=InvoiceDetail)
def review(
    invoice_id: int,
    body: ReviewIn,
    user: User = Depends(require_roles(Role.CLERK)),
    scope: SupplierScope = Depends(get_scope),
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Confirm (value omitted) or correct one extracted field. A reason is always required."""
    inv = get_invoice_in_scope(invoice_id, scope, db)
    try:
        review_field(db, inv, user, body.field, body.value, body.reason)
    except ReviewError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    db.refresh(inv)
    return _detail(db, inv, user)

