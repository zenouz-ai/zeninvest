"""Walk-forward validation: fixed time splits, deterministic seed, aggregate metrics."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from src.backtesting.engine import BacktestEngine
from src.backtesting.io import load_bars, load_benchmark
from src.utils.logger import get_logger

logger = get_logger("backtesting.walk_forward")


@dataclass
class WalkForwardSplit:
    """One fold: test window only (policy is deterministic, no train step in v1)."""
    fold_id: int
    test_start: str
    test_end: str


def make_splits(
    start_date: str,
    end_date: str,
    n_folds: int = 3,
    test_days: int = 252,
) -> list[WalkForwardSplit]:
    """Build non-overlapping test windows (e.g. one year each)."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    total_days = (end - start).days
    if total_days < test_days * n_folds:
        test_days = max(252 // 2, total_days // n_folds)
    splits: list[WalkForwardSplit] = []
    for i in range(n_folds):
        t0 = start + pd.Timedelta(days=i * (total_days // n_folds))
        t1 = t0 + pd.Timedelta(days=test_days)
        if t1 > end:
            t1 = end
        if (t1 - t0).days < 30:
            continue
        splits.append(WalkForwardSplit(
            fold_id=i + 1,
            test_start=t0.strftime("%Y-%m-%d"),
            test_end=t1.strftime("%Y-%m-%d"),
        ))
    return splits


def run_walk_forward(
    config: dict[str, Any],
    tickers: list[str],
    splits: list[WalkForwardSplit],
    bars_cache: dict[str, pd.DataFrame] | None = None,
) -> list[dict[str, Any]]:
    """Run backtest on each fold; return list of {fold_id, test_start, test_end, metrics}."""
    seed = config.get("seed", 42)
    results: list[dict[str, Any]] = []
    for split in splits:
        test_start = datetime.strptime(split.test_start, "%Y-%m-%d")
        test_end = datetime.strptime(split.test_end, "%Y-%m-%d")
        if bars_cache is None:
            bars = load_bars(tickers, test_start, test_end)
            benchmark = load_benchmark("SPY", test_start, test_end)
        else:
            bars = {}
            for t in tickers:
                if t in bars_cache:
                    df = bars_cache[t]
                    mask = (df["date"] >= pd.Timestamp(split.test_start)) & (df["date"] <= pd.Timestamp(split.test_end))
                    bars[t] = df.loc[mask].copy()
            benchmark = None
            if "SPY" in bars and not bars["SPY"].empty:
                benchmark = bars["SPY"].set_index("date")["close"]

        if not bars:
            logger.warning(f"Fold {split.fold_id}: no bars, skipping")
            continue
        engine = BacktestEngine(config, seed=seed)
        result = engine.run(bars, benchmark=benchmark)
        if "error" in result:
            logger.warning(f"Fold {split.fold_id}: {result['error']}")
            continue
        results.append({
            "fold_id": split.fold_id,
            "test_start": split.test_start,
            "test_end": split.test_end,
            "metrics": result["metrics"],
        })
    return results


def aggregate_fold_metrics(fold_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Average metrics across folds (for numeric fields)."""
    if not fold_results:
        return {}
    agg: dict[str, Any] = {}
    metrics_list = [r["metrics"] for r in fold_results]
    keys = metrics_list[0].keys()
    for k in keys:
        vals = [m.get(k) for m in metrics_list if m.get(k) is not None]
        if vals and isinstance(vals[0], (int, float)):
            agg[f"{k}_mean"] = sum(vals) / len(vals)
            agg[f"{k}_min"] = min(vals)
            agg[f"{k}_max"] = max(vals)
        elif vals:
            agg[k] = vals[0]
    agg["n_folds"] = len(fold_results)
    return agg
