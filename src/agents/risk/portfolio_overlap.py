"""Candidate-vs-portfolio overlap analysis for entry-quality guardrails."""

from __future__ import annotations

from typing import Any

import numpy as np


def default_portfolio_overlap() -> dict[str, Any]:
    """Return the empty portfolio-overlap payload."""
    return {
        "avg_correlation": None,
        "max_correlation": None,
        "high_correlation_flag": False,
        "top_overlaps": [],
    }


def analyze_candidate_portfolio_overlap(
    candidate_prices: list[float],
    position_prices_by_ticker: dict[str, list[float]],
    *,
    threshold: float = 0.6,
    lookback_days: int = 60,
    min_history_days: int = 20,
    top_n: int = 2,
) -> dict[str, Any]:
    """Compute candidate correlation against currently held positions."""
    result = default_portfolio_overlap()
    candidate_returns = _returns(candidate_prices, lookback_days=lookback_days)
    if len(candidate_returns) < min_history_days or not position_prices_by_ticker:
        return result

    overlaps: list[dict[str, Any]] = []
    coefficients: list[float] = []

    for ticker, price_history in position_prices_by_ticker.items():
        other_returns = _returns(price_history, lookback_days=lookback_days)
        min_len = min(len(candidate_returns), len(other_returns))
        if min_len < min_history_days:
            continue

        series_a = np.array(candidate_returns[-min_len:], dtype=float)
        series_b = np.array(other_returns[-min_len:], dtype=float)
        if np.isnan(series_a).any() or np.isnan(series_b).any():
            continue

        corr = float(np.corrcoef(series_a, series_b)[0, 1])
        if corr != corr:
            continue

        coefficients.append(corr)
        overlaps.append({"ticker": ticker, "correlation": round(corr, 4)})

    if not coefficients:
        return result

    overlaps.sort(key=lambda item: item["correlation"], reverse=True)
    avg_corr = float(np.mean(coefficients))
    max_corr = float(np.max(coefficients))
    result["avg_correlation"] = round(avg_corr, 4)
    result["max_correlation"] = round(max_corr, 4)
    result["high_correlation_flag"] = avg_corr > threshold
    result["top_overlaps"] = overlaps[:top_n]
    return result


def _returns(prices: list[float], *, lookback_days: int) -> list[float]:
    if not prices:
        return []
    trimmed = [float(price) for price in prices[-lookback_days:] if price is not None]
    if len(trimmed) < 2:
        return []
    returns: list[float] = []
    for prev, current in zip(trimmed[:-1], trimmed[1:], strict=False):
        if prev == 0:
            continue
        returns.append((current - prev) / prev)
    return returns
