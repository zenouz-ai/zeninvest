"""Tests for backtest engine: run with synthetic bars and export artifacts."""

from pathlib import Path
import tempfile

import pandas as pd
import pytest

from src.backtesting.engine import BacktestEngine
from src.backtesting.io import generate_synthetic_bars


def test_engine_run_synthetic() -> None:
    bars = {
        "AAPL": generate_synthetic_bars("AAPL", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-06-30"), seed=42),
        "MSFT": generate_synthetic_bars("MSFT", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-06-30"), seed=43),
    }
    config = {"seed": 42, "initial_cash": 10000.0, "slippage_bps": 5.0, "max_positions": 5, "sma_period": 20}
    engine = BacktestEngine(config, seed=42)
    result = engine.run(bars, benchmark=None)
    assert "error" not in result
    assert "equity_curve" in result
    assert "trades" in result
    assert "metrics" in result
    assert len(result["equity_curve"]) >= 2
    assert "sharpe" in result["metrics"] or result["metrics"].get("num_trades") is not None


def test_engine_export_artifacts() -> None:
    bars = {
        "AAPL": generate_synthetic_bars("AAPL", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-03-31"), seed=1),
    }
    config = {"seed": 1, "initial_cash": 10000.0}
    engine = BacktestEngine(config, seed=1)
    result = engine.run(bars, benchmark=None)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        engine.export_artifacts(result, out)
        assert (out / "results.json").exists()
        assert (out / "run_metadata.json").exists()
        assert (out / "equity_curve.csv").exists()
        # trades.csv may be empty if no trades
        assert (out / "trades.csv").exists()
