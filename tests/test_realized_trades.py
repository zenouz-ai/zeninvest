"""Tests for realized trade eligibility helpers."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.agents.reporting.realized_trades import (
    count_realized_trade_outcomes,
    is_realized_entry_order,
    is_realized_exit_order,
    realized_trade_outcomes_query,
)
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


def test_is_realized_exit_order_requires_filled_status() -> None:
    assert is_realized_exit_order(Order(action="SELL", status="filled"))
    assert not is_realized_exit_order(Order(action="SELL", status="dry_run", order_type="stop"))
    assert not is_realized_exit_order(Order(action="SELL", status="pending", order_type="stop"))


def test_is_realized_entry_order_requires_filled_status() -> None:
    assert is_realized_entry_order(Order(action="BUY", status="filled"))
    assert not is_realized_entry_order(Order(action="BUY", status="dry_run"))


def test_realized_trade_outcomes_query_excludes_simulated_pairs(db_session) -> None:
    buy = Order(
        timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ticker="AAPL_US_EQ",
        action="BUY",
        order_type="market",
        quantity=1.0,
        value_gbp=100.0,
        status="filled",
    )
    sell = Order(
        timestamp=datetime(2026, 6, 2, tzinfo=timezone.utc),
        ticker="AAPL_US_EQ",
        action="SELL",
        order_type="market",
        quantity=-1.0,
        value_gbp=110.0,
        status="filled",
    )
    dry_buy = Order(
        timestamp=datetime(2026, 6, 14, tzinfo=timezone.utc),
        ticker="GEF/B_US_EQ",
        action="BUY",
        order_type="market",
        quantity=4.0,
        value_gbp=286.0,
        status="dry_run",
    )
    dry_stop = Order(
        timestamp=datetime(2026, 6, 14, tzinfo=timezone.utc),
        ticker="GEF/B_US_EQ",
        action="SELL",
        order_type="stop",
        quantity=-4.0,
        value_gbp=253.0,
        status="dry_run",
    )
    db_session.add_all([buy, sell, dry_buy, dry_stop])
    db_session.flush()
    db_session.add_all(
        [
            TradeOutcome(
                buy_order_id=buy.id,
                sell_order_id=sell.id,
                ticker="AAPL_US_EQ",
                sell_timestamp=sell.timestamp,
                buy_value_gbp=100.0,
                sell_value_gbp=110.0,
                pnl_gbp=10.0,
                pnl_pct=10.0,
            ),
            TradeOutcome(
                buy_order_id=dry_buy.id,
                sell_order_id=dry_stop.id,
                ticker="GEF/B_US_EQ",
                sell_timestamp=dry_stop.timestamp,
                buy_value_gbp=286.0,
                sell_value_gbp=253.0,
                pnl_gbp=-33.0,
                pnl_pct=-11.0,
            ),
        ]
    )
    db_session.commit()

    rows = realized_trade_outcomes_query(db_session).all()
    assert len(rows) == 1
    assert rows[0].ticker == "AAPL_US_EQ"
    assert count_realized_trade_outcomes(db_session) == 1
