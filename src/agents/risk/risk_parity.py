"""Risk-parity sizing for BUY decisions."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("risk_parity")


@dataclass
class RiskParitySizing:
    """Sizing output for a single BUY ticker."""

    ticker: str
    claude_target_pct: float
    risk_parity_target_pct: float
    trailing_vol_pct: float | None
    applied: bool
    sizing_reason: str


class RiskParitySizer:
    """Compute BUY target allocations from inverse volatility."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @staticmethod
    def compute_annualized_volatility(close_prices: list[float], lookback_days: int) -> float | None:
        """Compute annualized realized volatility from close prices."""
        if len(close_prices) < lookback_days + 1:
            return None
        window = np.array(close_prices[-(lookback_days + 1):], dtype=float)
        if np.any(window <= 0):
            return None
        returns = np.diff(window) / window[:-1]
        if len(returns) < lookback_days:
            return None
        vol = float(np.std(returns, ddof=1) * sqrt(252))
        if np.isnan(vol) or np.isinf(vol):
            return None
        return vol

    @staticmethod
    def _risk_load(weights_pct: dict[str, float], vols: dict[str, float]) -> float:
        """Approximate portfolio volatility from weighted vols, assuming zero correlation."""
        total = sum(
            ((float(weight_pct) / 100.0) * float(vols[ticker])) ** 2
            for ticker, weight_pct in weights_pct.items()
            if ticker in vols and weight_pct > 0
        )
        return float(sqrt(max(0.0, total)))

    def size_buys(
        self,
        *,
        approved_buys: list[dict],
        current_allocations: dict[str, float],
        close_prices_by_ticker: dict[str, list[float]],
        sell_tickers: set[str],
        cash_pct: float,
    ) -> dict[str, RiskParitySizing]:
        """Return risk-parity sizing decisions keyed by ticker."""
        lookback = self.settings.risk_parity_lookback_days
        vol_floor = self.settings.risk_parity_vol_floor
        max_single = self.settings.max_single_stock_pct
        deployable_cash_pct = max(0.0, cash_pct - self.settings.cash_floor_pct)

        fixed_holdings = {
            ticker: alloc
            for ticker, alloc in current_allocations.items()
            if ticker not in sell_tickers and alloc > 0
        }
        universe = set(fixed_holdings)
        universe.update(str(item.get("ticker", "")).strip().upper() for item in approved_buys if item.get("ticker"))

        vols: dict[str, float] = {}
        for ticker in universe:
            vol = self.compute_annualized_volatility(close_prices_by_ticker.get(ticker, []), lookback)
            if vol is not None:
                vols[ticker] = max(vol, vol_floor)

        if not approved_buys:
            return {}

        inverse_weights = {ticker: 1.0 / vols[ticker] for ticker in universe if ticker in vols}
        total_inverse = sum(inverse_weights.values())

        fixed_risk_load = self._risk_load(fixed_holdings, vols)
        candidate_targets: dict[str, float] = {}
        fallback_targets: dict[str, float] = {}

        for item in approved_buys:
            ticker = str(item.get("ticker", "")).strip().upper()
            claude_target = float(item.get("claude_target_allocation_pct", item.get("target_allocation_pct", 0.0)) or 0.0)
            if ticker not in vols or total_inverse <= 0:
                fallback_targets[ticker] = min(claude_target, max_single)
                continue
            ideal_total = (inverse_weights[ticker] / total_inverse) * 100.0
            candidate_targets[ticker] = min(ideal_total, max_single)

        increments = {
            ticker: max(0.0, target_pct - fixed_holdings.get(ticker, 0.0))
            for ticker, target_pct in candidate_targets.items()
        }
        positive_increments = {ticker: inc for ticker, inc in increments.items() if inc > 0}

        total_increment_pct = sum(positive_increments.values())
        cash_scale = min(1.0, deployable_cash_pct / total_increment_pct) if total_increment_pct > 0 else 1.0

        proposed_buy_weights = {ticker: positive_increments[ticker] * cash_scale for ticker in positive_increments}
        buy_risk_load = self._risk_load(proposed_buy_weights, vols)
        target_vol = self.settings.risk_parity_target_vol
        remaining_risk_budget = max(target_vol - fixed_risk_load, 0.0)
        risk_scale = min(1.0, remaining_risk_budget / buy_risk_load) if buy_risk_load > 0 else 1.0

        results: dict[str, RiskParitySizing] = {}
        for item in approved_buys:
            ticker = str(item.get("ticker", "")).strip().upper()
            claude_target = float(item.get("claude_target_allocation_pct", item.get("target_allocation_pct", 0.0)) or 0.0)
            current_alloc = fixed_holdings.get(ticker, 0.0)
            if ticker in fallback_targets:
                results[ticker] = RiskParitySizing(
                    ticker=ticker,
                    claude_target_pct=claude_target,
                    risk_parity_target_pct=fallback_targets[ticker],
                    trailing_vol_pct=round(vols[ticker] * 100.0, 4) if ticker in vols else None,
                    applied=False,
                    sizing_reason="fallback_missing_history",
                )
                continue

            target_total = candidate_targets.get(ticker, current_alloc)
            scaled_increment = max(0.0, (target_total - current_alloc) * cash_scale * risk_scale)
            adjusted_total = min(max_single, current_alloc + scaled_increment)

            if adjusted_total <= current_alloc + 1e-6:
                reason = "already_at_or_above_target"
            elif cash_scale < 1.0 and risk_scale < 1.0:
                reason = "scaled_by_cash_and_target_vol"
            elif cash_scale < 1.0:
                reason = "scaled_by_cash_budget"
            elif risk_scale < 1.0:
                reason = "scaled_by_target_vol"
            else:
                reason = "inverse_vol_target"

            results[ticker] = RiskParitySizing(
                ticker=ticker,
                claude_target_pct=claude_target,
                risk_parity_target_pct=round(adjusted_total, 4),
                trailing_vol_pct=round(vols[ticker] * 100.0, 4),
                applied=adjusted_total > current_alloc + 1e-6,
                sizing_reason=reason,
            )

        return results
