"""Tests for the Zen Evolution Engine planner API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.routers import evolution
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
    with patch("src.agents.evolution.manager.get_session", return_value=db_session), patch(
        "src.agents.evolution.manager.log_event",
        lambda *args, **kwargs: None,
    ):
        app = FastAPI()
        app.include_router(evolution.router, prefix="/api/evolution")
        with TestClient(app) as test_client:
            yield test_client


def test_dashboard_copy_request_creates_low_risk_plan(client: TestClient):
    response = client.post(
        "/api/evolution/requests",
        json={"message_text": "Change the dashboard copy on the Costs page to explain monthly burn more clearly."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PLANNED"
    assert body["risk_class"] == "LOW"
    assert "Dashboard UI" in body["latest_plan"]["touched_areas"]
    assert any(check["id"] == "frontend_tests" for check in body["latest_plan"]["validation_matrix"])
    assert body["phase_capabilities"]["build_enabled"] is False


def test_vague_request_forces_clarification_then_replans(client: TestClient):
    response = client.post(
        "/api/evolution/requests",
        json={"message_text": "Improve the system."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEEDS_CLARIFICATION"
    assert len(body["clarification_questions"]) >= 1

    updated = client.post(
        f"/api/evolution/requests/{body['id']}/messages",
        json={"message_text": "Limit this to dashboard copy changes on the Costs page only."},
    )
    assert updated.status_code == 200
    replanned = updated.json()
    assert replanned["status"] == "PLANNED"
    assert replanned["latest_plan_version"] == 2
    assert replanned["latest_plan"]["clarification_questions"] == []


def test_trading_request_is_high_risk_with_backtest_gates(client: TestClient):
    response = client.post(
        "/api/evolution/requests",
        json={"message_text": "Change the trading strategy from swing trading to long-term investing and adjust decision logic."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PLANNED"
    assert body["risk_class"] == "HIGH"
    validation_ids = {check["id"] for check in body["latest_plan"]["validation_matrix"]}
    assert {"trading_pytest", "dry_run_cycle", "backtest_cli", "walk_forward"} <= validation_ids
    assert body["latest_plan"]["risk_policy"]["backtest_required"] is True


def test_build_gate_is_blocked_and_audited(client: TestClient):
    response = client.post(
        "/api/evolution/requests",
        json={"message_text": "Change the dashboard copy on the Costs page to explain monthly burn more clearly."},
    )
    request_id = response.json()["id"]

    blocked = client.post(
        f"/api/evolution/requests/{request_id}/approve-build",
        json={"notes": "Try to start the branch runner."},
    )
    assert blocked.status_code == 409
    payload = blocked.json()
    assert payload["status"] == "blocked"
    assert payload["approval"]["status"] == "blocked"

    detail = client.get(f"/api/evolution/requests/{request_id}")
    assert detail.status_code == 200
    detail_json = detail.json()
    assert len(detail_json["approvals"]) == 1
    assert detail_json["approvals"][0]["approval_type"] == "build"


def test_runs_artifacts_and_deployments_endpoints_work(client: TestClient):
    response = client.post(
        "/api/evolution/requests",
        json={"message_text": "Change the dashboard copy on the Costs page to explain monthly burn more clearly."},
    )
    request_id = response.json()["id"]

    runs = client.get(f"/api/evolution/requests/{request_id}/runs")
    artifacts = client.get(f"/api/evolution/requests/{request_id}/artifacts")
    deployments = client.get(f"/api/evolution/requests/{request_id}/deployments")

    assert runs.status_code == 200
    assert artifacts.status_code == 200
    assert deployments.status_code == 200
    assert len(runs.json()) == 1
    assert len(artifacts.json()) == 3
    assert deployments.json() == []
