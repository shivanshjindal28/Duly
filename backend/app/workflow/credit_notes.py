"""Credit notes: how an over-billed invoice gets resolved without anyone overriding a BLOCK.

The supplier (or the AP clerk on its behalf) issues a credit note against one blocked or flagged
invoice, for the quantity billed but not received (goods) or the value billed above what was
accepted (services). Duly prices it from the invoice line (unit price, GST rate, CGST+SGST or
IGST as on the invoice), stores it next to the invoice, and re-runs the rules: the engine matches
the invoice net of its credit notes, so an exact credit releases the block. Approval bands and the
payment run use the net amount; the printed invoice itself is never changed.

Not built in the demo: reading a credit-note PDF (the note is entered in a form), price-difference
credit notes clearing PRICE_VARIANCE (the clerk override covers that FLAG), credit notes after approval.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.enums import InvoiceStatus, Severity
from app.engine.types import Reason, fmt_num
from app.models import CreditNote, CreditNoteLine, Invoice, InvoiceLine, MatchResult, PurchaseOrder, ReasonCode, User

OPEN_FOR_CREDIT = (InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED)
_CENT = Decimal("0.01")
ZERO = Decimal(0)


class CreditNoteError(ValueError):
    """User-facing problem with a credit note."""


def _money(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


def _inr(v: Decimal) -> str:
    return f"\u20b9{_money(v):,.2f}"


def normalise(number: str) -> str:
    return "".join(ch for ch in number.upper() if ch.isalnum())


def credited_by_line(db: Session, invoice_ids: list[int] | None = None,
                     line_ids: list[int] | None = None) -> dict[int, tuple[Decimal, Decimal]]:
    """invoice_line_id -> (credited qty, credited taxable value), summed over credit notes."""
    q = (select(CreditNoteLine.invoice_line_id, CreditNoteLine.qty, CreditNoteLine.taxable_value)
         .join(CreditNote, CreditNote.id == CreditNoteLine.credit_note_id))
    if invoice_ids is not None:
        q = q.where(CreditNote.invoice_id.in_(invoice_ids))
    if line_ids is not None:
        q = q.where(CreditNoteLine.invoice_line_id.in_(line_ids))
    out: dict[int, tuple[Decimal, Decimal]] = defaultdict(lambda: (ZERO, ZERO))
    for line_id, qty, value in db.execute(q):
        q0, v0 = out[line_id]
        out[line_id] = (q0 + qty, v0 + value)
    return dict(out)


def net_amounts(db: Session, invoices: list[Invoice]) -> dict[int, tuple[Decimal, Decimal]]:
    """invoice_id -> (taxable, total) after credit notes. Invoices without credit notes keep their own."""
    out = {i.id: (i.taxable_total, i.total) for i in invoices}
    if not out:
        return out
    for inv_id, taxable, total in db.execute(select(CreditNote.invoice_id, CreditNote.taxable, CreditNote.total)
                                             .where(CreditNote.invoice_id.in_(list(out)))):
        t0, g0 = out[inv_id]
        out[inv_id] = (t0 - taxable, g0 - total)
    return out


def net_total(db: Session, inv: Invoice) -> Decimal:
    return net_amounts(db, [inv])[inv.id][1]


def net_total_inr(db: Session, inv: Invoice) -> Decimal:
    """Net payable in INR (at the invoice's FX rate): what approval limits and MFA compare against."""
    return (net_total(db, inv) * (inv.fx_rate or Decimal(1))).quantize(Decimal("0.01"))


def credit_reasons(db: Session, inv: Invoice) -> list[Reason]:
    """Engine input (information): which credit notes the match is net of."""
    notes = db.scalars(select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.id)).all()
    if not notes:
        return []
    credited = sum((n.total for n in notes), ZERO)
    return [Reason("CREDIT_NOTE_APPLIED", Severity.INFO,
                   f"Matched net of credit note{'s' if len(notes) > 1 else ''} "
                   f"{', '.join(n.number for n in notes)}: {_inr(credited)} credited, net payable "
                   f"{_inr(inv.total - credited)} (invoice total {_inr(inv.total)}).",
                   {"credit_notes": [n.number for n in notes], "credited": str(credited),
                    "net_total": str(inv.total - credited)})]


