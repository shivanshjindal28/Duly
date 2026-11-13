"""Invoice endpoints with row-level supplier scoping.

Every query goes through `get_scope`: a supplier only ever sees its own invoices, and a
request for another supplier's invoice returns 404 (not 403) so existence is not revealed.
Stores users cannot touch invoices. Upload is open to suppliers (own invoices) and AP
clerks (on behalf of a supplier, e.g. invoices received by email).
"""
from __future__ import annotations

from dataclasses import asdict
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
from app.core import clock, jobs
from app.core.enums import InvoiceStatus, Role
from app.engine.catalog import info
from app.erp import S4HanaAdapterStub
from app.models import CreditNote, Document, InboundEmail, Invoice, MatchResult, PurchaseOrder, ReasonCode, Supplier, User
from app.models.base import as_utc
from app.workflow import approvals as wf
from app.workflow.credit_notes import OPEN_FOR_CREDIT, CreditNoteError, can_credit, net_total
from app.workflow.credit_notes import issue as issue_credit_note
from app.workflow.credit_notes import suggest as suggest_credit
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
    currency: str = "INR"
    total_inr: Decimal | None = None  # INR equivalent (foreign-currency invoices)
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
    purged_at: datetime | None = None


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
    can_clerk_reject: bool = False


class EInvoiceField(BaseModel):
    field: str
    printed: str | None
    signed: str | None
    same: bool


class EInvoiceOut(BaseModel):
    status: str  # none | valid | invalid
    error: str | None
    applicable: bool  # supplier above the e-invoicing threshold
    sandbox: bool  # trusted key is the demo Sandbox IRP (production: NIC IRP key)
    irn: str | None
    fields: list[EInvoiceField]


def _einvoice(inv: Invoice, supplier: Supplier | None) -> EInvoiceOut:
    from app.core.config import get_settings

    p = inv.qr_payload or {}
    pairs = [
        ("Supplier GSTIN", inv.supplier_gstin, p.get("SellerGstin")),
        ("Buyer GSTIN", inv.buyer_gstin, p.get("BuyerGstin")),
        ("Invoice number", inv.invoice_number, p.get("DocNo")),
        ("Invoice date", inv.invoice_date.strftime("%d/%m/%Y") if inv.invoice_date else None, p.get("DocDt")),
        ("Total", f"{inv.total:.2f}", f"{Decimal(str(p['TotInvVal'])):.2f}" if "TotInvVal" in p else None),
        ("IRN", inv.irn, p.get("Irn")),
    ]
    return EInvoiceOut(
        status=inv.qr_status or "none", error=inv.qr_error, applicable=bool(supplier and supplier.e_invoice_applicable),
        sandbox=not get_settings().irp_public_key_path, irn=p.get("Irn") or inv.irn,
        fields=[EInvoiceField(field=f, printed=a, signed=None if b is None else str(b),
                              same=a is not None and b is not None and str(a).upper() == str(b).upper())
                for f, a, b in pairs] if p else [],
    )


class CreditNoteLineOut(BaseModel):
    line_no: int
    qty: Decimal
    taxable_value: Decimal


class CreditNoteOut(BaseModel):
    number: str
    note_date: date
    reason: str
    taxable: Decimal
    total: Decimal
    entered_by: str | None
    created_at: datetime
    lines: list[CreditNoteLineOut]


class CreditSuggestionOut(BaseModel):
    line_no: int
    item: str
    uom: str
    mode: str  # qty | value
    qty: Decimal
    value: Decimal
    total: Decimal
    reason_code: str


def _source_email(db: Session, inv: Invoice) -> dict | None:
    em = db.get(InboundEmail, inv.source_email_id) if inv.source_email_id else None
    if em is None:
        return None
    return {"from_addr": em.from_addr, "from_name": em.from_name, "subject": em.subject,
            "received_at": em.received_at, "sender_status": em.sender_status}


def _credit_notes(db: Session, inv: Invoice) -> list[CreditNoteOut]:
    notes = db.scalars(select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.id)).all()
    if not notes:
        return []
    names = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({n.created_by_user_id for n in notes if n.created_by_user_id})))}
    line_no = {ln.id: ln.line_no for ln in inv.lines}
    return [CreditNoteOut(number=n.number, note_date=n.note_date, reason=n.reason, taxable=n.taxable, total=n.total,
                          entered_by=names.get(n.created_by_user_id), created_at=n.created_at,
                          lines=[CreditNoteLineOut(line_no=line_no.get(cl.invoice_line_id, 0), qty=cl.qty,
                                                   taxable_value=cl.taxable_value) for cl in n.lines])
            for n in notes]


