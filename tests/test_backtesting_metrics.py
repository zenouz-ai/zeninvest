"""Tests for backtest metrics: Sharpe, Sortino, drawdown, hit rate."""

from datetime import datetime

import pytest

from src.backtesting.metrics import compute_metrics


def test_compute_metrics_insufficient_data() -> None:
    out = compute_metrics([], [])
    assert out["sharpe"] is None
    assert out["num_trades"] == 0

    out = compute_metrics([(datetime(2024, 1, 1), 10000.0)], [])
    assert out["num_trades"] == 0


def test_compute_metrics_return_series() -> None:
    # Equity curve: 101 days, slight drift
    from datetime import timedelta
    base = 10000.0
    curve = []
    d = datetime(2024, 1, 1)
    for i in range(101):
        curve.append((d, base + i * 5))
        d += timedelta(days=1)
    trades = [{"value": 100, "pnl_gbp": 10}, {"value": 100, "pnl_gbp": -5}]
    out = compute_metrics(curve, trades)
    assert out["sharpe"] is not None
    assert out["max_drawdown_pct"] is not None
    assert out["num_trades"] == 2
    assert out["hit_rate_pct"] == 50.0
