"""Datetime helpers.

SQLite often drops timezone info for SQLAlchemy `DateTime` columns, which can lead
to mixing offset-aware and offset-naive datetimes. These helpers normalize
datetimes to UTC-aware instances before arithmetic/comparisons.
"""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc_datetime(dt: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime.

    If `dt` is offset-naive (common with SQLite), we assume it is already in UTC.
    """

    if dt is None:
        return None

    # SQLite + SQLAlchemy may return naive datetimes even if we wrote aware ones.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    # Convert any other tz to UTC.
    return dt.astimezone(timezone.utc)

