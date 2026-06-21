"""Tests for latency observability API."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run
from dashboard.backend.app.routers import latency as latency_router
from src.data.models import Base as AgentBase


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AgentBase.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    app = FastAPI()
    app.include_router(latency_router.router, prefix="/api/latency")
    with patch("src.data.database.get_session", return_value=db_session), patch(
        "dashboard.backend.app.routers.latency.get_session",
        return_value=db_session,
    ):
        yield TestClient(app)


def test_latency_schedule_endpoint(client):
    response = client.get("/api/latency/schedule")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert any(j["run_type"] == "scheduled" for j in data["jobs"])


def test_latency_summary_endpoint(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        Run(
            cycle_id="latency_test_cycle",
            run_type="scheduled",
            started_at=now,
            completed_at=now,
            status="completed",
            summary_json={
                "duration_seconds": 540.0,
                "phase_timing": {
                    "screening": {"seconds": 120.0},
                    "strategy": {"seconds": 300.0},
                },
                "step_timing": {"order_sync": 10.0},
            },
        )
    )
    db_session.commit()

    response = client.get("/api/latency/summary?days=30")
    assert response.status_code == 200
    data = response.json()
    assert "run_types" in data
    assert data["phases"].get("screening", {}).get("p50_seconds") == 120.0
    assert "truncation_rate" in data
    assert "frozen_baseline" in data
    assert data["truncation_rate"] == 0.0
    assert data["baseline_delta"]["p50_seconds"] == -5.0


def test_latency_summary_empty_scheduled_window_has_null_scorecard_fields(client):
    response = client.get("/api/latency/summary?days=30")

    assert response.status_code == 200
    data = response.json()
    assert data["truncation_rate"] is None
    assert data["baseline_delta"] == {
        "p50_seconds": None,
        "p95_seconds": None,
        "truncation_rate": None,
    }
    assert data["frozen_baseline"]["p95_seconds"] == 900.0
