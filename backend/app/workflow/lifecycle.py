"""The 5-stop Duly rail: ordered -> received -> matched -> approved -> paid, from real invoice state."""
from __future__ import annotations

from app.core.enums import Decision, InvoiceStatus
from app.models import Invoice

_RECEIPT_MISSING = {"MISSING_GR", "MISSING_SES"}


def rail_progress(inv: Invoice, reason_codes: set[str]) -> int:
    """Number of completed stops (0-5). A stop only counts if every stop before it is done."""
    stops = [
        inv.po_id is not None,  # Duly ordered: invoice quotes a valid PO
        not (reason_codes & _RECEIPT_MISSING),  # Duly received: GR/SES posted
        inv.decision == Decision.APPROVE and inv.status != InvoiceStatus.NEEDS_REVIEW,  # Duly matched
        inv.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID),  # Duly approved
        inv.status == InvoiceStatus.PAID,  # Duly paid
    ]
    done = 0
    for ok in stops:
        if not ok:
            break
        done += 1
    return done
