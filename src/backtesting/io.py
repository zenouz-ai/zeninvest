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
            start_ts = pd.Timestamp(start.replace(tzinfo=None) if getattr(start, "tzinfo", None) else start)
            end_ts = pd.Timestamp(end.replace(tzinfo=None) if getattr(end, "tzinfo", None) else end)
            df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]
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


def fetch_bars_yfinance(
    tickers: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV from yfinance when CSV data is not available.

    Returns:
        Dict ticker -> DataFrame with columns: date, open, high, low, close, volume.
    """
    import yfinance as yf

    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
            if df.empty or len(df) < 2:
                logger.warning(f"Insufficient yfinance data for {ticker}; skipping")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
            start_d = pd.Timestamp(start).tz_localize(None) if hasattr(start, "tzinfo") and start.tzinfo else pd.Timestamp(start)
            end_d = pd.Timestamp(end).tz_localize(None) if hasattr(end, "tzinfo") and end.tzinfo else pd.Timestamp(end)
            df = df[(df["date"].dt.date >= start_d.date()) & (df["date"].dt.date <= end_d.date())]
            df = df.sort_values("date").reset_index(drop=True)
            result[ticker] = df[["date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker} from yfinance: {e}")
    return result


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
