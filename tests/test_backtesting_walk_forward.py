"""Tests for walk-forward runner and promotion report."""

from pathlib import Path
import tempfile

import pandas as pd
import pytest

from src.backtesting.io import generate_synthetic_bars
from src.backtesting.promotion_report import write_promotion_report
from src.backtesting.walk_forward import aggregate_fold_metrics, make_splits, run_walk_forward


def test_make_splits() -> None:
    splits = make_splits("2020-01-01", "2023-12-31", n_folds=3, test_days=252)
    assert len(splits) >= 1
    assert splits[0].fold_id == 1
    assert splits[0].test_start <= splits[0].test_end


def test_aggregate_fold_metrics() -> None:
    fold_results = [
        {"fold_id": 1, "metrics": {"sharpe": 0.5, "max_drawdown_pct": 10.0}},
        {"fold_id": 2, "metrics": {"sharpe": 0.8, "max_drawdown_pct": 15.0}},
    ]
    agg = aggregate_fold_metrics(fold_results)
    assert agg["sharpe_mean"] == pytest.approx(0.65)
    assert agg["n_folds"] == 2


def test_run_walk_forward_synthetic() -> None:
    bars = {
        "AAPL": generate_synthetic_bars("AAPL", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31"), seed=1),
        "SPY": generate_synthetic_bars("SPY", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31"), seed=2),
    }
    config = {"seed": 1, "initial_cash": 10000.0}
    splits = make_splits("2022-01-01", "2023-12-31", n_folds=2, test_days=252)
    results = run_walk_forward(config, ["AAPL", "SPY"], splits, bars_cache=bars)
    assert len(results) >= 1
    assert "metrics" in results[0]


def test_write_promotion_report() -> None:
    metrics = {"sharpe_mean": 0.6, "max_drawdown_pct_mean": 12.0, "hit_rate_pct_mean": 50.0}
    fold_results = [{"fold_id": 1, "test_start": "2022-01-01", "test_end": "2022-12-31", "metrics": metrics}]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.md"
        rec = write_promotion_report(metrics, fold_results, path)
        assert rec in ("safe to deploy", "hold")
        assert path.exists()
        assert "Recommendation" in path.read_text()
