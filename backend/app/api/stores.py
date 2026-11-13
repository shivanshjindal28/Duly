"""Stores / receiving: open POs, goods receipts and service entry sheets (simulates the ERP).

Stores never sees invoices. After a posting it is only told how many waiting invoices Duly
re-checked and how many were released, not which ones.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.models import GoodsReceipt, PurchaseOrder, ServiceEntrySheet, Supplier, User
from app.engine import units
from app.workflow.matching import item_packs
from app.workflow.receipts import (ReceiptError, Rematch, accepted_value, post_goods_receipt, post_service_entry,
                                   received_qty)

router = APIRouter(prefix="/stores", tags=["stores"], dependencies=[Depends(require_roles(Role.STORES))])


class POLineOut(BaseModel):
    id: int
    line_no: int
    item_code: str
    description: str
    uom: str
    ordered: Decimal
    unit_price: Decimal
    received: Decimal  # goods: quantity; services: accepted value
    open: Decimal
    units: list[str] = []  # units stores may receive in (converted to the PO unit)
    packs: list[str] = []  # e.g. ["1 BOX = 10 NOS"]


class ReceiptOut(BaseModel):
    number: str
    kind: str  # GR | SES
    posted_at: datetime


class OpenPOOut(BaseModel):
    po_number: str
    supplier_name: str
    po_date: date
    is_service: bool
    ers: bool
    lines: list[POLineOut]
    receipts: list[ReceiptOut]


class GRLineIn(BaseModel):
    po_line_id: int
    qty: Decimal = Field(ge=0, max_digits=16, decimal_places=3)
    uom: str | None = Field(None, max_length=10)  # default: the PO unit


class GRIn(BaseModel):
    po_number: str = Field(max_length=20)
    lines: list[GRLineIn] = Field(min_length=1, max_length=50)


class SESIn(BaseModel):
    po_number: str = Field(max_length=20)
    po_line_id: int
    value: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    description: str = Field("", max_length=200)


class PostingOut(BaseModel):
    number: str
    kind: str
    rechecked: int
    released: int
    message: str
    ers_settled: bool = False


def _posting(number: str, kind: str, results: list[Rematch], ers_settled: bool = False) -> PostingOut:
    released = sum(r.released for r in results)
    label = "GR" if kind == "GR" else "service entry"
    if not results:
        msg = f"{label} {number} posted. No invoices were waiting on this PO."
    else:
        msg = (f"{label} {number} posted. Duly re-checked {len(results)} waiting invoice"
               f"{'s' if len(results) > 1 else ''}; {released} released from block.")
    if ers_settled:
        msg += " ERS: Duly settled this receipt at the PO price; the supplier does not send an invoice."
    return PostingOut(number=number, kind=kind, rechecked=len(results), released=released, message=msg,
                      ers_settled=ers_settled)


@router.get("/open-pos", response_model=list[OpenPOOut])
def open_pos(db: Session = Depends(get_db)) -> list[OpenPOOut]:
    names = {s.id: s.name for s in db.scalars(select(Supplier))}
    out = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "open").order_by(PurchaseOrder.po_number)):
        lines = []
        for pl in po.lines:
            if po.is_service:
                ordered, received = pl.qty * pl.unit_price, accepted_value(db, pl.id)
            else:
                ordered, received = pl.qty, received_qty(db, pl.id)
            packs = item_packs(db, pl.item_code)
            lines.append(POLineOut(id=pl.id, line_no=pl.line_no, item_code=pl.item_code, description=pl.description,
                                   uom=pl.uom, ordered=ordered, unit_price=pl.unit_price, received=received,
                                   open=ordered - received,
                                   units=[] if po.is_service else units.convertible_units(pl.uom, packs),
                                   packs=[f"1 {u} = {q.normalize():f} {b}" for u, q, b in packs]))
        receipts = [ReceiptOut(number=g.gr_number, kind="GR", posted_at=g.posted_at)
                    for g in db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id))]
        receipts += [ReceiptOut(number=s.ses_number, kind="SES", posted_at=s.posted_at)
                     for s in db.scalars(select(ServiceEntrySheet).where(ServiceEntrySheet.po_id == po.id))]
        out.append(OpenPOOut(po_number=po.po_number, supplier_name=names[po.supplier_id], po_date=po.po_date,
                             is_service=po.is_service, ers=po.ers, lines=lines,
                             receipts=sorted(receipts, key=lambda r: r.posted_at, reverse=True)))
    return out


@router.post("/goods-receipts", response_model=PostingOut, status_code=status.HTTP_201_CREATED)
def goods_receipt(body: GRIn, user: User = Depends(require_roles(Role.STORES)), db: Session = Depends(get_db)) -> PostingOut:
    try:
        gr, results, settled = post_goods_receipt(db, user, body.po_number,
                                                  [(ln.po_line_id, ln.qty, ln.uom) for ln in body.lines])
    except ReceiptError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _posting(gr.gr_number, "GR", results, settled is not None)


@router.post("/service-entries", response_model=PostingOut, status_code=status.HTTP_201_CREATED)
def service_entry(body: SESIn, user: User = Depends(require_roles(Role.STORES)), db: Session = Depends(get_db)) -> PostingOut:
    try:
        ses, results, settled = post_service_entry(db, user, body.po_number, body.po_line_id, body.value, body.description)
    except ReceiptError as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _posting(ses.ses_number, "SES", results, settled is not None)