class InvoiceDetail(InvoiceSummary):
    supplier_gstin: str | None
    buyer_gstin: str | None
    place_of_supply: str | None
    fx_rate: Decimal = Decimal(1)
    supplier_country: str = "IN"
    taxable_total: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    bank_account_masked: str | None
    bank_ifsc: str | None
    irn: str | None
    ai_mode: str | None
    origin: str  # upload | email | ers (self-billed from a receipt; no document)
    source_email: dict | None  # for emailed invoices: from, subject, received_at, sender_status
    lines: list[LineOut]
    document: DocumentOut | None
    fields: list[FieldOut]
    confidence_threshold: float
    pending_review: list[str]
    can_review: bool  # filled per request: clerk and invoice still editable
    match: MatchOut | None
    workflow: WorkflowOut
    einvoice: EInvoiceOut
    injection: dict | None  # D2 scan: {"found", "findings", "ai_quarantined"}
    credit_notes: list[CreditNoteOut]
    net_total: Decimal  # total minus credit notes: what approval and payment use
    credit_suggestion: list[CreditSuggestionOut]  # credit that would clear qty / value exceptions
    can_issue_credit: bool


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
        can_clerk_reject=user.role == Role.CLERK and inv.status in (InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED,
                                                                  InvoiceStatus.NEEDS_REVIEW),
    )


def _summary_kwargs(inv: Invoice, supplier_name: str | None, codes: set[str]) -> dict:
    return dict(
        id=inv.id, supplier_id=inv.supplier_id, supplier_name=supplier_name, invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date, po_number=inv.po_number_text, total=inv.total, status=inv.status,
        currency=inv.currency or "INR", total_inr=inv.total_inr or inv.total,
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
        taxable_total=inv.taxable_total, cgst=inv.cgst, sgst=inv.sgst, igst=inv.igst,
        fx_rate=inv.fx_rate or 1, supplier_country=(supplier.country if supplier else None) or "IN",
        bank_account_masked=("XXXXXX" + inv.bank_account_last4) if inv.bank_account_last4 else None,
        bank_ifsc=inv.bank_ifsc, irn=inv.irn, ai_mode=inv.ai_mode, origin=inv.origin or "upload",
        source_email=_source_email(db, inv),
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
        einvoice=_einvoice(inv, supplier),
        injection=inv.injection,
        credit_notes=_credit_notes(db, inv),
        net_total=net_total(db, inv),
        credit_suggestion=[CreditSuggestionOut(**vars(s)) for s in suggest_credit(db, inv)]
        if inv.status in OPEN_FOR_CREDIT else [],
        can_issue_credit=user.role in (Role.SUPPLIER, Role.CLERK) and can_credit(db, inv),
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
        inv = jobs.enqueue("process_upload", process_upload, db, user, file.filename or "upload", data, supplier_id).result
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
    if doc.purged_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "The document was deleted under the data retention policy")
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


class CreditLineIn(BaseModel):
    line_no: int
    qty: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=3)  # goods
    value: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=2)  # services: taxable value


class CreditNoteIn(BaseModel):
    number: str = Field(min_length=1, max_length=16)
    note_date: date
    reason: str = Field(min_length=3, max_length=300)
    lines: list[CreditLineIn] = Field(min_length=1, max_length=50)


