"""Tests for weekly report generation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.weekly_report import (
    _build_weekly_md,
    _get_moderation_stats,
    _get_risk_events,
    _get_snapshots,
    _get_week_costs,
    _get_week_trades,
    generate_weekly_report,
)
from src.data.models import (
    Base,
    CostLog,
    ModerationLog,
    Order,
    PortfolioSnapshot,
    RiskDecision,
)


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
    with patch("src.agents.reporting.weekly_report.get_session", return_value=db_session):
        yield


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def _week_range():
    end = _now()
    start = end - timedelta(days=7)
    return start, end


# --- _get_snapshots ---


def test_get_snapshots_empty_db():
    start, end = _week_range()
    assert _get_snapshots(start, end) == []


def test_get_snapshots_returns_in_range(db_session):
    start, end = _week_range()
    mid = start + timedelta(days=3)

    db_session.add(PortfolioSnapshot(
        timestamp=mid, total_value_gbp=10000.0, cash_gbp=2000.0,
        invested_gbp=8000.0, pnl_gbp=0.0, pnl_pct=1.0,
        num_positions=3, state="ACTIVE",
    ))
    # Out of range
    db_session.add(PortfolioSnapshot(
        timestamp=start - timedelta(days=10), total_value_gbp=9000.0,
        cash_gbp=1000.0, invested_gbp=8000.0, pnl_gbp=0.0, pnl_pct=0.0,
        num_positions=2, state="ACTIVE",
    ))
    db_session.commit()

    snaps = _get_snapshots(start, end)
    assert len(snaps) == 1
    assert snaps[0]["total_value"] == 10000.0


# --- _get_week_trades ---


def test_get_week_trades_filters_correctly(db_session):
    start, end = _week_range()
    mid = start + timedelta(days=2)

    db_session.add(Order(
        timestamp=mid, ticker="AAPL_US_EQ", action="BUY",
        order_type="market", quantity=5.0, price=150.0,
        value_gbp=750.0, status="filled", strategy="momentum",
    ))
    db_session.commit()

    trades = _get_week_trades(start, end)
    assert len(trades) == 1
    assert trades[0]["ticker"] == "AAPL_US_EQ"


# --- _get_moderation_stats ---


def test_get_moderation_stats_aggregation(db_session):
    start, end = _week_range()
    mid = start + timedelta(days=3)

    for verdict, consensus in [("AGREE", "APPROVED"), ("AGREE", "APPROVED"), ("DISAGREE", "BLOCKED")]:
        db_session.add(ModerationLog(
            timestamp=mid, cycle_id="c1", ticker="AAPL_US_EQ",
            moderator="gpt-4o", verdict=verdict, consensus=consensus,
        ))
    db_session.commit()

    stats = _get_moderation_stats(start, end)
    assert stats["total_reviews"] == 3
    assert stats["agree"] == 2
    assert stats["disagree"] == 1
    assert stats["approved"] == 2
    assert stats["blocked"] == 1


# --- _get_risk_events ---


def test_get_risk_events_counts_vetoes(db_session):
    start, end = _week_range()
    mid = start + timedelta(days=4)

    db_session.add(RiskDecision(
        timestamp=mid, cycle_id="c1", ticker="AAPL_US_EQ",
        proposed_action="BUY", verdict="REJECT", reasoning="Max position exceeded",
    ))
    db_session.add(RiskDecision(
        timestamp=mid, cycle_id="c1", ticker="MSFT_US_EQ",
        proposed_action="BUY", verdict="APPROVE", reasoning="OK",
    ))
    db_session.commit()

    events = _get_risk_events(start, end)
    assert len(events) == 1  # Only non-APPROVE events
    assert events[0]["ticker"] == "AAPL_US_EQ"
    assert events[0]["verdict"] == "REJECT"


# --- _get_week_costs ---


def test_get_week_costs_by_provider(db_session):
    start, end = _week_range()
    mid = start + timedelta(days=2)

    db_session.add(CostLog(
        timestamp=mid, provider="anthropic", model="claude-sonnet",
        input_tokens=1000, output_tokens=500, cost_gbp=0.15,
    ))
    db_session.add(CostLog(
        timestamp=mid, provider="openai", model="gpt-4o",
        input_tokens=800, output_tokens=400, cost_gbp=0.10,
    ))
    db_session.commit()

    costs = _get_week_costs(start, end)
    assert costs["anthropic"] == pytest.approx(0.15)
    assert costs["openai"] == pytest.approx(0.10)
    assert costs["total"] == pytest.approx(0.25)


# --- _build_weekly_md ---


def test_build_weekly_md_all_sections():
    start, end = _week_range()
    snapshots = [
        {"timestamp": start, "total_value": 10000.0, "pnl_pct": 0.0,
         "benchmark_pnl_pct": 0.5, "alpha_pct": -0.5, "num_positions": 3, "state": "ACTIVE"},
        {"timestamp": end, "total_value": 10200.0, "pnl_pct": 2.0,
         "benchmark_pnl_pct": 1.0, "alpha_pct": 1.0, "num_positions": 4, "state": "ACTIVE"},
    ]
    trades = [{"ticker": "AAPL_US_EQ", "action": "BUY", "quantity": 5.0,
               "price": 150.0, "value_gbp": 750.0, "status": "filled",
               "strategy": "momentum", "timestamp": start + timedelta(days=1)}]
    mod_stats = {"total_reviews": 5, "agree": 4, "disagree": 1, "approved": 4, "blocked": 1}
    risk_events = []
    cost = {"total": 0.50, "anthropic": 0.30, "openai": 0.20}

    md = _build_weekly_md(start, end, 12, snapshots, trades, mod_stats, risk_events, cost)

    assert "# Weekly Report" in md
    assert "Performance" in md
    assert "Trade Statistics" in md
    assert "Moderation Panel" in md
    assert "Risk Events" in md
    assert "LLM Costs" in md
    assert "*No risk events this week*" in md


def test_build_weekly_md_no_data():
    start, end = _week_range()
    md = _build_weekly_md(start, end, 12, [], [], {}, [], {"total": 0})
    assert "*No snapshot data available*" in md
    assert "*No trades this week*" in md


# --- generate_weekly_report (integration) ---


def test_generate_weekly_report_writes_file(db_session, tmp_path):
    with patch("src.agents.reporting.weekly_report._WEEKLY_DIR", tmp_path):
        path = generate_weekly_report(_now())
        assert "weekly" in path.lower()
        content = open(path).read()
        assert "# Weekly Report" in content
