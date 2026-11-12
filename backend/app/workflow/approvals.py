"""Approval workflow (spec C4): Delegation of Authority, SoD, overrides, MFA step-up, SLA.

DoA (policy data, defaults are assumptions):
  clean match, total <= touchless max (Rs 50,000)  -> approved by policy P-01, no human
  total <= Rs 10 lakh                               -> L1 Finance Manager
  total <= Rs 1 crore                               -> L1 then L2 Plant Head
  above                                             -> L1, L2, then L3 CFO
A FLAG can be routed anyway by a clerk with a written justification (an override). An
override is never touchless and always needs at least two approvers (L1 and L2). A BLOCK
can never be overridden.

Segregation of duties, enforced here (not in the UI): an approver may not approve an
invoice they processed, an invoice for a PO they created, or two steps of the same invoice.
Approvals above the MFA threshold (Rs 10 lakh) need a valid TOTP code.
SLA: each step is due `sla_hours` after it opens; an overdue step escalates so the next
level can act on it as well. Escalation is evaluated lazily against the business clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pyotp
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.crypto import decrypt_str
from app.core.enums import Decision, InvoiceStatus, Role, StepStatus
from app.models import ApprovalStep, Delegation, Invoice, Policy, PurchaseOrder, User
from app.models.base import as_utc
from app.workflow.credit_notes import net_total

LEVEL_TITLE = {1: "L1 Finance Manager", 2: "L2 Plant Head", 3: "L3 CFO"}


class ApprovalError(ValueError):
    """User-facing refusal; `sod` marks a segregation-of-duties refusal."""

    def __init__(self, message: str, sod: bool = False, mfa: bool = False):
        super().__init__(message)
        self.sod = sod
        self.mfa = mfa


def _policy(db: Session) -> dict:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True))).data


def required_levels(total: Decimal, policy: dict, override: bool) -> list[int]:
    """Approval levels for an invoice value. [] means touchless (approved by policy P-01)."""
    doa = policy["doa"]
    if not override and total <= Decimal(str(doa["touchless_max_inr"])):
        return []
    for band in doa["bands"]:
        if band["max_inr"] is None or total <= Decimal(str(band["max_inr"])):
            levels = list(band["levels"])
            break
    if override and len(levels) < 2:
        levels = [1, 2]  # an override needs a second approver
    return levels


def steps_of(db: Session, invoice_id: int) -> list[ApprovalStep]:
    return list(db.scalars(select(ApprovalStep).where(ApprovalStep.invoice_id == invoice_id)
                           .order_by(ApprovalStep.sequence, ApprovalStep.id)))


def current_step(db: Session, invoice_id: int) -> ApprovalStep | None:
    return next((s for s in steps_of(db, invoice_id) if s.status == StepStatus.PENDING), None)


def _owner_for(step: ApprovalStep) -> str:
    owner = f"Awaiting {LEVEL_TITLE[step.level]}"
    if step.escalated_at is not None and step.level < 3:
        owner += f" (escalated to L{step.level + 1})"
    return owner


def _open_route(db: Session, inv: Invoice, override: bool) -> None:
    policy = _policy(db)
    amount = net_total(db, inv)  # net of credit notes
    levels = required_levels(amount, policy, override)
    now = clock.now()
    if not levels:
        db.add(ApprovalStep(invoice_id=inv.id, sequence=1, level=0, status=StepStatus.APPROVED, by_policy="P-01",
                            decided_at=now, comment=f"Clean match at or below the touchless limit "
                                                    f"(Rs {policy['doa']['touchless_max_inr']:,})."))
        inv.status, inv.current_owner = InvoiceStatus.APPROVED, "Approved by policy P-01; awaiting payment run"
        audit.queue(db, "approval.by_policy", "invoice", inv.id,
                    after={"policy": "P-01", "total": amount, "touchless_max": policy["doa"]["touchless_max_inr"]}, actor=audit.SYSTEM)
        return
    sla = timedelta(hours=policy.get("sla_hours", 48))
    for i, level in enumerate(levels, start=1):
        db.add(ApprovalStep(invoice_id=inv.id, sequence=i, level=level, status=StepStatus.PENDING,
                            due_at=now + sla if i == 1 else None))
    inv.status = InvoiceStatus.PENDING_APPROVAL
    inv.current_owner = f"Awaiting {LEVEL_TITLE[levels[0]]}"
    audit.queue(db, "approval.routed", "invoice", inv.id,
                after={"levels": levels, "total": amount, "override": override,
                       "sla_hours": sla.total_seconds() / 3600}, actor=audit.SYSTEM)


def _cancel_open_steps(db: Session, inv: Invoice, why: str) -> None:
    for s in steps_of(db, inv.id):
        if s.status == StepStatus.PENDING:
            s.status, s.comment, s.decided_at = StepStatus.SKIPPED, why, clock.now()


def sync_after_match(db: Session, inv: Invoice) -> None:
    """Called by run_match: open an approval route for a clean match, close it otherwise."""
    if inv.status == InvoiceStatus.PENDING_APPROVAL and inv.decision == Decision.APPROVE:
        if current_step(db, inv.id) is None:
            _open_route(db, inv, override=False)
    elif inv.status in (InvoiceStatus.FLAGGED, InvoiceStatus.BLOCKED):
        inv.override_by_user_id = inv.override_justification = inv.override_at = None
        _cancel_open_steps(db, inv, f"Cancelled: invoice re-matched as {inv.decision}")


def override_flag(db: Session, inv: Invoice, clerk: User, justification: str) -> None:
    """Clerk routes a FLAGGED invoice for approval with a written justification."""
    if inv.status == InvoiceStatus.BLOCKED or inv.decision == Decision.BLOCK:
        raise ApprovalError("A BLOCK cannot be overridden. Fix the cause (for example a GR or a credit note) "
                            "and Duly will re-check the invoice.")
    if inv.status != InvoiceStatus.FLAGGED:
        raise ApprovalError("Only a flagged invoice can be routed with an override.")
    if len(justification.strip()) < 15:
        raise ApprovalError("Write a justification of at least 15 characters; it is shown to approvers and auditors.")
    audit.queue(db, "invoice.flag_overridden", "invoice", inv.id,
                before={"decision": inv.decision, "status": inv.status}, after={"justification": justification.strip()})
    inv.override_by_user_id, inv.override_justification, inv.override_at = clerk.id, justification.strip(), clock.now()
    inv.processed_by_user_id = clerk.id
    _open_route(db, inv, override=True)
    db.commit()


# --- SLA escalation -------------------------------------------------------------------------

def escalate_overdue(db: Session) -> int:
    """Mark overdue pending steps as escalated. Returns how many were escalated now."""
    now = clock.now()
    n = 0
    for s in db.scalars(select(ApprovalStep).where(ApprovalStep.status == StepStatus.PENDING,
                                                   ApprovalStep.escalated_at.is_(None),
                                                   ApprovalStep.due_at.is_not(None))):
        if as_utc(s.due_at) < now and s.level < 3:
            s.escalated_at = now
            inv = db.get(Invoice, s.invoice_id)
            inv.current_owner = _owner_for(s)
            audit.queue(db, "approval.escalated", "invoice", inv.id,
                        after={"level": s.level, "to_level": s.level + 1, "due_at": s.due_at},
                        actor=audit.SYSTEM)
            n += 1
    if n:
        db.commit()
    return n


# --- Who may act on a step -----------------------------------------------------------------

@dataclass(frozen=True)
class Authority:
    allowed: bool
    reason: str | None = None  # why not (shown in the UI)
    via_delegation_from: int | None = None
    sod: bool = False


def _active_delegators(db: Session, user: User) -> list[User]:
    now = clock.now()
    rows = db.scalars(select(Delegation).where(Delegation.to_user_id == user.id, Delegation.revoked.is_(False)))
    return [db.get(User, d.from_user_id) for d in rows if as_utc(d.starts_at) <= now <= as_utc(d.ends_at)]


def authority(db: Session, inv: Invoice, step: ApprovalStep, user: User) -> Authority:
    if user.role != Role.APPROVER:
        if user.role == Role.CLERK:
            return Authority(False, "Segregation of duties: AP clerks process invoices and cannot approve them.",
                             sod=True)
        return Authority(False, "Only approvers can approve invoices.")
    # SoD rules come first: they apply whatever the level.
    if inv.processed_by_user_id == user.id:
        return Authority(False, "Segregation of duties: you processed this invoice, so you cannot approve it.", sod=True)
    po = db.get(PurchaseOrder, inv.po_id) if inv.po_id else None
    if po is not None and po.created_by_user_id == user.id:
        return Authority(False, f"Segregation of duties: you created PO {po.po_number}, so you cannot approve "
                                "its invoice.", sod=True)
    if any(s.approver_user_id == user.id and s.status == StepStatus.APPROVED for s in steps_of(db, inv.id)):
        return Authority(False, "Segregation of duties: you already approved an earlier step of this invoice.",
                         sod=True)
    if user.approver_level == step.level:
        return Authority(True)
    if step.escalated_at is not None and user.approver_level == step.level + 1:
        return Authority(True)
    for d in _active_delegators(db, user):
        if d.approver_level == step.level:
            return Authority(True, via_delegation_from=d.id)
    if (user.approver_level or 0) < step.level:
        return Authority(False, f"This step needs {LEVEL_TITLE[step.level]}; your limit is "
                                f"{LEVEL_TITLE.get(user.approver_level or 0, 'none')}.")
    return Authority(False, f"This step is for {LEVEL_TITLE[step.level]}.")


def mfa_required(db: Session, inv: Invoice) -> bool:
    return net_total(db, inv) > Decimal(str(_policy(db).get("mfa_threshold_inr", 1_000_000)))


def _check_mfa(db: Session, inv: Invoice, user: User, code: str | None) -> bool:
    if not mfa_required(db, inv):
        return False
    if not user.mfa_enabled or not user.mfa_secret_enc:
        raise ApprovalError("This approval needs MFA, but your account has no authenticator enrolled.", mfa=True)
    if not code or not pyotp.TOTP(decrypt_str(user.mfa_secret_enc)).verify(code.strip(), valid_window=1):
        raise ApprovalError("Invoices above Rs 10 lakh need a valid 6-digit code from your authenticator app.",
                            mfa=True)
    return True


# --- Actions --------------------------------------------------------------------------------

def _actionable(db: Session, inv: Invoice, user: User) -> tuple[ApprovalStep, Authority]:
    escalate_overdue(db)
    if inv.status != InvoiceStatus.PENDING_APPROVAL:
        raise ApprovalError("This invoice is not waiting for approval.")
    step = current_step(db, inv.id)
    if step is None:
        raise ApprovalError("This invoice has no open approval step.")
    auth = authority(db, inv, step, user)
    if not auth.allowed:
        raise ApprovalError(auth.reason or "Not allowed.", sod=auth.sod)
    return step, auth


def approve(db: Session, inv: Invoice, user: User, comment: str, totp: str | None) -> None:
    step, auth = _actionable(db, inv, user)
    step.mfa_verified = _check_mfa(db, inv, user, totp)
    now = clock.now()
    step.status, step.approver_user_id, step.decided_at = StepStatus.APPROVED, user.id, now
    step.delegated_from_user_id, step.comment = auth.via_delegation_from, comment.strip() or None
    audit.queue(db, "approval.approved", "invoice", inv.id,
                after={"level": step.level, "mfa": step.mfa_verified, "delegated_from": auth.via_delegation_from,
                       "comment": step.comment, "total": inv.total})
    nxt = current_step(db, inv.id)
    if nxt is None:
        inv.status, inv.current_owner = InvoiceStatus.APPROVED, "Approved; awaiting payment run"
    else:
        nxt.due_at = now + timedelta(hours=_policy(db).get("sla_hours", 48))
        inv.current_owner = _owner_for(nxt)
    db.commit()


def reject(db: Session, inv: Invoice, user: User, reason: str) -> None:
    if len(reason.strip()) < 5:
        raise ApprovalError("A rejection needs a reason; the supplier will see it.")
    step, auth = _actionable(db, inv, user)
    step.status, step.approver_user_id, step.decided_at = StepStatus.REJECTED, user.id, clock.now()
    step.delegated_from_user_id, step.comment = auth.via_delegation_from, reason.strip()
    audit.queue(db, "approval.rejected", "invoice", inv.id, after={"level": step.level, "reason": reason.strip()})
    _cancel_open_steps(db, inv, "Cancelled: invoice rejected")
    inv.status, inv.current_owner = InvoiceStatus.REJECTED, "Rejected"
    db.commit()


def send_back(db: Session, inv: Invoice, user: User, comment: str) -> None:
    if len(comment.strip()) < 5:
        raise ApprovalError("Say what the clerk should look at.")
    step, auth = _actionable(db, inv, user)
    step.status, step.approver_user_id, step.decided_at = StepStatus.SKIPPED, user.id, clock.now()
    step.delegated_from_user_id, step.comment = auth.via_delegation_from, f"Sent back to AP clerk: {comment.strip()}"
    audit.queue(db, "approval.sent_back", "invoice", inv.id, after={"level": step.level, "comment": comment.strip()})
    _cancel_open_steps(db, inv, "Cancelled: sent back to AP clerk")
    inv.status, inv.current_owner = InvoiceStatus.FLAGGED, f"AP clerk (sent back by {LEVEL_TITLE[step.level][:2]})"
    db.commit()


def request_info(db: Session, inv: Invoice, user: User, question: str) -> None:
    if len(question.strip()) < 5:
        raise ApprovalError("Write the question for the supplier.")
    step, _auth = _actionable(db, inv, user)
    step.comment = f"Information requested from supplier: {question.strip()}"
    inv.current_owner = "Supplier (information requested)"
    audit.queue(db, "approval.info_requested", "invoice", inv.id,
                after={"level": step.level, "question": question.strip()})
    db.commit()


def add_delegation(db: Session, user: User, to_user_id: int, days: int, reason: str) -> Delegation:
    if user.role != Role.APPROVER:
        raise ApprovalError("Only approvers can delegate.")
    target = db.get(User, to_user_id)
    if target is None or target.role != Role.APPROVER or target.id == user.id:
        raise ApprovalError("Delegate to another approver.")
    if not 1 <= days <= 30:
        raise ApprovalError("Delegations last 1 to 30 days.")
    if len(reason.strip()) < 3:
        raise ApprovalError("Give a reason for the delegation.")
    now = clock.now()
    d = Delegation(from_user_id=user.id, to_user_id=target.id, starts_at=now, ends_at=now + timedelta(days=days),
                   reason=reason.strip())
    db.add(d)
    db.flush()
    audit.queue(db, "approval.delegated", "delegation", d.id,
                after={"to_user_id": target.id, "days": days, "reason": reason.strip(), "ends_at": d.ends_at})
    db.commit()
    return d


def approver_queue(db: Session, user: User) -> list[tuple[Invoice, ApprovalStep, Authority]]:
    """Invoices whose current step this user could act on, plus ones they are blocked from by SoD."""
    escalate_overdue(db)
    out = []
    for inv in db.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.PENDING_APPROVAL)
                          .order_by(Invoice.received_at)):
        step = current_step(db, inv.id)
        if step is None:
            continue
        auth = authority(db, inv, step, user)
        relevant = auth.allowed or (auth.sod and (user.approver_level == step.level))
        if relevant:
            out.append((inv, step, auth))
    return out


def delegations_for(db: Session, user: User) -> list[Delegation]:
    return list(db.scalars(select(Delegation).where(or_(Delegation.from_user_id == user.id,
                                                        Delegation.to_user_id == user.id))
                           .order_by(Delegation.id.desc())))
