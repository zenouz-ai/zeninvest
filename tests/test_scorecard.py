"""Tests for production latency scorecard (US-9.12)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run
from src.data.models import Base as AgentBase
from src.observability.scorecard import (
    FROZEN_BASELINE,
    INCLUDED_STATUSES,
    TRUNCATION_THRESHOLD_SECONDS,
    compute_latency_scorecard,
    write_scorecard,
)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    AgentBase.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


def _add_run(
    session,
    *,
    duration: float,
    run_type: str = "scheduled",
    status: str = "completed",
) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        Run(
            cycle_id=f"cycle_{run_type}_{status}_{duration}_{now.timestamp()}",
            run_type=run_type,
            started_at=now - timedelta(seconds=duration),
            completed_at=now,
            status=status,
            summary_json={"duration_seconds": duration},
        )
    )
    session.commit()


def test_compute_scorecard_p50_and_truncation(session):
    _add_run(session, duration=400.0)
    _add_run(session, duration=900.0)
    result = compute_latency_scorecard(session, days=30, run_type="scheduled")
    assert result["current"]["count"] == 2
    assert result["current"]["p50_seconds"] == 400.0
    assert result["current"]["truncated_count"] == 1
    assert result["current"]["truncation_rate"] == 0.5
    assert result["window"]["included_statuses"] == list(INCLUDED_STATUSES)
    assert result["window"]["truncation_threshold_seconds"] == TRUNCATION_THRESHOLD_SECONDS
    assert result["baseline_delta"]["p50_seconds"] == round(400.0 - FROZEN_BASELINE["p50_seconds"], 2)


def test_truncation_threshold(session):
    assert TRUNCATION_THRESHOLD_SECONDS == 895.0


def test_empty_window_returns_no_data_without_false_baseline_delta(session):
    result = compute_latency_scorecard(session, days=30, run_type="scheduled")

    assert result["current"]["count"] == 0
    assert result["current"]["avg_seconds"] is None
    assert result["current"]["p50_seconds"] is None
    assert result["current"]["p95_seconds"] is None
    assert result["current"]["truncation_rate"] is None
    assert result["baseline_delta"] == {
        "p50_seconds": None,
        "p95_seconds": None,
        "truncation_rate": None,
    }


def test_scorecard_includes_failed_and_strategy_error_runs(session):
    _add_run(session, duration=100.0, status="failed")
    _add_run(session, duration=200.0, status="strategy_error")
    _add_run(session, duration=300.0, status="running")

    result = compute_latency_scorecard(session, days=30, run_type="scheduled")

    assert result["current"]["count"] == 2
    assert result["current"]["avg_seconds"] == 150.0


def test_write_scorecard_persists_expected_json_keys(session, tmp_path):
    _add_run(session, duration=895.0)
    payload = compute_latency_scorecard(session, days=30, run_type="scheduled")
    out = tmp_path / "agentic_scorecard.json"

    written = write_scorecard(payload, out)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert written == str(out)
    assert data["captured_at"]
    assert "git_commit" in data
    assert data["frozen_baseline"]["p95_seconds"] == FROZEN_BASELINE["p95_seconds"]
    assert data["window"]["run_type"] == "scheduled"
    assert data["window"]["days"] == 30
    assert data["window"]["truncation_threshold_seconds"] == 895.0
    assert data["current"]["truncated_count"] == 1
