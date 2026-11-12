"""Payment assistant endpoint. Suppliers: their own data. AP clerks: any supplier they pick
(e.g. while answering a supplier's phone call). The supplier id never comes from the model."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.chat.service import chat
from app.core.db import get_db
from app.core.enums import Role
from app.core.ratelimit import limiter
from app.core.security import SupplierScope, get_scope, require_roles
from app.models import Supplier

router = APIRouter(prefix="/chat", tags=["payment assistant"],
                   dependencies=[Depends(require_roles(Role.SUPPLIER, Role.CLERK))])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    lang: str = Field("en", pattern="^(en|hi)$")
    session_id: int | None = None
    supplier_id: int | None = None  # clerks only; ignored for suppliers


class ToolChip(BaseModel):
    name: str
    ref: str | None
    label: str


class ChatOut(BaseModel):
    session_id: int
    answer: str
    tools: list[ToolChip]
    mode: str
    refused: bool
    flagged: bool


@router.post("", response_model=ChatOut)
@limiter.limit("20/minute")
def ask(request: Request, body: ChatIn, scope: SupplierScope = Depends(get_scope), db: Session = Depends(get_db)) -> ChatOut:
    if scope.supplier_id is not None:
        supplier_id = scope.supplier_id  # suppliers: always their own, whatever the request says
    else:
        if body.supplier_id is None or db.get(Supplier, body.supplier_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose the supplier you are helping.")
        supplier_id = body.supplier_id
    r = chat(db, scope.user, supplier_id, body.message, body.lang, body.session_id)
    return ChatOut(session_id=r.session_id, answer=r.answer, tools=[ToolChip(**c) for c in r.tools], mode=r.mode,
                   refused=r.refused, flagged=r.flagged)