@router.post("/{invoice_id}/credit-notes", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def add_credit_note(
    invoice_id: int,
    body: CreditNoteIn,
    user: User = Depends(require_roles(Role.SUPPLIER, Role.CLERK)),
    scope: SupplierScope = Depends(get_scope),
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """Supplier (own invoice) or AP clerk on its behalf records a credit note; Duly re-runs the match net of it."""
    inv = get_invoice_in_scope(invoice_id, scope, db)
    try:
        issue_credit_note(db, user, inv, body.number, body.note_date, body.reason,
                          [(ln.line_no, ln.qty, ln.value) for ln in body.lines])
    except CreditNoteError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    db.refresh(inv)
    return _detail(db, inv, user)


class CompareField(BaseModel):
    field: str
    this: str | None
    other: str | None
    same: bool
    normalised_same: bool | None = None


class DupSignalOut(BaseModel):
    name: str
    score: float
    detail: str


class DupOther(BaseModel):
    id: int
    invoice_number: str
    status: str
    decision: str | None
    received_at: datetime
    pages: int


class DupMatchOut(BaseModel):
    probability: float
    exact: bool
    signals: list[DupSignalOut]
    other: DupOther
    fields: list[CompareField]


class DuplicatesOut(BaseModel):
    invoice_id: int
    invoice_number: str = ""
    pages: int
    matches: list[DupMatchOut]


def _compare_fields(a: Invoice, b: Invoice, da: Document | None, db_: Document | None) -> list[CompareField]:
    def lines(inv: Invoice) -> str:
        return "; ".join(f"{ln.item_code} x {ln.qty.normalize():f}" for ln in inv.lines)

    pairs = [
        ("invoice_number", a.invoice_number, b.invoice_number),
        ("invoice_date", str(a.invoice_date or ""), str(b.invoice_date or "")),
        ("supplier_gstin", a.supplier_gstin, b.supplier_gstin),
        ("po_number", a.po_number_text, b.po_number_text),
        ("taxable_total", str(a.taxable_total), str(b.taxable_total)),
        ("total", str(a.total), str(b.total)),
        ("lines", lines(a), lines(b)),
        ("bank_account", f"XXXXXX{a.bank_account_last4}" if a.bank_account_last4 else None,
         f"XXXXXX{b.bank_account_last4}" if b.bank_account_last4 else None),
        ("irn", a.irn, b.irn),
        ("file_sha256", da.sha256[:16] if da else None, db_.sha256[:16] if db_ else None),
    ]
    out = [CompareField(field=f, this=x, other=y, same=x is not None and x == y) for f, x, y in pairs]
    out[0].normalised_same = a.invoice_number_norm == b.invoice_number_norm
    return out


@router.get("/{invoice_id}/duplicates", response_model=DuplicatesOut)
def duplicates(invoice_id: int, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> DuplicatesOut:
    """Side-by-side evidence for every earlier invoice this one may duplicate."""
    from app.workflow.matching import duplicate_check, invoice_to_doc

    inv = get_invoice_in_scope(invoice_id, scope, db)
    matches, _ = duplicate_check(db, inv, invoice_to_doc(inv))
    doc = db.get(Document, inv.document_id) if inv.document_id else None
    out = []
    for m in matches:
        other = db.get(Invoice, m.invoice_id)
        if other is None or not scope.allows(other.supplier_id):
            continue
        odoc = db.get(Document, other.document_id) if other.document_id else None
        out.append(DupMatchOut(
            probability=m.probability, exact=m.exact,
            signals=[DupSignalOut(name=s.name, score=s.score, detail=s.detail) for s in m.signals],
            other=DupOther(id=other.id, invoice_number=other.invoice_number, status=other.status,
                           decision=other.decision, received_at=other.received_at, pages=odoc.pages if odoc else 0),
            fields=_compare_fields(inv, other, doc, odoc),
        ))
    return DuplicatesOut(invoice_id=inv.id, invoice_number=inv.invoice_number, pages=doc.pages if doc else 0, matches=out)


@router.get("/{invoice_id}/sap-preview")
def sap_preview(invoice_id: int, user: User = Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN)),
                db: Session = Depends(get_db)) -> dict:
    """SAP posting preview (D6): the S/4HANA supplier-invoice request Duly would send (never sent)."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    stub = S4HanaAdapterStub(db)
    post = stub.post_supplier_invoice(inv, dry_run=True)
    po_number = db.get(PurchaseOrder, inv.po_id).po_number if inv.po_id else (inv.po_number_text or "")
    reads = [asdict(stub.read_purchase_order(po_number)), asdict(stub.read_goods_receipts(po_number))] if po_number else []
    return {"posting": asdict(post), "reads": reads, "ready": inv.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID),
            "transaction": "MIRO (Enter Incoming Invoice)",
            "note": "Duly runs beside SAP S/4HANA (for example as an SAP BTP extension); SAP stays the system of record. "
                    "This request is built, not sent. Company code, plant, tax codes and withholding tax types are "
                    "fictional configuration."}


@router.get("/{invoice_id}/explain")
def explain_decision(invoice_id: int, user: User = Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN)),
                     db: Session = Depends(get_db)) -> dict:
    """Plain-language explanation of the latest decision, from its reason codes only (spec C3)."""
    from app.api.portal import _todos
    from app.workflow.explain import ReasonFact, explain

    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    m = latest_match(db, inv.id)
    if m is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice has not been checked yet.")
    reasons = db.scalars(select(ReasonCode).where(ReasonCode.match_result_id == m.id).order_by(ReasonCode.id)).all()
    facts = [ReasonFact(r.code, str(r.severity), r.message, r.line_no) for r in reasons]
    out = asdict(explain(str(m.decision), str(inv.status), facts, m.engine_version, m.policy_version))
    # What the supplier is told about the same decision (rendered in English or Hindi from the reviewed i18n files).
    out["supplier_view"] = [t.model_dump() for t in _todos(db, inv, [])]
    return out


class MappingIn(BaseModel):
    po_line_id: int | None = None  # None = not on the PO
    reason: str = Field(min_length=3, max_length=300)


@router.post("/{invoice_id}/lines/{line_no}/mapping", response_model=InvoiceDetail)
def line_mapping(invoice_id: int, line_no: int, body: MappingIn, user: User = Depends(require_roles(Role.CLERK)),
                 scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> InvoiceDetail:
    """Confirm (po_line_id) or reject (null) a line the engine matched by description."""
    from app.workflow.line_mapping import MappingError, decide_mapping

    inv = get_invoice_in_scope(invoice_id, scope, db)
    try:
        decide_mapping(db, inv, line_no, user, body.po_line_id, body.reason)
    except MappingError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    db.refresh(inv)
    return _detail(db, inv, user)
