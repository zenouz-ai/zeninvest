"""Tests for backtesting I/O: bar loading, synthetic generation, lookahead checks."""

from datetime import datetime

import pandas as pd
import pytest

from src.backtesting.io import (
    check_no_lookahead,
    generate_synthetic_bars,
    load_bars,
)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample CSV bar file for testing."""
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=5, freq="B"),
        "open": [100.0, 101.0, 102.0, 101.5, 103.0],
        "high": [101.0, 102.5, 103.0, 102.0, 104.0],
        "low": [99.5, 100.5, 101.0, 100.0, 102.5],
        "close": [100.5, 102.0, 101.5, 101.0, 103.5],
        "volume": [1e6, 1.1e6, 0.9e6, 1.2e6, 1e6],
    })
    path = tmp_path / "AAPL.csv"
    df.to_csv(path, index=False)
    return tmp_path


# --- load_bars ---


def test_load_bars_from_csv(sample_csv):
    bars = load_bars(
        ["AAPL"],
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        data_dir=sample_csv,
    )
    assert "AAPL" in bars
    assert len(bars["AAPL"]) == 5
    assert list(bars["AAPL"].columns) == ["date", "open", "high", "low", "close", "volume"]


def test_load_bars_missing_file_returns_empty(tmp_path):
    bars = load_bars(["MISSING"], start=datetime(2024, 1, 1), end=datetime(2024, 12, 31), data_dir=tmp_path)
    assert bars == {}


def test_load_bars_date_filtering(sample_csv):
    bars = load_bars(
        ["AAPL"],
        start=datetime(2024, 1, 3),
        end=datetime(2024, 1, 4),
        data_dir=sample_csv,
    )
    assert len(bars["AAPL"]) == 2


# --- generate_synthetic_bars ---


def test_generate_synthetic_bars_deterministic():
    bars1 = generate_synthetic_bars("TEST", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01"), seed=42)
    bars2 = generate_synthetic_bars("TEST", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01"), seed=42)
    pd.testing.assert_frame_equal(bars1, bars2)


def test_generate_synthetic_bars_shape():
    bars = generate_synthetic_bars("TEST", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-31"), seed=1)
    assert set(bars.columns) == {"date", "open", "high", "low", "close", "volume"}
    assert len(bars) > 0
    # High should be >= max(open, close), Low <= min(open, close)
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1) - 0.01).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1) + 0.01).all()


# --- check_no_lookahead ---


def test_check_no_lookahead_passes_clean_data():
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5, freq="B")})
    assert check_no_lookahead(df, pd.Timestamp("2024-01-31")) == True


def test_check_no_lookahead_fails_future_data():
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5, freq="B")})
    assert check_no_lookahead(df, pd.Timestamp("2024-01-02")) == False


def test_check_no_lookahead_empty_df():
    df = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]")})
    assert check_no_lookahead(df, pd.Timestamp("2024-01-01")) == True
