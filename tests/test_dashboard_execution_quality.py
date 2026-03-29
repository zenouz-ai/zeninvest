"""Tests for dashboard execution-quality endpoint."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase
from dashboard.backend.app.routers import orders as orders_router
from src.data.models import Base, Order


def test_execution_quality_rollup_and_recent_partial_fills():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    now = datetime.now(timezone.utc)
    eligible_partial = Order(
        ticker="AAPL_US_EQ",
        action="BUY",
        order_type="market",
        quantity=5.0,
        decision_price=100.0,
        price=101.0,
        filled_quantity=3.0,
        remaining_quantity=2.0,
        slippage_bps=100.0,
        status="cancelled",
        strategy="momentum",
        timestamp=now - timedelta(hours=2),
    )
    direct_partial = Order(
        ticker="TSLA_US_EQ",
        action="BUY",
        order_type="market",
        quantity=4.0,
        decision_price=100.0,
        price=99.5,
        filled_quantity=2.0,
        remaining_quantity=2.0,
        slippage_bps=-50.0,
        status="cancelled",
        strategy="slack_direct",
        timestamp=now - timedelta(hours=3),
    )
    seed.add_all([
        eligible_partial,
        direct_partial,
        Order(
            ticker="MSFT_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-1.0,
            decision_price=100.0,
            price=99.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            slippage_bps=100.0,
            status="filled",
            timestamp=now - timedelta(days=1),
        ),
        Order(
            ticker="NVDA_US_EQ",
            action="BUY",
            order_type="market",
            quantity=1.0,
            decision_price=100.0,
            price=100.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            slippage_bps=0.0,
            status="filled",
            timestamp=now - timedelta(days=2),
        ),
    ])
    seed.commit()
    seed.close()

    app = FastAPI()
    app.include_router(orders_router.router, prefix="/api/orders")

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        mock_settings.execution_quality_enabled = True
        mock_settings.execution_quality_warning_threshold_bps = 25.0
        mock_settings.execution_quality_warning_min_fills = 2

        client = TestClient(app)
        response = client.get("/api/orders/execution-quality?days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["window_days"] == 30
    assert payload["overall"]["count"] == 4
    assert payload["buy"]["count"] == 3
    assert payload["exit"]["count"] == 1
    assert payload["overall"]["mean_bps"] == 37.5
    assert payload["warning_breached"] is True
    assert "above the 25.0 bps threshold" in payload["warning_message"]
    assert len(payload["recent_partial_fills"]) == 2

    partials_by_ticker = {row["ticker"]: row for row in payload["recent_partial_fills"]}
    assert partials_by_ticker["AAPL_US_EQ"]["resubmission_eligible"] is True
    assert partials_by_ticker["TSLA_US_EQ"]["resubmission_eligible"] is False
    assert all(row["remaining_quantity"] > 0 for row in payload["recent_partial_fills"])
