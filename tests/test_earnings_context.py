"""Tests for per-ticker earnings context helpers."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.agents.market_data.earnings import (
    count_trading_days_between,
    count_trading_days_until,
    default_earnings_context,
    get_earnings_context,
)


def _price_history() -> pd.DataFrame:
    index = pd.to_datetime(
        ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03", "2026-04-06", "2026-04-07"]
    )
    return pd.DataFrame({"Close": [100, 101, 103, 104, 105, 107, 108]}, index=index)


def test_count_trading_days_until_skips_weekends() -> None:
    assert count_trading_days_until(date(2026, 4, 3), date(2026, 4, 7)) == 2


def test_count_trading_days_between_skips_weekends() -> None:
    # Good Friday on 2026-04-03 is a market holiday and should not be counted.
    assert count_trading_days_between(date(2026, 4, 1), date(2026, 4, 7)) == 3


def test_get_earnings_context_flags_imminent_and_positive_drift() -> None:
    earnings_dates = pd.DataFrame(
        {
            "EPS Estimate": [2.0],
            "Reported EPS": [2.2],
            "Surprise(%)": [10.0],
        },
        index=pd.to_datetime(["2026-04-01"]),
    )
    fake_ticker = SimpleNamespace(
        calendar={"Earnings Date": [date(2026, 4, 8)]},
        get_earnings_dates=lambda limit=6: earnings_dates,
    )

    with patch("src.agents.market_data.earnings.yf.Ticker", return_value=fake_ticker):
        context = get_earnings_context(
            "AAPL",
            price_history=_price_history(),
            now=date(2026, 4, 7),
            pre_window_trading_days=5,
            post_window_trading_days=10,
        )

    assert context["next_earnings_date"] == "2026-04-08"
    assert context["trading_days_to_earnings"] == 1
    assert context["earnings_imminent"] is True
    assert context["recent_earnings_date"] == "2026-04-01"
    assert context["recent_earnings_surprise_pct"] == 10.0
    assert context["post_earnings_drift_active"] is True
    assert context["post_earnings_drift_bias"] == "positive"
    assert context["post_earnings_price_change_pct"] is not None


def test_get_earnings_context_outside_windows_is_not_imminent() -> None:
    earnings_dates = pd.DataFrame(columns=["EPS Estimate", "Reported EPS", "Surprise(%)"])
    fake_ticker = SimpleNamespace(
        calendar={"Earnings Date": [date(2026, 4, 20)]},
        get_earnings_dates=lambda limit=6: earnings_dates,
    )

    with patch("src.agents.market_data.earnings.yf.Ticker", return_value=fake_ticker):
        context = get_earnings_context(
            "AAPL",
            price_history=_price_history(),
            now=date(2026, 4, 7),
            pre_window_trading_days=5,
            post_window_trading_days=10,
        )

    assert context["earnings_imminent"] is False
    assert context["recent_earnings_date"] is None


def test_get_earnings_context_handles_missing_lxml() -> None:
    fake_ticker = SimpleNamespace(
        calendar={"Earnings Date": [date(2026, 4, 20)]},
        get_earnings_dates=lambda limit=6: (_ for _ in ()).throw(ImportError("lxml missing")),
    )

    with patch("src.agents.market_data.earnings.yf.Ticker", return_value=fake_ticker):
        context = get_earnings_context(
            "AAPL",
            price_history=_price_history(),
            now=date(2026, 4, 7),
        )

    expected = default_earnings_context()
    assert context["next_earnings_date"] == "2026-04-20"
    assert context["recent_earnings_date"] == expected["recent_earnings_date"]
    assert context["post_earnings_drift_bias"] == expected["post_earnings_drift_bias"]


def test_get_earnings_context_marks_negative_drift_after_miss() -> None:
    earnings_dates = pd.DataFrame(
        {
            "EPS Estimate": [2.0],
            "Reported EPS": [1.6],
            "Surprise(%)": [-20.0],
        },
        index=pd.to_datetime(["2026-04-01"]),
    )
    price_history = pd.DataFrame(
        {"Close": [100, 98, 96, 95, 94]},
        index=pd.to_datetime(["2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03", "2026-04-06"]),
    )
    fake_ticker = SimpleNamespace(
        calendar={"Earnings Date": [date(2026, 4, 30)]},
        get_earnings_dates=lambda limit=6: earnings_dates,
    )

    with patch("src.agents.market_data.earnings.yf.Ticker", return_value=fake_ticker):
        context = get_earnings_context(
            "AAPL",
            price_history=price_history,
            now=date(2026, 4, 6),
            post_window_trading_days=10,
        )

    assert context["post_earnings_drift_active"] is True
    assert context["post_earnings_drift_bias"] == "negative"


def test_get_earnings_context_ignores_malformed_recent_earnings_dates() -> None:
    earnings_dates = pd.DataFrame(
        [
            {"EPS Estimate": 1.0, "Reported EPS": 1.1, "Surprise(%)": 10.0},
        ],
        index=["2011-01-00"],
    )
    fake_ticker = SimpleNamespace(
        calendar={"Earnings Date": [datetime(2026, 4, 20)]},
        get_earnings_dates=lambda limit=6: earnings_dates,
    )

    with patch("src.agents.market_data.earnings.yf.Ticker", return_value=fake_ticker):
        context = get_earnings_context(
            "BROKEN",
            price_history=_price_history(),
            now=date(2026, 4, 7),
        )

    assert context["next_earnings_date"] == "2026-04-20"
    assert context["recent_earnings_date"] is None
    assert context["post_earnings_drift_active"] is False
