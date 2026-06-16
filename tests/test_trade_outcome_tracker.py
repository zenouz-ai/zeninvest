"""Tests for trade outcome tracker: BUY/SELL matching and P&L."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.trade_outcome_tracker import _match_sell_to_buys, update_trade_outcomes
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


def test_recompute_trade_outcomes_rebuilds_from_wallet(db_session) -> None:
    db_session.add(
        Order(
            timestamp=_ts(5),
            ticker="WAL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10.0,
            filled_quantity=10.0,
            price=100.0,
            value_gbp=1000.0,
            status="filled",
        )
    )
    db_session.add(
        Order(
            timestamp=_ts(0),
            ticker="WAL_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-10.0,
            filled_quantity=10.0,
            price=110.0,
            value_gbp=1100.0,
            status="filled",
        )
    )
    db_session.commit()
    db_session.add(
        TradeOutcome(
            buy_order_id=1,
            sell_order_id=2,
            ticker="WAL_US_EQ",
            sell_timestamp=_ts(0),
            buy_value_gbp=1.0,
            sell_value_gbp=1.0,
            pnl_gbp=0.0,
            pnl_pct=0.0,
        )
    )
    db_session.commit()

    from src.agents.reporting.trade_outcome_tracker import recompute_trade_outcomes

    count = recompute_trade_outcomes(session=db_session)
    assert count == 1
    out = db_session.query(TradeOutcome).one()
    assert out.buy_value_gbp == 1000.0
    assert out.sell_value_gbp == 1100.0
    assert out.pnl_gbp == 100.0


def test_holding_days_mixed_naive_and_aware_timestamps_no_typeerror(db_session) -> None:
    """Regression: subtracting naive ORM timestamps from aware datetimes must not raise."""
    naive_buy = datetime(2026, 3, 1, 12, 0, 0)
    aware_sell = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)

    db_session.add(
        Order(
            timestamp=naive_buy,
            ticker="MIX_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10.0,
            price=100.0,
            value_gbp=1000.0,
            status="filled",
        )
    )
    sell = Order(
        timestamp=aware_sell,
        ticker="MIX_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-10.0,
        price=110.0,
        value_gbp=1100.0,
        status="filled",
    )
    db_session.add(sell)
    db_session.commit()
    db_session.refresh(sell)
    sell.timestamp = aware_sell

    outcome = _match_sell_to_buys(db_session, sell)
    assert outcome is not None
    assert outcome.holding_days is not None
    assert outcome.holding_days > 0


def test_dry_run_stop_placement_does_not_create_outcome(db_session) -> None:
    """Regression: deploy dry-run stop placement must not appear as a closed trade."""
    buy_ts = datetime(2026, 6, 14, 11, 39, 27, tzinfo=timezone.utc)
    stop_ts = buy_ts + timedelta(milliseconds=14)
    db_session.add(
        Order(
            timestamp=buy_ts.replace(tzinfo=None),
            ticker="GEF/B_US_EQ",
            action="BUY",
            order_type="market",
            quantity=4.0,
            price=85.12,
            value_gbp=286.57,
            status="dry_run",
            strategy="momentum",
        )
    )
    db_session.add(
        Order(
            timestamp=stop_ts.replace(tzinfo=None),
            ticker="GEF/B_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-4.0,
            price=85.12,
            stop_price=78.31,
            value_gbp=253.77,
            status="dry_run",
            strategy="momentum",
        )
    )
    db_session.commit()

    assert update_trade_outcomes(session=db_session) == 0
    assert db_session.query(TradeOutcome).count() == 0


def test_dry_run_market_round_trip_does_not_create_outcome(db_session) -> None:
    db_session.add(
        Order(
            timestamp=_ts(1),
            ticker="DRY_US_EQ",
            action="BUY",
            order_type="market",
            quantity=2.0,
            value_gbp=200.0,
            status="dry_run",
        )
    )
    db_session.add(
        Order(
            timestamp=_ts(0),
            ticker="DRY_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-2.0,
            value_gbp=210.0,
            status="dry_run",
        )
    )
    db_session.commit()

    assert update_trade_outcomes(session=db_session) == 0


def test_filled_stop_creates_outcome(db_session) -> None:
    db_session.add(
        Order(
            timestamp=_ts(5),
            ticker="STOP_US_EQ",
            action="BUY",
            order_type="market",
            quantity=5.0,
            value_gbp=500.0,
            status="filled",
        )
    )
    db_session.add(
        Order(
            timestamp=_ts(0),
            ticker="STOP_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-5.0,
            stop_price=90.0,
            value_gbp=450.0,
            status="filled",
        )
    )
    db_session.commit()

    assert update_trade_outcomes(session=db_session) == 1
    out = db_session.query(TradeOutcome).one()
    assert out.ticker == "STOP_US_EQ"
    assert out.pnl_gbp == -50.0
