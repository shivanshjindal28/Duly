"""Impact page data: measured on Duly's data + projection assumptions (spec section 11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.reports.impact import impact

router = APIRouter(tags=["impact"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


@router.get("/impact")
def get_impact(db: Session = Depends(get_db)) -> dict:
    return impact(db)
