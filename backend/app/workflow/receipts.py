"""Goods receipts (MIGO 101) and service entry sheets (ML81N) posted by stores, plus the
automatic re-match of every invoice waiting on that PO.

When a GR arrives for an invoice blocked with MISSING_GR, the engine runs again (trigger
"gr_posted:<GR number>") and, if the invoice is now clean, it is released without anyone
touching it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.enums import Decision, InvoiceStatus
from app.models import GoodsReceipt, GRLine, Invoice, POLine, PurchaseOrder, ServiceEntrySheet, User
from app.workflow.matching import run_match

# Invoices that a new receipt can change. Approved or paid invoices are final.
_WAITING = (InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED, InvoiceStatus.RECEIVED, InvoiceStatus.NEEDS_REVIEW)
OVER_RECEIPT_PCT = Decimal("0.5")  # weighbridge allowance on bulk MT lines; other units must not exceed the PO


class ReceiptError(ValueError):
    """User-facing problem with a receipt posting."""


@dataclass(frozen=True)
class Rematch:
    invoice_id: int
    before: Decision | None
    after: Decision
    released: bool  # was BLOCK, now FLAG or APPROVE


def _open_po(db: Session, po_number: str) -> PurchaseOrder:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))
    if po is None:
        raise ReceiptError(f"PO {po_number} not found.")
    if po.status != "open":
        raise ReceiptError(f"PO {po_number} is {po.status}.")
    return po


def received_qty(db: Session, po_line_id: int) -> Decimal:
    return Decimal(str(db.scalar(select(func.coalesce(func.sum(GRLine.qty), 0)).where(GRLine.po_line_id == po_line_id))))


def accepted_value(db: Session, po_line_id: int) -> Decimal:
    return Decimal(str(db.scalar(select(func.coalesce(func.sum(ServiceEntrySheet.value), 0))
                                 .where(ServiceEntrySheet.po_line_id == po_line_id))))


def _next_number(db: Session, column, start: int) -> str:
    current = db.scalar(select(func.max(column)))
    return str(max(int(current) + 1, start) if current else start)


def rematch_waiting(db: Session, po: PurchaseOrder, trigger: str) -> list[Rematch]:
    """Re-run the engine for every not-yet-approved invoice on this PO."""
    out: list[Rematch] = []
    for inv in db.scalars(select(Invoice).where(Invoice.po_number_text == po.po_number,
                                                Invoice.status.in_(_WAITING)).order_by(Invoice.id)):
        before = inv.decision
        outcome = run_match(db, inv, trigger=trigger)
        out.append(Rematch(inv.id, before, outcome.decision,
                           before == Decision.BLOCK and outcome.decision != Decision.BLOCK))
    return out


def post_goods_receipt(db: Session, user: User, po_number: str, lines: list[tuple[int, Decimal]]
                       ) -> tuple[GoodsReceipt, list[Rematch]]:
    po = _open_po(db, po_number)
    if po.is_service:
        raise ReceiptError(f"PO {po_number} is for services: post a service entry sheet instead.")
    po_lines = {pl.id: pl for pl in po.lines}
    lines = [(lid, q) for lid, q in lines if q != 0]
    if not lines:
        raise ReceiptError("Enter a received quantity for at least one line.")
    for line_id, qty in lines:
        pl = po_lines.get(line_id)
        if pl is None:
            raise ReceiptError("A line does not belong to this PO.")
        if qty < 0:
            raise ReceiptError("Quantities must be positive (returns are not supported in the demo).")
        allowance = pl.qty * OVER_RECEIPT_PCT / 100 if pl.uom.upper() == "MT" else Decimal(0)
        if received_qty(db, pl.id) + qty > pl.qty + allowance:
            raise ReceiptError(f"Line {pl.line_no} ({pl.item_code}): receiving {qty} would exceed the ordered "
                               f"{pl.qty} {pl.uom} (already received {received_qty(db, pl.id)}).")
    gr = GoodsReceipt(gr_number=_next_number(db, GoodsReceipt.gr_number, 5000000101), po_id=po.id,
                      posted_by_user_id=user.id, posted_at=clock.now())
    db.add(gr)
    db.flush()
    for line_id, qty in lines:
        db.add(GRLine(gr_id=gr.id, po_line_id=line_id, qty=qty, uom=po_lines[line_id].uom))
    db.flush()
    audit.queue(db, "gr.posted", "goods_receipt", gr.gr_number,
                after={"po": po.po_number, "movement_type": "101",
                       "lines": [{"po_line_id": i, "qty": q} for i, q in lines]})
    results = rematch_waiting(db, po, trigger=f"gr_posted:{gr.gr_number}")
    db.commit()
    return gr, results


def post_service_entry(db: Session, user: User, po_number: str, po_line_id: int, value: Decimal,
                       description: str) -> tuple[ServiceEntrySheet, list[Rematch]]:
    po = _open_po(db, po_number)
    if not po.is_service:
        raise ReceiptError(f"PO {po_number} is for goods: post a goods receipt instead.")
    pl = db.get(POLine, po_line_id)
    if pl is None or pl.po_id != po.id:
        raise ReceiptError("The line does not belong to this PO.")
    if value <= 0:
        raise ReceiptError("Accepted value must be positive.")
    if accepted_value(db, pl.id) + value > pl.qty * pl.unit_price:
        raise ReceiptError(f"Accepting {value} would exceed the PO line value {pl.qty * pl.unit_price}.")
    ses = ServiceEntrySheet(ses_number=_next_number(db, ServiceEntrySheet.ses_number, 1000000201), po_id=po.id,
                            po_line_id=pl.id, description=description.strip() or pl.description, value=value,
                            posted_by_user_id=user.id, posted_at=clock.now())
    db.add(ses)
    db.flush()
    audit.queue(db, "ses.posted", "service_entry", ses.ses_number,
                after={"po": po.po_number, "po_line_id": pl.id, "value": value})
    results = rematch_waiting(db, po, trigger=f"ses_posted:{ses.ses_number}")
    db.commit()
    return ses, results
