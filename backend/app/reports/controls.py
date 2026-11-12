"""Controls report for auditors (spec B3). Each control is TESTED on the live data for the
period, not asserted: the result is computed from invoices, match results, approval steps,
audit events and users.

Result values: effective | exceptions | no_activity (nothing happened in the period that
the control applies to, so it could not be tested; reported honestly, not as a pass).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.enums import Decision, InvoiceStatus, Role, StepStatus
from app.models import (ApprovalStep, AuditEvent, BankChangeRequest, ExtractionResult, Invoice, MatchResult, Payment,
                        Policy, PurchaseOrder, ReasonCode, User)
from app.models.base import as_utc
from app.workflow.approvals import required_levels

FINAL = (InvoiceStatus.APPROVED, InvoiceStatus.PAID)


@dataclass
class ControlResult:
    id: str
    title: str
    objective: str
    how: str
    test: str
    result: str  # effective | exceptions | no_activity
    population: int  # how many items the test examined
    exceptions: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)  # {label, invoice_id?}


@dataclass
class ControlsReport:
    period_from: date
    period_to: date
    generated_at: datetime
    controls: list[ControlResult]
    overrides: list[dict]
    opinion: str


def _result(population: int, exceptions: list) -> str:
    if population == 0:
        return "no_activity"
    return "exceptions" if exceptions else "effective"


def _latest_matches(db: Session, ids: list[int]) -> dict[int, MatchResult]:
    out: dict[int, MatchResult] = {}
    for m in db.scalars(select(MatchResult).where(MatchResult.invoice_id.in_(ids)).order_by(MatchResult.id)):
        out[m.invoice_id] = m
    return out


def build(db: Session, period_from: date, period_to: date) -> ControlsReport:
    start = datetime.combine(period_from, time.min, clock.IST)
    end = datetime.combine(period_to + timedelta(days=1), time.min, clock.IST)
    invoices = [i for i in db.scalars(select(Invoice)) if start <= as_utc(i.received_at) < end]
    ids = [i.id for i in invoices]
    by_id = {i.id: i for i in invoices}
    final = [i for i in invoices if i.status in FINAL]
    latest = _latest_matches(db, ids)
    codes: dict[int, set[str]] = {}
    for r in db.execute(select(MatchResult.invoice_id, ReasonCode.code)
                        .join(ReasonCode, ReasonCode.match_result_id == MatchResult.id)
                        .where(MatchResult.id.in_([m.id for m in latest.values()]))):
        codes.setdefault(r[0], set()).add(r[1])
    steps: dict[int, list[ApprovalStep]] = {}
    for s in db.scalars(select(ApprovalStep).where(ApprovalStep.invoice_id.in_(ids)).order_by(ApprovalStep.sequence)):
        steps.setdefault(s.invoice_id, []).append(s)
    events = [e for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id))
              if start <= as_utc(e.ts) < end]
    users = {u.id: u for u in db.scalars(select(User))}
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True))).data
    ev = lambda i, why: {"invoice_id": i.id, "invoice_number": i.invoice_number, "detail": why}  # noqa: E731
    controls: list[ControlResult] = []

    # C-01 No PO, no pay
    exc = [ev(i, "approved without a valid PO") for i in final if i.po_id is None or "NO_PO" in codes.get(i.id, set())]
    controls.append(ControlResult(
        "C-01", "No PO, no pay", "Every invoice approved for payment is backed by a valid purchase order.",
        "Rules engine blocks NO_PO and PO_CLOSED; a BLOCK cannot be approved or overridden.",
        f"Checked all {len(final)} approved/paid invoices received in the period for a linked PO and no NO_PO reason.",
        _result(len(final), exc), len(final), exc,
        {"blocked_no_po": sum("NO_PO" in codes.get(i, set()) for i in ids)}))

    # C-02 Three-way match enforced; blocks cannot be overridden
    exc = [ev(i, f"approved while its latest match is {latest[i.id].decision}") for i in final
           if i.id in latest and latest[i.id].decision == Decision.BLOCK]
    # Overrides are allowed for flagged or sent-back invoices; a BLOCK must never be overridden.
    bad_overrides = [e for e in events if e.action == "invoice.flag_overridden"
                     and ((e.before or {}).get("decision") == "BLOCK" or (e.before or {}).get("status") == "blocked")]
    exc += [{"invoice_id": int(e.entity_id), "invoice_number": by_id.get(int(e.entity_id)).invoice_number
             if by_id.get(int(e.entity_id)) else e.entity_id, "detail": "override of a BLOCK"} for e in bad_overrides]
    matched = [i for i in invoices if i.id in latest]
    controls.append(ControlResult(
        "C-02", "Three-way match enforced; blocks never overridden",
        "Invoices are paid only after PO, receipt and invoice agree within tolerance; blocked invoices are never paid.",
        "Deterministic engine runs on every upload, correction and receipt; override API refuses BLOCK decisions.",
        f"Re-checked the latest match of {len(matched)} invoices; confirmed none approved while BLOCK and no override of a BLOCK.",
        _result(len(matched), exc), len(matched), exc,
        {"decisions": dict(Counter(m.decision for m in latest.values())),
         "overrides": sum(e.action == "invoice.flag_overridden" for e in events)}))

    # C-03 Duplicate prevention
    dups = [i for i in invoices if codes.get(i.id, set()) & {"DUPLICATE", "POSSIBLE_DUPLICATE"}]
    exc = [ev(i, "duplicate approved for payment") for i in dups if "DUPLICATE" in codes.get(i.id, set()) and i.status in FINAL]
    controls.append(ControlResult(
        "C-03", "Duplicate prevention", "The same invoice is never paid twice.",
        "Exact match on normalised number + supplier + FY, IRN or file hash blocks; near-matches and look-alike scans flag.",
        f"Examined {len(invoices)} invoices; caught as duplicates or possible duplicates: {len(dups)}.",
        _result(len(invoices), exc), len(invoices), exc,
        {"caught": len(dups), "value_caught": str(sum((i.total for i in dups), Decimal(0))),
         "blocked_exact": sum("DUPLICATE" in codes.get(i.id, set()) for i in dups)},
        [ev(i, ", ".join(sorted(codes[i.id] & {"DUPLICATE", "POSSIBLE_DUPLICATE"}))) for i in dups[:10]]))

    # C-04 Delegation of Authority respected
    exc = []
    for i in final:
        done = [s for s in steps.get(i.id, []) if s.status == StepStatus.APPROVED]
        if any(s.by_policy for s in done):
            if i.override_justification or i.total > Decimal(str(policy["doa"]["touchless_max_inr"])):
                exc.append(ev(i, "approved by policy above the touchless limit or after an override"))
            continue
        need = required_levels(i.total, policy, override=bool(i.override_justification))
        have = sorted({s.level for s in done})
        if not set(need) <= set(have):
            exc.append(ev(i, f"needed levels {need}, approved at {have}"))
    controls.append(ControlResult(
        "C-04", "Delegation of Authority thresholds",
        "No invoice is approved above the approver's limit or without every required level.",
        "Approval route built from the versioned DoA policy; an approver can act only at their own level (or by "
        "escalation/delegation, both logged).",
        f"Compared the approval steps of {len(final)} approved invoices with the levels the DoA policy requires.",
        _result(len(final), exc), len(final), exc,
        {"touchless": sum(any(s.by_policy for s in steps.get(i.id, [])) for i in final)}))

    # C-05 Segregation of duties
    exc = []
    for i in final:
        po = db.get(PurchaseOrder, i.po_id) if i.po_id else None
        approvers = [s.approver_user_id for s in steps.get(i.id, []) if s.status == StepStatus.APPROVED and s.approver_user_id]
        if i.processed_by_user_id and i.processed_by_user_id in approvers:
            exc.append(ev(i, "approved by the user who processed it"))
        if po and po.created_by_user_id in approvers:
            exc.append(ev(i, "approved by the user who created the PO"))
        if len(approvers) != len(set(approvers)):
            exc.append(ev(i, "same approver on two steps"))
    refusals = [e for e in events if e.action == "security.sod_refused"]
    controls.append(ControlResult(
        "C-05", "Segregation of duties",
        "Nobody approves an invoice they processed, a PO they raised, or two steps of the same invoice.",
        "Checked on the server before every approval; refusals are logged as security events.",
        f"Checked approvers of {len(final)} approved invoices against processors and PO creators.",
        _result(len(final), exc), len(final), exc,
        {"sod_conflicts": len(exc), "sod_refusals_logged": len(refusals)},
        [{"label": f"SoD refusal: {(e.after or {}).get('reason', '')}", "invoice_id": int(e.entity_id)}
         for e in refusals[:10] if e.entity_id and e.entity_id.isdigit()]))

    # C-06 Vendor bank detail changes (maker-checker with cooling period)
    changes = [c for c in db.scalars(select(BankChangeRequest)) if start <= as_utc(c.requested_at) < end]
    exc = [{"detail": f"bank change #{c.id} approved by its own maker"} for c in changes
           if c.approved_by_user_id and c.approved_by_user_id == c.proposed_by_user_id]
    controls.append(ControlResult(
        "C-06", "Vendor bank detail changes",
        "Bank details change only through maker-checker with a cooling period and call-back confirmation.",
        "Invoices with a bank account different from the vendor master are blocked (BANK_MISMATCH). The change "
        "request workflow arrives with D3 (Phase 3).",
        f"Examined {len(changes)} bank change requests in the period.",
        _result(len(changes), exc), len(changes), exc,
        {"bank_mismatch_blocks": sum("BANK_MISMATCH" in codes.get(i, set()) for i in ids)}))

    # C-07 Audit trail integrity
    v = audit.verify(db)
    controls.append(ControlResult(
        "C-07", "Audit trail integrity", "The audit trail is complete and has not been altered.",
        "Append-only hash chain (SHA-256 over every event); head signed with an Ed25519 key.",
        f"Re-hashed all {v.events} events and verified the signed head.",
        "effective" if v.ok else "exceptions", v.events,
        [] if v.ok else [{"detail": f"chain broken at event #{v.broken_at_id}: {v.problem}"}],
        {"events_in_period": len(events), "head_id": v.head_id, "head_signature_ok": v.head_signature_ok}))

    # C-08 MSME payments within the statutory due date
    msme = [i for i in invoices if i.msme_due_date]
    pays = {p.invoice_id: p for p in db.scalars(select(Payment).where(Payment.invoice_id.in_(ids)))}
    today = clock.today()
    late_paid = [i for i in msme if i.id in pays and as_utc(pays[i.id].paid_at).astimezone(clock.IST).date() > i.msme_due_date]
    overdue = [i for i in msme if i.id not in pays and i.status != InvoiceStatus.REJECTED and i.msme_due_date < today]
    rate = Decimal(str(policy.get("msme", {}).get("rbi_bank_rate_pct", 6.5))) * 3 / 100
    exposure = sum((i.total * (((1 + rate / 12) ** ((today - i.msme_due_date).days / 30)) - 1) for i in overdue), Decimal(0))
    paid_msme = [i for i in msme if i.id in pays]
    controls.append(ControlResult(
        "C-08", "MSME payments on time",
        "Micro and small suppliers are paid within 45 days of acceptance (15 without a written agreement).",
        "Statutory due date computed at acceptance; countdown on the dashboard and supplier portal; payment run "
        "prioritises MSMEs (D5, Phase 3).",
        f"Checked {len(msme)} MSME invoices: {len(paid_msme)} paid, {len(overdue)} unpaid past the due date.",
        _result(len(msme), late_paid + overdue),
        len(msme), [ev(i, "paid after the MSME due date") for i in late_paid] +
        [ev(i, f"unpaid {(today - i.msme_due_date).days} days after the MSME due date") for i in overdue],
        {"on_time_pct": round(100 * (len(paid_msme) - len(late_paid)) / len(paid_msme), 1) if paid_msme else None,
         "interest_exposure_inr": str(exposure.quantize(Decimal("0.01"))),
         "interest_rate_pct": str((rate * 100).quantize(Decimal("0.01")))}))

    # C-09 AI governance
    results = db.scalars(select(ExtractionResult).where(ExtractionResult.invoice_id.in_(ids))).all()
    latest_field: dict[tuple[int, str], ExtractionResult] = {}
    for r in sorted(results, key=lambda r: r.id):
        latest_field[(r.invoice_id, r.field)] = r
    threshold = float(policy.get("confidence_threshold", 0.85))
    unreviewed = {k[0] for k, r in latest_field.items()
                  if r.source != "manual" and r.value is not None and r.confidence < threshold and by_id[k[0]].status in FINAL}
    ai_decided = [e for e in events if e.action == "invoice.matched" and (e.after or {}).get("ai_decided") is not False]
    exc = [ev(by_id[i], "approved with low-confidence fields never reviewed") for i in unreviewed]
    exc += [{"detail": f"match event #{e.id} not marked as a rules decision"} for e in ai_decided]
    reviewed = sum(1 for r in results if r.source == "manual")
    models = Counter(f"{r.model} / {r.prompt_version}" for r in results if r.source != "manual")
    controls.append(ControlResult(
        "C-09", "AI governance", "AI never decides; low-confidence AI output is checked by a person.",
        "AI only extracts and explains; the rules engine (no AI import, enforced by a test) decides; fields below "
        f"{threshold:.0%} confidence go to human review; model and prompt version stored per field.",
        f"Checked {len(final)} approved invoices for unreviewed low-confidence fields and {sum(e.action == 'invoice.matched' for e in events)} "
        "decisions for AI involvement.",
        _result(len(invoices), exc), len(invoices), exc,
        {"fields_extracted": len(results) - reviewed, "fields_human_reviewed": reviewed,
         "ai_approvals": 0 if not ai_decided else len(ai_decided), "models_and_prompts": dict(models)}))

    # C-10 Access reviews
    staff = [u for u in users.values()]
    exc = [{"detail": f"approver {u.full_name} has no MFA enrolled"} for u in staff
           if u.role == Role.APPROVER and not u.mfa_enabled]
    exc += [{"detail": f"admin {u.full_name} also holds approval rights"} for u in staff
            if u.role == Role.ADMIN and u.approver_level]
    controls.append(ControlResult(
        "C-10", "Access review", "Only the right people have access; approvers use MFA; admins cannot approve.",
        "Role-based access on every API call, supplier row scoping, lockout after 5 failures, MFA for high-value approvals.",
        f"Reviewed {len(staff)} user accounts (role, last login, MFA, lock status).",
        _result(len(staff), exc), len(staff), exc,
        {"users": [{"name": u.full_name, "role": u.role, "level": u.approver_level, "mfa": u.mfa_enabled,
                    "last_login": as_utc(u.last_login_at).isoformat() if u.last_login_at else None,
                    "locked": bool(u.locked_until and as_utc(u.locked_until) > clock.now())}
                   for u in sorted(staff, key=lambda u: (u.role, u.full_name))]}))

    overrides = []
    for i in invoices:
        if i.override_justification:
            approvers = [users[s.approver_user_id].full_name for s in steps.get(i.id, [])
                         if s.status == StepStatus.APPROVED and s.approver_user_id in users]
            overrides.append({"invoice_id": i.id, "invoice_number": i.invoice_number, "total": str(i.total),
                              "by": users[i.override_by_user_id].full_name if i.override_by_user_id in users else None,
                              "at": as_utc(i.override_at).isoformat() if i.override_at else None,
                              "justification": i.override_justification, "approved_by": approvers,
                              "status": i.status})

    counts = Counter(c.result for c in controls)
    opinion = (f"{len(controls)} controls tested: {counts['effective']} effective, {counts['exceptions']} with exceptions"
               + (f", {counts['no_activity']} with no activity in the period" if counts["no_activity"] else "") + ".")
    return ControlsReport(period_from, period_to, clock.now(), controls, overrides, opinion)
