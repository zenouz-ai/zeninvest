from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.notifications.providers.base import NotificationProvider
from src.agents.notifications.service import NotificationService
from src.agents.notifications.types import NotificationMessage
from src.data.models import Base, NotificationLog
from src.utils.config import Settings


class FakeProvider(NotificationProvider):
    def __init__(self, channel: str, *, fail_times: int = 0, configured: bool = True) -> None:
        self.channel = channel
        self.fail_times = fail_times
        self.configured = configured
        self.sent_messages: list[NotificationMessage] = []
        self.recipient = f"{channel}://recipient"

    @property
    def is_configured(self) -> bool:
        return self.configured

    def send(self, message: NotificationMessage, timeout_seconds: float) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("transient")
        self.sent_messages.append(message)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def factory() -> Any:
        return Session()

    return factory


def _settings(enabled: bool = True) -> Settings:
    return Settings(
        {
            "notifications": {
                "enabled": enabled,
                "channels": ["slack", "email"],
                "routes": {
                    "trade_execution_result": ["slack"],
                    "cycle_run_summary": ["slack", "email"],
                },
                "max_retries": 2,
                "timeout_seconds": 5,
                "dedup_window_seconds": 300,
                "include_dry_run_alerts": True,
                "command_gateway": {"enabled": False},
            },
        },
    )


def test_notifications_disabled_no_send(session_factory) -> None:
    provider = FakeProvider("slack")
    service = NotificationService(
        settings=_settings(enabled=False),
        session_factory=session_factory,
        providers={"slack": provider},
    )

    service.emit_trade_execution_result(
        cycle_id="c1",
        payload={
            "cycle_id": "c1",
            "ticker": "AAPL_US_EQ",
            "action": "BUY",
            "execution_status": "filled",
            "quantity": 1,
            "value_gbp": 100,
        },
    )

    assert provider.sent_messages == []


def test_channel_unconfigured_logs_skipped(session_factory) -> None:
    provider = FakeProvider("slack", configured=False)
    service = NotificationService(
        settings=_settings(enabled=True),
        session_factory=session_factory,
        providers={"slack": provider},
    )

    service.emit_trade_execution_result(
        cycle_id="c1",
        payload={
            "cycle_id": "c1",
            "ticker": "AAPL_US_EQ",
            "action": "BUY",
            "execution_status": "filled",
        },
    )

    session = session_factory()
    try:
        logs = session.query(NotificationLog).all()
        assert len(logs) == 1
        assert logs[0].status == "skipped"
    finally:
        session.close()


def test_retry_then_success_logs_failed_and_sent(session_factory) -> None:
    provider = FakeProvider("slack", fail_times=1)
    service = NotificationService(
        settings=_settings(enabled=True),
        session_factory=session_factory,
        providers={"slack": provider},
    )

    service.emit_trade_execution_result(
        cycle_id="c2",
        payload={
            "cycle_id": "c2",
            "ticker": "MSFT_US_EQ",
            "action": "BUY",
            "execution_status": "filled",
        },
    )

    session = session_factory()
    try:
        logs = session.query(NotificationLog).order_by(NotificationLog.id).all()
        statuses = [l.status for l in logs]
        assert statuses == ["failed", "sent"]
        assert len(provider.sent_messages) == 1
    finally:
        session.close()


def test_permanent_failure_logs_all_attempts(session_factory) -> None:
    provider = FakeProvider("slack", fail_times=10)
    service = NotificationService(
        settings=_settings(enabled=True),
        session_factory=session_factory,
        providers={"slack": provider},
    )

    service.emit_trade_execution_result(
        cycle_id="c3",
        payload={
            "cycle_id": "c3",
            "ticker": "NVDA_US_EQ",
            "action": "BUY",
            "execution_status": "failed",
        },
    )

    session = session_factory()
    try:
        logs = session.query(NotificationLog).order_by(NotificationLog.id).all()
        assert len(logs) == 3  # 1 initial + 2 retries
        assert all(log.status == "failed" for log in logs)
    finally:
        session.close()


def test_dedup_suppresses_second_send(session_factory) -> None:
    provider = FakeProvider("slack")
    service = NotificationService(
        settings=_settings(enabled=True),
        session_factory=session_factory,
        providers={"slack": provider},
    )

    payload = {
        "cycle_id": "c4",
        "ticker": "AAPL_US_EQ",
        "action": "BUY",
        "execution_status": "filled",
        "quantity": 1,
    }

    service.emit_trade_execution_result(cycle_id="c4", payload=payload)
    service.emit_trade_execution_result(cycle_id="c4", payload=payload)

    session = session_factory()
    try:
        logs = session.query(NotificationLog).order_by(NotificationLog.id).all()
        assert len(provider.sent_messages) == 1
        assert logs[-1].status == "deduped"
    finally:
        session.close()


def test_dry_run_suppressed_by_setting(session_factory) -> None:
    s = _settings(enabled=True)
    s._config["notifications"]["include_dry_run_alerts"] = False
    provider = FakeProvider("slack")
    service = NotificationService(
        settings=s,
        session_factory=session_factory,
        providers={"slack": provider},
    )

    service.emit_cycle_run_summary(
        cycle_id="c5",
        payload={
            "cycle_id": "c5",
            "status": "completed",
            "dry_run": True,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "counts": {"decisions": 0, "trades": 0, "rejected": 0, "queued": 0, "filtered": 0},
            "decisions": [],
        },
    )

    assert provider.sent_messages == []
