"""Dashboard portfolio and stop-loss route coverage for operator-visible fields."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.routers import portfolio as portfolio_router
from dashboard.backend.app.routers import stop_loss as stop_loss_router
from src.data.models import Base, Instrument, Order, PortfolioSnapshot, StopLossAdjustment


def _make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_stop_loss_current_merges_orders_adjustments_and_missing_positions():
    """Current stops should show one row per position, preferring orders but keeping adjustment-only tickers."""
    Session = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add(
        PortfolioSnapshot(
            timestamp=now,
            total_value_gbp=15000.0,
            cash_gbp=1000.0,
            invested_gbp=14000.0,
            pnl_gbp=1200.0,
            pnl_pct=8.7,
            num_positions=3,
            positions_json=json.dumps([
                {
                    "ticker": "AAPL_US_EQ",
                    "quantity": 5.0,
                    "value_gbp": 2500.0,
                    "pnl_gbp": 420.0,
                    "pnl_pct": 20.2,
                    "profit_lock_status": "protected",
                    "profit_lock_required_price_gbp": 95.0,
                    "profit_lock_stop_price_gbp": 96.5,
                    "profit_lock_protected_qty": 5.0,
                },
                {
                    "ticker": "MSFT_US_EQ",
                    "quantity": 4.0,
                    "value_gbp": 1800.0,
                    "pnl_gbp": 270.0,
                    "pnl_pct": 17.8,
                    "profit_lock_status": "eligible",
                    "profit_lock_required_price_gbp": 110.0,
                    "profit_lock_stop_price_gbp": None,
                    "profit_lock_protected_qty": 0.0,
                },
                {
                    "ticker": "NVDA_US_EQ",
                    "quantity": 2.0,
                    "value_gbp": 950.0,
                    "pnl_gbp": 40.0,
                    "pnl_pct": 4.4,
                    "profit_lock_status": "inactive",
                    "profit_lock_required_price_gbp": None,
                    "profit_lock_stop_price_gbp": None,
                    "profit_lock_protected_qty": 0.0,
                },
            ]),
        )
    )
    seed.add(
        Order(
            ticker="AAPL_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-5.0,
            stop_price=121.5,
            status="pending",
            timestamp=now,
        )
    )
    seed.add(
        StopLossAdjustment(
            ticker="MSFT_US_EQ",
            adjustment_type="profit_lock",
            new_stop_price=210.0,
            trigger_reason="profit_lock_stop_placed",
            status="placed",
            timestamp=now,
        )
    )
    seed.commit()
    seed.close()

    app = FastAPI()
    app.include_router(stop_loss_router.router, prefix="/api/stop-loss")

    with patch("dashboard.backend.app.routers.stop_loss.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.stop_loss.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        response = client.get("/api/stop-loss/current")

    assert response.status_code == 200
    payload = {row["ticker"]: row for row in response.json()}

    assert set(payload) == {"AAPL_US_EQ", "MSFT_US_EQ", "NVDA_US_EQ"}
    assert payload["AAPL_US_EQ"]["source"] == "order"
    assert payload["AAPL_US_EQ"]["profit_lock_status"] == "protected"
    assert payload["AAPL_US_EQ"]["profit_lock_stop_price_gbp"] == 96.5
    assert payload["MSFT_US_EQ"]["source"] == "adjustment"
    assert payload["MSFT_US_EQ"]["profit_lock_status"] == "eligible"
    assert payload["MSFT_US_EQ"]["profit_lock_required_price_gbp"] == 110.0
    assert payload["NVDA_US_EQ"]["source"] == "position (no stop)"
    assert payload["NVDA_US_EQ"]["stop_price"] is None


def test_portfolio_current_exposes_profit_lock_fields():
    """Portfolio snapshot rows should serialize the profit-lock fields consumed by the dashboard."""
    Session = _make_session_factory()
    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add(Instrument(ticker="ENGGY_US_EQ", sector="Utilities", data_available=True))
    seed.add(
        PortfolioSnapshot(
            timestamp=now,
            total_value_gbp=12000.0,
            cash_gbp=1500.0,
            invested_gbp=10500.0,
            pnl_gbp=900.0,
            pnl_pct=8.1,
            num_positions=1,
            positions_json=json.dumps([
                {
                    "ticker": "ENGGY_US_EQ",
                    "quantity": 65.39,
                    "value_gbp": 480.3,
                    "pnl_gbp": 72.16,
                    "pnl_pct": 17.45,
                    "profit_lock_status": "protected",
                    "profit_lock_required_price_gbp": 7.34,
                    "profit_lock_stop_price_gbp": 7.41,
                    "profit_lock_protected_qty": 65.39,
                }
            ]),
        )
    )
    seed.commit()
    seed.close()

    app = FastAPI()
    app.include_router(portfolio_router.router, prefix="/api/portfolio")

    with patch("dashboard.backend.app.routers.portfolio.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.portfolio.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        response = client.get("/api/portfolio/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["num_positions"] == 1
    position = payload["positions"][0]
    assert position["ticker"] == "ENGGY_US_EQ"
    assert position["sector"] == "Utilities"
    assert position["profit_lock_status"] == "protected"
    assert position["profit_lock_required_price_gbp"] == 7.34
    assert position["profit_lock_stop_price_gbp"] == 7.41
    assert position["profit_lock_protected_qty"] == 65.39
