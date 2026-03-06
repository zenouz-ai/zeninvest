"""Typed models for notification events and rendered messages."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict


NotificationSeverity = Literal["info", "warning", "critical"]
NotificationChannel = Literal["slack", "email"]
NotificationStatus = Literal["sent", "failed", "skipped", "deduped"]


class TradeInstructionPayload(TypedDict, total=False):
    """Payload shape for trade_instruction_approved events."""

    cycle_id: str
    dry_run: bool
    ticker: str
    action: str
    target_allocation_pct: float
    final_allocation_pct: float
    conviction: int | float
    moderation_consensus: str | None
    risk_verdict: str | None
    reasoning_summary: str
    occurred_at: str


class TradeExecutionPayload(TypedDict, total=False):
    """Payload shape for trade_execution_result events."""

    cycle_id: str
    dry_run: bool
    ticker: str
    action: str
    execution_status: str
    quantity: int | float | None
    price: float | None
    value_gbp: float | None
    stop_loss_pct: float | None
    stop_loss_status: str | None
    error_message: str | None
    reasoning_summary: str
    moderation_consensus: str | None
    risk_verdict: str | None
    occurred_at: str


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


class NotificationError(Exception):
    """Raised when a notification send fails; caught and logged by service (fail-open)."""
