"""Tests for triple-barrier path labeling."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.learning.dataset.triple_barrier import first_touch_barrier


def _days(start: datetime, n: int, *, step: float) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(n)]
    closes = [100.0 + i * step for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return pd.DataFrame({"date": dates, "close": closes, "high": highs, "low": lows})


def test_first_touch_upper_barrier():
    anchor = datetime(2026, 1, 1, 12, 0)
    prices = _days(anchor, 15, step=0.6)
    result = first_touch_barrier(
        prices,
        anchor,
        100.0,
        upper_pct=5.0,
        lower_pct=-7.0,
        vertical_days=12.0,
    )
    assert result.outcome == "upper"
    assert result.days_to_touch is not None
    assert result.days_to_touch <= 12.0


def test_first_touch_lower_barrier():
    anchor = datetime(2026, 1, 1, 12, 0)
    prices = _days(anchor, 15, step=-0.8)
    result = first_touch_barrier(
        prices,
        anchor,
        100.0,
        upper_pct=5.0,
        lower_pct=-7.0,
        vertical_days=12.0,
    )
    assert result.outcome == "lower"


def test_vertical_barrier_timeout_flat():
    anchor = datetime(2026, 1, 1, 12, 0)
    dates = [anchor + timedelta(days=i) for i in range(15)]
    closes = [100.0 + 0.1 * ((-1) ** i) for i in range(15)]
    prices = pd.DataFrame({"date": dates, "close": closes, "high": closes, "low": closes})
    result = first_touch_barrier(
        prices,
        anchor,
        100.0,
        upper_pct=5.0,
        lower_pct=-7.0,
        vertical_days=12.0,
    )
    assert result.outcome == "vertical"
    assert result.end_return_pct is not None
    assert abs(result.end_return_pct) < 3.0
