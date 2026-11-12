"""Policy changes: finance rules are versioned data, changed by an admin without a code release.

A change never edits the active policy in place. It validates the edited values, writes a new
version (the old one stays, inactive, so every past decision remains explainable by the version
stored on its MatchResult), switches the active flag in the same transaction and audits the
before/after values with the written reason. New matches, approvals and payment runs use the new
version from the next request; nothing already decided is re-decided.

Statutory values (MSMED Act 45 / 15 days) are shown but not editable here: they are law, not policy.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.enums import Role
from app.models import Policy, User


@dataclass(frozen=True)
class Field:
    path: str  # dotted path into policy data; doa bands use doa.bands.<index>.max_inr
    section: str
    label: str
    unit: str  # "%", "INR", "hours", "days", "ratio"
    lo: float
    hi: float
    integer: bool = False
    help: str = ""


FIELDS: tuple[Field, ...] = (
    Field("tolerances.PP.flag_pct", "Tolerances", "PP price variance: flag above", "%", 0, 20,
          help="SAP tolerance key PP. Flag when the unit price is above the PO price by more than this percentage..."),
    Field("tolerances.PP.flag_abs_inr", "Tolerances", "PP price variance: or above (absolute)", "INR", 0, 1_000_000,
          help="...or by more than this amount on the line, whichever is hit first."),
    Field("tolerances.PP.block_pct", "Tolerances", "PP price variance: block above", "%", 0, 50,
          help="Above this percentage the invoice is blocked, not flagged."),
    Field("tolerances.DQ.default_pct", "Tolerances", "DQ quantity: allowed over-billing", "%", 0, 10,
          help="SAP tolerance key DQ. Invoiced quantity above the received quantity within this is accepted."),
    Field("tolerances.DQ.bulk_mt_pct", "Tolerances", "DQ quantity: bulk materials in MT", "%", 0, 10,
          help="Weighbridge differences on bulk materials."),
    Field("tolerances.DQ.block_pct", "Tolerances", "DQ quantity: block above", "%", 0, 50,
          help="Excess above this percentage of the received quantity blocks."),
    Field("tolerances.BD.auto_accept_inr", "Tolerances", "BD small differences auto-accepted up to", "INR", 0, 1000,
          help="SAP tolerance key BD."),
    Field("doa.touchless_max_inr", "Approvals", "Touchless (policy P-01) up to", "INR", 0, 10_000_000, True,
          "Clean matches up to this value (incl. GST) are approved by policy without a person. 0 turns touchless off."),
    Field("doa.bands.0.max_inr", "Approvals", "L1 Finance Manager alone up to", "INR", 1, 1_000_000_000, True),
    Field("doa.bands.1.max_inr", "Approvals", "L1 then L2 Plant Head up to", "INR", 1, 10_000_000_000, True,
          "Above this, L1, L2 and L3 CFO."),
    Field("mfa_threshold_inr", "Approvals", "MFA step-up above", "INR", 0, 10_000_000_000, True,
          "Approvers must enter a TOTP code to approve invoices above this value."),
    Field("sla_hours", "Approvals", "Approval SLA per step", "hours", 1, 720, True,
          "After this, the step escalates to the next level."),
    Field("confidence_threshold", "Extraction", "Human review below confidence", "ratio", 0.5, 0.99,
          help="Fields read with lower confidence go to the clerk for review."),
    Field("bank_change_cooling_hours", "Payments", "Bank change cooling period", "hours", 24, 720, True,
          "Minimum wait between the call-back and approval of a bank detail change."),
    Field("msme.rbi_bank_rate_pct", "Payments", "RBI bank rate (for MSMED interest)", "%", 0, 20,
          help="Late-payment interest is three times this rate, monthly rests. Verify the current rate."),
    Field("payments.cost_of_funds_pct", "Payments", "Cost of funds", "%", 0, 40,
          help="Early-payment discounts are taken only when their yearly return beats this."),
    Field("payments.run_interval_days", "Payments", "Days between payment runs", "days", 1, 31, True),
    Field("payments.msme_buffer_days", "Payments", "MSME safety buffer", "days", 0, 30, True,
          "MSME invoices due before the next run plus this buffer are paid in this run."),
    Field("corporate_tax_rate_pct", "Payments", "Tax rate for 'deduction at risk'", "%", 0, 50,
          help="Display only. Confirm with the tax team."),
    Field("tds.contractor.rate_other_pct", "TDS (verify with tax team)", "Contractor rate (companies, firms)", "%", 0, 30),
    Field("tds.contractor.rate_individual_pct", "TDS (verify with tax team)", "Contractor rate (individuals, HUF)", "%", 0, 30),
    Field("tds.contractor.single_threshold_inr", "TDS (verify with tax team)", "Contractor single-bill threshold", "INR", 0, 10_000_000, True),
    Field("tds.contractor.annual_threshold_inr", "TDS (verify with tax team)", "Contractor yearly threshold", "INR", 0, 100_000_000, True),
    Field("tds.technical.rate_pct", "TDS (verify with tax team)", "Technical services rate", "%", 0, 30),
    Field("tds.professional.rate_pct", "TDS (verify with tax team)", "Professional fees rate", "%", 0, 30),
    Field("tds.goods.rate_pct", "TDS (verify with tax team)", "Purchase of goods rate", "%", 0, 30),
    Field("tds.goods.annual_threshold_inr", "TDS (verify with tax team)", "Purchase of goods yearly threshold", "INR", 0, 1_000_000_000, True),
)
BY_PATH = {f.path: f for f in FIELDS}
STATUTORY = (("msme.max_term_days", "MSME payment term cap", "days"),
             ("msme.no_agreement_days", "MSME term without a written agreement", "days"))


class PolicyError(ValueError):
    pass


def _get(data: dict, path: str):
    node = data
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _set(data: dict, path: str, value) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def active(db: Session) -> Policy:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True)))


def values(data: dict) -> dict[str, float | int | None]:
    out = {}
    for f in FIELDS:
        try:
            out[f.path] = _get(data, f.path)
        except (KeyError, IndexError, TypeError):
            out[f.path] = None
    return out


def _check(data: dict) -> None:
    """Rules that span fields, so a policy can never contradict itself."""
    pp, dq = data["tolerances"]["PP"], data["tolerances"]["DQ"]
    if pp["block_pct"] < pp["flag_pct"]:
        raise PolicyError("PP: the block level must be at or above the flag level.")
    if dq["block_pct"] < max(dq["default_pct"], dq["bulk_mt_pct"]):
        raise PolicyError("DQ: the block level must be at or above the allowed over-billing.")
    bands = data["doa"]["bands"]
    if not bands[0]["max_inr"] < bands[1]["max_inr"]:
        raise PolicyError("Approvals: the L1+L2 limit must be above the L1-only limit.")
    if data["doa"]["touchless_max_inr"] > bands[0]["max_inr"]:
        raise PolicyError("Approvals: the touchless limit cannot be above the L1-only limit.")


def change(db: Session, user: User, changes: dict[str, float], reason: str) -> Policy:
    """Validate `changes` (path -> new value) and activate them as a new policy version."""
    if user.role != Role.ADMIN:
        raise PolicyError("Only an administrator can change the policy.")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise PolicyError("Write a reason of at least 10 characters (it goes into the audit trail).")
    current = active(db)
    data = copy.deepcopy(current.data)
    diff = {}
    for path, raw in changes.items():
        f = BY_PATH.get(path)
        if f is None:
            raise PolicyError(f"'{path}' is not an editable policy value.")
        try:
            value = float(raw)
        except (TypeError, ValueError) as e:
            raise PolicyError(f"{f.label}: not a number.") from e
        if not f.lo <= value <= f.hi:
            raise PolicyError(f"{f.label}: must be between {f.lo:g} and {f.hi:g} {f.unit}.")
        if f.integer:
            if value != int(value):
                raise PolicyError(f"{f.label}: must be a whole number.")
            value = int(value)
        old = _get(data, path)
        if old is None or float(old) != float(value):
            diff[path] = {"from": old, "to": value}
            _set(data, path, value)
    if not diff:
        raise PolicyError("Nothing changed.")
    _check(data)
    version = (db.scalar(select(func.max(Policy.version))) or 0) + 1
    current.is_active = False
    db.flush()
    new = Policy(version=version, name=reason[:100], data=data, is_active=True, created_by_user_id=user.id)
    db.add(new)
    db.flush()
    audit.queue(db, "policy.changed", "policy", version,
                before={"version": current.version, **{p: d["from"] for p, d in diff.items()}},
                after={"version": version, "reason": reason, **{p: d["to"] for p, d in diff.items()}})
    db.commit()
    return new


def history(db: Session) -> list[tuple[Policy, dict]]:
    """Every version, newest first, with what changed from the version before it."""
    rows = list(db.scalars(select(Policy).order_by(Policy.version)))
    out = []
    prev = None
    for p in rows:
        if prev is None:
            changed = {}
        else:
            a, b = values(prev.data), values(p.data)
            changed = {k: {"from": a[k], "to": b[k]} for k in b if a.get(k) != b[k]}
        out.append((p, changed))
        prev = p
    return list(reversed(out))
