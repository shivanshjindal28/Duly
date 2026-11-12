"""Invoices, their source documents, extraction results and match results."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import Money, Qty, created_at_col, utcnow
from app.core.enums import Decision, InvoiceStatus, Severity


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)  # random name outside web root
    mime_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    pages: Mapped[int] = mapped_column(Integer, default=1)
    phash: Mapped[str | None] = mapped_column(String(32), index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    po_number_text: Mapped[str | None] = mapped_column(String(40))  # as printed on the invoice
    invoice_number: Mapped[str] = mapped_column(String(40), index=True)
    invoice_number_norm: Mapped[str] = mapped_column(String(40), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[str | None] = mapped_column(String(9))  # e.g. 2026-27
    irn: Mapped[str | None] = mapped_column(String(64), index=True)
    # Signed e-invoice QR: none | valid | invalid, the signed payload, and why it failed.
    qr_status: Mapped[str] = mapped_column(String(10), default="none")
    qr_payload: Mapped[dict | None] = mapped_column(JSON)
    qr_error: Mapped[str | None] = mapped_column(String(200))
    # Prompt-injection scan: {"found": bool, "findings": [...], "ai_quarantined": {...} | None}
    injection: Mapped[dict | None] = mapped_column(JSON)
    supplier_gstin: Mapped[str | None] = mapped_column(String(15))
    buyer_gstin: Mapped[str | None] = mapped_column(String(15))
    place_of_supply: Mapped[str | None] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    taxable_total: Mapped[Decimal] = mapped_column(Money, default=0)
    cgst: Mapped[Decimal] = mapped_column(Money, default=0)
    sgst: Mapped[Decimal] = mapped_column(Money, default=0)
    igst: Mapped[Decimal] = mapped_column(Money, default=0)
    total: Mapped[Decimal] = mapped_column(Money, default=0)
    bank_account_enc: Mapped[str | None] = mapped_column(String(200))
    bank_account_last4: Mapped[str | None] = mapped_column(String(4))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    status: Mapped[InvoiceStatus] = mapped_column(String(20), default=InvoiceStatus.RECEIVED, index=True)
    decision: Mapped[Decision | None] = mapped_column(String(7))
    current_owner: Mapped[str] = mapped_column(String(80), default="AP clerk")
    ai_mode: Mapped[str | None] = mapped_column(String(10))  # live | cached | offline
    origin: Mapped[str] = mapped_column(String(10), default="upload")  # upload | ers (self-billed from a receipt)
    processed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # A FLAG routed for approval anyway: who, when, and the written justification.
    override_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    override_justification: Mapped[str | None] = mapped_column(Text)
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # GR/SES acceptance
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    msme_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    lines: Mapped[list[InvoiceLine]] = relationship(back_populates="invoice", order_by="InvoiceLine.line_no")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str | None] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(Qty)
    uom: Mapped[str] = mapped_column(String(6))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Money, default=0)
    cgst: Mapped[Decimal] = mapped_column(Money, default=0)
    sgst: Mapped[Decimal] = mapped_column(Money, default=0)
    igst: Mapped[Decimal] = mapped_column(Money, default=0)
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class ExtractionResult(Base):
    """One extracted field with confidence and the place on the document it came from."""

    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    field: Mapped[str] = mapped_column(String(60))  # e.g. "invoice_number", "lines[2].qty"
    value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSON)  # [x0, y0, x1, y1] in page fractions
    source: Mapped[str] = mapped_column(String(10))  # text | ocr | ai | qr | manual
    model: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)  # superseded by a human review row
    # For human review rows (source="manual"): who, why, and the value before the change.
    previous_value: Mapped[str | None] = mapped_column(Text)
    previous_confidence: Mapped[float | None] = mapped_column(Float)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at_col()


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    decision: Mapped[Decision] = mapped_column(String(7))
    policy_version: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(60), default="upload")  # upload | gr_posted | correction ...
    matrix: Mapped[list] = mapped_column(JSON, default=list)  # match matrix snapshot for the UI and audit
    created_at: Mapped[datetime] = created_at_col()

    reasons: Mapped[list[ReasonCode]] = relationship(back_populates="match_result", order_by="ReasonCode.id")


class ReasonCode(Base):
    __tablename__ = "reason_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_result_id: Mapped[int] = mapped_column(ForeignKey("match_results.id"), index=True)
    code: Mapped[str] = mapped_column(String(30), index=True)
    severity: Mapped[Severity] = mapped_column(String(5))
    message: Mapped[str] = mapped_column(String(600))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    sap_equivalent: Mapped[str | None] = mapped_column(String(120))
    line_no: Mapped[int | None] = mapped_column(Integer)

    match_result: Mapped[MatchResult] = relationship(back_populates="reasons")
