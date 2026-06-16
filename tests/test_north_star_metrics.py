"""Tests for north-star KPI computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.reporting.north_star_metrics import compute_north_star_metrics
from src.learning.spec import LabelConfig


class _Outcome:
    def __init__(self, *, pnl_pct: float, holding_days: float, pnl_gbp: float, sell_ts: datetime):
        self.pnl_pct = pnl_pct
        self.holding_days = holding_days
        self.pnl_gbp = pnl_gbp
        self.sell_timestamp = sell_ts


def test_north_star_metrics_counts_labels() -> None:
    now = datetime(2026, 6, 14, tzinfo=timezone.utc)
    cfg = LabelConfig(success_min_profit_per_day_pct=0.25, stall_min_gain_per_day_pct=-0.05)
    outcomes = [
        _Outcome(pnl_pct=5.0, holding_days=20.0, pnl_gbp=50.0, sell_ts=now - timedelta(days=1)),
        _Outcome(pnl_pct=2.0, holding_days=20.0, pnl_gbp=10.0, sell_ts=now - timedelta(days=2)),
        _Outcome(pnl_pct=-5.0, holding_days=10.0, pnl_gbp=-30.0, sell_ts=now - timedelta(days=3)),
    ]
    metrics = compute_north_star_metrics(outcomes, window_days=90, label_cfg=cfg, reference_ts=now)
    assert metrics.total_trades == 3
    assert metrics.big_winner_hit_rate == pytest.approx(1 / 3, rel=1e-3)
    assert metrics.stall_rate == pytest.approx(1 / 3, rel=1e-3)
    assert metrics.big_loser_rate == pytest.approx(1 / 3, rel=1e-3)
    assert metrics.expectancy_gbp == pytest.approx(10.0, rel=1e-2)