def is_duplicate(db: Session, inv: Invoice) -> bool:
    """Blocked as a duplicate: the fix is to withdraw the copy, not to credit part of it."""
    mid = db.scalar(select(MatchResult.id).where(MatchResult.invoice_id == inv.id).order_by(MatchResult.id.desc()))
    return mid is not None and db.scalar(select(ReasonCode.id).where(
        ReasonCode.match_result_id == mid, ReasonCode.code == "DUPLICATE")) is not None


def can_credit(db: Session, inv: Invoice) -> bool:
    return inv.status in OPEN_FOR_CREDIT and not is_duplicate(db, inv)


@dataclass
class Suggestion:
    line_no: int
    item: str
    uom: str
    mode: str  # qty (goods) | value (services)
    qty: Decimal  # suggested quantity to credit (goods)
    value: Decimal  # taxable value of the suggestion
    total: Decimal  # incl. GST
    reason_code: str


def in_line_unit(db: Session, ln: InvoiceLine, qty_po_unit: Decimal) -> Decimal:
    """A quantity in the PO line's unit expressed in the invoice line's unit (e.g. 40 NOS -> 4 BOX)."""
    from app.engine import units
    from app.models import POLine
    from app.workflow.matching import item_packs

    pl = db.get(POLine, ln.po_line_id) if ln.po_line_id else None
    f = units.factor(ln.uom, pl.uom, item_packs(db, pl.item_code)) if pl else None
    return (qty_po_unit / f).quantize(Decimal("0.001")) if f else qty_po_unit


def suggest(db: Session, inv: Invoice) -> list[Suggestion]:
    """What credit note would clear this invoice's quantity / value exceptions (from its latest match)."""
    mid = db.scalar(select(MatchResult.id).where(MatchResult.invoice_id == inv.id).order_by(MatchResult.id.desc()))
    if mid is None or is_duplicate(db, inv):
        return []
    lines = {ln.line_no: ln for ln in inv.lines}
    out = []
    for r in db.scalars(select(ReasonCode).where(ReasonCode.match_result_id == mid,
                                                 ReasonCode.code.in_(("QTY_EXCEEDS_GR", "SES_VALUE_EXCEEDED")),
                                                 ReasonCode.severity != Severity.INFO)):
        ln = lines.get(r.line_no)
        if ln is None:
            continue
        excess = Decimal(str((r.evidence or {}).get("excess", "0")))
        if excess <= 0:
            continue
        if r.code == "QTY_EXCEEDS_GR":
            # The excess is in the PO unit; the credit note is in the invoice line's unit (e.g. 40 NOS = 4 BOX).
            qty = in_line_unit(db, ln, excess)
            value = _money(qty * ln.unit_price)
            out.append(Suggestion(ln.line_no, ln.item_code or ln.description, ln.uom, "qty", qty, value,
                                  _money(value * (1 + ln.gst_rate / 100)), r.code))
        else:
            value = _money(excess)
            out.append(Suggestion(ln.line_no, ln.item_code or ln.description, ln.uom, "value", ZERO, value,
                                  _money(value * (1 + ln.gst_rate / 100)), r.code))
    return out


