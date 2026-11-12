"""Human confirmation of line matches the engine made by description (spec C3).

When an invoice line's item code does not match the PO, the engine may match it by description.
That is only a suggestion (LINE_MAPPED flag): an AP clerk confirms it (to that PO line or another
line of the same PO) or rejects it (the line is then "not on the PO" and blocks). The decision is
stored on the invoice line, audited with the reason, and honoured by every later match.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import audit
from app.core.enums import Role
from app.models import Invoice, POLine, User
from app.workflow.matching import run_match
from app.workflow.review import EDITABLE_STATUSES


class MappingError(ValueError):
    pass


def decide_mapping(db: Session, inv: Invoice, line_no: int, clerk: User, po_line_id: int | None, reason: str) -> None:
    """po_line_id = the PO line this invoice line is (confirm); None = it is not on the PO (reject)."""
    if clerk.role != Role.CLERK:
        raise MappingError("Only an AP clerk can confirm line matches.")
    if inv.status not in EDITABLE_STATUSES:
        raise MappingError(f"The invoice is {inv.status}; line matches can no longer change.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise MappingError("Give a short reason.")
    line = next((ln for ln in inv.lines if ln.line_no == line_no), None)
    if line is None:
        raise MappingError(f"Line {line_no} does not exist.")
    if po_line_id is not None:
        pl = db.get(POLine, po_line_id)
        if pl is None or pl.po_id != inv.po_id:
            raise MappingError("That PO line is not on this invoice's purchase order.")
        taken = [ln.line_no for ln in inv.lines if ln.line_no != line_no and ln.po_line_id == po_line_id]
        if taken:
            raise MappingError(f"PO line {pl.line_no} is already matched to invoice line {taken[0]}.")
    before = {"line_no": line_no, "po_line_id": line.po_line_id, "decision": line.mapping_decision}
    line.mapping_decision = "confirmed" if po_line_id is not None else "rejected"
    line.mapping_po_line_id = po_line_id
    line.mapping_by_user_id = clerk.id
    audit.queue(db, f"line.mapping_{line.mapping_decision}", "invoice", inv.id, before=before,
                after={"line_no": line_no, "po_line_id": po_line_id, "reason": reason})
    db.flush()
    run_match(db, inv, trigger=f"mapping_{line.mapping_decision}")
    db.commit()
