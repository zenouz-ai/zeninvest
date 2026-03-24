"""Tests for chat API validation and missing-session handling."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.routers import chat
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
        app = FastAPI()
        app.include_router(chat.router, prefix="/api/chat")
        with TestClient(app) as client:
            yield client


def test_add_turn_missing_session_returns_404(client):
    response = client.post(
        "/api/chat/sessions/999/turns",
        json={"role": "user", "message_text": "BUY AAPL"},
    )

    assert response.status_code == 404


def test_invalid_role_returns_422(client):
    response = client.post(
        "/api/chat/sessions",
        json={"channel_type": "dashboard"},
    )
    session_id = response.json()["session_id"]

    invalid = client.post(
        f"/api/chat/sessions/{session_id}/turns",
        json={"role": "trader", "message_text": "BUY AAPL"},
    )

    assert invalid.status_code == 422


def test_invalid_channel_type_returns_422(client):
    response = client.post(
        "/api/chat/sessions",
        json={"channel_type": "email"},
    )

    assert response.status_code == 422


def test_end_missing_session_returns_404(client):
    response = client.post("/api/chat/sessions/999/end")

    assert response.status_code == 404
