"""Human review of extracted fields (spec C2 step 7).

A clerk either confirms a field as read or corrects it, always with a reason. Each action
appends a new ExtractionResult (source="manual", confidence 1.0) that records the previous
value and confidence; the old row is kept and marked `corrected`. The invoice record is
updated, the match is re-run, and once no field is below the threshold the invoice leaves
the review queue.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core import audit
from app.core.crypto import encrypt_str
from app.core.enums import InvoiceStatus
from app.ingestion.pipeline import latest_fields, normalise_invoice_number, pending_review
from app.models import ExtractionResult, Invoice, User
from app.validation.rules import fiscal_year
from app.workflow.matching import run_match

EDITABLE_STATUSES = {InvoiceStatus.RECEIVED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.FLAGGED, InvoiceStatus.BLOCKED}
_MONEY = {"taxable_total", "cgst", "sgst", "igst", "total"}
_LINE_DECIMAL = {"qty", "unit_price", "taxable_value", "gst_rate", "cgst", "sgst", "igst"}
_LINE_TEXT = {"item_code", "description", "hsn_sac", "uom"}
_LINE_PATH = re.compile(r"^lines\[(\d+)\]\.(\w+)$")


class ReviewError(ValueError):
    """User-facing problem with a review action."""


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation as e:
        raise ReviewError(f"'{value}' is not a number.") from e


def _apply(inv: Invoice, path: str, value: str) -> str:
    """Write a reviewed value onto the invoice; return the value as stored in the review log."""
    value = value.strip()
    m = _LINE_PATH.match(path)
    if m:
        idx, name = int(m.group(1)), m.group(2)
        line = next((ln for ln in inv.lines if ln.line_no == idx + 1), None)
        if line is None:
            raise ReviewError(f"Line {idx + 1} does not exist.")
        if name in _LINE_DECIMAL:
            setattr(line, name, _decimal(value))
        elif name in _LINE_TEXT:
            setattr(line, name, value.upper() if name in {"uom", "item_code"} else value)
        else:
            raise ReviewError(f"Field '{name}' cannot be edited.")
        return value
    if path in _MONEY:
        setattr(inv, path, _decimal(value))
    elif path == "invoice_number":
        inv.invoice_number, inv.invoice_number_norm = value, normalise_invoice_number(value)
    elif path == "invoice_date":
        try:
            d = date.fromisoformat(value)
        except ValueError as e:
            raise ReviewError("Invoice date must be YYYY-MM-DD.") from e
        inv.invoice_date, inv.fiscal_year = d, fiscal_year(d)
    elif path == "po_number":
        inv.po_number_text = value.upper()
    elif path in {"supplier_gstin", "buyer_gstin", "bank_ifsc"}:
        setattr(inv, path, value.upper())
    elif path in {"place_of_supply", "currency", "irn"}:
        setattr(inv, path, value.upper() if path == "currency" else value)
    elif path == "bank_account":
        digits = re.sub(r"\D", "", value)
        if not 9 <= len(digits) <= 18:
            raise ReviewError("Bank account must be 9 to 18 digits.")
        inv.bank_account_enc, inv.bank_account_last4 = encrypt_str(digits), digits[-4:]
        return "X" * (len(digits) - 4) + digits[-4:]  # never log the plain account
    elif path == "supplier_name":
        pass  # informational only: suppliers are identified by GSTIN
    else:
        raise ReviewError(f"Field '{path}' cannot be edited.")
    return value


def review_field(db: Session, inv: Invoice, user: User, path: str, value: str | None, reason: str) -> list[str]:
    """Confirm (value=None) or correct one field. Returns the fields still pending review."""
    if inv.status not in EDITABLE_STATUSES:
        raise ReviewError(f"Invoice is {inv.status.replace('_', ' ')}; fields can no longer be changed.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ReviewError("A reason is required for every review action.")
    current = latest_fields(db, inv.id).get(path)
    if current is None:
        raise ReviewError(f"Unknown field '{path}'.")
    if value is None:
        if current.value is None:
            raise ReviewError("This field was not found on the document; enter the value instead.")
        new_value = current.value  # confirm as read
        if path != "bank_account":  # the logged account is masked; the invoice already holds it
            _apply(inv, path, current.value)
    else:
        new_value = _apply(inv, path, value)

    audit.queue(db, "field.reviewed", "invoice", inv.id,
                before={"field": path, "value": current.value, "confidence": current.confidence,
                        "source": current.source},
                after={"field": path, "value": new_value, "action": "confirmed" if value is None else "corrected",
                       "reason": reason[:300]})
    current.corrected = True
    db.add(ExtractionResult(
        invoice_id=inv.id, field=path, value=new_value, confidence=1.0, page=current.page, bbox=current.bbox,
        source="manual", previous_value=current.value, previous_confidence=current.confidence,
        reviewed_by_user_id=user.id, review_reason=reason[:300],
    ))
    inv.processed_by_user_id = user.id  # SoD: whoever processes an invoice may not approve it
    db.flush()

    db.refresh(inv)  # reload lines with the corrected values for the engine
    remaining = pending_review(db, inv.id)
    if not remaining and inv.status == InvoiceStatus.NEEDS_REVIEW:
        inv.status = InvoiceStatus.RECEIVED  # review complete: let the decision take effect
    run_match(db, inv, trigger="review_completed" if not remaining else "correction")
    db.commit()
    return remaining
