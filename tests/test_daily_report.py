"""Tests for daily report generation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.daily_report import (
    _build_daily_md,
    _get_latest_snapshot,
    _get_trades,
    generate_daily_report,
)
from src.data.models import Base, Order, PortfolioSnapshot


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
def mock_get_session(db_session):
    with patch("src.agents.reporting.daily_report.get_session", return_value=db_session):
        yield


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


# --- _get_latest_snapshot ---


def test_get_latest_snapshot_empty_db():
    result = _get_latest_snapshot(datetime.now(timezone.utc))
    assert result == {}


def test_get_latest_snapshot_returns_most_recent(db_session):
    old_ts = _now() - timedelta(hours=6)
    recent_ts = _now() - timedelta(hours=1)

    db_session.add(PortfolioSnapshot(
        timestamp=old_ts, total_value_gbp=9000.0, cash_gbp=1000.0,
        invested_gbp=8000.0, pnl_gbp=0.0, pnl_pct=0.0,
        num_positions=3, state="ACTIVE",
    ))
    db_session.add(PortfolioSnapshot(
        timestamp=recent_ts, total_value_gbp=10500.0, cash_gbp=1500.0,
        invested_gbp=9000.0, pnl_gbp=500.0, pnl_pct=5.0,
        num_positions=5, state="ACTIVE",
    ))
    db_session.commit()

    result = _get_latest_snapshot(_now())
    assert result["total_value"] == 10500.0
    assert result["num_positions"] == 5


# --- _get_trades ---


def test_get_trades_filters_by_date(db_session):
    today = _now()
    day_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    # Today's trade
    db_session.add(Order(
        timestamp=today, ticker="AAPL_US_EQ", action="BUY",
        order_type="market", quantity=5.0, price=150.0, value_gbp=750.0,
        status="filled", strategy="momentum", conviction=8,
    ))
    # Yesterday's trade — should be excluded
    db_session.add(Order(
        timestamp=today - timedelta(days=1), ticker="MSFT_US_EQ", action="SELL",
        order_type="market", quantity=-3.0, price=300.0, value_gbp=900.0,
        status="filled", strategy="factor",
    ))
    db_session.commit()

    trades = _get_trades(day_start, day_end)
    assert len(trades) == 1
    assert trades[0]["ticker"] == "AAPL_US_EQ"


# --- _build_daily_md ---


def test_build_daily_md_with_snapshot():
    snapshot = {
        "total_value": 10000.0, "cash": 2000.0, "invested": 8000.0,
        "pnl_pct": 5.0, "alpha_pct": 1.5, "num_positions": 4,
        "state": "ACTIVE",
    }
    md = _build_daily_md(_now(), snapshot, [], {"total": 0.5, "anthropic": 0.3})
    assert "# Daily Report" in md
    assert "£10,000.00" in md
    assert "5 positions" not in md  # num_positions = 4
    assert "+5.00%" in md
    assert "+1.50%" in md
    assert "ACTIVE" in md


def test_build_daily_md_no_data():
    md = _build_daily_md(_now(), {}, [], {"total": 0})
    assert "*No snapshot available*" in md
    assert "*No trades today*" in md


# --- generate_daily_report (integration) ---


def test_generate_daily_report_writes_file(db_session, tmp_path):
    with patch("src.agents.reporting.daily_report._DAILY_DIR", tmp_path), \
         patch("src.agents.reporting.daily_report.get_cost_summary", return_value={"total": 0.0}):
        path = generate_daily_report(_now())
        assert tmp_path.name in path or "daily" in path
        content = open(path).read()
        assert "# Daily Report" in content
