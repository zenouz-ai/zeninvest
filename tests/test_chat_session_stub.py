"""Tests for chat session manager stub (US-1.9)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from src.agents.conversation.session_manager import SessionManager
from src.data.models import Base, ChatSession, ChatTurn


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
    with patch(
        "src.agents.conversation.session_manager.get_session",
        return_value=db_session,
    ):
        yield


class TestSessionManager:

    def test_create_session(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard", user_id="user1")
        assert isinstance(session_id, int)
        assert session_id > 0

    def test_add_turn(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="slack")
        turn_id = mgr.add_turn(session_id, role="user", message_text="Hello")
        assert isinstance(turn_id, int)
        assert turn_id > 0

    def test_get_session_with_turns(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="dashboard", user_id="u1")
        mgr.add_turn(session_id, role="user", message_text="BUY AAPL")
        mgr.add_turn(session_id, role="assistant", message_text="Processing...")

        result = mgr.get_session(session_id)
        assert result is not None
        assert result["id"] == session_id
        assert result["status"] == "active"
        assert result["channel_type"] == "dashboard"
        assert len(result["turns"]) == 2
        assert result["turns"][0]["role"] == "user"
        assert result["turns"][1]["role"] == "assistant"
        assert result["turns"][0]["turn_index"] == 0
        assert result["turns"][1]["turn_index"] == 1

    def test_get_nonexistent_session(self):
        mgr = SessionManager()
        result = mgr.get_session(99999)
        assert result is None

    def test_end_session(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="slack")
        mgr.end_session(session_id)

        result = mgr.get_session(session_id)
        assert result["status"] == "closed"
        assert result["ended_at"] is not None

    def test_session_with_intent(self):
        mgr = SessionManager()
        session_id = mgr.create_session(channel_type="slack")
        turn_id = mgr.add_turn(
            session_id,
            role="user",
            message_text="BUY AAPL",
            intent_json='{"action": "BUY", "ticker": "AAPL"}',
        )
        result = mgr.get_session(session_id)
        assert result["turns"][0]["intent_json"] is not None
