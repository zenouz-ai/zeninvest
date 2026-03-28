"""Tests for extended chat API endpoints (Phase 7).

Covers: paginated turns, actions listing, session spend, session archival,
and channel_type filter on session list.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.conversation.session_manager import (
    ChatSessionNotFoundError,
    SessionManager,
)
from src.data.models import Base, ChatAction, ChatSession, ChatTurn


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def manager(db_session):
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        yield SessionManager()


@pytest.fixture
def session_with_turns(manager, db_session):
    """Create a session with multiple turns."""
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        sid = manager.create_session(channel_type="dashboard", user_id="u1")
        # Add turns manually
        for i in range(10):
            turn = ChatTurn(
                session_id=sid,
                turn_index=i,
                role="user" if i % 2 == 0 else "assistant",
                message_text=f"Turn {i}",
            )
            db_session.add(turn)
        db_session.commit()
        return sid


@pytest.fixture
def session_with_actions(manager, db_session):
    """Create a session with actions in various states."""
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        sid = manager.create_session(channel_type="dashboard", user_id="u1")
        manager.create_action(
            session_id=sid,
            turn_id=None,
            action_type="trade",
            status="awaiting_confirmation",
            title="Buy AAPL",
            ticker="AAPL_US_EQ",
            requires_confirmation=True,
        )
        manager.create_action(
            session_id=sid,
            turn_id=None,
            action_type="trade",
            status="executed",
            title="Sell MSFT",
            ticker="MSFT_US_EQ",
        )
        manager.create_action(
            session_id=sid,
            turn_id=None,
            action_type="trade",
            status="expired",
            title="Buy GOOG",
            ticker="GOOG_US_EQ",
        )
        return sid


# ---------------------------------------------------------------------------
# Paginated turns
# ---------------------------------------------------------------------------


class TestListTurns:
    def test_returns_all_turns(self, manager, db_session, session_with_turns):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            turns = manager.list_turns(session_with_turns)
            assert len(turns) == 10

    def test_pagination_offset(self, manager, db_session, session_with_turns):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            turns = manager.list_turns(session_with_turns, offset=5, limit=3)
            assert len(turns) == 3
            assert turns[0]["turn_index"] == 5

    def test_pagination_limit(self, manager, db_session, session_with_turns):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            turns = manager.list_turns(session_with_turns, limit=3)
            assert len(turns) == 3
            assert turns[0]["turn_index"] == 0

    def test_empty_session(self, manager, db_session):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            sid = manager.create_session(channel_type="test")
            turns = manager.list_turns(sid)
            assert turns == []


# ---------------------------------------------------------------------------
# Actions listing with status filter
# ---------------------------------------------------------------------------


class TestListActions:
    def test_returns_all_actions(self, manager, db_session, session_with_actions):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            actions = manager.list_actions(session_with_actions)
            assert len(actions) == 3

    def test_filter_by_status(self, manager, db_session, session_with_actions):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            pending = manager.list_actions(session_with_actions, status="awaiting_confirmation")
            assert len(pending) == 1
            assert pending[0]["ticker"] == "AAPL_US_EQ"

    def test_filter_executed(self, manager, db_session, session_with_actions):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            executed = manager.list_actions(session_with_actions, status="executed")
            assert len(executed) == 1
            assert executed[0]["ticker"] == "MSFT_US_EQ"


# ---------------------------------------------------------------------------
# Session spend
# ---------------------------------------------------------------------------


class TestGetSessionSpend:
    def test_returns_cost_summary(self, manager, db_session):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            sid = manager.create_session(channel_type="test")
            spend = manager.get_session_spend(sid)
            assert isinstance(spend, dict)

    def test_not_found_raises(self, manager, db_session):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            with pytest.raises(ChatSessionNotFoundError):
                manager.get_session_spend(99999)


# ---------------------------------------------------------------------------
# Session archival (soft delete)
# ---------------------------------------------------------------------------


class TestArchiveSession:
    def test_archive_sets_status(self, manager, db_session):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            sid = manager.create_session(channel_type="test")
            manager.archive_session(sid)
            detail = manager.get_session(sid)
            assert detail["status"] == "archived"
            assert detail["ended_at"] is not None

    def test_archive_not_found_raises(self, manager, db_session):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            with pytest.raises(ChatSessionNotFoundError):
                manager.archive_session(99999)
