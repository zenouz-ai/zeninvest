"""Tests for macro intelligence module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.agents.market_data.macro_intelligence import (
    get_economic_headlines,
    get_macro_intelligence,
    get_sector_headwind,
    get_sector_performance,
    get_sector_performance_yfinance,
    _parse_pct,
)


def test_parse_pct() -> None:
    assert _parse_pct("2.50%") == 2.5
    assert _parse_pct("-1.20%") == -1.2
    assert _parse_pct("0") == 0.0
    assert _parse_pct(None) == 0.0
    assert _parse_pct("") == 0.0


def test_get_sector_performance_parses_response() -> None:
    av = MagicMock()
    av.get_sector_performance.return_value = {
        "Rank A: Real-Time Performance": {
            "Information Technology": "2.50%",
            "Health Care": "-0.80%",
        },
        "Rank B: 1 Day Performance": {
            "Information Technology": "1.20%",
            "Health Care": "-0.50%",
        },
        "Rank C: 5 Day Performance": {
            "Information Technology": "3.00%",
            "Health Care": "-1.20%",
        },
        "Rank D: 1 Month Performance": {
            "Information Technology": "5.00%",
            "Health Care": "-2.00%",
        },
    }

    result = get_sector_performance(av)

    assert "error" not in result or result["error"] is None
    sectors = result.get("sectors", {})
    assert "Information Technology" in sectors
    assert sectors["Information Technology"]["real_time_pct"] == 2.5
    assert sectors["Information Technology"]["trend"] == "outperform"
    assert "Health Care" in sectors
    assert sectors["Health Care"]["real_time_pct"] == -0.8
    assert sectors["Health Care"]["trend"] == "underperform"


def test_get_sector_performance_handles_error() -> None:
    av = MagicMock()
    av.get_sector_performance.return_value = {"error": "Rate limit"}

    result = get_sector_performance(av)

    assert result.get("error") == "Rate limit"
    assert result.get("sectors") == {}


def test_get_economic_headlines() -> None:
    fh = MagicMock()
    fh.get_market_news.return_value = [
        {"headline": "Fed holds rates steady", "source": "Reuters", "datetime": 12345},
        {"headline": "Earnings season kicks off", "source": "CNBC", "datetime": 12340},
    ]

    result = get_economic_headlines(fh, limit=5)

    assert "error" not in result or result["error"] is None
    assert len(result["headlines"]) >= 1
    assert result["earnings_season_flag"] in (True, False)


def test_get_sector_headwind_underperform() -> None:
    macro_intel = {
        "enabled": True,
        "sector_trends": {
            "Information Technology": {
                "real_time_pct": -1.5,
                "trend": "underperform",
            },
        },
    }
    msg = get_sector_headwind(macro_intel, "Technology")
    assert msg is not None
    assert "underperforming" in msg
    assert "Information Technology" in msg


def test_get_sector_headwind_outperform() -> None:
    macro_intel = {
        "enabled": True,
        "sector_trends": {
            "Information Technology": {
                "real_time_pct": 2.0,
                "trend": "outperform",
            },
        },
    }
    msg = get_sector_headwind(macro_intel, "Technology")
    assert msg is None


def test_get_sector_headwind_disabled() -> None:
    macro_intel = {"enabled": False}
    assert get_sector_headwind(macro_intel, "Technology") is None


def test_get_macro_intelligence_disabled() -> None:
    with patch(
        "src.agents.market_data.macro_intelligence.get_sector_performance"
    ) as mock_sector, patch(
        "src.agents.market_data.macro_intelligence.get_economic_headlines"
    ) as mock_headlines:
        av = MagicMock()
        fh = MagicMock()
        result = get_macro_intelligence(av, fh, enabled=False)

        mock_sector.assert_not_called()
        mock_headlines.assert_not_called()
        assert result["enabled"] is False
        assert result["sector_trends"] == {}
        assert result["economic_highlights"] == ""


def test_get_sector_performance_yfinance_returns_sectors() -> None:
    """yfinance fallback returns sector data when OHLCV is available."""
    dates = pd.date_range("2025-02-01", periods=10, freq="B")
    df = pd.DataFrame(
        {
            "Close_XLK": [100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 105.0, 106.0, 107.0],
            "Close_XLV": [150.0, 149.0, 148.0, 147.5, 148.0, 149.0, 148.5, 149.0, 150.0, 151.0],
        },
        index=dates,
    )

    with patch("src.agents.market_data.macro_intelligence.yf.download", return_value=df):
        result = get_sector_performance_yfinance()

    assert result.get("source") == "yfinance"
    sectors = result.get("sectors", {})
    assert "Information Technology" in sectors
    assert "Health Care" in sectors
    assert "real_time_pct" in sectors["Information Technology"]
    assert "trend" in sectors["Information Technology"]


def test_get_macro_intelligence_uses_yfinance_fallback_when_av_fails() -> None:
    """When Alpha Vantage returns empty sectors, fallback to yfinance if enabled."""
    av = MagicMock()
    av.get_sector_performance.return_value = {"error": "Daily limit reached", "sectors": {}}
    fh = MagicMock()
    fh.get_market_news.return_value = []

    dates = pd.date_range("2025-02-01", periods=10, freq="B")
    df = pd.DataFrame(
        {"Close_XLK": [100 + i * 0.5 for i in range(10)], "Close_XLV": [150 - i * 0.2 for i in range(10)]},
        index=dates,
    )

    with patch("src.agents.market_data.macro_intelligence.yf.download", return_value=df), patch(
        "src.agents.market_data.macro_intelligence.get_settings"
    ) as mock_settings:
        mock_settings.return_value.data_providers = {"sector_fallback_yfinance": True}
        result = get_macro_intelligence(av, fh, enabled=True)

    assert result["enabled"] is True
    assert len(result["sector_trends"]) > 0
    assert "Information Technology" in result["sector_trends"] or "Health Care" in result["sector_trends"]
