"""Purchase orders, goods receipts and service entry sheets (the ERP side of the match)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import Money, Qty, created_at_col, utcnow


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    po_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=60)
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)
    # Evaluated receipt settlement (SAP ERS / MRRL): Duly settles from the GR / SES at PO price;
    # the supplier sends no invoice.
    ers: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_col()

    lines: Mapped[list[POLine]] = relationship(back_populates="po", order_by="POLine.line_no")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(Qty)
    uom: Mapped[str] = mapped_column(String(6))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Money)  # percent, e.g. 18.00

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class GoodsReceipt(Base):
    """Goods receipt (SAP MIGO, movement type 101)."""

    __tablename__ = "goods_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    gr_number: Mapped[str] = mapped_column(String(20), unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(3), default="101")
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list[GRLine]] = relationship(back_populates="gr")


class GRLine(Base):
    __tablename__ = "gr_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    gr_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id"), index=True)
    qty: Mapped[Decimal] = mapped_column(Qty)  # in the PO unit
    uom: Mapped[str] = mapped_column(String(6))  # the PO unit
    # What stores entered, if in another unit (e.g. 12 BOX for a PO in NOS); qty above is converted.
    entered_qty: Mapped[Decimal | None] = mapped_column(Qty)
    entered_uom: Mapped[str | None] = mapped_column(String(6))

    gr: Mapped[GoodsReceipt] = relationship(back_populates="lines")


class ItemUnit(Base):
    """Item master pack size: 1 `unit` of `item_code` = `qty` `base_unit` (e.g. 1 BOX of BRG-6205 = 10 NOS)."""

    __tablename__ = "item_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(40), index=True)
    unit: Mapped[str] = mapped_column(String(6))
    qty: Mapped[Decimal] = mapped_column(Qty)
    base_unit: Mapped[str] = mapped_column(String(6))


class ServiceEntrySheet(Base):
    """Service entry sheet (SAP ML81N): acceptance of services where there is no physical GR."""

    __tablename__ = "service_entry_sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ses_number: Mapped[str] = mapped_column(String(20), unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id"))
    description: Mapped[str] = mapped_column(String(200))
    value: Mapped[Decimal] = mapped_column(Money)
    posted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
