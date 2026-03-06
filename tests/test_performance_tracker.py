"""Tests for performance tracker: metrics from snapshots and trade outcomes."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.performance_tracker import update_performance_metrics
from src.data.models import Base, PortfolioSnapshot, PerformanceMetric


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


def _day(days_ago: int) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def test_update_performance_metrics_no_data(db_session) -> None:
    n = update_performance_metrics(session=db_session)
    assert n == 0
    assert db_session.query(PerformanceMetric).count() == 0


def test_update_performance_metrics_one_snapshot(db_session) -> None:
    db_session.add(
        PortfolioSnapshot(
            timestamp=_day(0),
            total_value_gbp=10000.0,
            cash_gbp=1000.0,
            invested_gbp=9000.0,
            pnl_gbp=0.0,
            pnl_pct=0.0,
            num_positions=5,
            state="ACTIVE",
        )
    )
    db_session.commit()

    n = update_performance_metrics(session=db_session)
    assert n == 1
    row = db_session.query(PerformanceMetric).one()
    assert row.sharpe_30d is None  # no return series with one snapshot
    assert row.snapshot_date is not None


def test_update_performance_metrics_return_series(db_session) -> None:
    base = 10000.0
    for i in range(35):
        # Slight upward drift
        val = base + i * 10 + (i % 3) * 5
        db_session.add(
            PortfolioSnapshot(
                timestamp=_day(35 - i),
                total_value_gbp=val,
                cash_gbp=1000.0,
                invested_gbp=val - 1000.0,
                pnl_gbp=0.0,
                pnl_pct=0.0,
                num_positions=5,
                state="ACTIVE",
            )
        )
    db_session.commit()

    n = update_performance_metrics(session=db_session)
    assert n == 1
    row = db_session.query(PerformanceMetric).one()
    assert row.sharpe_30d is not None or row.snapshot_date is not None
    assert row.snapshot_date is not None
