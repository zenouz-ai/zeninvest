"""Tests for macro intelligence module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.market_data.macro_intelligence import (
    build_proactive_macro_state,
    generate_macro_action_plan,
    get_economic_headlines,
    get_latest_macro_state,
    get_macro_intelligence,
    get_sector_headwind,
    get_sector_performance,
    get_sector_performance_yfinance,
    persist_macro_state,
    run_proactive_macro_scan,
    _parse_pct,
)
from src.agents.market_data.data_fetcher import DataFetcher
from src.data.models import Base, MacroSignalLog, MacroState


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


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


def test_build_proactive_macro_state_derives_regime_and_signals() -> None:
    macro_state = build_proactive_macro_state(
        {
            "vix": 15.0,
            "sp500_above_200ma": True,
            "market_regime": "BULL",
            "macro_intelligence": {
                "sector_trends": {
                    "Information Technology": {"trend": "outperform", "real_time_pct": 1.8},
                },
                "sector_summary": "Tech leadership intact",
                "economic_highlights": "- Fed holds steady",
                "headlines": [{"headline": "Fed holds rates steady", "source": "Reuters"}],
            },
        }
    )

    assert macro_state["regime"] == "RISK_ON"
    assert macro_state["confidence_score"] > 0.5
    assert len(macro_state["top_signals"]) >= 2


def test_persist_macro_state_writes_state_and_signal_logs(db_session) -> None:
    macro_state = {
        "regime": "NEUTRAL",
        "confidence_score": 0.8,
        "source": "scheduled_scan",
        "top_signals": [
            {"signal_type": "volatility", "signal_text": "VIX at 19.20", "source": "market_data"},
            {"signal_type": "headline", "signal_text": "Fed holds rates steady", "source": "Reuters"},
        ],
        "action_plan": {"summary": "Stay balanced", "sector_implications": []},
        "sector_summary": "Sector summary",
        "economic_highlights": "Economic highlights",
        "raw_payload": {"vix": 19.2},
    }

    with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
        result = persist_macro_state(macro_state, signal_log_enabled=True)

    assert result["status"] == "ok"
    assert db_session.query(MacroState).count() == 1
    assert db_session.query(MacroSignalLog).count() == 2


def test_get_latest_macro_state_returns_newest_snapshot(db_session) -> None:
    with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
        persist_macro_state(
            {
                "regime": "RISK_OFF",
                "confidence_score": 0.9,
                "source": "scheduled_scan",
                "top_signals": [{"signal_type": "volatility", "signal_text": "VIX at 31.00"}],
                "action_plan": {"summary": "Be defensive", "sector_implications": []},
                "sector_summary": "Defensive tilt",
                "economic_highlights": "Tariff headlines rising",
                "raw_payload": {"vix": 31.0},
            },
            signal_log_enabled=False,
        )
        latest = get_latest_macro_state()

    assert latest is not None
    assert latest["regime"] == "RISK_OFF"
    assert latest["economic_highlights"] == "Tariff headlines rising"
    assert latest["action_plan"]["summary"] == "Be defensive"


def test_data_fetcher_injects_latest_macro_state_when_enabled() -> None:
    settings = MagicMock()
    settings.macro_intelligence_enabled = False
    settings.macro_proactive_scan_enabled = True

    fetcher = DataFetcher()
    fetcher.settings = settings

    with patch.object(fetcher, "get_ohlcv", return_value=pd.DataFrame()), patch.object(
        fetcher, "get_macro_intelligence_cached", return_value={"enabled": False}
    ), patch(
        "src.agents.market_data.data_fetcher.get_latest_macro_state",
        return_value={"enabled": True, "regime": "NEUTRAL", "top_signals": []},
    ):
        result = fetcher.get_macro_data()

    assert result["macro_state"]["regime"] == "NEUTRAL"


def test_generate_macro_action_plan_falls_back_when_disabled() -> None:
    with patch("src.agents.market_data.macro_intelligence.get_settings") as mock_settings:
        mock_settings.return_value.macro_second_order_reasoning_enabled = False
        plan = generate_macro_action_plan(
            {
                "regime": "RISK_OFF",
                "confidence_score": 0.8,
                "top_signals": [{"signal_text": "VIX at 32.00"}],
            }
        )

    assert plan["portfolio_bias"] == "defensive"
    assert len(plan["sector_implications"]) >= 1


def test_run_proactive_macro_scan_persists_action_plan(db_session) -> None:
    alpha_vantage = MagicMock()
    finnhub = MagicMock()
    fake_fetcher = MagicMock()
    fake_fetcher.get_macro_data.return_value = {
        "vix": 16.0,
        "sp500_above_200ma": True,
        "market_regime": "BULL",
        "macro_intelligence": {
            "sector_trends": {"Information Technology": {"trend": "outperform", "real_time_pct": 1.2}},
            "sector_summary": "Tech leading",
            "economic_highlights": "Fed steady",
            "headlines": [{"headline": "Fed holds rates steady", "source": "Reuters"}],
        },
    }

    settings = MagicMock()
    settings.macro_proactive_scan_enabled = True
    settings.macro_signal_log_enabled = True
    settings.macro_second_order_reasoning_enabled = False

    with patch("src.agents.market_data.macro_intelligence.get_settings", return_value=settings), patch(
        "src.agents.market_data.data_fetcher.DataFetcher", return_value=fake_fetcher
    ), patch(
        "src.agents.market_data.macro_intelligence.get_session", return_value=db_session
    ):
        result = run_proactive_macro_scan(alpha_vantage=alpha_vantage, finnhub=finnhub)

    assert result["status"] == "ok"
    latest = db_session.query(MacroState).order_by(MacroState.id.desc()).first()
    assert latest is not None
    assert latest.action_plan_json is not None
