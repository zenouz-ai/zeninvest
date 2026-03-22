"""Technical indicator calculations using the `ta` library.

Only indicators that directly influence sub-strategy scoring are computed and returned.
See docs/DATA_RATIONALE.md for why each indicator is kept or removed.
"""

from typing import Any

import pandas as pd
import ta


def calculate_indicators(
    df: pd.DataFrame,
    volume_signals_enabled: bool = True,
) -> dict[str, Any]:
    """Calculate technical indicators from OHLCV data.

    Returns only indicators consumed by sub-strategies:
    - RSI(14): momentum scoring, mean reversion entry/exit
    - MACD crossovers + histogram: momentum scoring
    - Bollinger Band breach: mean reversion entry
    - 50-day MA position: momentum BUY gate
    - 20-day MA: mean reversion exit target
    - Current price: mean reversion exit check
    - OBV + 20-day volume ratio: optional volume confirmation (US-4.1)

    Args:
        df: DataFrame with columns: Open, High, Low, Close, Volume

    Returns:
        Dictionary of indicator values (latest values).
    """
    if df.empty or len(df) < 200:
        return {"error": "Insufficient data (need >= 200 rows)"}

    close = df["Close"]

    current_price = close.iloc[-1]

    # RSI(14) — used by momentum (score ±25) and mean reversion (entry/exit thresholds)
    rsi_indicator = ta.momentum.RSIIndicator(close=close, window=14)
    rsi = rsi_indicator.rsi().iloc[-1]

    # MACD(12, 26, 9) — crossovers and histogram used by momentum strategy
    macd_indicator = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_histogram = macd_indicator.macd_diff().iloc[-1]
    macd_vals = macd_indicator.macd()
    signal_vals = macd_indicator.macd_signal()
    macd_bullish_cross = bool(
        macd_vals.iloc[-1] > signal_vals.iloc[-1] and macd_vals.iloc[-2] <= signal_vals.iloc[-2]
    )
    macd_bearish_cross = bool(
        macd_vals.iloc[-1] < signal_vals.iloc[-1] and macd_vals.iloc[-2] >= signal_vals.iloc[-2]
    )

    # Bollinger Bands(20, 2) — only below-lower-band boolean used (mean reversion BUY)
    bb_indicator = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_lower = bb_indicator.bollinger_lband().iloc[-1]

    # 50-day MA — above_50ma is the momentum BUY gate (+25 score)
    ma_50 = close.rolling(window=50).mean().iloc[-1]
    above_50ma = bool(current_price > ma_50)

    # 20-day MA — mean reversion exit target (price reaching MA-20 triggers SELL)
    ma_20 = close.rolling(window=20).mean().iloc[-1]

    indicators = {
        "current_price": float(current_price),
        "rsi_14": float(rsi),
        "macd_histogram": float(macd_histogram),
        "macd_bullish_crossover": macd_bullish_cross,
        "macd_bearish_crossover": macd_bearish_cross,
        "below_lower_bb": bool(current_price < bb_lower),
        "above_50ma": above_50ma,
        "ma_20": float(ma_20),
    }

    if volume_signals_enabled and "Volume" in df.columns:
        volume = df["Volume"].fillna(0.0)
        direction = close.diff().apply(lambda change: 1 if change > 0 else -1 if change < 0 else 0)
        direction.iloc[0] = 1
        obv_series = (direction * volume).cumsum()
        volume_sma_20 = volume.rolling(window=20).mean().iloc[-1]
        volume_ratio_20 = None
        if pd.notna(volume_sma_20) and float(volume_sma_20) > 0:
            volume_ratio_20 = float(volume.iloc[-1] / volume_sma_20)

        indicators.update(
            {
                "obv": float(obv_series.iloc[-1]),
                "obv_rising_5d": bool(obv_series.iloc[-1] > obv_series.iloc[-6]),
                "volume_sma_20": float(volume_sma_20),
                "volume_sma_ratio_20": volume_ratio_20,
            }
        )

    return indicators


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
