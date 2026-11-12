"""Business clock in IST. All date rules (due dates, invoice-date checks) use this.

A fixed UTC+05:30 offset is used instead of zoneinfo so no tzdata package is needed on
Windows (India has no daylight saving).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return now().astimezone(IST).date()
