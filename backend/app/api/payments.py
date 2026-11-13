"""Payment run (D5) and MSME guardian (D4). Staff only; release is a finance approver action."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import get_current_user, require_roles
from app.models import Invoice, Payment, Policy, Supplier, User
from app.payments import msme as m
from app.payments import run as pr

router = APIRouter(prefix="/payments", tags=["payments"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


class ReleaseIn(BaseModel):
    invoice_ids: list[int] = Field(min_length=1, max_length=200)


def _policy(db: Session) -> dict:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True))).data


@router.get("/run")
def proposal(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    pl = pr.plan(db)
    policy = _policy(db)
    return {"run_date": pl.run_date, "next_run": pl.next_run, "cost_of_funds_pct": pl.cost_of_funds_pct,
            "items": [asdict(i) for i in pl.items], "summary": pr.summary(pl),
            "assumptions": {"payments": policy.get("payments"), "tds": policy.get("tds"),
                            "rbi_bank_rate_pct": policy.get("msme", {}).get("rbi_bank_rate_pct")},
            "can_release": user.role == Role.APPROVER}


@router.post("/run/release")
def release(body: ReleaseIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        run_id, pays = pr.release(db, user, body.invoice_ids)
    except pr.PaymentError as e:
        db.rollback()
        code = status.HTTP_403_FORBIDDEN if user.role != Role.APPROVER else status.HTTP_409_CONFLICT
        raise HTTPException(code, str(e)) from e
    return {"run_id": run_id, "payments": [{"invoice_id": p.invoice_id, "utr": p.utr, "net": p.net_amount,
                                            "tds": p.tds_amount} for p in pays]}


@router.get("/history")
def history(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(Payment, Invoice, Supplier).join(Invoice, Invoice.id == Payment.invoice_id)
                      .join(Supplier, Supplier.id == Invoice.supplier_id).order_by(Payment.id.desc()).limit(200)).all()
    return [{"id": p.id, "run_id": p.payment_run_id, "invoice_id": i.id, "invoice_number": i.invoice_number,
             "supplier_name": s.name, "paid_at": p.paid_at, "gross": p.gross_amount, "discount": p.discount_amount,
             "tds": p.tds_amount, "tds_section": p.tds_section, "tds_rate_pct": p.tds_rate_pct, "net": p.net_amount,
             "utr": p.utr, "reason": p.reason, "currency": p.currency or "INR", "net_inr": p.net_inr or p.net_amount}
            for p, i, s in rows]


@router.get("/msme")
def msme_guardian(half: str = Query("current", pattern="^(current|previous)$"), db: Session = Depends(get_db)) -> dict:
    rows = pr.msme_rows(db)
    policy = _policy(db)
    on = clock.today()
    if half == "previous":
        on = m.half_year(on)[0] - timedelta(days=1)
    paid = [r for r in rows if r.paid_on]
    return {
        "rows": [asdict(r) for r in rows],
        "totals": {
            "open": sum(1 for r in rows if r.status == "open"),
            "due_7d": sum(1 for r in rows if r.status == "open" and r.days_left is not None and r.days_left <= 7),
            "overdue": sum(1 for r in rows if r.status == "overdue"),
            "on_time_pct": round(100 * sum(1 for r in paid if r.status == "on_time") / len(paid), 1) if paid else None,
            "interest": sum((r.interest for r in rows if r.status in ("overdue", "paid_late")), 0),
            "deduction_at_risk": sum((r.deduction_at_risk for r in rows), 0),
            "tax_effect": sum((r.tax_effect for r in rows), 0),
        },
        "assumptions": {"rbi_bank_rate_pct": policy.get("msme", {}).get("rbi_bank_rate_pct"),
                        "interest_rate_pct": 3 * float(policy.get("msme", {}).get("rbi_bank_rate_pct", 5.75)),
                        "corporate_tax_rate_pct": policy.get("corporate_tax_rate_pct")},
        "tax_rule": m.TAX_RULE,
        "form1": pr.form1_summary(db, on),
    }
