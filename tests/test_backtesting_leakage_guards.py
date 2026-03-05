"""Leakage guards: ensure no future data is used in backtest inputs."""

import pandas as pd
import pytest

from src.backtesting.io import check_no_lookahead


def test_check_no_lookahead_empty() -> None:
    df = pd.DataFrame(columns=["date", "close"])
    assert check_no_lookahead(df, pd.Timestamp("2024-01-15")) is True


def test_check_no_lookahead_all_before() -> None:
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-10", "2024-01-14"]),
        "close": [100.0, 101.0, 102.0],
    })
    assert check_no_lookahead(df, pd.Timestamp("2024-01-15")) is True


def test_check_no_lookahead_fails_when_future() -> None:
    df = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-20"]),
        "close": [100.0, 102.0],
    })
    assert check_no_lookahead(df, pd.Timestamp("2024-01-15")) is False
