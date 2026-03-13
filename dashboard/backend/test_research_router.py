"""Unit tests for research router — logs and summary endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.data.database import SessionLocal, engine
from src.data.models import Base, ResearchLog


@pytest.fixture
def db_session():
    """Use the test suite's in-memory engine (conftest sets INVESTMENT_AGENT_USE_INMEMORY_DB=1)."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_research_logs(db_session):
    """Add sample ResearchLog rows for testing."""
    logs = [
        ResearchLog(
            cycle_id="cycle-1",
            member="strategy",
            ticker="AAPL_US_EQ",
            tool_name="web_search",
            query="AAPL earnings",
            num_results=5,
            provider="brave",
            cache_hit=False,
            created_at=datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
        ),
        ResearchLog(
            cycle_id="cycle-1",
            member="skeptic",
            ticker="AAPL_US_EQ",
            tool_name="news_search",
            query="AAPL downgrade",
            num_results=3,
            provider="tavily",
            cache_hit=True,
            created_at=datetime(2026, 3, 10, 12, 5, 0, tzinfo=timezone.utc),
        ),
    ]
    for log in logs:
        db_session.add(log)
    db_session.commit()
    return db_session


def test_get_research_summary_empty(sample_research_logs, monkeypatch):
    """get_research_summary returns correct structure with no date filters."""
    from fastapi.testclient import TestClient

    from dashboard.backend.app.main import app

    session = sample_research_logs

    def _get_session_override():
        return session

    mock_settings = MagicMock()
    mock_settings.dashboard_enabled = True

    monkeypatch.setattr(
        "dashboard.backend.app.routers.research.get_session",
        _get_session_override,
    )
    monkeypatch.setattr(
        "dashboard.backend.app.routers.research.settings",
        mock_settings,
    )

    client = TestClient(app)
    response = client.get("/api/research/summary")

    assert response.status_code == 200
    data = response.json()
    assert "total_calls" in data
    assert "cache_hits" in data
    assert "cache_hit_rate" in data
    assert "by_member" in data
    assert data["total_calls"] == 2
    assert data["cache_hits"] == 1
    assert data["cache_hit_rate"] == 0.5
    assert data["by_member"]["strategy"] == 1
    assert data["by_member"]["skeptic"] == 1


def test_get_research_summary_with_date_filters(sample_research_logs, monkeypatch):
    """get_research_summary with from_date/to_date works (no NameError)."""
    from fastapi.testclient import TestClient

    from dashboard.backend.app.main import app

    session = sample_research_logs

    def _get_session_override():
        return session

    mock_settings = MagicMock()
    mock_settings.dashboard_enabled = True

    monkeypatch.setattr(
        "dashboard.backend.app.routers.research.get_session",
        _get_session_override,
    )
    monkeypatch.setattr(
        "dashboard.backend.app.routers.research.settings",
        mock_settings,
    )

    client = TestClient(app)
    # Filter to date range that includes our sample data
    response = client.get(
        "/api/research/summary",
        params={
            "from_date": "2026-03-10T00:00:00",
            "to_date": "2026-03-11T00:00:00",
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Shared in-memory DB may have rows from other tests; key is no NameError and correct shape
    assert data["total_calls"] >= 2
    assert data["cache_hits"] >= 1
    assert 0 <= data["cache_hit_rate"] <= 1


def test_get_research_summary_disabled_dashboard(monkeypatch):
    """get_research_summary returns 503 when dashboard disabled."""
    from fastapi.testclient import TestClient

    from dashboard.backend.app.main import app

    mock_settings = MagicMock()
    mock_settings.dashboard_enabled = False

    monkeypatch.setattr(
        "dashboard.backend.app.routers.research.settings",
        mock_settings,
    )

    client = TestClient(app)
    response = client.get("/api/research/summary")

    assert response.status_code == 503
