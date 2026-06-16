"""First-touch triple-barrier labeling on daily OHLC paths (López de Prado style)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

BarrierOutcome = Literal["upper", "lower", "vertical", "none", "unknown"]
PriceSource = Literal["ohlc", "close_only", "unknown"]


@dataclass(frozen=True)
class BarrierResult:
    outcome: BarrierOutcome
    days_to_touch: float | None
    mtm_max_drawdown_pct: float | None
    end_return_pct: float | None
    price_source: PriceSource


def first_touch_barrier(
    prices: pd.DataFrame,
    anchor_ts: datetime,
    anchor_price: float,
    *,
    upper_pct: float,
    lower_pct: float,
    vertical_days: float,
) -> BarrierResult:
    """Walk forward day-by-day; first barrier touched wins.

    ``prices`` must include ``date`` and ``close``. ``high``/``low`` used when present.
    """
    if prices is None or prices.empty or anchor_price <= 0:
        return BarrierResult("unknown", None, None, None, "unknown")

    has_ohlc = "high" in prices.columns and "low" in prices.columns
    price_source: PriceSource = "ohlc" if has_ohlc else "close_only"

    upper_level = anchor_price * (1.0 + upper_pct / 100.0)
    lower_level = anchor_price * (1.0 + lower_pct / 100.0)

    sorted_prices = prices.sort_values("date").reset_index(drop=True)
    anchor_mask = sorted_prices["date"] <= anchor_ts
    if not anchor_mask.any():
        return BarrierResult("unknown", None, None, None, price_source)
    anchor_pos = int(anchor_mask[anchor_mask].index[-1])

    future = sorted_prices.iloc[anchor_pos + 1 :].copy()
    if future.empty:
        return BarrierResult("none", None, None, None, price_source)

    future["days_after"] = (future["date"] - anchor_ts).dt.total_seconds() / 86400.0
    window = future[future["days_after"] <= vertical_days].copy()
    if window.empty:
        return BarrierResult("none", None, None, None, price_source)

    window["ret_pct"] = (window["close"] - anchor_price) / anchor_price * 100.0
    mtm_dd = float(window["ret_pct"].min())

    end_return = float(window.iloc[-1]["ret_pct"])
    days_to_touch: float | None = None
    outcome: BarrierOutcome = "vertical"

    for _, row in window.iterrows():
        days_after = float(row["days_after"])
        if has_ohlc:
            high = float(row["high"])
            low = float(row["low"])
            hit_upper = high >= upper_level
            hit_lower = low <= lower_level
        else:
            close = float(row["close"])
            hit_upper = close >= upper_level
            hit_lower = close <= lower_level

        if hit_upper and hit_lower:
            # Same bar touched both — conservative: lower wins (loss avoidance).
            return BarrierResult("lower", days_after, mtm_dd, end_return, price_source)
        if hit_lower:
            return BarrierResult("lower", days_after, mtm_dd, end_return, price_source)
        if hit_upper:
            return BarrierResult("upper", days_after, mtm_dd, end_return, price_source)

    return BarrierResult("vertical", days_to_touch, mtm_dd, end_return, price_source)
