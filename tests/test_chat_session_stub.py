"""Tests for conversational session persistence."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.conversation.session_manager import (
    ChatSessionNotFoundError,
    SessionManager,
)
from src.data.models import Base


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
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        yield


class TestSessionManager:
    def test_create_session_and_resume_by_channel_key(self):
        mgr = SessionManager()
        first_id = mgr.create_session(
            channel_type="slack",
            user_id="user1",
            channel_session_key="thread-1",
        )
        second_id = mgr.create_session(
            channel_type="slack",
            user_id="user1",
            channel_session_key="thread-1",
        )

        assert first_id == second_id

    def test_list_sessions_and_get_detail(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard", user_id="u1", title="Dashboard thread")
        mgr.add_turn(session_id, role="user", message_text="BUY AAPL", channel_type="dashboard")
        mgr.add_turn(session_id, role="assistant", message_text="Preview ready", channel_type="dashboard")

        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == session_id
        assert sessions[0]["title"] == "Dashboard thread"
        assert sessions[0]["last_message_role"] == "assistant"

        result = mgr.get_session(session_id)
        assert result is not None
        assert result["id"] == session_id
        assert result["channel_type"] == "dashboard"
        assert result["turns"][0]["turn_index"] == 0
        assert result["turns"][1]["turn_index"] == 1

    def test_create_action_and_research_log(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard", user_id="u1")
        turn_id = mgr.add_turn(session_id, role="user", message_text="Research AMD", channel_type="dashboard")
        action = mgr.create_action(
            session_id=session_id,
            turn_id=turn_id,
            action_type="strategy_trade",
            status="awaiting_confirmation",
            title="BUY AMD",
            ticker="AMD_US_EQ",
            payload_json={"ticker": "AMD_US_EQ"},
            preview_text="Preview",
            requires_confirmation=True,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        log = mgr.add_research_log(
            session_id=session_id,
            turn_id=turn_id,
            tool_name="lite_analysis",
            provider="yfinance",
            query="AMD_US_EQ",
            result_summary="Summary",
        )

        result = mgr.get_session(session_id)
        assert result is not None
        assert result["actions"][0]["id"] == action["id"]
        assert result["research_logs"][0]["id"] == log["id"]
        assert result["actions"][0]["status"] == "awaiting_confirmation"

    def test_workflow_steps_persist_and_serialize(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard", user_id="u1")
        turn_id = mgr.add_turn(session_id, role="user", message_text="Compare AMD and NVDA", channel_type="dashboard")
        step = mgr.add_workflow_step(
            session_id=session_id,
            turn_id=turn_id,
            step_key="planning",
            status="running",
            label="Planning response",
            detail="Choosing the best route.",
            model="gpt-5.4",
        )
        updated = mgr.update_workflow_step(
            step["id"],
            status="completed",
            detail="Planner selected grounded research.",
            cost_gbp=0.0123,
            completed_at=datetime.now(timezone.utc),
            detail_json={"route": "grounded_research"},
        )

        result = mgr.get_session(session_id)
        assert result is not None
        assert result["workflow_steps"][0]["id"] == step["id"]
        assert updated["status"] == "completed"
        assert result["workflow_steps"][0]["detail_json"]["route"] == "grounded_research"
        assert result["workflow_steps"][0]["cost_gbp"] == 0.0123

    def test_expire_old_pending_actions(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard")
        turn_id = mgr.add_turn(session_id, role="user", message_text="Sell losers", channel_type="dashboard")
        mgr.create_action(
            session_id=session_id,
            turn_id=turn_id,
            action_type="portfolio_batch_sell",
            status="awaiting_confirmation",
            title="Sell losers",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        expired = mgr.expire_old_pending_actions()
        result = mgr.get_session(session_id)

        assert expired == 1
        assert result is not None
        assert result["actions"][0]["status"] == "expired"

    def test_find_active_session_by_key_or_user(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="slack", user_id="u1", channel_session_key="thread-1")

        by_key = mgr.find_active_session(channel_type="slack", channel_session_key="thread-1")
        by_user = mgr.find_active_session(channel_type="slack", user_id="u1")

        assert by_key is not None
        assert by_user is not None
        assert by_key["id"] == session_id
        assert by_user["id"] == session_id

    def test_end_session(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="slack")
        mgr.end_session(session_id)

        result = mgr.get_session(session_id)
        assert result is not None
        assert result["status"] == "closed"
        assert result["ended_at"] is not None

    def test_add_turn_to_missing_session_raises_not_found(self):
        mgr = SessionManager()
        with pytest.raises(ChatSessionNotFoundError):
            mgr.add_turn(99999, role="user", message_text="Hello")

    def test_end_missing_session_raises_not_found(self):
        mgr = SessionManager()
        with pytest.raises(ChatSessionNotFoundError):
            mgr.end_session(99999)
