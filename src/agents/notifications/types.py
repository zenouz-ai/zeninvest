"""Typed models for notification events and rendered messages."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


NotificationSeverity = Literal["info", "warning", "critical"]
NotificationChannel = Literal["slack", "email"]
NotificationStatus = Literal["sent", "failed", "skipped", "deduped"]


@dataclass(slots=True)
class NotificationEvent:
    """Canonical outbound event envelope."""

    event_id: str
    event_type: str
    occurred_at: datetime
    cycle_id: str | None
    severity: NotificationSeverity
    source: str
    dedup_key: str
    payload: dict[str, Any]

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)


@dataclass(slots=True)
class NotificationMessage:
    """Rendered message ready for a specific channel."""

    subject: str
    body: str
