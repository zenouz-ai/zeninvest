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
        user_id="U123",
        channel_id="C456",
        cycle_id="slack-2026-03-23T12:00:00",
    ))
    session.add(SlackCommandLog(
        raw_message="SELL TSLA",
        ticker="TSLA",
        action="SELL",
        status="rejected",
        rejection_reason="Risk VETO: max_single_stock",
        user_id="U123",
        channel_id="C456",
    ))
    session.add(SlackCommandLog(
        raw_message="REVIEW MSFT",
        ticker="MSFT",
        action="REVIEW",
        status="review_only",
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
        assert len(result) == 3
        actions = {r["action"] for r in result}
        assert actions == {"BUY", "SELL", "REVIEW"}

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
        assert result["total"] == 3
        assert result["by_status"]["executed"] == 1
        assert result["by_status"]["rejected"] == 1
        assert result["by_action"]["BUY"] == 1
        assert result["by_action"]["SELL"] == 1
