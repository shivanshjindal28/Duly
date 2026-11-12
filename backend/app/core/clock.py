"""Business clock in IST, with a demo offset. All date rules (SLA timers, due dates,
invoice-date checks, cooling periods) read time from here, never from datetime.now().

DEMO_MODE lets admin "advance the clock" so SLA escalation and MSME countdowns can be
shown live. The offset is stored in app_settings and loaded at startup.

A fixed UTC+05:30 offset is used instead of zoneinfo so no tzdata package is needed on
Windows (India has no daylight saving).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
_KEY = "clock_offset_seconds"
_offset = timedelta(0)


def now() -> datetime:
    return datetime.now(UTC) + _offset


def today() -> date:
    return now().astimezone(IST).date()


def offset() -> timedelta:
    return _offset


def load_offset(db) -> None:
    """Read the persisted demo offset (called at startup)."""
    from app.models import AppSetting

    global _offset
    row = db.get(AppSetting, _KEY)
    _offset = timedelta(seconds=float(row.value)) if row else timedelta(0)


def set_offset(db, new_offset: timedelta) -> None:
    from app.models import AppSetting

    global _offset
    row = db.get(AppSetting, _KEY)
    if row is None:
        db.add(AppSetting(key=_KEY, value=str(new_offset.total_seconds())))
    else:
        row.value = str(new_offset.total_seconds())
    db.commit()
    _offset = new_offset
