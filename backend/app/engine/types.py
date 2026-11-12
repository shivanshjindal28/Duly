"""Plain data types for validation and the decision engine. No I/O, no ORM, no AI."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import Severity


def fmt_num(v: Decimal) -> str:
    """Plain number for messages: Decimal('2000.000') -> '2000', Decimal('1.50') -> '1.5'."""
    return format(v.normalize(), "f")


@dataclass(frozen=True)
class DocLine:
    line_no: int
    item_code: str | None
    description: str
    hsn_sac: str | None
    qty: Decimal
    uom: str
    unit_price: Decimal
    taxable_value: Decimal
    gst_rate: Decimal
    cgst: Decimal = Decimal(0)
    sgst: Decimal = Decimal(0)
    igst: Decimal = Decimal(0)
    # Credited on the supplier's credit notes against this invoice: the match uses the net
    # (quantity in this line's unit for goods, taxable value for services).
    credited_qty: Decimal = Decimal(0)
    credited_value: Decimal = Decimal(0)
    # A person's decision on a description match: confirmed PO line id, or rejected (not on the PO).
    confirmed_po_line_id: int | None = None
    mapping_rejected: bool = False


@dataclass(frozen=True)
class InvoiceDoc:
    """An invoice as the rules see it (after extraction and any human corrections)."""

    invoice_number: str
    invoice_date: date | None
    supplier_gstin: str | None
    buyer_gstin: str | None
    place_of_supply: str | None
    po_number: str | None
    currency: str
    taxable_total: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal
    lines: tuple[DocLine, ...] = ()
    bank_account: str | None = None
    bank_ifsc: str | None = None


@dataclass(frozen=True)
class Reason:
    """One reason code: what was found, how serious it is, and the evidence values."""

    code: str
    severity: Severity
    message: str
    evidence: dict = field(default_factory=dict)
    line_no: int | None = None
