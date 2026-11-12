"""Evaluated receipt settlement (ERS; SAP transaction MRRL) for POs flagged `ers`.

The supplier sends no invoice. When stores posts a goods receipt or service entry sheet on
an ERS PO, Duly creates the payable itself ("self-billed settlement") from that receipt at
the PO price and GST rate, and runs it through the same rules engine and approval route as
any uploaded invoice. One settlement per receipt, numbered after it (ERS-<GR/SES number>),
so it can never be settled twice.

Used for freight (Konkan Bulk Carriers): trips are confirmed by stores, prices are fixed on
the PO, and chasing a paper invoice per trip adds nothing but delay.

GST note (assumption, verify with the tax team): in India a registered supplier still issues
the tax invoice that gives Plant X its input tax credit; this settlement drives the payment,
and the supplier's tax invoice would be linked to it for GST returns (not built in the demo).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schema import ExtractedField, ExtractedInvoice
from app.core import audit, clock
from app.core.enums import Severity
from app.engine.types import Reason
from app.models import ExtractionResult, Invoice, InvoiceLine, Organisation, POLine, PurchaseOrder, Supplier
from app.validation.rules import fiscal_year

ORIGIN = "ers"
EXTRACTOR = "ers-settlement"
VERSION = "ers-v1"
_CENT = Decimal("0.01")


def _money(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


def _qty(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def number_for(receipt_number: str) -> str:
    return f"ERS-{receipt_number}"


def _field(value) -> ExtractedField:
    return ExtractedField(value=None if value is None else str(value), confidence=1.0, source=ORIGIN)


def settle(db: Session, po: PurchaseOrder, receipt_kind: str, receipt_number: str,
           received: list[tuple[POLine, Decimal]]) -> Invoice | None:
    """Create and match the self-billed settlement for one receipt on an ERS PO.

    received: per PO line, the quantity received (goods) or the value accepted (services)."""
    if not po.ers or not received:
        return None
    number = number_for(receipt_number)
    if db.scalar(select(Invoice.id).where(Invoice.invoice_number == number, Invoice.supplier_id == po.supplier_id)):
        return None  # already settled (never twice for one receipt)
    from app.ingestion.pipeline import normalise_invoice_number  # local: pipeline -> matching -> this module

    supplier = db.get(Supplier, po.supplier_id)
    org = db.scalar(select(Organisation).limit(1))
    intra = supplier.state_code == org.state_code
    today = clock.today()

    lines, totals = [], {"taxable": Decimal(0), "cgst": Decimal(0), "sgst": Decimal(0), "igst": Decimal(0)}
    for pl, amount in received:
        if po.is_service:
            taxable = _money(amount)
            qty = _qty(amount / pl.unit_price) if pl.unit_price else Decimal(1)
        else:
            qty = amount
            taxable = _money(amount * pl.unit_price)
        tax = _money(taxable * pl.gst_rate / 100)
        cgst = sgst = _money(tax / 2) if intra else Decimal(0)
        igst = Decimal(0) if intra else tax
        lines.append({"item_code": pl.item_code, "description": pl.description, "hsn_sac": pl.hsn_sac, "qty": qty,
                      "uom": pl.uom, "unit_price": pl.unit_price, "taxable_value": taxable, "gst_rate": pl.gst_rate,
                      "cgst": cgst, "sgst": sgst, "igst": igst, "po_line_id": pl.id})
        totals["taxable"] += taxable
        totals["cgst"] += cgst
        totals["sgst"] += sgst
        totals["igst"] += igst
    total = totals["taxable"] + totals["cgst"] + totals["sgst"] + totals["igst"]

    inv = Invoice(
        supplier_id=supplier.id, po_id=po.id, document_id=None, po_number_text=po.po_number,
        invoice_number=number, invoice_number_norm=normalise_invoice_number(number),
        invoice_date=today, fiscal_year=fiscal_year(today), supplier_gstin=supplier.gstin, buyer_gstin=org.gstin,
        place_of_supply=org.state_code, currency=po.currency, taxable_total=totals["taxable"],
        cgst=totals["cgst"], sgst=totals["sgst"], igst=totals["igst"], total=total,
        qr_status="none", injection={"found": False, "findings": [], "ai_quarantined": None},
        ai_mode=None, origin=ORIGIN, processed_by_user_id=None, current_owner="Duly (ERS)",
    )
    db.add(inv)
    db.flush()
    for i, ln in enumerate(lines, start=1):
        db.add(InvoiceLine(invoice_id=inv.id, line_no=i, **{k: v for k, v in ln.items() if k != "po_line_id"}))

    # Field log in the same shape as an extraction, source "ers": every value comes from the PO and the receipt.
    header = {"supplier_name": supplier.name, "supplier_gstin": supplier.gstin, "buyer_gstin": org.gstin,
              "invoice_number": number, "invoice_date": today.isoformat(), "po_number": po.po_number,
              "place_of_supply": org.state_code, "currency": po.currency, "taxable_total": totals["taxable"],
              "cgst": totals["cgst"], "sgst": totals["sgst"], "igst": totals["igst"], "total": total}
    record = ExtractedInvoice(
        header={k: _field(v) for k, v in header.items()},
        lines=[{k: _field(v) for k, v in ln.items() if k != "po_line_id"} for ln in lines],
        method=ORIGIN, extractor=EXTRACTOR, extractor_version=VERSION)
    for path, f in record.all_fields():
        db.add(ExtractionResult(invoice_id=inv.id, field=path, value=f.value, confidence=f.confidence,
                                source=ORIGIN, model=EXTRACTOR, prompt_version=VERSION))
    db.flush()
    db.refresh(inv)
    audit.queue(db, "invoice.ers_settled", "invoice", inv.id, actor=audit.SYSTEM, after={
        "invoice_number": number, "supplier": supplier.code, "po": po.po_number, "receipt": f"{receipt_kind} {receipt_number}",
        "taxable": str(totals["taxable"]), "total": str(total), "priced_at": "PO price and GST rate",
    })
    from app.workflow.matching import run_match  # local import: matching imports this module

    run_match(db, inv, trigger=f"ers:{receipt_kind.lower()}_{receipt_number}")
    return inv


def ers_reasons(inv: Invoice, po: PurchaseOrder | None) -> list[Reason]:
    """Engine input (pure): what ERS means for this invoice."""
    if po is None or not po.ers:
        return []
    if inv.origin == ORIGIN:
        receipt = inv.invoice_number.removeprefix("ERS-")
        return [Reason("ERS_SETTLEMENT", Severity.INFO,
                       f"Self-billed by Duly from receipt {receipt} at the PO price; PO {po.po_number} is on "
                       "evaluated receipt settlement, so no supplier invoice is needed.",
                       {"receipt": receipt, "po": po.po_number})]
    return [Reason("ERS_PO_INVOICE", Severity.FLAG,
                   f"PO {po.po_number} is settled from receipts (ERS): Duly pays each goods receipt or service "
                   "entry without an invoice. Check this is not a second bill for trips already settled.",
                   {"po": po.po_number})]


def is_ers(inv: Invoice) -> bool:
    return inv.origin == ORIGIN

