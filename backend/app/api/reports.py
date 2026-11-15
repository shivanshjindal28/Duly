"""Controls report endpoints (auditor, admin): JSON for the screen, PDF for download."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.enums import Role
from app.core.security import require_roles
from app.reports import controls, pdf

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_roles(Role.AUDITOR, Role.ADMIN))])


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    to = date_to or clock.today()
    frm = date_from or to - timedelta(days=120)
    if frm > to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The start date is after the end date.")
    return frm, to


@router.get("/controls")
def controls_json(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                  db: Session = Depends(get_db)) -> dict:
    frm, to = _period(date_from, date_to)
    report = controls.build(db, frm, to)
    audit.queue(db, "report.controls_generated", "report", None,
                after={"from": frm, "to": to, "format": "screen", "opinion": report.opinion})
    db.commit()
    return asdict(report)


@router.get("/controls.pdf")
@limiter.limit("10/minute")
def controls_pdf(request: Request, date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                 db: Session = Depends(get_db)) -> Response:
    frm, to = _period(date_from, date_to)
    report = controls.build(db, frm, to)
    data = pdf.render(report)
    audit.queue(db, "report.controls_generated", "report", None,
                after={"from": frm, "to": to, "format": "pdf", "opinion": report.opinion, "bytes": len(data)})
    db.commit()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="duly-controls-{frm}-to-{to}.pdf"'})