def issue(db: Session, user: User, inv: Invoice, number: str, note_date: date, reason: str,
          lines: list[tuple[int, Decimal | None, Decimal | None]]) -> CreditNote:
    """Record and apply a credit note. lines: (invoice line_no, qty for goods, taxable value for services)."""
    from app.workflow.matching import run_match  # local import: matching imports this module

    number = (number or "").strip()
    if inv.status not in OPEN_FOR_CREDIT:
        raise CreditNoteError(f"Invoice {inv.invoice_number} is {inv.status}: credit notes apply to blocked or "
                              "flagged invoices before approval.")
    if is_duplicate(db, inv):
        raise CreditNoteError(f"Invoice {inv.invoice_number} is blocked as a duplicate: a credit note does not resolve "
                              "it. The copy should be withdrawn.")
    if not 1 <= len(number) <= 16:
        raise CreditNoteError("Credit note number must be 1 to 16 characters (GST rule, as for invoices).")
    norm = normalise(number)
    clash = db.scalar(select(CreditNote.id).where(CreditNote.supplier_id == inv.supplier_id,
                                                  CreditNote.number_norm == norm))
    clash = clash or db.scalar(select(Invoice.id).where(Invoice.supplier_id == inv.supplier_id,
                                                        Invoice.invoice_number == number))
    if clash:
        raise CreditNoteError(f"Number {number} is already used by this supplier.")
    today = clock.today()
    if note_date > today:
        raise CreditNoteError("The credit note date cannot be in the future.")
    if inv.invoice_date and note_date < inv.invoice_date:
        raise CreditNoteError("A credit note cannot be dated before the invoice it corrects.")
    if not (reason or "").strip():
        raise CreditNoteError("Give a reason (for example: 20 bearings not delivered).")

    po = db.get(PurchaseOrder, inv.po_id) if inv.po_id else None
    service = bool(po and po.is_service)
    by_no = {ln.line_no: ln for ln in inv.lines}
    already = credited_by_line(db, [inv.id])
    intra = not (inv.igst and inv.igst > 0)
    rows = []
    for line_no, qty, value in lines:
        ln = by_no.get(line_no)
        if ln is None:
            raise CreditNoteError(f"Line {line_no} is not on invoice {inv.invoice_number}.")
        done_qty, done_value = already.get(ln.id, (ZERO, ZERO))
        if service:
            if value is None or value <= 0:
                raise CreditNoteError(f"Line {line_no}: enter the value to credit.")
            if done_value + value > ln.taxable_value:
                raise CreditNoteError(f"Line {line_no}: cannot credit more than the line's taxable value "
                                      f"{_inr(ln.taxable_value)} (already credited {_inr(done_value)}).")
            qty, taxable = ZERO, _money(value)
        else:
            if qty is None or qty <= 0:
                raise CreditNoteError(f"Line {line_no}: enter the quantity to credit.")
            if done_qty + qty > ln.qty:
                raise CreditNoteError(f"Line {line_no}: cannot credit more than the {fmt_num(ln.qty)} {ln.uom} billed "
                                      f"(already credited {fmt_num(done_qty)}).")
            taxable = _money(qty * ln.unit_price)
        tax = _money(taxable * ln.gst_rate / 100)
        half = _money(tax / 2)
        rows.append((ln, qty, taxable, half if intra else ZERO, half if intra else ZERO, ZERO if intra else tax))
    if not rows:
        raise CreditNoteError("Add at least one line.")

    totals = [sum((r[i] for r in rows), ZERO) for i in (2, 3, 4, 5)]
    note = CreditNote(invoice_id=inv.id, supplier_id=inv.supplier_id, number=number, number_norm=norm,
                      note_date=note_date, reason=reason.strip()[:300], taxable=totals[0], cgst=totals[1],
                      sgst=totals[2], igst=totals[3], total=sum(totals, ZERO), created_by_user_id=user.id)
    db.add(note)
    db.flush()
    for ln, qty, taxable, cgst, sgst, igst in rows:
        db.add(CreditNoteLine(credit_note_id=note.id, invoice_line_id=ln.id, qty=qty, taxable_value=taxable,
                              cgst=cgst, sgst=sgst, igst=igst))
    db.flush()
    audit.queue(db, "credit_note.applied", "invoice", inv.id, after={
        "credit_note": number, "date": note_date.isoformat(), "reason": note.reason, "taxable": str(note.taxable),
        "total": str(note.total), "net_payable": str(inv.total - sum((n.total for n in db.scalars(
            select(CreditNote).where(CreditNote.invoice_id == inv.id))), ZERO)),
        "lines": [{"line_no": r[0].line_no, "qty": str(r[1]), "taxable": str(r[2])} for r in rows],
        "entered_by_role": user.role,
    })
    run_match(db, inv, trigger=f"credit_note:{number}")
    db.commit()
    db.refresh(note)
    return note
