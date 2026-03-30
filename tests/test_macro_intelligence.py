"""Tests for macro intelligence module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.market_data.macro_intelligence import (
    build_proactive_macro_state,
    categorize_headline,
    generate_macro_action_plan,
    get_economic_headlines,
    get_latest_macro_state,
    get_macro_intelligence,
    get_sector_headwind,
    get_sector_performance,
    get_sector_performance_yfinance,
    persist_headlines,
    persist_macro_state,
    run_proactive_macro_scan,
    _parse_pct,
    _derive_proactive_regime,
    _confidence_from_inputs,
)
from src.agents.market_data.data_fetcher import DataFetcher
from src.data.models import Base, MacroHeadline, MacroSignalLog, MacroState


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
        mock_settings.return_value.sector_fallback_yfinance = True
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


# --- Edge-case / boundary tests ---


def test_derive_proactive_regime_boundary_values() -> None:
    """Verify boundary conditions for regime classification."""
    # VIX exactly 30 → RISK_OFF
    assert _derive_proactive_regime(30.0, True) == "RISK_OFF"
    # VIX exactly 18, sp_above True → RISK_ON
    assert _derive_proactive_regime(18.0, True) == "RISK_ON"
    # VIX 18.5 alone (sp_above None) → NEUTRAL
    assert _derive_proactive_regime(18.5, None) == "NEUTRAL"
    # sp_above False, low VIX → RISK_OFF (sp below 200MA dominates)
    assert _derive_proactive_regime(15.0, False) == "RISK_OFF"
    # Both None → NEUTRAL
    assert _derive_proactive_regime(None, None) == "NEUTRAL"
    # VIX 25, sp_above True → NEUTRAL (VIX in the gap)
    assert _derive_proactive_regime(25.0, True) == "NEUTRAL"


def test_confidence_from_inputs_all_missing() -> None:
    """When all inputs are missing, confidence should be base level."""
    c = _confidence_from_inputs(vix=None, sp_above_200ma=None, sector_count=0, headline_count=0)
    assert c == 0.35


def test_confidence_from_inputs_all_present() -> None:
    """When all inputs are present, confidence should be capped at 0.95."""
    c = _confidence_from_inputs(vix=20.0, sp_above_200ma=True, sector_count=5, headline_count=3)
    # 0.35 + 0.15 + 0.15 + 0.20 + 0.15 = 1.00 → capped to 0.95
    assert c == 0.95


def test_run_proactive_macro_scan_disabled() -> None:
    """When proactive scan is disabled, should return disabled status."""
    with patch("src.agents.market_data.macro_intelligence.get_settings") as mock_settings:
        mock_settings.return_value.macro_proactive_scan_enabled = False
        result = run_proactive_macro_scan(MagicMock(), MagicMock())
    assert result == {"status": "disabled"}


def test_run_proactive_macro_scan_data_fetcher_fails() -> None:
    """When DataFetcher.get_macro_data() raises, the scan should propagate the error."""
    fake_fetcher = MagicMock()
    fake_fetcher.get_macro_data.side_effect = RuntimeError("Network failure")

    settings = MagicMock()
    settings.macro_proactive_scan_enabled = True

    with patch("src.agents.market_data.macro_intelligence.get_settings", return_value=settings), \
         patch("src.agents.market_data.data_fetcher.DataFetcher", return_value=fake_fetcher):
        with pytest.raises(RuntimeError, match="Network failure"):
            run_proactive_macro_scan(MagicMock(), MagicMock())


def test_get_latest_macro_state_empty_db(db_session) -> None:
    """When no macro state exists, should return None."""
    with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
        result = get_latest_macro_state()
    assert result is None


def test_macro_state_staleness_guard() -> None:
    """Stale macro state (>48h) should not be injected into cycle context."""
    from datetime import datetime, timedelta, timezone

    settings = MagicMock()
    settings.macro_proactive_scan_enabled = True

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    stale_state = {"enabled": True, "regime": "RISK_OFF", "timestamp": stale_ts, "top_signals": []}

    fetcher = DataFetcher()
    fetcher.settings = settings

    with patch.object(fetcher, "get_ohlcv", return_value=pd.DataFrame()), \
         patch.object(fetcher, "get_macro_intelligence_cached", return_value={"enabled": False}), \
         patch("src.agents.market_data.data_fetcher.get_latest_macro_state", return_value=stale_state):
        result = fetcher.get_macro_data()

    assert "macro_state" not in result


def test_macro_state_fresh_is_injected() -> None:
    """Fresh macro state (<48h) should be injected into cycle context."""
    from datetime import datetime, timezone

    settings = MagicMock()
    settings.macro_proactive_scan_enabled = True

    fresh_ts = datetime.now(timezone.utc).isoformat()
    fresh_state = {"enabled": True, "regime": "RISK_ON", "timestamp": fresh_ts, "top_signals": []}

    fetcher = DataFetcher()
    fetcher.settings = settings

    with patch.object(fetcher, "get_ohlcv", return_value=pd.DataFrame()), \
         patch.object(fetcher, "get_macro_intelligence_cached", return_value={"enabled": False}), \
         patch("src.agents.market_data.data_fetcher.get_latest_macro_state", return_value=fresh_state):
        result = fetcher.get_macro_data()

    assert result["macro_state"]["regime"] == "RISK_ON"


def test_headline_sorting_highest_score_first() -> None:
    """Headlines with higher keyword scores should appear first."""
    fh = MagicMock()
    fh.get_market_news.return_value = [
        {"headline": "Tech earnings surprise", "source": "CNBC", "datetime": 100},
        {"headline": "Fed rate decision and inflation CPI jobs GDP tariff", "source": "Reuters", "datetime": 200},
        {"headline": "Sports update", "source": "ESPN", "datetime": 300},
    ]

    result = get_economic_headlines(fh, limit=3)
    headlines = result["headlines"]
    assert len(headlines) >= 2
    # The Fed headline has the most keyword matches and should come first
    assert "Fed" in headlines[0]["headline"]


# ---------------------------------------------------------------------------
# Headline categorisation and persistence (World News)
# ---------------------------------------------------------------------------


class TestCategorizeHeadline:
    def test_fed_category(self) -> None:
        assert categorize_headline("Fed holds rates steady at 5.5%") == "fed"
        assert categorize_headline("FOMC meeting minutes released") == "fed"

    def test_rates_category(self) -> None:
        assert categorize_headline("Treasury yields surge to 4.8%") == "rates"

    def test_trade_category(self) -> None:
        assert categorize_headline("China tariffs increased by 25%") == "trade"

    def test_earnings_category(self) -> None:
        assert categorize_headline("Apple earnings beat expectations") == "earnings"

    def test_inflation_category(self) -> None:
        assert categorize_headline("CPI report shows inflation cooling") == "inflation"

    def test_jobs_category(self) -> None:
        assert categorize_headline("Nonfarm payrolls beat expectations") == "jobs"

    def test_gdp_category(self) -> None:
        assert categorize_headline("GDP growth revised higher to 3.1%") == "gdp"

    def test_market_category(self) -> None:
        assert categorize_headline("S&P 500 hits new record high") == "market"

    def test_general_fallback(self) -> None:
        assert categorize_headline("Company XYZ announces new product") == "general"


class TestPersistHeadlines:
    def test_persists_headlines(self, db_session) -> None:
        headlines = [
            {
                "headline": "Fed holds rates steady",
                "source": "Reuters",
                "datetime": 1710891600,
                "url": "https://example.com/1",
            },
            {
                "headline": "China tariffs increased",
                "source": "CNBC",
                "datetime": 1710895200,
                "url": None,
            },
        ]
        with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
            count = persist_headlines(headlines, cycle_id="test_cycle")
        assert count == 2
        rows = db_session.query(MacroHeadline).all()
        assert len(rows) == 2
        assert rows[0].category == "fed"
        assert rows[1].category == "trade"
        assert rows[0].cycle_id == "test_cycle"

    def test_deduplicates_headlines(self, db_session) -> None:
        headlines = [
            {"headline": "Fed holds rates", "source": "Reuters", "datetime": 1710891600},
        ]
        with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
            count1 = persist_headlines(headlines)
            count2 = persist_headlines(headlines)  # Same headline again
        assert count1 == 1
        assert count2 == 0
        assert db_session.query(MacroHeadline).count() == 1

    def test_empty_headlines(self, db_session) -> None:
        with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
            count = persist_headlines([])
        assert count == 0

    def test_handles_missing_fields(self, db_session) -> None:
        headlines = [
            {"headline": "Some news", "source": "BBC"},  # No datetime, no url
        ]
        with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
            count = persist_headlines(headlines)
        assert count == 1
        row = db_session.query(MacroHeadline).first()
        assert row.headline == "Some news"
        assert row.url is None

    def test_skips_empty_headline_text(self, db_session) -> None:
        headlines = [
            {"headline": "", "source": "Reuters", "datetime": 1710891600},
            {"source": "CNBC", "datetime": 1710891600},  # No headline key
        ]
        with patch("src.agents.market_data.macro_intelligence.get_session", return_value=db_session):
            count = persist_headlines(headlines)
        assert count == 0
