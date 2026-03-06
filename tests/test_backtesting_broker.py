"""Tests for paper broker: fills, cash, positions."""

from datetime import datetime, timezone

import pytest

from src.backtesting.broker import PaperBroker, Fill


def test_broker_initial_state() -> None:
    b = PaperBroker(initial_cash=10000.0, slippage_bps=10.0)
    assert b.cash == 10000.0
    assert b.total_equity({}) == 10000.0
    assert len(b.fills) == 0
    assert b.position("AAPL") is None


def test_broker_buy_fill() -> None:
    b = PaperBroker(initial_cash=10000.0, slippage_bps=0)
    b.submit_order("AAPL", "BUY", 10.0, datetime.now(timezone.utc))
    b.process_fills(datetime.now(timezone.utc), {"AAPL": 100.0})
    assert b.cash == 10000.0 - 10.0 * 100.0
    pos = b.position("AAPL")
    assert pos is not None
    assert pos.quantity == 10.0
    assert len(b.fills) == 1
    assert b.fills[0].side == "BUY"
    assert b.fills[0].cost_basis is None


def test_broker_sell_fill_with_cost_basis() -> None:
    from datetime import timedelta
    t1 = datetime.now(timezone.utc)
    t2 = t1 + timedelta(days=1)
    b = PaperBroker(initial_cash=10000.0, slippage_bps=0)
    b.submit_order("AAPL", "BUY", 10.0, t1)
    b.process_fills(t1, {"AAPL": 100.0})
    b.submit_order("AAPL", "SELL", 10.0, t2)
    b.process_fills(t2, {"AAPL": 110.0})
    assert "AAPL" not in b.positions
    assert len(b.fills) == 2
    sell_fill = b.fills[1]
    assert sell_fill.side == "SELL"
    assert sell_fill.cost_basis == 1000.0  # 10 * 100
    assert b.cash == 10000.0 - 1000.0 + 10.0 * 110.0
