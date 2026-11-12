"""Bridge between stored invoices and the pure rules: build InvoiceDoc, run validation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.crypto import decrypt_str
from app.engine.types import DocLine, InvoiceDoc, Reason
from app.models import Invoice, Organisation
from app.validation.rules import validate


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


def validate_invoice(db: Session, inv: Invoice) -> list[Reason]:
    return validate(invoice_to_doc(inv), plant_gstin(db), clock.today())
