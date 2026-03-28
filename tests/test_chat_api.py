"""Tests for the conversational chat API."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.routers import chat
from src.agents.conversation.session_manager import SessionManager
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


@pytest.fixture
def client(db_session):
    with patch("src.agents.conversation.session_manager.get_session", return_value=db_session):
        with patch("src.agents.conversation.orchestrator.get_session", return_value=db_session):
            app = FastAPI()
            app.include_router(chat.router, prefix="/api/chat")
            with TestClient(app) as test_client:
                yield test_client


def test_create_list_and_get_session(client):
    created = client.post("/api/chat/sessions", json={"channel_type": "dashboard", "title": "Test session"})
    assert created.status_code == 200
    detail = created.json()

    assert detail["status"] == "active"
    assert detail["channel_type"] == "dashboard"
    assert detail["title"] == "Test session"
    assert detail["turns"] == []
    assert detail["actions"] == []
    assert detail["cost_summary"]["total_cost_gbp"] == 0.0

    listed = client.get("/api/chat/sessions")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 1
    assert payload[0]["id"] == detail["id"]

    fetched = client.get(f"/api/chat/sessions/{detail['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == detail["id"]


def test_submit_turn_returns_refreshed_session(client):
    created = client.post("/api/chat/sessions", json={"channel_type": "dashboard"})
    session_id = created.json()["id"]

    response = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={"message_text": "help me understand this workflow", "channel_type": "dashboard"},
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == session_id
    assert len(detail["turns"]) == 2
    assert detail["turns"][0]["role"] == "user"
    assert detail["turns"][1]["role"] == "assistant"
    assert "I can help" in detail["turns"][1]["message_text"]
    assert detail["turn_mode"] in {"research", "quick", "trade", "committee"}
    assert "workflow_steps" in detail


def test_submit_turn_accepts_mode_and_budget_tier(client):
    created = client.post("/api/chat/sessions", json={"channel_type": "dashboard"})
    session_id = created.json()["id"]

    response = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={
            "message_text": "help me understand this workflow",
            "channel_type": "dashboard",
            "mode": "committee",
            "budget_tier": "premium",
        },
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["turns"][0]["intent_json"]["requested_mode"] == "committee"
    assert detail["turns"][0]["intent_json"]["budget_tier"] == "premium"


def test_submit_turn_missing_session_returns_404(client):
    response = client.post(
        "/api/chat/sessions/999/turns",
        json={"message_text": "BUY AAPL", "channel_type": "dashboard"},
    )

    assert response.status_code == 404


def test_invalid_channel_type_returns_422(client):
    response = client.post(
        "/api/chat/sessions",
        json={"channel_type": "email"},
    )

    assert response.status_code == 422


def test_confirm_and_reject_action_routes(client, db_session):
    mgr = SessionManager()
    session_id = mgr.create_session(channel_type="dashboard", user_id="operator")
    turn_id = mgr.add_turn(session_id, role="user", message_text="sell losers below 5", channel_type="dashboard")
    action = mgr.create_action(
        session_id=session_id,
        turn_id=turn_id,
        action_type="portfolio_batch_sell",
        status="awaiting_confirmation",
        title="Sell losers below -5%",
        ticker="AAPL_US_EQ",
        payload_json={"positions": []},
        preview_text="Preview",
        requires_confirmation=True,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    rejected = client.post(
        f"/api/chat/sessions/{session_id}/actions/{action['id']}/reject",
        json={"channel_type": "dashboard", "expected_version": action["version"]},
    )
    assert rejected.status_code == 200
    rejected_detail = rejected.json()
    assert rejected_detail["actions"][0]["status"] == "rejected"

    action = mgr.create_action(
        session_id=session_id,
        turn_id=turn_id,
        action_type="portfolio_batch_sell",
        status="awaiting_confirmation",
        title="Sell losers below -5%",
        ticker="AAPL_US_EQ",
        payload_json={"positions": []},
        preview_text="Preview",
        requires_confirmation=True,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    mgr.expire_old_pending_actions()
    confirmed = client.post(
        f"/api/chat/sessions/{session_id}/actions/{action['id']}/confirm",
        json={"channel_type": "dashboard", "expected_version": action["version"]},
    )
    assert confirmed.status_code == 200
    confirmed_detail = confirmed.json()
    latest_assistant = confirmed_detail["turns"][-1]["message_text"]
    assert latest_assistant == "Confirmation expired. Please submit the request again."


def test_confirm_route_returns_409_for_stale_version(client):
    mgr = SessionManager()
    session_id = mgr.create_session(channel_type="dashboard", user_id="operator")
    action = mgr.create_action(
        session_id=session_id,
        turn_id=None,
        action_type="direct_trade",
        status="awaiting_confirmation",
        title="Buy AAPL",
        ticker="AAPL_US_EQ",
        requires_confirmation=True,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    mgr.update_action_versioned(action["id"], expected_version=1, status="confirmed")

    response = client.post(
        f"/api/chat/sessions/{session_id}/actions/{action['id']}/confirm",
        json={"channel_type": "dashboard", "expected_version": 1},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["action"]["id"] == action["id"]
    assert detail["action"]["status"] == "confirmed"
    assert detail["action"]["version"] == 2


def test_reject_route_returns_409_for_stale_version(client):
    mgr = SessionManager()
    session_id = mgr.create_session(channel_type="dashboard", user_id="operator")
    action = mgr.create_action(
        session_id=session_id,
        turn_id=None,
        action_type="direct_trade",
        status="awaiting_confirmation",
        title="Sell TSLA",
        ticker="TSLA_US_EQ",
        requires_confirmation=True,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    mgr.update_action_versioned(action["id"], expected_version=1, status="confirmed")

    response = client.post(
        f"/api/chat/sessions/{session_id}/actions/{action['id']}/reject",
        json={"channel_type": "dashboard", "expected_version": 1},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["action"]["id"] == action["id"]
    assert detail["action"]["status"] == "confirmed"
    assert detail["action"]["version"] == 2


def test_extended_session_endpoints(client):
    created = client.post("/api/chat/sessions", json={"channel_type": "dashboard", "title": "Extended"})
    session_id = created.json()["id"]
    turn_response = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={"message_text": "help me understand this workflow", "channel_type": "dashboard"},
    )
    detail = turn_response.json()

    turns = client.get(f"/api/chat/sessions/{session_id}/turns")
    actions = client.get(f"/api/chat/sessions/{session_id}/actions")
    spend = client.get(f"/api/chat/sessions/{session_id}/spend")
    archived = client.delete(f"/api/chat/sessions/{session_id}")

    assert turns.status_code == 200
    assert len(turns.json()) == len(detail["turns"])
    assert actions.status_code == 200
    assert actions.json() == []
    assert spend.status_code == 200
    assert "total_cost_gbp" in spend.json()
    assert archived.status_code == 200
    assert archived.json() == {"status": "archived", "session_id": session_id}


def test_end_missing_session_returns_404(client):
    response = client.post("/api/chat/sessions/999/end")
    assert response.status_code == 404


def test_end_session_returns_closed_status(client):
    created = client.post("/api/chat/sessions", json={"channel_type": "dashboard"})
    session_id = created.json()["id"]

    response = client.post(f"/api/chat/sessions/{session_id}/end")

    assert response.status_code == 200
    assert response.json() == {"status": "closed", "session_id": session_id}
