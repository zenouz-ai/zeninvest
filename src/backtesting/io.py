"""Data loading for backtesting: daily bars and benchmark with integrity checks."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("backtesting.io")


def load_bars(
    tickers: list[str],
    start: datetime,
    end: datetime,
    *,
    data_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load daily OHLCV for tickers in [start, end]. No lookahead: bars are as-of end of day.

    Returns:
        Dict ticker -> DataFrame with columns: date, open, high, low, close, volume.
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "backtest"
    data_dir = Path(data_dir)
    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        path = data_dir / f"{ticker.replace(' ', '_')}.csv"
        if path.exists():
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
            df = df.sort_values("date").reset_index(drop=True)
            result[ticker] = df
        else:
            logger.warning(f"No bar data for {ticker} at {path}; skipping")
    return result


def load_benchmark(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    data_dir: Path | None = None,
) -> pd.Series | None:
    """Load benchmark (e.g. SPY) daily close for return comparison."""
    bars = load_bars([symbol], start, end, data_dir=data_dir)
    if symbol not in bars or bars[symbol].empty:
        return None
    return bars[symbol].set_index("date")["close"].sort_index()


def check_no_lookahead(df: pd.DataFrame, as_of_date: pd.Timestamp) -> bool:
    """Verify no bar has date > as_of_date (leakage check)."""
    if df.empty:
        return True
    return (df["date"] <= as_of_date).all()


def generate_synthetic_bars(
    ticker: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic daily bars for testing (no external data)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, end=end, freq="B")
    n = len(dates)
    returns = rng.standard_normal(n) * 0.01
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    high = np.maximum(open_, close) * (1 + np.abs(rng.standard_normal(n)) * 0.005)
    low = np.minimum(open_, close) * (1 - np.abs(rng.standard_normal(n)) * 0.005)
    volume = (rng.integers(1_000_000, 10_000_000, size=n)).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
