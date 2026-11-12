"""Bridge between stored data and the pure rules: build engine inputs, run, persist results.

`run_match` is called after upload, after a human correction, and whenever stores posts a
GR/SES against the invoice's PO (automatic re-match that can release a MISSING_GR block).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.crypto import decrypt_str
from app.core.enums import Decision, InvoiceStatus
from app.engine.catalog import info
from app.engine.decide import UOM_FACTORS, MatchOutcome, PoLineView, PoView, SupplierView, decide
from app.engine.policy import Tolerances
from app.engine.types import DocLine, InvoiceDoc, Reason
from app.models import (Document, GoodsReceipt, GRLine, Invoice, InvoiceLine, MatchResult, Organisation, Policy, PurchaseOrder,
                        ReasonCode, ServiceEntrySheet, Supplier)
from app.models.base import as_utc
from app.payments.msme import msme_eligible, statutory_due_date
from app.validation.rules import validate
from app.duplicates.detector import DupView, assess
from app.ingestion.injection import injection_reasons
from app.ingestion.qr import einvoice_reasons
from app.workflow.approvals import sync_after_match

# Invoices whose quantities count as "already invoiced" against a PO line.
_CONSUMING = (InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.APPROVED, InvoiceStatus.PAID)

_STATUS = {
    Decision.BLOCK: (InvoiceStatus.BLOCKED, "Blocked: AP clerk to resolve"),
    Decision.FLAG: (InvoiceStatus.FLAGGED, "AP clerk (exception)"),
    Decision.APPROVE: (InvoiceStatus.PENDING_APPROVAL, "Approval workflow"),
}


def invoice_to_doc(inv: Invoice) -> InvoiceDoc:
    return InvoiceDoc(
        invoice_number=inv.invoice_number, invoice_date=inv.invoice_date, supplier_gstin=inv.supplier_gstin,
        buyer_gstin=inv.buyer_gstin, place_of_supply=inv.place_of_supply, po_number=inv.po_number_text,
        currency=inv.currency, taxable_total=inv.taxable_total, cgst=inv.cgst, sgst=inv.sgst, igst=inv.igst,
        total=inv.total,
        lines=tuple(
            DocLine(ln.line_no, ln.item_code, ln.description, ln.hsn_sac, ln.qty, ln.uom, ln.unit_price,
                    ln.taxable_value, ln.gst_rate, ln.cgst, ln.sgst, ln.igst)
            for ln in inv.lines
        ),
        bank_account=decrypt_str(inv.bank_account_enc) if inv.bank_account_enc else None,
        bank_ifsc=inv.bank_ifsc,
    )


def plant_gstin(db: Session) -> str:
    return db.scalar(select(Organisation.gstin).limit(1))


def active_policy(db: Session) -> Policy:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True)))


def validate_invoice(db: Session, inv: Invoice) -> list[Reason]:
    return validate(invoice_to_doc(inv), plant_gstin(db), clock.today())


def _to_po_unit(qty: Decimal, uom: str, po_uom: str) -> Decimal:
    u, p = (uom or "").upper(), (po_uom or "").upper()
    return qty if u == p else qty * UOM_FACTORS.get((u, p), Decimal(1))


def build_po_view(db: Session, po: PurchaseOrder, exclude_invoice_id: int | None) -> PoView:
    supplier = db.get(Supplier, po.supplier_id)
    lines = []
    for pl in po.lines:
        received = db.scalar(select(func.coalesce(func.sum(GRLine.qty), 0)).where(GRLine.po_line_id == pl.id))
        accepted = db.scalar(select(func.coalesce(func.sum(ServiceEntrySheet.value), 0))
                             .where(ServiceEntrySheet.po_line_id == pl.id))
        prior = db.execute(
            select(InvoiceLine.qty, InvoiceLine.uom, InvoiceLine.taxable_value)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(InvoiceLine.po_line_id == pl.id, Invoice.status.in_(_CONSUMING), Invoice.id != (exclude_invoice_id or -1))
        ).all()
        lines.append(PoLineView(
            id=pl.id, line_no=pl.line_no, item_code=pl.item_code, description=pl.description, qty=pl.qty,
            uom=pl.uom, unit_price=pl.unit_price, gst_rate=pl.gst_rate,
            received_qty=Decimal(str(received)), accepted_value=Decimal(str(accepted)),
            invoiced_qty=sum((_to_po_unit(q, u, pl.uom) for q, u, _ in prior), Decimal(0)),
            invoiced_value=sum((v for _, _, v in prior), Decimal(0)),
        ))
    return PoView(po.po_number, supplier.gstin, po.status, po.currency, po.payment_terms_days, po.is_service,
                  tuple(lines))


def _supplier_view(s: Supplier) -> SupplierView:
    return SupplierView(s.gstin, s.payment_terms_days, decrypt_str(s.bank_account_enc), s.bank_ifsc)


def _acceptance_time(db: Session, po: PurchaseOrder):
    gr = db.scalar(select(func.max(GoodsReceipt.posted_at)).where(GoodsReceipt.po_id == po.id))
    ses = db.scalar(select(func.max(ServiceEntrySheet.posted_at)).where(ServiceEntrySheet.po_id == po.id))
    return max((t for t in (gr, ses) if t is not None), default=None)


def dup_view(inv: Invoice, doc_row: Document | None, bank_account: str | None) -> DupView:
    return DupView(
        invoice_id=inv.id, invoice_number=inv.invoice_number, number_norm=inv.invoice_number_norm,
        supplier_id=inv.supplier_id, supplier_gstin=inv.supplier_gstin, fiscal_year=inv.fiscal_year, irn=inv.irn,
        sha256=doc_row.sha256 if doc_row else None, phash=doc_row.phash if doc_row else None, total=inv.total,
        invoice_date=inv.invoice_date, lines=tuple((ln.item_code or "", ln.qty) for ln in inv.lines),
        bank_account=bank_account, status=inv.status,
    )


def duplicate_check(db: Session, inv: Invoice, doc: InvoiceDoc):
    """Compare with every earlier, non-rejected invoice (so an original is never flagged as a copy)."""
    docs = {d.id: d for d in db.scalars(select(Document))}
    earlier = []
    for o in db.scalars(select(Invoice).where(Invoice.id < inv.id, Invoice.status != InvoiceStatus.REJECTED)):
        bank = decrypt_str(o.bank_account_enc) if o.bank_account_enc else None
        earlier.append(dup_view(o, docs.get(o.document_id), bank))
    return assess(dup_view(inv, docs.get(inv.document_id), doc.bank_account), earlier)


def _set_due_dates(inv: Invoice, supplier: Supplier, policy: dict) -> None:
    """Contract due date for everyone; statutory MSME due date for eligible micro/small suppliers."""
    if inv.accepted_at is None:
        return
    accepted = as_utc(inv.accepted_at).astimezone(clock.IST).date()
    inv.due_date = accepted + timedelta(days=supplier.payment_terms_days)
    if msme_eligible(supplier.msme_category, supplier.enterprise_type):
        m = policy.get("msme", {})
        inv.msme_due_date = statutory_due_date(accepted, supplier.payment_terms_days, supplier.written_agreement,
                                               m.get("max_term_days", 45), m.get("no_agreement_days", 15))


def _jsonable(row) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(row).items()}


def run_match(db: Session, inv: Invoice, trigger: str = "upload") -> MatchOutcome:
    """Run the engine for `inv`, store a MatchResult snapshot, and update the invoice's status."""
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number_text)) \
        if inv.po_number_text else None
    inv.po_id = po.id if po else None
    policy = active_policy(db)
    tol = Tolerances.from_policy(policy.data, policy.version)
    supplier = db.get(Supplier, inv.supplier_id)
    doc = invoice_to_doc(inv)
    _matches, dup_reasons = duplicate_check(db, inv, doc)
    qr_reasons = einvoice_reasons(doc, inv.qr_status, inv.qr_payload, supplier.e_invoice_applicable)
    qr_reasons += injection_reasons(inv.injection)
    outcome = decide(doc, build_po_view(db, po, inv.id) if po else None, _supplier_view(supplier),
                     tol, plant_gstin(db), clock.today(), tuple(dup_reasons + qr_reasons))

    result = MatchResult(invoice_id=inv.id, decision=outcome.decision, policy_version=outcome.policy_version,
                         engine_version=outcome.engine_version, trigger=trigger,
                         matrix=[_jsonable(r) for r in outcome.matrix])
    db.add(result)
    db.flush()
    for r in outcome.reasons:
        ci = info(r.code)
        db.add(ReasonCode(match_result_id=result.id, code=r.code, severity=r.severity, message=r.message,
                          evidence=r.evidence, sap_equivalent=f"{ci.sap_block} · {ci.sap_tcode}", line_no=r.line_no))
    for ln in inv.lines:
        ln.po_line_id = outcome.line_map.get(ln.line_no)

    inv.decision = outcome.decision
    if inv.status != InvoiceStatus.NEEDS_REVIEW:  # review must finish before the decision takes effect
        inv.status, inv.current_owner = _STATUS[outcome.decision]
    if po is not None:
        # The MSME clock starts at acceptance (GR / SES), whatever the match outcome.
        inv.accepted_at = _acceptance_time(db, po)
        _set_due_dates(inv, supplier, policy.data)
    db.flush()
    audit.queue(db, "invoice.matched", "invoice", inv.id, after={
        "decision": outcome.decision, "reasons": [f"{r.code}:{r.severity}" for r in outcome.reasons],
        "trigger": trigger, "policy_version": outcome.policy_version, "engine": outcome.engine_version,
        "status": inv.status, "ai_decided": False,
    }, actor=audit.SYSTEM)  # the rules engine decided, not the person whose action triggered it
    sync_after_match(db, inv)  # open (or close) the approval route
    db.flush()
    return outcome


def latest_match(db: Session, invoice_id: int) -> MatchResult | None:
    return db.scalar(select(MatchResult).where(MatchResult.invoice_id == invoice_id)
                     .order_by(MatchResult.id.desc()).limit(1))
