"""Dashboard API tests for strategy decision risk-parity fields."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase
from dashboard.backend.app.routers import decisions as decisions_router
from src.data.models import Base, ModerationLog, RiskDecision, StrategyDecision


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
    app.include_router(decisions_router.router, prefix="/api/decisions")
    with patch("src.data.database.get_session", return_value=db_session), patch(
        "dashboard.backend.app.routers.decisions.get_session",
        return_value=db_session,
    ):
        yield TestClient(app)


def test_decisions_and_waterfall_include_risk_parity_fields(client, db_session):
    strategy = StrategyDecision(
        timestamp=datetime.now(timezone.utc),
        cycle_id="cycle-risk-parity",
        ticker="AAPL_US_EQ",
        action="BUY",
        target_allocation_pct=10.0,
        risk_parity_target_allocation_pct=7.5,
        risk_parity_trailing_vol_pct=22.4,
        risk_parity_applied=True,
        conviction=82,
        primary_strategy="momentum",
        reasoning="Sized by inverse volatility",
    )
    moderation = ModerationLog(
        timestamp=datetime.now(timezone.utc),
        cycle_id="cycle-risk-parity",
        ticker="AAPL_US_EQ",
        moderator="strategy",
        verdict="AGREE",
        consensus="APPROVED",
    )
    risk = RiskDecision(
        timestamp=datetime.now(timezone.utc),
        cycle_id="cycle-risk-parity",
        ticker="AAPL_US_EQ",
        proposed_action="BUY",
        proposed_allocation_pct=7.5,
        verdict="APPROVE",
        adjusted_allocation_pct=7.5,
        rules_checked_json="[]",
        triggered_rules_json="[]",
        reasoning="All risk checks passed",
    )
    db_session.add_all([strategy, moderation, risk])
    db_session.commit()

    decisions_resp = client.get("/api/decisions/", params={"cycle_id": "cycle-risk-parity"})
    waterfall_resp = client.get(
        "/api/decisions/waterfall",
        params={"cycle_id": "cycle-risk-parity", "ticker": "AAPL_US_EQ"},
    )

    assert decisions_resp.status_code == 200
    assert waterfall_resp.status_code == 200

    decisions_payload = decisions_resp.json()
    waterfall_payload = waterfall_resp.json()

    assert decisions_payload[0]["target_allocation_pct"] == 10.0
    assert decisions_payload[0]["risk_parity_target_allocation_pct"] == 7.5
    assert decisions_payload[0]["risk_parity_trailing_vol_pct"] == 22.4
    assert decisions_payload[0]["risk_parity_applied"] is True

    assert waterfall_payload["strategy"]["target_allocation_pct"] == 10.0
    assert waterfall_payload["strategy"]["risk_parity_target_allocation_pct"] == 7.5
    assert waterfall_payload["strategy"]["risk_parity_trailing_vol_pct"] == 22.4
    assert waterfall_payload["strategy"]["risk_parity_applied"] is True
    assert waterfall_payload["risk"]["proposed_allocation_pct"] == 7.5
