"""Approvals, payments, bank-change requests, chat sessions, audit events and policies."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import Money, created_at_col, utcnow
from app.models.enums import BankChangeStatus, StepStatus


class ApprovalStep(Base):
    __tablename__ = "approval_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)  # 1 = Finance Manager, 2 = Plant Head, 3 = CFO
    status: Mapped[StepStatus] = mapped_column(String(10), default=StepStatus.PENDING)
    approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delegated_from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    by_policy: Mapped[str | None] = mapped_column(String(10))  # e.g. "P-01" for touchless
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    payment_run_id: Mapped[str | None] = mapped_column(String(20))
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    tds_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    net_amount: Mapped[Decimal] = mapped_column(Money)
    utr: Mapped[str] = mapped_column(String(22))  # simulated
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BankChangeRequest(Base):
    __tablename__ = "bank_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    new_account_enc: Mapped[str] = mapped_column(String(200))
    new_account_last4: Mapped[str] = mapped_column(String(4))
    new_ifsc: Mapped[str] = mapped_column(String(11))
    status: Mapped[BankChangeStatus] = mapped_column(String(10), default=BankChangeStatus.PROPOSED)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    proposed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # maker
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # checker
    callback_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    cooling_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    messages: Mapped[list] = mapped_column(JSON, default=list)  # redacted transcript
    started_at: Mapped[datetime] = created_at_col()


class AuditEvent(Base):
    """Append-only, hash-chained audit log. hash = SHA256(prev_hash + canonical_json(event))."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str | None] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(45))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Policy(Base):
    """Versioned policy data: tolerances, DoA matrix, thresholds. Finance edits data, not code."""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_col()
