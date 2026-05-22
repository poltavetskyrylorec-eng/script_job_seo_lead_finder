from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def now_in_timezone(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def utc_now() -> datetime:
    return datetime.now(UTC)


def lookback_threshold(tz_name: str, hours: int) -> datetime:
    return now_in_timezone(tz_name) - timedelta(hours=hours)


def is_within_last_hours(dt: datetime, tz_name: str, hours: int) -> bool:
    threshold = lookback_threshold(tz_name, hours)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(ZoneInfo(tz_name)) >= threshold
