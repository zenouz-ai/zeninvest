"""Backtest engine: replay daily bars with deterministic policy and paper broker."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtesting.broker import PaperBroker
from src.backtesting.metrics import compute_metrics
from src.backtesting.policies.deterministic_proxy import DeterministicPolicy
from src.utils.logger import get_logger

logger = get_logger("backtesting.engine")


class BacktestEngine:
    """Replay historical bars with a deterministic policy and record equity + trades."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        seed: int | None = None,
    ) -> None:
        self.config = config
        self.seed = seed or config.get("seed", 42)
        self.initial_cash = float(config.get("initial_cash", 10000.0))
        self.slippage_bps = float(config.get("slippage_bps", 10.0))
        self.max_positions = int(config.get("max_positions", 10))
        self.broker = PaperBroker(initial_cash=self.initial_cash, slippage_bps=self.slippage_bps)
        self.policy = DeterministicPolicy(
            sma_period=int(config.get("sma_period", 20)),
            max_positions=self.max_positions,
        )
        self.equity_curve: list[tuple[pd.Timestamp, float]] = []
        self.benchmark_curve: list[tuple[pd.Timestamp, float]] = []

    def run(
        self,
        bars: dict[str, pd.DataFrame],
        benchmark: pd.Series | None = None,
    ) -> dict[str, Any]:
        """Run backtest over bars. Bars keyed by ticker; each DataFrame has date, open, high, low, close, volume."""
        if not bars:
            return {"error": "No bar data", "equity_curve": [], "trades": [], "metrics": {}}

        # Align dates: union of all bar dates
        all_dates = sorted(set().union(*(set(df["date"].tolist()) for df in bars.values())))
        if len(all_dates) < 2:
            return {"error": "Insufficient bars", "equity_curve": [], "trades": [], "metrics": {}}

        # Build daily close + SMA per ticker (no lookahead: SMA at t uses close up to t)
        daily_bars: dict[pd.Timestamp, dict[str, dict[str, Any]]] = {}
        for i, date in enumerate(all_dates):
            day_bars: dict[str, dict[str, Any]] = {}
            for ticker, df in bars.items():
                hist = df[df["date"] <= date].tail(self.policy.sma_period + 5)
                if hist.empty:
                    continue
                row = hist[hist["date"] == date]
                if row.empty:
                    continue
                row = row.iloc[0]
                close = float(row["close"])
                sma = hist["close"].tail(self.policy.sma_period).mean() if len(hist) >= self.policy.sma_period else close
                day_bars[ticker] = {"close": close, "sma": sma, "open": float(row["open"])}
            if day_bars:
                daily_bars[date] = day_bars

        # Re-sort dates
        dates = sorted(daily_bars.keys())
        self.equity_curve = []
        self.benchmark_curve = []

        for idx, date in enumerate(dates):
            day_bars = daily_bars[date]
            open_prices = {t: day_bars[t]["open"] for t in day_bars}
            next_date = dates[idx + 1] if idx + 1 < len(dates) else None

            # Fill at today's open (orders submitted yesterday)
            self.broker.process_fills(date, open_prices)

            current_positions = {t for t, pos in self.broker.positions.items() if pos.quantity > 0}
            signals = self.policy.run(date, day_bars, current_positions)

            # Submit orders (fill at next open)
            for sig in signals:
                if sig.action == "SELL":
                    pos = self.broker.position(sig.ticker)
                    if pos and pos.quantity > 0 and sig.ticker in day_bars:
                        self.broker.submit_order(sig.ticker, "SELL", pos.quantity, date)
                elif sig.action == "BUY" and len(current_positions) < self.max_positions:
                    if sig.ticker in day_bars and next_date is not None:
                        alloc = self.broker.cash * 0.95 / self.max_positions * sig.weight
                        price = day_bars[sig.ticker]["close"]
                        if price > 0 and alloc >= price:
                            qty = alloc / price
                            self.broker.submit_order(sig.ticker, "BUY", qty, next_date)

            # Record equity
            prices = {t: day_bars[t]["close"] for t in day_bars}
            equity = self.broker.total_equity(prices)
            self.equity_curve.append((date, equity))
            if benchmark is not None and date in benchmark.index:
                self.benchmark_curve.append((date, float(benchmark.loc[date])))

        # Build trades from fills (pnl_gbp: for SELL = value - cost_basis from Fill)
        trades = []
        for f in self.broker.fills:
            pnl = (f.value - f.cost_basis) if f.side == "SELL" and f.cost_basis is not None else None
            trades.append({
                "timestamp": f.timestamp.isoformat(),
                "ticker": f.ticker,
                "side": f.side,
                "quantity": f.quantity,
                "price": f.price,
                "value": f.value,
                "pnl_gbp": pnl,
            })

        benchmark_returns = None
        if len(self.benchmark_curve) >= 2:
            bench_vals = [v for _, v in self.benchmark_curve]
            benchmark_returns = [(bench_vals[i] - bench_vals[i - 1]) / bench_vals[i - 1] if bench_vals[i - 1] else 0 for i in range(1, len(bench_vals))]
        metrics = compute_metrics(self.equity_curve, trades, benchmark_returns=benchmark_returns)
        return {
            "equity_curve": [(d.isoformat(), v) for d, v in self.equity_curve],
            "trades": trades,
            "metrics": metrics,
            "benchmark_curve": [(d.isoformat(), v) for d, v in self.benchmark_curve],
        }

    def export_artifacts(self, result: dict[str, Any], output_dir: Path) -> None:
        """Write results.json, trades.csv, equity_curve.csv, run_metadata.json."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_dir / "results.json", "w") as f:
            json.dump({"metrics": result.get("metrics", {})}, f, indent=2)

        trades = result.get("trades", [])
        pd.DataFrame(trades).to_csv(output_dir / "trades.csv", index=False)

        equity = result.get("equity_curve", [])
        if equity:
            pd.DataFrame(equity, columns=["date", "value"]).to_csv(output_dir / "equity_curve.csv", index=False)

        config_hash = hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()[:16]
        run_metadata = {
            "config_hash": config_hash,
            "seed": self.seed,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        with open(output_dir / "run_metadata.json", "w") as f:
            json.dump(run_metadata, f, indent=2)
