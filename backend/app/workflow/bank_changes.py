"""Vendor bank detail changes (D3): the defence against payment-redirection (BEC) fraud.

  1. Supplier requests the change in the portal (new account, IFSC, bank, reason).
  2. AP clerk (maker) calls the supplier back on the phone number ALREADY in the vendor master
     (never one from the request or an email), completes the checklist, and proposes the change.
  3. Cooling period (72 h by policy): nothing can be approved before it ends, so a fraudulent
     request has time to be noticed.
  4. Finance manager (checker, approver L1+, not the maker) approves; only then is the vendor
     master updated (account encrypted, AES-GCM) and waiting invoices re-checked.
Every step is audited. Until then, an invoice printing the new account stays BLOCKED (BANK_MISMATCH).
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.crypto import decrypt_str, encrypt_str
from app.core.enums import BankChangeStatus, InvoiceStatus, Role
from app.models import BankChangeRequest, Invoice, Policy, Supplier, User
from app.models.base import as_utc
from app.workflow.matching import run_match

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
CHECKLIST = {
    "called_number_on_file": "Called the supplier on the phone number already in the vendor master (not one given in the request)",
    "confirmed_with_known_contact": "Spoke to a known contact who confirmed the new account number and IFSC",
    "bank_proof_received": "Received a cancelled cheque or bank letter for the new account",
}


class BankChangeError(ValueError):
    def __init__(self, message: str, sod: bool = False):
        super().__init__(message)
        self.sod = sod


def _cooling_hours(db: Session) -> int:
    return int(db.scalar(select(Policy).where(Policy.is_active.is_(True))).data.get("bank_change_cooling_hours", 72))


def mask(last4: str) -> str:
    return "XXXXXX" + last4


def request_change(db: Session, user: User, account: str, ifsc: str, bank_name: str, reason: str) -> BankChangeRequest:
    if user.role != Role.SUPPLIER:
        raise BankChangeError("Only the supplier can request a change of its own bank details.")
    digits = re.sub(r"\D", "", account)
    ifsc = ifsc.strip().upper()
    if not 9 <= len(digits) <= 18:
        raise BankChangeError("Account number must be 9 to 18 digits.")
    if not IFSC_RE.match(ifsc):
        raise BankChangeError("IFSC must look like ABCD0123456.")
    if len(reason.strip()) < 5 or len(bank_name.strip()) < 3:
        raise BankChangeError("Give the bank name and a reason for the change.")
    supplier = db.get(Supplier, user.supplier_id)
    if digits == decrypt_str(supplier.bank_account_enc) and ifsc == supplier.bank_ifsc:
        raise BankChangeError("These are already your bank details on record.")
    if db.scalar(select(BankChangeRequest).where(BankChangeRequest.supplier_id == supplier.id,
                                                 BankChangeRequest.status.in_(("requested", "proposed", "cooling")))):
        raise BankChangeError("A bank change request is already in progress.")
    r = BankChangeRequest(supplier_id=supplier.id, new_account_enc=encrypt_str(digits), new_account_last4=digits[-4:],
                          new_ifsc=ifsc, new_bank_name=bank_name.strip()[:100], reason=reason.strip()[:300],
                          status=BankChangeStatus.REQUESTED, requested_by_user_id=user.id, requested_at=clock.now())
    db.add(r)
    db.flush()
    audit.queue(db, "bank_change.requested", "bank_change", r.id,
                before={"account": mask(supplier.bank_account_last4), "ifsc": supplier.bank_ifsc},
                after={"account": mask(r.new_account_last4), "ifsc": ifsc, "bank": r.new_bank_name, "reason": r.reason})
    db.commit()
    return r


def propose(db: Session, r: BankChangeRequest, clerk: User, checklist: dict[str, bool], contact: str, notes: str) -> None:
    if clerk.role != Role.CLERK:
        raise BankChangeError("Only an AP clerk can propose a bank change (maker).", sod=True)
    if r.status != BankChangeStatus.REQUESTED:
        raise BankChangeError(f"This request is {r.status}.")
    missing = [label for key, label in CHECKLIST.items() if not checklist.get(key)]
    if missing:
        raise BankChangeError("Complete the call-back checklist first: " + "; ".join(missing))
    if len(contact.strip()) < 3:
        raise BankChangeError("Record who you spoke to.")
    now = clock.now()
    r.status, r.proposed_by_user_id, r.callback_confirmed = BankChangeStatus.COOLING, clerk.id, True
    r.callback = {"checklist": {k: bool(checklist.get(k)) for k in CHECKLIST}, "contact": contact.strip()[:100],
                  "notes": notes.strip()[:300], "at": now.isoformat()}
    r.cooling_until = now + timedelta(hours=_cooling_hours(db))
    audit.queue(db, "bank_change.proposed", "bank_change", r.id,
                after={"cooling_until": r.cooling_until, "contact": contact.strip()[:100], "callback": True})
    db.commit()


def approve(db: Session, r: BankChangeRequest, approver: User, note: str) -> list[int]:
    """Checker approval: update the vendor master and re-check waiting invoices. Returns their ids."""
    if approver.role != Role.APPROVER:
        raise BankChangeError("Only a finance approver can approve a bank change (checker).", sod=True)
    if approver.id in (r.proposed_by_user_id, r.requested_by_user_id):
        raise BankChangeError("Segregation of duties: the maker cannot also be the checker.", sod=True)
    if r.status != BankChangeStatus.COOLING:
        raise BankChangeError(f"This request is {r.status}; it must be proposed and cooled first.")
    left = as_utc(r.cooling_until) - clock.now()
    if left.total_seconds() > 0:
        hours = int(left.total_seconds() // 3600) + 1
        raise BankChangeError(f"Cooling period: this change can be approved in about {hours} hour(s).")
    supplier = db.get(Supplier, r.supplier_id)
    before = {"account": mask(supplier.bank_account_last4), "ifsc": supplier.bank_ifsc, "bank": supplier.bank_name}
    supplier.bank_account_enc, supplier.bank_account_last4 = r.new_account_enc, r.new_account_last4
    supplier.bank_ifsc, supplier.bank_name = r.new_ifsc, r.new_bank_name
    r.status, r.approved_by_user_id, r.decided_at, r.decision_note = (BankChangeStatus.APPROVED, approver.id,
                                                                      clock.now(), note.strip()[:300] or None)
    audit.queue(db, "bank_change.approved", "supplier", supplier.id, before=before,
                after={"account": mask(r.new_account_last4), "ifsc": r.new_ifsc, "bank": r.new_bank_name,
                       "request": r.id})
    db.flush()
    rechecked = []
    for inv in db.scalars(select(Invoice).where(Invoice.supplier_id == supplier.id,
                                                Invoice.status.in_((InvoiceStatus.BLOCKED, InvoiceStatus.FLAGGED)))):
        run_match(db, inv, trigger=f"bank_change_approved:{r.id}")
        rechecked.append(inv.id)
    db.commit()
    return rechecked


def reject(db: Session, r: BankChangeRequest, user: User, note: str) -> None:
    if user.role not in (Role.CLERK, Role.APPROVER):
        raise BankChangeError("Only AP staff can reject a bank change.")
    if r.status not in (BankChangeStatus.REQUESTED, BankChangeStatus.COOLING):
        raise BankChangeError(f"This request is {r.status}.")
    if len(note.strip()) < 5:
        raise BankChangeError("Give a reason; the supplier will see it.")
    r.status, r.decided_at, r.decision_note = BankChangeStatus.REJECTED, clock.now(), note.strip()[:300]
    audit.queue(db, "bank_change.rejected", "bank_change", r.id, after={"reason": r.decision_note})
    db.commit()
