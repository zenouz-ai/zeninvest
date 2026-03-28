"""Tests for session concurrency safety (Phase 4).

Covers: optimistic concurrency on ChatAction, version mismatch,
idempotent confirm, and action expiry.
"""

import os

os.environ.setdefault("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.conversation.session_manager import (
    ChatActionNotFoundError,
    SessionManager,
    StaleActionError,
)
from src.data.models import Base, ChatAction, ChatSession


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
def session_id(manager, db_session):
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        return manager.create_session(channel_type="test", user_id="u1")


# ---------------------------------------------------------------------------
# Optimistic concurrency — version checks
# ---------------------------------------------------------------------------


class TestVersionedUpdate:
    def test_successful_versioned_update(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            action = manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="awaiting_confirmation",
                title="Buy AAPL",
                ticker="AAPL_US_EQ",
                requires_confirmation=True,
            )
            result = manager.update_action_versioned(
                action["id"],
                expected_version=1,
                status="confirmed",
                confirmed_at=datetime.now(timezone.utc),
            )
            assert result["status"] == "confirmed"
            assert result["version"] == 2

    def test_version_mismatch_raises_stale_error(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            action = manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="awaiting_confirmation",
                title="Buy MSFT",
                ticker="MSFT_US_EQ",
                requires_confirmation=True,
            )
            # First update succeeds (version 1 → 2)
            manager.update_action_versioned(
                action["id"], expected_version=1, status="confirmed"
            )
            # Second attempt with stale version should fail
            with pytest.raises(StaleActionError):
                manager.update_action_versioned(
                    action["id"], expected_version=1, status="executed"
                )

    def test_sequential_versioned_updates(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            action = manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="draft",
                title="Sell NVDA",
                ticker="NVDA_US_EQ",
            )
            # version 1 → 2
            r1 = manager.update_action_versioned(
                action["id"], expected_version=1, status="awaiting_confirmation"
            )
            assert r1["version"] == 2
            # version 2 → 3
            r2 = manager.update_action_versioned(
                r1["id"], expected_version=2, status="confirmed"
            )
            assert r2["version"] == 3

    def test_not_found_raises(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            with pytest.raises(ChatActionNotFoundError):
                manager.update_action_versioned(99999, expected_version=1, status="confirmed")


# ---------------------------------------------------------------------------
# Idempotent confirm
# ---------------------------------------------------------------------------


class TestIdempotentConfirm:
    def test_confirming_already_confirmed_is_idempotent(self, manager, db_session, session_id):
        """A second confirm on an already-confirmed action should be safe
        if the version is correct."""
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            action = manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="awaiting_confirmation",
                title="Buy AMD",
                ticker="AMD_US_EQ",
                requires_confirmation=True,
            )
            r1 = manager.update_action_versioned(
                action["id"], expected_version=1, status="confirmed"
            )
            # Second confirm with correct new version
            r2 = manager.update_action_versioned(
                r1["id"], expected_version=2, status="confirmed"
            )
            assert r2["status"] == "confirmed"
            assert r2["version"] == 3


# ---------------------------------------------------------------------------
# Action expiry
# ---------------------------------------------------------------------------


class TestActionExpiry:
    def test_expire_stale_actions(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            # Create an action that expired 5 minutes ago
            manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="awaiting_confirmation",
                title="Buy GOOG",
                ticker="GOOG_US_EQ",
                requires_confirmation=True,
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            # Create a non-expired action
            manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="awaiting_confirmation",
                title="Buy META",
                ticker="META_US_EQ",
                requires_confirmation=True,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            count = manager.expire_old_pending_actions()
            assert count == 1

    def test_expire_does_not_touch_non_pending(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="executed",
                title="Already done",
                ticker="TSLA_US_EQ",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            count = manager.expire_old_pending_actions()
            assert count == 0


# ---------------------------------------------------------------------------
# Version field in serialization
# ---------------------------------------------------------------------------


class TestVersionSerialization:
    def test_version_in_serialized_action(self, manager, db_session, session_id):
        with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
            action = manager.create_action(
                session_id=session_id,
                turn_id=None,
                action_type="trade",
                status="draft",
                title="Test",
            )
            assert "version" in action
            assert action["version"] == 1
