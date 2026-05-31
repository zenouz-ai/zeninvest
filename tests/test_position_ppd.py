"""Tests for profit-per-day-held (PPD) enrichment and snapshot persistence.

The orchestrator stamps `held_hours`, `held_days`, and `profit_per_day_pct`
onto every position that lands in `PortfolioSnapshot.positions_json`. This
gives the dashboard a PPD column and creates a historical dataset
(one row per ticker per snapshot) that future ML stages can use to
promote high-PPD setups and demote stagnating ones.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, Order, PortfolioSnapshot
from src.orchestrator.main import Orchestrator


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
def _patch_get_session(db_session):
    targets = [
        "src.data.database.get_session",
        "src.orchestrator.main.get_session",
        "src.orchestrator.state_machine.get_session",
        "src.agents.execution.order_manager.get_session",
        "src.agents.execution.stop_loss_manager.get_session",
        "src.agents.execution.t212_client.get_session",
        "src.agents.notifications.service.get_session",
        "src.agents.strategy.engine.get_session",
        "src.utils.cost_tracker.get_session",
    ]
    patches = []
    for target in targets:
        try:
            p = patch(target, return_value=db_session)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            continue
    yield
    for p in patches:
        p.stop()


def test_compute_profit_per_day_pct_returns_none_when_inputs_missing() -> None:
    assert Orchestrator._compute_profit_per_day_pct(None, 24.0) is None
    assert Orchestrator._compute_profit_per_day_pct(5.0, None) is None
    assert Orchestrator._compute_profit_per_day_pct(5.0, 0) is None
    assert Orchestrator._compute_profit_per_day_pct(5.0, -1) is None
    assert Orchestrator._compute_profit_per_day_pct(5.0, "nope") is None  # type: ignore[arg-type]


def test_compute_profit_per_day_pct_divides_pnl_over_days_held() -> None:
    assert Orchestrator._compute_profit_per_day_pct(10.0, 24.0 * 5) == pytest.approx(2.0)
    assert Orchestrator._compute_profit_per_day_pct(-3.0, 24.0 * 2) == pytest.approx(-1.5)
    assert Orchestrator._compute_profit_per_day_pct(0.0, 24.0 * 5) == pytest.approx(0.0)


def test_holding_metrics_annotator_adds_ppd_and_preserves_existing_fields() -> None:
    normalised = [
        {"ticker": "AAPL_US_EQ", "quantity": 10.0, "value_gbp": 1000.0, "pnl_gbp": 20.0, "pnl_pct": 2.0},
        {"ticker": "MSFT_US_EQ", "quantity": 5.0, "value_gbp": 400.0, "pnl_gbp": 0.0, "pnl_pct": 0.0},
        {"ticker": "NO_HOLD_EQ", "quantity": 1.0, "value_gbp": 50.0, "pnl_gbp": 0.0, "pnl_pct": 5.0},
    ]
    context = {
        "AAPL_US_EQ": {"held_hours": 24.0 * 10},
        "MSFT_US_EQ": {"held_hours": 24.0 * 2},
    }

    enriched = Orchestrator._annotate_normalized_positions_with_holding_metrics(
        normalised, position_context=context
    )

    enriched_by_ticker = {p["ticker"]: p for p in enriched}
    aapl = enriched_by_ticker["AAPL_US_EQ"]
    assert aapl["held_hours"] == pytest.approx(240.0)
    assert aapl["held_days"] == pytest.approx(10.0)
    assert aapl["profit_per_day_pct"] == pytest.approx(0.2)
    assert aapl["value_gbp"] == 1000.0

    msft = enriched_by_ticker["MSFT_US_EQ"]
    assert msft["profit_per_day_pct"] == pytest.approx(0.0)

    missing_ctx = enriched_by_ticker["NO_HOLD_EQ"]
    assert missing_ctx["held_hours"] is None
    assert missing_ctx["held_days"] is None
    assert missing_ctx["profit_per_day_pct"] is None


def test_save_snapshot_persists_ppd_into_positions_json(db_session) -> None:
    """A live position with a logged BUY lands in positions_json with
    held_hours / held_days / profit_per_day_pct so the dashboard and any
    downstream ML job can read PPD directly without recomputing it."""
    db_session.add(
        Order(
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10,
            price=100.0,
            value_gbp=1000.0,
            status="filled",
            timestamp=datetime.now(timezone.utc) - timedelta(days=8),
        )
    )
    db_session.commit()

    orchestrator = Orchestrator(dry_run=True)
    portfolio_data = {
        "total_value": 1050.0,
        "cash": 50.0,
        "invested": 1000.0,
        "total_return_pct": 2.0,
        "num_positions": 1,
        "positions": [
            {
                "ticker": "AAPL_US_EQ",
                "quantity": 10,
                "currentPrice": 102.0,
                "averagePrice": 100.0,
                "value_gbp": 1020.0,
                "pnl_gbp": 20.0,
            }
        ],
    }

    orchestrator._save_snapshot(portfolio_data, state="ACTIVE")

    snap = (
        db_session.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.id.desc())
        .first()
    )
    assert snap is not None
    positions = json.loads(snap.positions_json or "[]")
    assert len(positions) == 1
    pos = positions[0]
    assert pos["ticker"] == "AAPL_US_EQ"
    assert pos["held_hours"] is not None and pos["held_hours"] > 24 * 7
    assert pos["held_days"] is not None and pos["held_days"] > 7
    assert pos["profit_per_day_pct"] is not None
    assert 0.15 < pos["profit_per_day_pct"] < 0.35
