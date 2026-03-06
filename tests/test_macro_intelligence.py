"""Tests for macro intelligence module."""

from unittest.mock import MagicMock, patch

import pytest

from src.agents.market_data.macro_intelligence import (
    get_economic_headlines,
    get_macro_intelligence,
    get_sector_headwind,
    get_sector_performance,
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
