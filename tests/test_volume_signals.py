"""Tests for US-4.1 volume-weighted indicator calculations."""

import pandas as pd

from src.agents.market_data.indicators import calculate_indicators


def _build_ohlcv(rows: int = 220) -> pd.DataFrame:
    close = pd.Series([100 + i for i in range(rows)], dtype=float)
    volume = pd.Series([1_000_000.0] * (rows - 1) + [2_000_000.0], dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 1,
            "Low": close - 2,
            "Close": close,
            "Volume": volume,
        }
    )


def test_calculate_indicators_includes_volume_signals_when_enabled():
    df = _build_ohlcv()
    indicators = calculate_indicators(df, volume_signals_enabled=True)

    expected_obv = float(df["Volume"].sum())
    expected_ratio = float(df["Volume"].iloc[-1] / df["Volume"].tail(20).mean())

    assert indicators["obv"] == expected_obv
    assert indicators["obv_rising_5d"] is True
    assert indicators["volume_sma_20"] == float(df["Volume"].tail(20).mean())
    assert indicators["volume_sma_ratio_20"] == expected_ratio


def test_calculate_indicators_omits_volume_signals_when_disabled():
    df = _build_ohlcv()
    indicators = calculate_indicators(df, volume_signals_enabled=False)

    assert "obv" not in indicators
    assert "obv_rising_5d" not in indicators
    assert "volume_sma_20" not in indicators
    assert "volume_sma_ratio_20" not in indicators


def test_calculate_indicators_requires_sufficient_history():
    df = _build_ohlcv(rows=50)
    indicators = calculate_indicators(df)

    assert indicators == {"error": "Insufficient data (need >= 200 rows)"}
