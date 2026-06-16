"""North-star KPIs from closed trade outcomes (pace-aligned v6 labels)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.agents.reporting.outcome_classification import (
    derive_label_3class,
    gain_per_day_pct,
)
from src.learning.spec import LabelConfig, get_effective_label_config


MIN_DISPLAY_TRADES = 30


@dataclass(frozen=True)
class NorthStarMetrics:
    window_days: int
    total_trades: int
    sufficient_data: bool
    big_winner_hit_rate: float | None
    stall_rate: float | None
    big_loser_rate: float | None
    slow_win_rate: float | None
    avg_gain_per_day_pct: float | None
    expectancy_gbp: float | None
    avg_pnl_pct: float | None
    targets: dict[str, Any]
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "total_trades": self.total_trades,
            "sufficient_data": self.sufficient_data,
            "big_winner_hit_rate": self.big_winner_hit_rate,
            "stall_rate": self.stall_rate,
            "big_loser_rate": self.big_loser_rate,
            "slow_win_rate": self.slow_win_rate,
            "avg_gain_per_day_pct": self.avg_gain_per_day_pct,
            "expectancy_gbp": self.expectancy_gbp,
            "avg_pnl_pct": self.avg_pnl_pct,
            "targets": self.targets,
            "thresholds": self.thresholds,
        }


def default_targets() -> dict[str, Any]:
    return {
        "big_winner_hit_rate_interim": 0.35,
        "big_winner_hit_rate_stretch": 0.50,
        "stall_rate_max": 0.30,
        "big_loser_rate_max": 0.20,
        "min_trades_for_display": MIN_DISPLAY_TRADES,
    }


def compute_north_star_metrics(
    outcomes: list[Any],
    *,
    window_days: int = 90,
    label_cfg: LabelConfig | None = None,
    reference_ts: datetime | None = None,
) -> NorthStarMetrics:
    """Compute rolling north-star KPIs from TradeOutcome-like rows."""
    cfg = label_cfg or get_effective_label_config()
    now = reference_ts or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    filtered: list[Any] = []
    for row in outcomes:
        sell_ts = getattr(row, "sell_timestamp", None)
        if sell_ts is None:
            continue
        if sell_ts.tzinfo is None:
            sell_ts = sell_ts.replace(tzinfo=timezone.utc)
        if sell_ts >= cutoff:
            filtered.append(row)

    n = len(filtered)
    sufficient = n >= MIN_DISPLAY_TRADES
    thresholds = {
        "success_min_profit_per_day_pct": cfg.success_min_profit_per_day_pct,
        "stall_min_gain_per_day_pct": cfg.stall_min_gain_per_day_pct,
    }

    if n == 0:
        return NorthStarMetrics(
            window_days=window_days,
            total_trades=0,
            sufficient_data=False,
            big_winner_hit_rate=None,
            stall_rate=None,
            big_loser_rate=None,
            slow_win_rate=None,
            avg_gain_per_day_pct=None,
            expectancy_gbp=None,
            avg_pnl_pct=None,
            targets=default_targets(),
            thresholds=thresholds,
        )

    labels: list[str] = []
    gain_days: list[float] = []
    pnl_gbps: list[float] = []
    pnl_pcts: list[float] = []
    slow_wins = 0
    wins = 0

    for row in filtered:
        pnl_pct = float(getattr(row, "pnl_pct", 0.0) or 0.0)
        holding = float(getattr(row, "holding_days", 0.0) or 0.0)
        pnl_gbp = float(getattr(row, "pnl_gbp", 0.0) or 0.0)
        label = derive_label_3class(
            pnl_pct=pnl_pct,
            holding_days=holding,
            exit_reason=None,
            label_cfg=cfg,
        )
        labels.append(label)
        gain_days.append(gain_per_day_pct(pnl_pct, holding))
        pnl_gbps.append(pnl_gbp)
        pnl_pcts.append(pnl_pct)
        if pnl_gbp > 0:
            wins += 1
            if label == "stall":
                slow_wins += 1

    bw = labels.count("big_winner") / n
    st = labels.count("stall") / n
    bl = labels.count("big_loser") / n
    slow_win = (slow_wins / wins) if wins else None

    return NorthStarMetrics(
        window_days=window_days,
        total_trades=n,
        sufficient_data=sufficient,
        big_winner_hit_rate=round(bw, 4),
        stall_rate=round(st, 4),
        big_loser_rate=round(bl, 4),
        slow_win_rate=round(slow_win, 4) if slow_win is not None else None,
        avg_gain_per_day_pct=round(sum(gain_days) / n, 4),
        expectancy_gbp=round(sum(pnl_gbps) / n, 2),
        avg_pnl_pct=round(sum(pnl_pcts) / n, 2),
        targets=default_targets(),
        thresholds=thresholds,
    )
