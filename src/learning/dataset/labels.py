"""Forward-return labels for the trade-outcome learning pipeline.

This module is the **only** place in the pipeline that is allowed to look
forward in time. Every other module must respect the leakage rule and only
read events with timestamp <= the decision row's timestamp.

Two label sources are joined:

1. Mark-to-market forward returns on the same ticker (yfinance close prices
   when available, otherwise the latest cached close from market_data_cache).
2. Realized P&L from ``trade_outcomes`` when the trade actually closed in our
   system, matched FIFO to the originating BUY order.

The 3-class target is then derived from these two signals using the
thresholds in :class:`src.learning.spec.LabelConfig`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

import pandas as pd
from sqlalchemy.orm import Session, aliased

from src.data.models import (
    MarketDataCache,
    Order,
    StopLossAdjustment,
    TradeOutcome,
)
from src.agents.reporting.realized_trades import REALIZED_ORDER_STATUS
from src.agents.reporting.outcome_classification import (
    derive_label_3class,
    infer_exit_reason,
    label_from_gain_per_day,
)
from src.learning.dataset.triple_barrier import BarrierResult, first_touch_barrier
from src.learning.spec import DatasetSpec, LabelConfig, get_default_spec
from src.utils.logger import get_logger
from src.utils.ticker_utils import t212_to_yf

logger = get_logger("learning.labels")


def _loads_json_mapping(raw: str | None) -> dict[str, object] | None:
    """Parse ``market_data_cache.data_json``. Returns ``None`` if invalid."""

    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _close_price_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass
class LabelRow:
    """Computed labels for one (cycle_id, ticker) decision row."""

    cycle_id: str
    ticker: str
    decision_ts: datetime

    # MTM forward returns per horizon, keyed as f"ret_{h}d".
    forward_returns: dict[str, float | None]

    # Per-horizon MTM extremes for drawdown veto on big_winner labels.
    forward_drawdowns: dict[str, float | None]
    forward_runups: dict[str, float | None]

    realized_pnl_pct: float | None
    realized_holding_days: float | None
    exit_reason: str | None
    actually_traded: bool
    label_3class: str
    trade_buy_timestamp: datetime | None = None
    trade_sell_timestamp: datetime | None = None
    trade_pnl_gbp: float | None = None
    trade_buy_value_gbp: float | None = None
    trade_sell_value_gbp: float | None = None
    trade_moderation_result: str | None = None
    trade_risk_result: str | None = None
    trade_strategy: str | None = None
    barrier_outcome: str | None = None
    barrier_days_to_touch: float | None = None
    barrier_mtm_max_drawdown_pct: float | None = None
    barrier_price_source: str | None = None

    def to_record(self) -> dict[str, object]:
        rec: dict[str, object] = {
            "cycle_id": self.cycle_id,
            "ticker": self.ticker,
            "decision_ts": self.decision_ts,
            "realized_pnl_pct": self.realized_pnl_pct,
            "realized_holding_days": self.realized_holding_days,
            "exit_reason": self.exit_reason,
            "actually_traded": self.actually_traded,
            "label_3class": self.label_3class,
            "trade_buy_timestamp": self.trade_buy_timestamp,
            "trade_sell_timestamp": self.trade_sell_timestamp,
            "trade_pnl_gbp": self.trade_pnl_gbp,
            "trade_buy_value_gbp": self.trade_buy_value_gbp,
            "trade_sell_value_gbp": self.trade_sell_value_gbp,
            "trade_moderation_result": self.trade_moderation_result,
            "trade_risk_result": self.trade_risk_result,
            "trade_strategy": self.trade_strategy,
            "barrier_outcome": self.barrier_outcome,
            "barrier_days_to_touch": self.barrier_days_to_touch,
            "barrier_mtm_max_drawdown_pct": self.barrier_mtm_max_drawdown_pct,
            "barrier_price_source": self.barrier_price_source,
        }
        rec.update(self.forward_returns)
        rec.update({f"mtm_max_drawdown_{k.split('_')[1]}": v for k, v in self.forward_drawdowns.items()})
        rec.update({f"mtm_max_runup_{k.split('_')[1]}": v for k, v in self.forward_runups.items()})
        return rec


class LabelComputer:
    """Compute forward labels for a batch of decision rows."""

    def __init__(
        self,
        session: Session,
        spec: DatasetSpec | None = None,
        *,
        price_fetcher=None,  # Callable[[str, datetime, int], pd.DataFrame|None]
    ) -> None:
        self.session = session
        self.spec = spec or get_default_spec()
        self.cfg: LabelConfig = self.spec.labels
        self._price_fetcher = price_fetcher
        # Per-ticker price cache: keyed by yfinance symbol. We fetch a wide
        # window once per ticker and slice it for each decision row.
        self._yf_history_cache: dict[str, pd.DataFrame | None] = {}
        self._yf_window_days = max(self.cfg.horizons_days) + 10

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, decision_rows: Iterable[Mapping[str, object]]) -> pd.DataFrame:
        """Return a label DataFrame aligned to ``decision_rows`` by (cycle_id, ticker).

        Each input row must include ``cycle_id``, ``ticker``, and ``timestamp``.
        """
        records: list[dict[str, object]] = []
        order_pairs = self._load_trade_outcomes_for_tickers(
            {str(r["ticker"]) for r in decision_rows}
        )
        stop_losses = self._load_stop_loss_exits({str(r["ticker"]) for r in decision_rows})

        for row in decision_rows:
            cycle_id = str(row["cycle_id"])
            ticker = str(row["ticker"])
            decision_ts = row["timestamp"]
            if not isinstance(decision_ts, datetime):
                continue
            forward_returns, drawdowns, runups = self._mtm_returns(ticker, decision_ts)
            prices = self._fetch_prices(ticker, decision_ts, max(self.cfg.horizons_days) + 5)
            barrier = self._barrier_from_prices(prices, decision_ts)
            realized = self._first_realized_outcome_after(
                order_pairs.get(ticker, ()),
                decision_ts,
            )
            exit_reason = self._infer_exit_reason(realized, stop_losses.get(ticker, ()))
            actually_traded = realized is not None
            label = self._derive_label(
                forward_returns=forward_returns,
                drawdowns=drawdowns,
                realized=realized,
                exit_reason=exit_reason,
                barrier=barrier,
            )
            records.append(
                LabelRow(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    decision_ts=decision_ts,
                    forward_returns=forward_returns,
                    forward_drawdowns=drawdowns,
                    forward_runups=runups,
                    realized_pnl_pct=(realized or {}).get("pnl_pct"),
                    realized_holding_days=(realized or {}).get("holding_days"),
                    exit_reason=exit_reason,
                    actually_traded=actually_traded,
                    label_3class=label,
                    trade_buy_timestamp=(realized or {}).get("buy_timestamp"),
                    trade_sell_timestamp=(realized or {}).get("sell_timestamp"),
                    trade_pnl_gbp=(realized or {}).get("pnl_gbp"),
                    trade_buy_value_gbp=(realized or {}).get("buy_value_gbp"),
                    trade_sell_value_gbp=(realized or {}).get("sell_value_gbp"),
                    trade_moderation_result=(realized or {}).get("moderation_result"),
                    trade_risk_result=(realized or {}).get("risk_result"),
                    trade_strategy=(realized or {}).get("strategy"),
                    barrier_outcome=barrier.outcome if barrier else None,
                    barrier_days_to_touch=barrier.days_to_touch if barrier else None,
                    barrier_mtm_max_drawdown_pct=barrier.mtm_max_drawdown_pct if barrier else None,
                    barrier_price_source=barrier.price_source if barrier else None,
                ).to_record()
            )
        if not records:
            return pd.DataFrame(columns=["cycle_id", "ticker", "decision_ts", "label_3class"])
        return pd.DataFrame.from_records(records)

    # ------------------------------------------------------------------
    # Forward returns
    # ------------------------------------------------------------------

    def _mtm_returns(
        self,
        ticker: str,
        decision_ts: datetime,
    ) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
        horizons = self.cfg.horizons_days
        max_horizon = max(horizons)
        prices = self._fetch_prices(ticker, decision_ts, max_horizon + 5)
        forward: dict[str, float | None] = {f"ret_{h}d": None for h in horizons}
        dd: dict[str, float | None] = {f"ret_{h}d": None for h in horizons}
        ru: dict[str, float | None] = {f"ret_{h}d": None for h in horizons}
        if prices is None or prices.empty:
            return forward, dd, ru

        prices = prices.sort_values("date").reset_index(drop=True)
        # Anchor price = the last close at or before the decision timestamp.
        anchor_idx = prices.index[prices["date"] <= decision_ts]
        if len(anchor_idx) == 0:
            return forward, dd, ru
        anchor_pos = int(anchor_idx[-1])
        anchor_price = float(prices.at[anchor_pos, "close"])
        if anchor_price <= 0 or math.isnan(anchor_price):
            return forward, dd, ru

        future = prices.iloc[anchor_pos + 1 :].copy()
        if future.empty:
            return forward, dd, ru
        future["days_after"] = (future["date"] - decision_ts).dt.total_seconds() / 86400.0
        future["ret_pct"] = (future["close"] - anchor_price) / anchor_price * 100.0

        for h in horizons:
            window = future[future["days_after"] <= h]
            if window.empty:
                continue
            last_row = window.iloc[-1]
            forward[f"ret_{h}d"] = float(last_row["ret_pct"])
            dd[f"ret_{h}d"] = float(window["ret_pct"].min())
            ru[f"ret_{h}d"] = float(window["ret_pct"].max())
        return forward, dd, ru

    def _fetch_prices(self, ticker: str, decision_ts: datetime, max_days: int) -> pd.DataFrame | None:
        """Return a DataFrame with columns date, close for the lookahead window.

        Uses the injected ``price_fetcher`` if provided (testable), else falls
        back to ``yfinance`` and finally to the latest ``market_data_cache`` row.
        """
        if self._price_fetcher is not None:
            try:
                return self._price_fetcher(ticker, decision_ts, max_days)
            except Exception:
                logger.debug("price_fetcher failed for %s", ticker, exc_info=True)

        # Try yfinance with per-ticker caching to avoid repeated fetches.
        try:
            yf_symbol = t212_to_yf(ticker)
        except Exception:
            yf_symbol = None
        if yf_symbol:
            df = self._fetch_yf_history_cached(yf_symbol, ticker)
            if df is not None and not df.empty:
                # Slice to the requested window.
                lower = decision_ts - timedelta(days=2)
                upper = decision_ts + timedelta(days=max_days + 5)
                mask = (df["date"] >= lower) & (df["date"] <= upper)
                window = df.loc[mask].copy()
                if not window.empty:
                    return window

        # Fallback: market_data_cache.
        cache_rows = (
            self.session.query(MarketDataCache)
            .filter(
                MarketDataCache.ticker == ticker,
                MarketDataCache.data_type == "ohlcv",
                MarketDataCache.timestamp >= decision_ts - timedelta(days=2),
                MarketDataCache.timestamp <= decision_ts + timedelta(days=max_days + 5),
            )
            .order_by(MarketDataCache.timestamp.asc())
            .all()
        )
        if not cache_rows:
            return None
        data = []
        for row in cache_rows:
            payload = _loads_json_mapping(row.data_json if isinstance(row.data_json, str) else None)
            if payload is None:
                continue
            close = payload.get("close") or payload.get("last_close")
            close_f = _close_price_float(close) if close is not None else None
            if close_f is None:
                continue
            high = payload.get("high")
            low = payload.get("low")
            high_f = _close_price_float(high) if high is not None else close_f
            low_f = _close_price_float(low) if low is not None else close_f
            data.append(
                {
                    "date": row.timestamp,
                    "close": close_f,
                    "high": high_f,
                    "low": low_f,
                }
            )
        if not data:
            return None
        return pd.DataFrame.from_records(data)

    def _fetch_yf_history_cached(self, yf_symbol: str, t212_ticker: str) -> pd.DataFrame | None:
        if yf_symbol in self._yf_history_cache:
            return self._yf_history_cache[yf_symbol]
        try:  # pragma: no cover - network optional
            import yfinance as yf  # type: ignore

            ticker_obj = yf.Ticker(yf_symbol)
            # Pull the full project window once; reuse for every (ticker, ts).
            hist = ticker_obj.history(period="2y", auto_adjust=False)
            if hist is None or hist.empty:
                self._yf_history_cache[yf_symbol] = None
                return None
            df = hist.reset_index()[["Date", "Close", "High", "Low"]].copy()
            df.columns = ["date", "close", "high", "low"]
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            self._yf_history_cache[yf_symbol] = df
            return df
        except Exception:  # pragma: no cover
            logger.debug("yfinance unavailable for %s (%s)", yf_symbol, t212_ticker)
            self._yf_history_cache[yf_symbol] = None
            return None

    def _barrier_from_prices(
        self,
        prices: pd.DataFrame | None,
        decision_ts: datetime,
    ) -> BarrierResult | None:
        if prices is None or prices.empty:
            return None
        sorted_prices = prices.sort_values("date").reset_index(drop=True)
        anchor_mask = sorted_prices["date"] <= decision_ts
        if not anchor_mask.any():
            return None
        anchor_pos = int(anchor_mask[anchor_mask].index[-1])
        anchor_price = float(sorted_prices.at[anchor_pos, "close"])
        if anchor_price <= 0 or math.isnan(anchor_price):
            return None
        return first_touch_barrier(
            sorted_prices,
            decision_ts,
            anchor_price,
            upper_pct=self.cfg.barrier_upper_pct,
            lower_pct=self.cfg.barrier_lower_pct,
            vertical_days=self.cfg.barrier_vertical_days,
        )

    # ------------------------------------------------------------------
    # Realized P&L join
    # ------------------------------------------------------------------

    def _load_trade_outcomes_for_tickers(self, tickers: set[str]) -> dict[str, list[dict]]:
        if not tickers:
            return {}
        buy_order = aliased(Order)
        sell_order = aliased(Order)
        rows = (
            self.session.query(TradeOutcome, buy_order, sell_order)
            .join(buy_order, buy_order.id == TradeOutcome.buy_order_id)
            .join(sell_order, sell_order.id == TradeOutcome.sell_order_id)
            .filter(TradeOutcome.ticker.in_(tickers))
            .filter(
                buy_order.status == REALIZED_ORDER_STATUS,
                sell_order.status == REALIZED_ORDER_STATUS,
            )
            .all()
        )
        out: dict[str, list[dict]] = {}
        for outcome, buy_row, sell_row in rows:
            entry = {
                "buy_timestamp": outcome.buy_timestamp,
                "sell_timestamp": outcome.sell_timestamp,
                "pnl_pct": float(outcome.pnl_pct or 0.0),
                "pnl_gbp": float(outcome.pnl_gbp or 0.0),
                "holding_days": float(outcome.holding_days or 0.0),
                "buy_order_id": outcome.buy_order_id,
                "sell_order_id": outcome.sell_order_id,
                "buy_value_gbp": float(outcome.buy_value_gbp or 0.0),
                "sell_value_gbp": float(outcome.sell_value_gbp or 0.0),
                "moderation_result": outcome.moderation_result,
                "risk_result": outcome.risk_result,
                "strategy": outcome.strategy,
                "buy_warning_note": getattr(buy_row, "warning_note", None),
                "sell_order_type": sell_row.order_type,
            }
            out.setdefault(outcome.ticker, []).append(entry)
        for ticker in out:
            out[ticker].sort(key=lambda r: r["buy_timestamp"] or datetime.min)
        return out

    def _load_stop_loss_exits(self, tickers: set[str]) -> dict[str, list[dict]]:
        if not tickers:
            return {}
        rows = (
            self.session.query(StopLossAdjustment)
            .filter(StopLossAdjustment.ticker.in_(tickers))
            .order_by(StopLossAdjustment.timestamp.asc())
            .all()
        )
        out: dict[str, list[dict]] = {}
        for row in rows:
            out.setdefault(row.ticker, []).append(
                {
                    "timestamp": row.timestamp,
                    "trigger_reason": row.trigger_reason,
                    "status": row.status,
                }
            )
        return out

    def _first_realized_outcome_after(
        self,
        outcomes: list[dict],
        decision_ts: datetime,
    ) -> dict | None:
        for outcome in outcomes:
            buy_ts = outcome.get("buy_timestamp")
            if buy_ts is None:
                continue
            # The BUY must be at or after the decision (we only keep one match per decision).
            if buy_ts >= decision_ts - timedelta(hours=1):
                return outcome
        return None

    def _infer_exit_reason(self, realized: dict | None, stops: list[dict]) -> str | None:
        if not realized:
            return None
        sell_ts = realized.get("sell_timestamp")
        if sell_ts is None:
            return None
        return infer_exit_reason(
            sell_timestamp=sell_ts,
            buy_warning_note=realized.get("buy_warning_note"),
            stop_adjustments=stops,
            pnl_pct=realized.get("pnl_pct"),
            sell_order_type=realized.get("sell_order_type"),
        )

    # ------------------------------------------------------------------
    # Label derivation
    # ------------------------------------------------------------------

    def _derive_label(
        self,
        *,
        forward_returns: dict[str, float | None],
        drawdowns: dict[str, float | None],
        realized: dict | None,
        exit_reason: str | None,
        barrier: BarrierResult | None = None,
    ) -> str:
        max_h = max(self.cfg.horizons_days)
        ret_key = f"ret_{max_h}d"
        ret_long = forward_returns.get(ret_key)
        ret_10 = forward_returns.get("ret_10d")
        drawdown_long = drawdowns.get(ret_key)
        realized_pct = (realized or {}).get("pnl_pct")
        holding_days = (realized or {}).get("holding_days")

        if realized is not None and realized_pct is not None and realized.get("sell_timestamp") is not None:
            return derive_label_3class(
                pnl_pct=realized_pct,
                holding_days=holding_days,
                exit_reason=exit_reason,
                label_cfg=self.cfg,
            )

        # Path-based triple barrier for open / MTM rows (Phase B).
        if barrier is not None and barrier.outcome not in {"unknown", "none"}:
            dd = barrier.mtm_max_drawdown_pct
            if barrier.outcome == "lower":
                return "big_loser"
            if barrier.outcome == "upper":
                if dd is None or dd > self.cfg.big_winner_max_drawdown_pct:
                    return "big_winner"
                return "stall"
            if barrier.outcome == "vertical":
                end_ret = barrier.end_return_pct
                if end_ret is not None and abs(end_ret) < self.cfg.stall_abs_return_pct:
                    return "stall"
                if end_ret is not None:
                    return label_from_gain_per_day(
                        float(end_ret),
                        self.cfg.barrier_vertical_days,
                        self.cfg,
                    )
                return "stall"

        # Phase A MTM fallback when barrier unavailable.
        holding_proxy = float(max_h)
        ret = ret_long if ret_long is not None else ret_10
        if ret is not None:
            if drawdown_long is None or drawdown_long > self.cfg.big_winner_max_drawdown_pct:
                return label_from_gain_per_day(float(ret), holding_proxy, self.cfg)

        if ret_long is not None and abs(ret_long) < self.cfg.stall_abs_return_pct:
            long_held = (holding_days or 0) > self.cfg.stall_min_holding_days
            never_closed = realized is None
            if long_held or never_closed:
                return "stall"

        if ret_long is not None:
            return label_from_gain_per_day(float(ret_long), holding_proxy, self.cfg)

        return "stall"
