"""Dashboard runs API tests for derived summary fields."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, EventsLog, Run
from dashboard.backend.app.routers import runs as runs_router
from src.data.models import Base, StrategyDecision


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(runs_router.router, prefix="/api/runs")
    with patch("src.data.database.get_session", return_value=db_session), patch(
        "dashboard.backend.app.routers.runs.get_session",
        return_value=db_session,
    ):
        yield TestClient(app)


def test_runs_api_derives_reviewed_and_screened_counts(client, db_session):
    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    completed_at = started_at + timedelta(minutes=3)

    run = Run(
        cycle_id="cycle-dashboard-test",
        run_type="manual",
        started_at=started_at,
        completed_at=completed_at,
        status="completed",
        summary_json={
            "num_trades": 0,
            "num_rejected": 35,
            "duration_seconds": 180.0,
        },
    )
    db_session.add(run)
    db_session.flush()

    decisions = [
        StrategyDecision(
            timestamp=started_at + timedelta(seconds=index + 1),
            cycle_id="cycle-dashboard-test",
            ticker=f"TICK{index}_US_EQ",
            action="HOLD",
            target_allocation_pct=0.0,
            conviction=40,
            primary_strategy="momentum",
            reasoning="No trade",
        )
        for index in range(35)
    ]
    db_session.add_all(decisions)
    db_session.add(
        EventsLog(
            timestamp=started_at + timedelta(seconds=10),
            event_type="universe_updated",
            source="screener",
            message="Screened 40 candidates",
            metadata_json={"num_candidates": 40},
        )
    )
    db_session.commit()

    list_resp = client.get("/api/runs/")
    detail_resp = client.get(f"/api/runs/{run.id}")

    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200

    list_payload = list_resp.json()
    detail_payload = detail_resp.json()

    assert list_payload[0]["summary_json"]["stocks_reviewed"] == 35
    assert list_payload[0]["summary_json"]["decisions_made"] == 35
    assert list_payload[0]["summary_json"]["stocks_screened"] == 40

    assert detail_payload["summary_json"]["stocks_reviewed"] == 35
    assert detail_payload["summary_json"]["decisions_made"] == 35
    assert detail_payload["summary_json"]["stocks_screened"] == 40
