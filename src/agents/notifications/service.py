"""Notification orchestration service with routing, retries, dedup, and audit logging."""

import hashlib
import json
import time
import uuid
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import and_

from src.agents.notifications.formatters import render_event
from src.agents.notifications.providers import EmailProvider, NotificationProvider, SlackProvider
from src.agents.notifications.types import NotificationEvent, NotificationStatus
from src.data.database import get_session
from src.data.models import NotificationLog
from src.utils.config import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("notifications")


class NotificationService:
    """Main notification service for outbound alerts."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: Callable[[], Any] = get_session,
        providers: dict[str, NotificationProvider] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.enabled = self.settings.notification_enabled
        self.max_retries = self.settings.notification_max_retries
        self.timeout_seconds = self.settings.notification_timeout_seconds
        self.dedup_window_seconds = self.settings.notification_dedup_window_seconds
        self.default_channels = self.settings.notification_channels
        self.routes = self.settings.notification_routes

        if providers is None:
            providers = self._build_default_providers()
        self.providers = providers

    def emit_trade_instruction_approved(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "orchestrator",
    ) -> None:
        self._emit(
            event_type="trade_instruction_approved",
            severity="info",
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[cycle_id, payload.get("ticker"), payload.get("action"), "instruction"],
        )

    def emit_trade_execution_result(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "orchestrator",
    ) -> None:
        severity = "warning" if payload.get("execution_status") in {"failed", "skipped"} else "info"
        self._emit(
            event_type="trade_execution_result",
            severity=severity,
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[
                cycle_id,
                payload.get("ticker"),
                payload.get("action"),
                payload.get("execution_status"),
                payload.get("quantity"),
            ],
        )

    def emit_cycle_run_summary(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "orchestrator",
    ) -> None:
        status = str(payload.get("status", "completed"))
        severity = "critical" if status in {"error", "halted_drawdown", "halted_liquidation"} else "info"
        self._emit(
            event_type="cycle_run_summary",
            severity=severity,
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[cycle_id, status, payload.get("num_trades"), payload.get("num_rejected")],
        )

    def emit_state_transition(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "state_machine",
    ) -> None:
        severity = "critical" if payload.get("new_state") == "HALTED" else "warning"
        self._emit(
            event_type="state_transition",
            severity=severity,
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[payload.get("old_state"), payload.get("new_state"), payload.get("reason")],
        )

    def emit_order_adjustment(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "stop_loss_manager",
    ) -> None:
        self._emit(
            event_type="order_adjustment",
            severity="info",
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[
                cycle_id,
                payload.get("ticker"),
                payload.get("adjustment_type"),
                payload.get("new_stop_price"),
            ],
        )

    def emit_critical_cycle_failure(
        self,
        *,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str = "orchestrator",
    ) -> None:
        self._emit(
            event_type="critical_cycle_failure",
            severity="critical",
            cycle_id=cycle_id,
            payload=payload,
            source=source,
            dedup_parts=[cycle_id, payload.get("stage"), payload.get("error_type"), payload.get("error_message")],
        )

    def _emit(
        self,
        *,
        event_type: str,
        severity: str,
        cycle_id: str | None,
        payload: dict[str, Any],
        source: str,
        dedup_parts: list[Any],
    ) -> None:
        try:
            if not self.enabled:
                return

            dry_run = bool(payload.get("dry_run", False))
            if dry_run and not self.settings.notification_include_dry_run_alerts:
                return

            now = NotificationEvent.now_utc()
            payload_with_meta = dict(payload)
            payload_with_meta.setdefault("cycle_id", cycle_id)
            payload_with_meta.setdefault("occurred_at", now.isoformat())

            dedup_key = self._hash_key(event_type, dedup_parts)
            event = NotificationEvent(
                event_id=uuid.uuid4().hex,
                event_type=event_type,
                occurred_at=now,
                cycle_id=cycle_id,
                severity=severity,  # type: ignore[arg-type]
                source=source,
                dedup_key=dedup_key,
                payload=payload_with_meta,
            )

            channels = self.routes.get(event.event_type, self.default_channels)
            for channel in channels:
                self._send_to_channel(event, channel)
        except Exception as exc:
            logger.error(
                "Notification emit failed (fail-open: pipeline continues): event=%s cycle_id=%s error=%s",
                event_type,
                cycle_id,
                exc,
                exc_info=True,
            )

    def _send_to_channel(self, event: NotificationEvent, channel: str) -> None:
        provider = self.providers.get(channel)
        payload_hash = self._payload_hash(event.payload)

        if provider is None or not provider.is_configured:
            self._record_attempt(
                event=event,
                channel=channel,
                status="skipped",
                attempt_number=0,
                payload_hash=payload_hash,
                error_message="provider_not_configured",
                latency_ms=None,
                recipient=(provider.recipient if provider else None),
            )
            return

        if self._is_duplicate(channel, event.dedup_key):
            self._record_attempt(
                event=event,
                channel=channel,
                status="deduped",
                attempt_number=0,
                payload_hash=payload_hash,
                error_message=None,
                latency_ms=None,
                recipient=provider.recipient,
            )
            return

        messages = render_event(event, channel)
        for message in messages:
            for attempt in range(1, self.max_retries + 2):
                start = time.perf_counter()
                try:
                    provider.send(message, timeout_seconds=self.timeout_seconds)
                    latency_ms = (time.perf_counter() - start) * 1000
                    self._record_attempt(
                        event=event,
                        channel=channel,
                        status="sent",
                        attempt_number=attempt,
                        payload_hash=payload_hash,
                        error_message=None,
                        latency_ms=latency_ms,
                        recipient=provider.recipient,
                    )
                    
                    # Log notification_sent event to dashboard (only on successful send)
                    if DASHBOARD_AVAILABLE and log_event:
                        try:
                            log_event(
                                event_type="notification_sent",
                                source="notifications",
                                message=f"Sent {event.event_type} to {channel}",
                                metadata={
                                    "event_type": event.event_type,
                                    "channel": channel,
                                    "cycle_id": event.cycle_id,
                                    "severity": event.severity,
                                    "ticker": event.payload.get("ticker"),
                                    "action": event.payload.get("action"),
                                    "latency_ms": latency_ms,
                                },
                            )
                        except Exception:
                            pass  # Fail-open
                    
                    break
                except Exception as exc:  # pragma: no cover - exercised via tests with mocks
                    latency_ms = (time.perf_counter() - start) * 1000
                    self._record_attempt(
                        event=event,
                        channel=channel,
                        status="failed",
                        attempt_number=attempt,
                        payload_hash=payload_hash,
                        error_message=str(exc),
                        latency_ms=latency_ms,
                        recipient=provider.recipient,
                    )
                    if attempt <= self.max_retries:
                        delay = 0.5 if attempt == 1 else 1.5
                        time.sleep(delay)
                    else:
                        logger.warning(
                            "Notification failed after retries (fail-open: pipeline continues)",
                            extra={
                                "event_type": event.event_type,
                                "channel": channel,
                                "error": str(exc),
                            },
                        )

    def _is_duplicate(self, channel: str, dedup_key: str) -> bool:
        session = self.session_factory()
        try:
            cutoff = NotificationEvent.now_utc() - timedelta(seconds=self.dedup_window_seconds)
            found = (
                session.query(NotificationLog.id)
                .filter(
                    and_(
                        NotificationLog.channel == channel,
                        NotificationLog.dedup_key == dedup_key,
                        NotificationLog.timestamp >= cutoff,
                        NotificationLog.status.in_(["sent", "deduped"]),
                    ),
                )
                .first()
            )
            return found is not None
        except Exception as exc:
            logger.debug(f"Dedup lookup failed, proceeding without dedup: {exc}")
            return False
        finally:
            session.close()

    def _record_attempt(
        self,
        *,
        event: NotificationEvent,
        channel: str,
        status: NotificationStatus,
        attempt_number: int,
        payload_hash: str,
        error_message: str | None,
        latency_ms: float | None,
        recipient: str | None,
    ) -> None:
        session = self.session_factory()
        try:
            log_entry = NotificationLog(
                timestamp=NotificationEvent.now_utc(),
                event_id=event.event_id,
                cycle_id=event.cycle_id,
                event_type=event.event_type,
                severity=event.severity,
                channel=channel,
                recipient=recipient,
                status=status,
                attempt_number=attempt_number,
                dedup_key=event.dedup_key,
                payload_hash=payload_hash,
                error_message=error_message,
                latency_ms=latency_ms,
            )
            session.add(log_entry)
            session.commit()
        except Exception as exc:
            logger.debug(f"Failed to persist notification log entry: {exc}")
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def _hash_key(event_type: str, parts: list[Any]) -> str:
        joined = "|".join(str(p) for p in [event_type, *parts])
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        text = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _build_default_providers(self) -> dict[str, NotificationProvider]:
        return {
            "slack": SlackProvider(self.settings.slack_webhook_url),
            "email": EmailProvider(
                host=self.settings.smtp_host,
                port=self.settings.smtp_port,
                username=self.settings.smtp_user,
                password=self.settings.smtp_pass,
                sender=self.settings.alert_email_from,
                recipient=self.settings.alert_email_to,
                use_tls=self.settings.smtp_use_tls,
            ),
        }
