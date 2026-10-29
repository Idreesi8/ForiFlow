"""Pakistan calendar dates for workflows; stored instants remain UTC."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Karachi")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    # SQLite removes timezone metadata from timestamps written in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def business_date(value: datetime | None = None) -> date:
    return as_utc(value if value is not None else utc_now()).astimezone(BUSINESS_TIMEZONE).date()
