"""Tests for search API tracker: monthly budget enforcement and call logging."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, ApiLog
from src.utils.search_api_tracker import (
    SERVICE_BRAVE_SEARCH,
    SERVICE_BRAVE_ANSWERS,
    SERVICE_TAVILY,
    get_search_api_monthly_count,
    check_search_api_budget,
    log_search_api_call,
)


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
    with patch("src.utils.search_api_tracker.get_session", return_value=db_session):
        yield


def _add_log(session, service: str, days_ago: int = 0):
    session.add(ApiLog(
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
        service=service,
        method="GET",
        endpoint="/search",
        status_code=200,
        duration_ms=100.0,
    ))
    session.commit()


# --- get_search_api_monthly_count ---


def test_monthly_count_empty_db(db_session):
    assert get_search_api_monthly_count(SERVICE_BRAVE_SEARCH) == 0


def test_monthly_count_current_month(db_session):
    _add_log(db_session, SERVICE_BRAVE_SEARCH, days_ago=0)
    _add_log(db_session, SERVICE_BRAVE_SEARCH, days_ago=1)
    _add_log(db_session, SERVICE_TAVILY, days_ago=0)  # Different service
    assert get_search_api_monthly_count(SERVICE_BRAVE_SEARCH) == 2
    assert get_search_api_monthly_count(SERVICE_TAVILY) == 1


def test_monthly_count_ignores_previous_month(db_session):
    # Add a log from 40 days ago (previous month)
    _add_log(db_session, SERVICE_BRAVE_SEARCH, days_ago=40)
    # Add a log from today
    _add_log(db_session, SERVICE_BRAVE_SEARCH, days_ago=0)
    assert get_search_api_monthly_count(SERVICE_BRAVE_SEARCH) == 1


# --- check_search_api_budget ---


def test_budget_under_limit(db_session):
    mock_settings = MagicMock()
    mock_settings.brave_search_monthly_calls = 2000
    with patch("src.utils.search_api_tracker.get_settings", return_value=mock_settings):
        assert check_search_api_budget(SERVICE_BRAVE_SEARCH) is True


def test_budget_at_limit(db_session):
    mock_settings = MagicMock()
    mock_settings.brave_search_monthly_calls = 1
    mock_settings.search_api_limits = {"brave_search_monthly_calls": 1}
    _add_log(db_session, SERVICE_BRAVE_SEARCH, days_ago=0)
    with patch("src.utils.search_api_tracker.get_settings", return_value=mock_settings):
        assert check_search_api_budget(SERVICE_BRAVE_SEARCH) is False


def test_budget_unknown_provider(db_session):
    mock_settings = MagicMock()
    # Ensure the limits dict returns None for unknown service
    with patch("src.utils.search_api_tracker.get_settings", return_value=mock_settings):
        # Unknown service not in the hardcoded limits dict → returns True
        assert check_search_api_budget("unknown_service") is True


# --- log_search_api_call ---


def test_log_call_creates_api_log(db_session):
    log_search_api_call(
        service=SERVICE_BRAVE_SEARCH,
        endpoint="/api/search",
        status_code=200,
        duration_ms=150.0,
    )
    logs = db_session.query(ApiLog).all()
    assert len(logs) == 1
    assert logs[0].service == SERVICE_BRAVE_SEARCH
    assert logs[0].status_code == 200
    assert logs[0].duration_ms == 150.0


def test_log_call_with_all_fields(db_session):
    log_search_api_call(
        service=SERVICE_TAVILY,
        endpoint="/api/search",
        status_code=500,
        duration_ms=3000.0,
        method="POST",
        error="Internal Server Error",
    )
    log = db_session.query(ApiLog).first()
    assert log.service == SERVICE_TAVILY
    assert log.method == "POST"
    assert log.error == "Internal Server Error"
    assert log.status_code == 500
