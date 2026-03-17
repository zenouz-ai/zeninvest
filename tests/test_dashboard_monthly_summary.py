"""Tests for dashboard monthly summary aggregation."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.backend.app.database import Base as DashboardBase, Run
from dashboard.backend.app.routers.dashboard import get_monthly_summary
from src.data.models import Base, CostLog


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for dashboard summary tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_monthly_summary_cost_includes_research(db_session):
    """monthly-summary cost_gbp should include llm + api + research costs."""
    db_session.add(
        Run(
            cycle_id="cycle_test_1",
            run_type="manual",
            started_at=datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 3, 15, 12, 5, tzinfo=timezone.utc),
            status="completed",
        )
    )
    db_session.add(
        CostLog(
            timestamp=datetime(2026, 3, 15, 12, 1, tzinfo=timezone.utc),
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cost_gbp=1.25,
        )
    )
    db_session.commit()

    with patch(
        "dashboard.backend.app.routers.dashboard.get_session",
        return_value=db_session,
    ), patch(
        "dashboard.backend.app.routers.dashboard.estimate_api_cost_gbp",
        return_value=0.75,
    ), patch(
        "dashboard.backend.app.routers.dashboard.get_research_cost_by_month",
        return_value={"2026-03": 0.5},
    ):
        response = asyncio.run(get_monthly_summary(year=2026, month=3))

    assert response["runs_count"] == 1
    assert response["llm_cost_gbp"] == 1.25
    assert response["api_cost_gbp"] == 0.75
    assert response["research_cost_gbp"] == 0.5
    assert response["cost_gbp"] == 2.5
