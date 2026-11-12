"""Column helpers shared across models."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import mapped_column

from app.core import clock

Money = Numeric(16, 2, asdecimal=True)
Qty = Numeric(16, 3, asdecimal=True)


def utcnow() -> datetime:
    """Default for record timestamps: the business clock (UTC), so received / matched / posted
    times line up with SLA timers and due dates when the demo clock is advanced."""
    return clock.now().astimezone(UTC)


def created_at_col():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes even for timezone=True columns; treat them as UTC."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
