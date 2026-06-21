"""Dashboard API tests for trade outcome timeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase
from dashboard.backend.app.routers import outcomes as outcomes_router
from src.data.models import Base, ModerationLog, Order, ResearchLog, RiskDecision, StrategyDecision, TradeOutcome


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
    app.include_router(outcomes_router.router, prefix="/api/outcomes")
    with patch("src.data.database.get_session", return_value=db_session), patch(
        "dashboard.backend.app.routers.outcomes.get_session",
        return_value=db_session,
    ), patch("dashboard.backend.app.routers.outcomes.settings") as mock_settings:
        mock_settings.dashboard_enabled = True
        yield TestClient(app)


def _seed_outcome(db_session) -> TradeOutcome:
    buy_ts = datetime(2025, 1, 10, 12, 0)
    sell_ts = datetime(2025, 3, 10, 12, 0)
    buy_order = Order(
        timestamp=buy_ts,
        ticker="BAC_US_EQ",
        action="BUY",
        order_type="market",
        quantity=10.0,
        price=35.0,
        value_gbp=350.0,
        status="filled",
        strategy="momentum",
        conviction=75,
    )
    sell_order = Order(
        timestamp=sell_ts,
        ticker="BAC_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-10.0,
        price=39.0,
        value_gbp=390.0,
        status="filled",
    )
    db_session.add_all([buy_order, sell_order])
    db_session.flush()
    db_session.add(
        StrategyDecision(
            timestamp=buy_ts,
            cycle_id="cycle-buy",
            ticker="BAC_US_EQ",
            action="BUY",
            reasoning="Momentum entry",
            primary_strategy="momentum",
        )
    )
    outcome = TradeOutcome(
        buy_order_id=buy_order.id,
        sell_order_id=sell_order.id,
        ticker="BAC_US_EQ",
        buy_timestamp=buy_ts,
        sell_timestamp=sell_ts,
        holding_days=59.0,
        buy_value_gbp=350.0,
        sell_value_gbp=390.0,
        pnl_gbp=40.0,
        pnl_pct=11.4,
        conviction=75,
        strategy="momentum",
    )
    db_session.add(outcome)
    db_session.commit()
    return outcome


def test_list_outcomes_excludes_simulated_pairs(client, db_session):
    real = _seed_outcome(db_session)
    buy_ts = datetime(2026, 6, 14, 11, 39, 27)
    stop_ts = buy_ts + timedelta(milliseconds=14)
    dry_buy = Order(
        timestamp=buy_ts,
        ticker="GEF/B_US_EQ",
        action="BUY",
        order_type="market",
        quantity=4.0,
        value_gbp=286.57,
        status="dry_run",
    )
    dry_stop = Order(
        timestamp=stop_ts,
        ticker="GEF/B_US_EQ",
        action="SELL",
        order_type="stop",
        quantity=-4.0,
        value_gbp=253.77,
        status="dry_run",
    )
    db_session.add_all([dry_buy, dry_stop])
    db_session.flush()
    db_session.add(
        TradeOutcome(
            buy_order_id=dry_buy.id,
            sell_order_id=dry_stop.id,
            ticker="GEF/B_US_EQ",
            sell_timestamp=stop_ts,
            buy_value_gbp=286.57,
            sell_value_gbp=253.77,
            pnl_gbp=-32.8,
            pnl_pct=-11.4,
        )
    )
    db_session.commit()

    response = client.get("/api/outcomes/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == real.id


def test_list_outcomes_includes_strategy_fields(client, db_session):
    outcome = _seed_outcome(db_session)
    response = client.get("/api/outcomes/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == outcome.id
    assert body[0]["strategy"] == "momentum"
    assert body[0]["buy_order_id"] == outcome.buy_order_id


def test_timeline_returns_prices_and_annotations(client, db_session, monkeypatch):
    outcome = _seed_outcome(db_session)
    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-02-01"]),
            "open": [34.0, 35.0],
            "high": [35.0, 36.0],
            "low": [33.0, 34.0],
            "close": [34.5, 35.5],
            "volume": [1000, 1100],
        }
    )

    def _fake_fetch(tickers, start, end):
        return {"BAC": fake_df}

    monkeypatch.setattr("src.agents.reporting.trade_review.fetch_bars_yfinance", _fake_fetch)

    response = client.get(f"/api/outcomes/{outcome.id}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "BAC_US_EQ"
    assert len(body["prices"]) == 4
    assert body["prices"][1]["date"] == "2025-01-10"
    assert body["prices"][-1] == {"date": "2025-03-10", "close": 39.0}
    assert body["buy"]["reasoning"] == "Momentum entry"
    assert body["outcome"]["result"] == "win"


def test_timeline_pads_sell_day_when_yfinance_ends_early(client, db_session, monkeypatch):
    outcome = _seed_outcome(db_session)
    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-09"]),
            "open": [34.0, 35.0, 38.0],
            "high": [35.0, 36.0, 39.0],
            "low": [33.0, 34.0, 37.0],
            "close": [34.5, 35.5, 38.5],
            "volume": [1000, 1100, 1200],
        }
    )

    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {"BAC": fake_df},
    )

    response = client.get(f"/api/outcomes/{outcome.id}/timeline")
    assert response.status_code == 200
    prices = response.json()["prices"]
    assert prices[-1]["date"] == "2025-03-10"
    assert prices[-1]["close"] == 39.0


def test_timeline_includes_committee_and_market_context(client, db_session, monkeypatch):
    outcome = _seed_outcome(db_session)
    db_session.add(
        ModerationLog(
            timestamp=datetime(2025, 1, 10, 12, 0),
            cycle_id="cycle-buy",
            ticker="BAC_US_EQ",
            moderator="gpt-4o",
            verdict="MODIFY",
            reasoning="Skeptic caution",
            consensus="APPROVED",
        )
    )
    db_session.add(
        RiskDecision(
            timestamp=datetime(2025, 1, 10, 12, 0),
            cycle_id="cycle-buy",
            ticker="BAC_US_EQ",
            proposed_action="BUY",
            proposed_allocation_pct=4.0,
            verdict="RESIZE",
            reasoning="Sector cap",
        )
    )
    db_session.commit()
    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-02-01"]),
            "open": [34.0, 35.0],
            "high": [35.0, 36.0],
            "low": [33.0, 34.0],
            "close": [34.5, 35.5],
            "volume": [1000, 1100],
        }
    )
    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {"BAC": fake_df},
    )
    response = client.get(f"/api/outcomes/{outcome.id}/timeline")
    assert response.status_code == 200
    buy = response.json()["buy"]
    assert buy["committee"] is not None
    assert any(m["moderator"] == "gpt-4o" for m in buy["committee"]["moderation"])
    assert buy["committee"]["risk"]["verdict"] == "RESIZE"
    assert buy["market_context"] is not None


def test_timeline_includes_research(client, db_session, monkeypatch):
    outcome = _seed_outcome(db_session)
    db_session.add(
        ResearchLog(
            cycle_id="cycle-buy",
            member="skeptic",
            ticker="BAC_US_EQ",
            tool_name="news_search",
            query="BAC earnings outlook",
            num_results=3,
            provider="brave",
            cost_usd=0.005,
            latency_ms=400,
            cache_hit=False,
        )
    )
    db_session.commit()
    fake_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-02-01"]),
            "open": [34.0, 35.0],
            "high": [35.0, 36.0],
            "low": [33.0, 34.0],
            "close": [34.5, 35.5],
            "volume": [1000, 1100],
        }
    )
    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {"BAC": fake_df},
    )
    response = client.get(f"/api/outcomes/{outcome.id}/timeline")
    assert response.status_code == 200
    research = response.json()["buy"]["research"]
    assert research is not None
    assert research["summary"]["total_calls"] == 1
    assert research["calls"][0]["tool_name"] == "news_search"
    assert "BAC earnings" in research["calls"][0]["query"]


def test_timeline_not_found(client):
    response = client.get("/api/outcomes/999/timeline")
    assert response.status_code == 404


def test_timeline_synthetic_event_bars_when_yfinance_empty(client, db_session, monkeypatch):
    outcome = _seed_outcome(db_session)
    monkeypatch.setattr(
        "src.agents.reporting.trade_review.fetch_bars_yfinance",
        lambda *args, **kwargs: {},
    )
    response = client.get(f"/api/outcomes/{outcome.id}/timeline")
    assert response.status_code == 200
    prices = response.json()["prices"]
    assert len(prices) == 2
    assert prices[0] == {"date": "2025-01-10", "close": 35.0}
    assert prices[1] == {"date": "2025-03-10", "close": 39.0}


def test_north_star_metrics_endpoint(client, db_session):
    now = datetime.now(timezone.utc)
    buy_ts = now - timedelta(days=45)
    sell_ts = now - timedelta(days=10)
    buy_order = Order(
        timestamp=buy_ts.replace(tzinfo=None),
        ticker="BAC_US_EQ",
        action="BUY",
        order_type="market",
        quantity=10.0,
        price=35.0,
        value_gbp=350.0,
        status="filled",
        strategy="momentum",
        conviction=75,
    )
    sell_order = Order(
        timestamp=sell_ts.replace(tzinfo=None),
        ticker="BAC_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-10.0,
        price=39.0,
        value_gbp=390.0,
        status="filled",
    )
    db_session.add_all([buy_order, sell_order])
    db_session.flush()
    db_session.add(
        TradeOutcome(
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            ticker="BAC_US_EQ",
            buy_timestamp=buy_ts.replace(tzinfo=None),
            sell_timestamp=sell_ts.replace(tzinfo=None),
            holding_days=35.0,
            buy_value_gbp=350.0,
            sell_value_gbp=390.0,
            pnl_gbp=40.0,
            pnl_pct=11.4,
            conviction=75,
            strategy="momentum",
        )
    )
    db_session.commit()

    response = client.get("/api/outcomes/north-star?window_days=90")
    assert response.status_code == 200
    body = response.json()
    assert body["total_trades"] == 1
    assert "big_winner_hit_rate" in body
    assert "stall_rate" in body
    assert "big_loser_rate" in body
    assert "expectancy_gbp" in body
    assert body["thresholds"]["success_min_profit_per_day_pct"] == pytest.approx(0.25)
