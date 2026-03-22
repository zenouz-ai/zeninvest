"""Tests for US-3.1 risk-parity sizing."""

from __future__ import annotations

from src.agents.risk.risk_parity import RiskParitySizer


def _close_series(start: float, swing: float, periods: int = 80) -> list[float]:
    prices = [start]
    for idx in range(periods):
        direction = 1 if idx % 2 == 0 else -1
        prices.append(round(prices[-1] * (1 + direction * swing), 6))
    return prices


def test_low_vol_gets_larger_target_than_high_vol(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "max_single_stock_pct", 80.0)
    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 1.0)
    monkeypatch.setitem(sizer.settings._config["trading"], "cash_floor_pct", 0.0)

    results = sizer.size_buys(
        approved_buys=[
            {"ticker": "LOW_US_EQ", "target_allocation_pct": 10.0},
            {"ticker": "HIGH_US_EQ", "target_allocation_pct": 10.0},
        ],
        current_allocations={},
        close_prices_by_ticker={
            "LOW_US_EQ": _close_series(100.0, 0.003),
            "HIGH_US_EQ": _close_series(100.0, 0.03),
        },
        sell_tickers=set(),
        cash_pct=100.0,
    )

    assert results["LOW_US_EQ"].risk_parity_target_pct > results["HIGH_US_EQ"].risk_parity_target_pct
    assert results["LOW_US_EQ"].applied is True
    assert results["HIGH_US_EQ"].applied is True


def test_configurable_lookback_changes_realized_vol(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "max_single_stock_pct", 80.0)
    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 1.0)
    monkeypatch.setitem(sizer.settings._config["trading"], "cash_floor_pct", 0.0)

    prices = _close_series(100.0, 0.03, periods=30) + _close_series(120.0, 0.002, periods=50)

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_lookback_days", 20)
    short_lookback = sizer.size_buys(
        approved_buys=[{"ticker": "SHIFT_US_EQ", "target_allocation_pct": 10.0}],
        current_allocations={},
        close_prices_by_ticker={"SHIFT_US_EQ": prices},
        sell_tickers=set(),
        cash_pct=100.0,
    )["SHIFT_US_EQ"].trailing_vol_pct

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_lookback_days", 60)
    long_lookback = sizer.size_buys(
        approved_buys=[{"ticker": "SHIFT_US_EQ", "target_allocation_pct": 10.0}],
        current_allocations={},
        close_prices_by_ticker={"SHIFT_US_EQ": prices},
        sell_tickers=set(),
        cash_pct=100.0,
    )["SHIFT_US_EQ"].trailing_vol_pct

    assert short_lookback is not None
    assert long_lookback is not None
    assert short_lookback != long_lookback


def test_vol_floor_prevents_oversized_allocation(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "max_single_stock_pct", 100.0)
    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 1.0)
    monkeypatch.setitem(sizer.settings._config["trading"], "cash_floor_pct", 0.0)

    prices = {
        "ULTRA_LOW_US_EQ": _close_series(100.0, 0.00005),
        "NORMAL_US_EQ": _close_series(100.0, 0.01),
    }

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_vol_floor", 0.0001)
    loose_floor = sizer.size_buys(
        approved_buys=[
            {"ticker": "ULTRA_LOW_US_EQ", "target_allocation_pct": 10.0},
            {"ticker": "NORMAL_US_EQ", "target_allocation_pct": 10.0},
        ],
        current_allocations={},
        close_prices_by_ticker=prices,
        sell_tickers=set(),
        cash_pct=100.0,
    )["ULTRA_LOW_US_EQ"].risk_parity_target_pct

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_vol_floor", 0.20)
    tight_floor = sizer.size_buys(
        approved_buys=[
            {"ticker": "ULTRA_LOW_US_EQ", "target_allocation_pct": 10.0},
            {"ticker": "NORMAL_US_EQ", "target_allocation_pct": 10.0},
        ],
        current_allocations={},
        close_prices_by_ticker=prices,
        sell_tickers=set(),
        cash_pct=100.0,
    )["ULTRA_LOW_US_EQ"].risk_parity_target_pct

    assert tight_floor < loose_floor


def test_insufficient_history_falls_back_to_claude_target(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_lookback_days", 60)

    result = sizer.size_buys(
        approved_buys=[{"ticker": "SHORT_US_EQ", "target_allocation_pct": 8.0}],
        current_allocations={},
        close_prices_by_ticker={"SHORT_US_EQ": _close_series(100.0, 0.01, periods=20)},
        sell_tickers=set(),
        cash_pct=100.0,
    )["SHORT_US_EQ"]

    assert result.risk_parity_target_pct == 8.0
    assert result.applied is False
    assert result.sizing_reason == "fallback_missing_history"


def test_target_vol_scaler_shrinks_buy_sleeve_when_binding(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "max_single_stock_pct", 100.0)
    monkeypatch.setitem(sizer.settings._config["trading"], "cash_floor_pct", 0.0)

    common_kwargs = dict(
        approved_buys=[
            {"ticker": "LOW_US_EQ", "target_allocation_pct": 10.0},
            {"ticker": "HIGH_US_EQ", "target_allocation_pct": 10.0},
        ],
        current_allocations={"FIXED_US_EQ": 60.0},
        close_prices_by_ticker={
            "FIXED_US_EQ": _close_series(100.0, 0.03),
            "LOW_US_EQ": _close_series(100.0, 0.003),
            "HIGH_US_EQ": _close_series(100.0, 0.02),
        },
        sell_tickers=set(),
        cash_pct=100.0,
    )

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 1.0)
    wide_budget = sizer.size_buys(**common_kwargs)

    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 0.05)
    tight_budget = sizer.size_buys(**common_kwargs)

    assert tight_budget["LOW_US_EQ"].risk_parity_target_pct < wide_budget["LOW_US_EQ"].risk_parity_target_pct
    assert tight_budget["HIGH_US_EQ"].risk_parity_target_pct < wide_budget["HIGH_US_EQ"].risk_parity_target_pct


def test_existing_holding_above_target_is_filtered(monkeypatch):
    sizer = RiskParitySizer()
    monkeypatch.setitem(sizer.settings._config["risk"], "max_single_stock_pct", 100.0)
    monkeypatch.setitem(sizer.settings._config["risk"], "risk_parity_target_vol", 1.0)
    monkeypatch.setitem(sizer.settings._config["trading"], "cash_floor_pct", 0.0)

    result = sizer.size_buys(
        approved_buys=[
            {"ticker": "HELD_US_EQ", "target_allocation_pct": 10.0},
            {"ticker": "LOW_US_EQ", "target_allocation_pct": 10.0},
        ],
        current_allocations={"HELD_US_EQ": 60.0},
        close_prices_by_ticker={
            "HELD_US_EQ": _close_series(100.0, 0.03),
            "LOW_US_EQ": _close_series(100.0, 0.003),
        },
        sell_tickers=set(),
        cash_pct=100.0,
    )["HELD_US_EQ"]

    assert result.applied is False
    assert result.sizing_reason == "already_at_or_above_target"
