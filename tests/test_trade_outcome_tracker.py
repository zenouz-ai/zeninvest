"""Tests for trade outcome tracker: BUY/SELL matching and P&L."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.trade_outcome_tracker import update_trade_outcomes
from src.data.models import Base, Order, TradeOutcome


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


def _ts(days_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def test_update_trade_outcomes_empty(db_session) -> None:
    n = update_trade_outcomes(session=db_session)
    assert n == 0
    assert db_session.query(TradeOutcome).count() == 0


def test_update_trade_outcomes_matches_buy_then_sell(db_session) -> None:
    db_session.add(
        Order(
            timestamp=_ts(5),
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10.0,
            price=150.0,
            value_gbp=1500.0,
            status="filled",
            strategy="momentum",
            conviction=75,
            moderation_result="APPROVED",
            risk_result="APPROVE",
        )
    )
    db_session.add(
        Order(
            timestamp=_ts(0),
            ticker="AAPL_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-10.0,
            price=160.0,
            value_gbp=1600.0,
            status="filled",
            strategy="momentum",
            conviction=75,
        )
    )
    db_session.commit()

    n = update_trade_outcomes(session=db_session)
    assert n == 1
    out = db_session.query(TradeOutcome).one()
    assert out.ticker == "AAPL_US_EQ"
    assert out.buy_value_gbp == 1500.0
    assert out.sell_value_gbp == 1600.0
    assert out.pnl_gbp == 100.0
    assert out.pnl_pct == pytest.approx(100 / 15, rel=0.01)
    assert out.conviction == 75
    assert out.strategy == "momentum"


def test_update_trade_outcomes_idempotent(db_session) -> None:
    db_session.add(
        Order(
            timestamp=_ts(5),
            ticker="MSFT_US_EQ",
            action="BUY",
            order_type="market",
            quantity=5.0,
            price=300.0,
            value_gbp=1500.0,
            status="filled",
        )
    )
    db_session.add(
        Order(
            timestamp=_ts(0),
            ticker="MSFT_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-5.0,
            price=310.0,
            value_gbp=1550.0,
            status="filled",
        )
    )
    db_session.commit()

    n1 = update_trade_outcomes(session=db_session)
    n2 = update_trade_outcomes(session=db_session)
    assert n1 == 1
    assert n2 == 0
    assert db_session.query(TradeOutcome).count() == 1
