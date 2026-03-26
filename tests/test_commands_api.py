"""Tests for dashboard commands API (Slack trade command audit log)."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from src.data.models import Base, SlackCommandLog


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed some commands
    session.add(SlackCommandLog(
        raw_message="BUY AAPL",
        ticker="AAPL",
        action="BUY",
        status="executed",
        command_kind="trade",
        execution_mode="direct",
        response_message="*BUY AAPL* — filled",
        user_id="U123",
        channel_id="C456",
        cycle_id="slack-2026-03-23T12:00:00",
    ))
    session.add(SlackCommandLog(
        raw_message="SELL TSLA",
        ticker="TSLA",
        action="SELL",
        status="rejected",
        command_kind="trade",
        execution_mode="strategy",
        rejection_reason="Risk VETO: max_single_stock",
        user_id="U123",
        channel_id="C456",
    ))
    session.add(SlackCommandLog(
        raw_message="REVIEW MSFT",
        ticker="MSFT",
        action="REVIEW",
        status="review_only",
        command_kind="review",
        execution_mode="strategy",
        user_id="U789",
        channel_id="C456",
    ))
    session.add(SlackCommandLog(
        raw_message="cancel stop sell NVDA, Microsoft",
        ticker="NVDA_US_EQ",
        action="CANCEL",
        status="partial",
        command_kind="cancel",
        execution_mode="cancel_only",
        target_order_class="stop_sell",
        target_tickers_json='["NVDA_US_EQ","MSFT_US_EQ"]',
        result_json='{"cancelled":["1"],"failures":[{"order_id":"2"}]}',
        user_id="U789",
        channel_id="C456",
    ))
    session.commit()

    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_deps(db_session):
    with patch(
        "dashboard.backend.app.routers.commands.get_session",
        return_value=db_session,
    ), patch(
        "dashboard.backend.app.routers.commands.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        yield


class TestCommandsRouter:

    def test_get_all_commands(self, db_session):
        from dashboard.backend.app.routers.commands import get_commands
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_commands(limit=50, offset=0, ticker=None, action=None, status=None, start_date=None, end_date=None)
        )
        assert len(result) == 4
        actions = {r["action"] for r in result}
        assert actions == {"BUY", "SELL", "REVIEW", "CANCEL"}
        assert any(r["response_message"] == "*BUY AAPL* — filled" for r in result)
        cancel_row = next(r for r in result if r["action"] == "CANCEL")
        assert cancel_row["execution_mode"] == "cancel_only"
        assert cancel_row["target_order_class"] == "stop_sell"

    def test_filter_by_action(self, db_session):
        from dashboard.backend.app.routers.commands import get_commands
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_commands(limit=50, offset=0, ticker=None, action="BUY", status=None, start_date=None, end_date=None)
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_filter_by_status(self, db_session):
        from dashboard.backend.app.routers.commands import get_commands
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            get_commands(limit=50, offset=0, ticker=None, action=None, status="rejected", start_date=None, end_date=None)
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"
        assert "Risk VETO" in result[0]["rejection_reason"]

    def test_stats(self, db_session):
        from dashboard.backend.app.routers.commands import get_command_stats
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(get_command_stats())
        assert result["total"] == 4
        assert result["by_status"]["executed"] == 1
        assert result["by_status"]["rejected"] == 1
        assert result["by_status"]["partial"] == 1
        assert result["by_action"]["BUY"] == 1
        assert result["by_action"]["SELL"] == 1
        assert result["by_action"]["CANCEL"] == 1
