"""Organisation (Plant X), suppliers and users."""
from __future__ import annotations

from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import created_at_col
from app.core.enums import EnterpriseType, MsmeCategory, Role


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15), unique=True)
    pan: Mapped[str] = mapped_column(String(10))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str] = mapped_column(String(400))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # SAP-style vendor number
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60))
    gstin: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    pan: Mapped[str] = mapped_column(String(10))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str] = mapped_column(String(400))
    # Non-resident (import) suppliers: country != "IN", `gstin` holds their foreign tax ID, no PAN.
    country: Mapped[str] = mapped_column(String(2), default="IN")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    msme_category: Mapped[MsmeCategory] = mapped_column(String(10), default=MsmeCategory.NONE)
    udyam_no: Mapped[str | None] = mapped_column(String(25))
    enterprise_type: Mapped[EnterpriseType] = mapped_column(String(15))
    e_invoice_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=60)
    written_agreement: Mapped[bool] = mapped_column(Boolean, default=True)
    tds_section: Mapped[str] = mapped_column(String(15), default="none")  # contractor|technical|professional|goods|none
    # Early-payment discount offered by the supplier (e.g. 1% if paid within 10 days of the invoice date).
    early_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    early_discount_days: Mapped[int] = mapped_column(Integer, default=0)
    # Bank details: account number encrypted at rest (AES-GCM); last 4 kept for masking.
    bank_account_enc: Mapped[str] = mapped_column(String(200))
    bank_account_last4: Mapped[str] = mapped_column(String(4))
    bank_ifsc: Mapped[str] = mapped_column(String(11))
    bank_name: Mapped[str] = mapped_column(String(100))
    contact_email: Mapped[str] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_col()

    users: Mapped[list[User]] = relationship(back_populates="supplier")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[Role] = mapped_column(String(12), index=True)
    approver_level: Mapped[int | None] = mapped_column(Integer)  # 1, 2, 3 for approvers
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(200))  # TOTP secret, AES-GCM
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_language: Mapped[str] = mapped_column(String(5), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke all sessions
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()

    supplier: Mapped[Supplier | None] = relationship(back_populates="users")
