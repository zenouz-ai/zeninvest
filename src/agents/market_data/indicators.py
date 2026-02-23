"""Technical indicator calculations using the `ta` library."""

from typing import Any

import pandas as pd
import ta


def calculate_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Calculate all technical indicators from OHLCV data.

    Args:
        df: DataFrame with columns: Open, High, Low, Close, Volume

    Returns:
        Dictionary of indicator values (latest values).
    """
    if df.empty or len(df) < 200:
        return {"error": "Insufficient data (need >= 200 rows)"}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # RSI(14)
    rsi_indicator = ta.momentum.RSIIndicator(close=close, window=14)
    rsi = rsi_indicator.rsi().iloc[-1]

    # MACD(12, 26, 9)
    macd_indicator = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd_indicator.macd().iloc[-1]
    macd_signal = macd_indicator.macd_signal().iloc[-1]
    macd_histogram = macd_indicator.macd_diff().iloc[-1]
    # Crossover: current macd > signal AND previous macd <= signal
    macd_vals = macd_indicator.macd()
    signal_vals = macd_indicator.macd_signal()
    macd_bullish_cross = bool(
        macd_vals.iloc[-1] > signal_vals.iloc[-1] and macd_vals.iloc[-2] <= signal_vals.iloc[-2]
    )
    macd_bearish_cross = bool(
        macd_vals.iloc[-1] < signal_vals.iloc[-1] and macd_vals.iloc[-2] >= signal_vals.iloc[-2]
    )

    # Bollinger Bands(20, 2)
    bb_indicator = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_upper = bb_indicator.bollinger_hband().iloc[-1]
    bb_middle = bb_indicator.bollinger_mavg().iloc[-1]
    bb_lower = bb_indicator.bollinger_lband().iloc[-1]
    bb_pct = bb_indicator.bollinger_pband().iloc[-1]  # % position within bands

    # Moving Averages
    ma_50 = close.rolling(window=50).mean().iloc[-1]
    ma_200 = close.rolling(window=200).mean().iloc[-1]
    current_price = close.iloc[-1]

    # Golden/Death cross
    ma_50_prev = close.rolling(window=50).mean().iloc[-2]
    ma_200_prev = close.rolling(window=200).mean().iloc[-2]
    golden_cross = bool(ma_50 > ma_200 and ma_50_prev <= ma_200_prev)
    death_cross = bool(ma_50 < ma_200 and ma_50_prev >= ma_200_prev)
    above_50ma = bool(current_price > ma_50)
    above_200ma = bool(current_price > ma_200)

    # ATR(14)
    atr_indicator = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14)
    atr = atr_indicator.average_true_range().iloc[-1]

    # 20-day MA (for mean reversion exit)
    ma_20 = close.rolling(window=20).mean().iloc[-1]

    return {
        "current_price": float(current_price),
        "rsi_14": float(rsi),
        "macd_line": float(macd_line),
        "macd_signal": float(macd_signal),
        "macd_histogram": float(macd_histogram),
        "macd_bullish_crossover": macd_bullish_cross,
        "macd_bearish_crossover": macd_bearish_cross,
        "bb_upper": float(bb_upper),
        "bb_middle": float(bb_middle),
        "bb_lower": float(bb_lower),
        "bb_pct": float(bb_pct),
        "below_lower_bb": bool(current_price < bb_lower),
        "ma_20": float(ma_20),
        "ma_50": float(ma_50),
        "ma_200": float(ma_200),
        "above_50ma": above_50ma,
        "above_200ma": above_200ma,
        "golden_cross": golden_cross,
        "death_cross": death_cross,
        "atr_14": float(atr),
    }


def calculate_relative_strength(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    period: int = 126,
) -> float:
    """Calculate 6-month relative strength vs benchmark.

    RS > 1.0 means stock outperformed benchmark.
    """
    if len(stock_df) < period or len(benchmark_df) < period:
        return 0.0

    stock_return = (stock_df["Close"].iloc[-1] / stock_df["Close"].iloc[-period] - 1)
    bench_return = (benchmark_df["Close"].iloc[-1] / benchmark_df["Close"].iloc[-period] - 1)

    if bench_return == 0:
        return 1.0

    return float((1 + stock_return) / (1 + bench_return))
