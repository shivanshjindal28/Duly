"""Column helpers shared across models."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import mapped_column

Money = Numeric(16, 2, asdecimal=True)
Qty = Numeric(16, 3, asdecimal=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


def created_at_col():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
