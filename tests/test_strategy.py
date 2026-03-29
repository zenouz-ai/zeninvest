"""Tests for the strategy agent — sub-strategies and engine."""

import pytest
import json
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base
from src.agents.strategy.momentum import evaluate_momentum
from src.agents.strategy.mean_reversion import evaluate_mean_reversion
from src.agents.strategy.factor import calculate_factor_score, rank_by_factor
from src.agents.strategy.engine import StrategyEngine
from src.agents.strategy.prompts import STRATEGY_SYSTEM_PROMPT, build_strategy_prompt


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.agents.strategy.engine.get_session", return_value=db_session):
        yield


def _good_momentum_indicators():
    """Indicators matching the cleaned output of calculate_indicators()."""
    return {
        "current_price": 175.0,
        "rsi_14": 60.0,
        "macd_histogram": 0.5,
        "macd_bullish_crossover": True,
        "macd_bearish_crossover": False,
        "below_lower_bb": False,
        "above_50ma": True,
        "ma_20": 170.0,
        "obv": 25000000.0,
        "obv_rising_5d": False,
        "volume_sma_20": 1500000.0,
        "volume_sma_ratio_20": 1.0,
    }


def _oversold_indicators():
    """Indicators for an oversold stock (mean reversion candidate)."""
    return {
        "current_price": 120.0,
        "rsi_14": 25.0,
        "macd_histogram": -0.5,
        "macd_bullish_crossover": False,
        "macd_bearish_crossover": False,
        "below_lower_bb": True,
        "above_50ma": False,
        "ma_20": 130.0,
        "obv": -12000000.0,
        "obv_rising_5d": False,
        "volume_sma_20": 900000.0,
        "volume_sma_ratio_20": 1.0,
    }


def _good_fundamentals():
    """Fundamentals matching the cleaned output of get_fundamentals()."""
    return {
        "trailing_pe": 18.0,
        "pb_ratio": 2.5,
        "roe": 0.25,
        "profit_margin": 0.22,
        "debt_equity": 0.8,
        "earnings_growth": 0.15,
        "earnings_momentum_qoq": 0.10,
        "sector": "Technology",
    }


class TestMomentum:
    def test_strong_buy_signal(self):
        signal = evaluate_momentum("AAPL", _good_momentum_indicators(), 1.15)
        assert signal.action == "BUY"
        assert signal.score >= 75

    def test_weak_signal_below_ma(self):
        indicators = _good_momentum_indicators()
        indicators["above_50ma"] = False
        signal = evaluate_momentum("AAPL", indicators, 0.8)
        assert signal.action == "HOLD"

    def test_overbought_held_position_becomes_caution_hold(self):
        indicators = _good_momentum_indicators()
        indicators["rsi_14"] = 85.0
        signal = evaluate_momentum("AAPL", indicators, 1.1, current_holding=True)
        assert signal.action == "HOLD"
        assert "Momentum caution" in signal.reasoning

    def test_below_ma_held_position_becomes_caution_hold(self):
        indicators = _good_momentum_indicators()
        indicators["above_50ma"] = False
        signal = evaluate_momentum("AAPL", indicators, 1.1, current_holding=True)
        assert signal.action == "HOLD"

    def test_macd_bearish_held_position_becomes_caution_hold(self):
        indicators = _good_momentum_indicators()
        indicators["macd_bearish_crossover"] = True
        signal = evaluate_momentum("AAPL", indicators, 1.1, current_holding=True)
        assert signal.action == "HOLD"

    def test_error_indicators(self):
        signal = evaluate_momentum("AAPL", {"error": "no data"}, None)
        assert signal.action == "HOLD"
        assert signal.score == 0

    def test_high_volume_breakout_can_promote_hold_to_buy(self):
        indicators = _good_momentum_indicators()
        indicators["macd_bullish_crossover"] = False
        indicators["volume_sma_ratio_20"] = 1.8
        indicators["obv_rising_5d"] = True
        signal = evaluate_momentum("AAPL", indicators, 0.8)
        assert signal.action == "BUY"
        assert "High-volume breakout" in signal.reasoning
        assert "OBV rising" in signal.reasoning

    def test_low_volume_penalizes_momentum_score(self):
        indicators = _good_momentum_indicators()
        indicators["macd_bullish_crossover"] = False
        indicators["volume_sma_ratio_20"] = 0.4
        signal = evaluate_momentum("AAPL", indicators, 0.95)
        assert signal.action == "HOLD"
        assert signal.score == 60
        assert "Volume below 50% avg" in signal.reasoning


class TestMeanReversion:
    def test_buy_oversold_good_fundamentals(self):
        signal = evaluate_mean_reversion(
            "XYZ", _oversold_indicators(), _good_fundamentals(), sector_avg_pe=22.0,
        )
        assert signal.action == "BUY"
        assert signal.score >= 70

    def test_no_buy_bad_fundamentals(self):
        bad_fund = _good_fundamentals()
        bad_fund["debt_equity"] = 3.0
        bad_fund["earnings_growth"] = -0.30
        signal = evaluate_mean_reversion("XYZ", _oversold_indicators(), bad_fund)
        assert signal.action == "HOLD"

    def test_recovery_target_becomes_caution_hold(self):
        indicators = _oversold_indicators()
        indicators["current_price"] = 135.0  # Above 20-day MA of 130
        signal = evaluate_mean_reversion(
            "XYZ", indicators, _good_fundamentals(), current_holding=True,
        )
        assert signal.action == "HOLD"

    def test_rsi_recovered_becomes_caution_hold(self):
        indicators = _oversold_indicators()
        indicators["rsi_14"] = 65.0
        signal = evaluate_mean_reversion(
            "XYZ", indicators, _good_fundamentals(), current_holding=True,
        )
        assert signal.action == "HOLD"

    def test_volume_confirmation_can_promote_mean_reversion_buy(self):
        indicators = _oversold_indicators()
        indicators["volume_sma_ratio_20"] = 1.4
        fundamentals = _good_fundamentals()
        fundamentals["earnings_growth"] = None
        fundamentals["trailing_pe"] = None
        signal = evaluate_mean_reversion("XYZ", indicators, fundamentals, sector_avg_pe=None)
        assert signal.action == "BUY"
        assert signal.score == 75
        assert "above-average volume" in signal.reasoning


class TestFactor:
    def test_high_quality_stock(self):
        score = calculate_factor_score(
            "AAPL",
            _good_fundamentals(),
            _good_momentum_indicators(),
            relative_strength=1.15,
            six_month_return=0.25,
        )
        assert score.composite_score > 60
        assert score.quality_score > 50
        assert score.momentum_score > 50

    def test_value_trap(self):
        fund = _good_fundamentals()
        fund["trailing_pe"] = 5.0  # Looks cheap
        fund["roe"] = -0.05  # But negative returns
        fund["profit_margin"] = -0.10  # Losing money
        score = calculate_factor_score(
            "XYZ", fund, _good_momentum_indicators(), relative_strength=0.7,
        )
        assert score.quality_score < 50

    def test_ranking(self):
        scores = [
            calculate_factor_score(f"STOCK{i}", _good_fundamentals(), _good_momentum_indicators(), 1.0)
            for i in range(20)
        ]
        # Manually adjust one to be best
        scores[5] = calculate_factor_score(
            "BEST", _good_fundamentals(), _good_momentum_indicators(), 1.3, 0.30,
        )
        top = rank_by_factor(scores, top_n=5)
        assert len(top) == 5
        assert top[0].ticker == "BEST"


class TestPrompts:
    def test_profit_gated_hold_friendly_prompt_language(self):
        assert "conviction-led stock picker" in STRATEGY_SYSTEM_PROMPT.lower()
        assert "underpriced-with-catalyst setups" in STRATEGY_SYSTEM_PROMPT
        assert "SELL vs REDUCE" in STRATEGY_SYSTEM_PROMPT
        assert "EXIT TRIGGER TYPE" in STRATEGY_SYSTEM_PROMPT

    def test_build_prompt(self):
        prompt = build_strategy_prompt(
            portfolio_state="Cash: £5000, Positions: AAPL 10%",
            market_regime="BULL",
            momentum_proposals="- AAPL: BUY (score 80)",
            mean_reversion_proposals="None",
            factor_proposals="- AAPL: composite=75",
            analyst_data="AAPL: Buy consensus, 10 analysts",
            news_sentiment="AAPL: bullish 60%, 5 articles",
            macro_context="Regime: RISK_ON",
            company_profiles="**AAPL** (Apple Inc) | Consumer Electronics\nDesigns and sells smartphones and computers.",
            entry_quality_guards="- AAPL_US_EQ: earnings 2026-04-30 (3 trading days, imminent) | avg corr 0.65 (high overlap) vs MSFT_US_EQ 0.72",
            tickers_to_decide="AAPL_US_EQ",
            system_state="ACTIVE",
            vix=18.0,
            cash_pct=50.0,
            max_position_pct=15.0,
            num_positions=3,
            max_positions=15,
            momentum_weight=0.35,
            mean_reversion_weight=0.30,
            factor_weight=0.35,
        )
        assert "AAPL" in prompt
        assert "BULL" in prompt
        assert "50.0%" in prompt
        assert "ENTRY QUALITY GUARDS" in prompt
        assert '"expected_holding_period": "5-30 trading days"' in prompt

    def test_cautious_mode_prompt(self):
        prompt = build_strategy_prompt(
            portfolio_state="Test",
            market_regime="SIDEWAYS",
            momentum_proposals="None",
            mean_reversion_proposals="None",
            factor_proposals="None",
            analyst_data="None",
            news_sentiment="None",
            macro_context="No proactive macro state available.",
            company_profiles="No profiles available.",
            entry_quality_guards="No entry-quality guardrail data available.",
            tickers_to_decide="TICK1, TICK2",
            system_state="CAUTIOUS",
            vix=28.0,
            cash_pct=20.0,
            max_position_pct=8.0,
            num_positions=8,
            max_positions=15,
            momentum_weight=0.35,
            mean_reversion_weight=0.30,
            factor_weight=0.35,
        )
        assert "CAUTIOUS" in prompt
        assert "No new positions" in prompt


class TestStrategyEngine:
    def test_run_sub_strategies(self):
        engine = StrategyEngine()
        stocks = [
            {
                "ticker": "AAPL",
                "indicators": _good_momentum_indicators(),
                "fundamentals": _good_fundamentals(),
                "relative_strength_6m": 1.1,
                "six_month_return": 0.15,
            },
        ]
        results = engine.run_sub_strategies(stocks, existing_positions=set())
        assert len(results["momentum"]) == 1
        assert len(results["mean_reversion"]) == 1
        assert len(results["factor"]) == 1

    def test_strategy_prompt_formatters_respect_max_candidates_setting(self):
        engine = StrategyEngine()
        engine.settings._config.setdefault("universe", {})["max_candidates"] = 40

        momentum_signals = [
            MagicMock(ticker=f"SIG{i}", action="BUY", score=100 - i, reasoning=f"momentum {i}")
            for i in range(45)
        ]
        mean_reversion_signals = [
            MagicMock(ticker=f"MR{i}", action="HOLD", score=90 - i, reasoning=f"mean reversion {i}")
            for i in range(45)
        ]
        factor_scores = [
            MagicMock(
                ticker=f"FAC{i}",
                composite_score=80 - i,
                value_score=70 - i,
                quality_score=75 - i,
                momentum_score=65 - i,
                reasoning=f"factor {i}",
            )
            for i in range(45)
        ]

        momentum_text = engine._format_momentum_proposals(momentum_signals)
        mean_reversion_text = engine._format_mean_reversion_proposals(mean_reversion_signals)
        factor_text = engine._format_factor_proposals(factor_scores)

        assert momentum_text.count("\n") + 1 == 40
        assert mean_reversion_text.count("\n") + 1 == 40
        assert factor_text.count("\n") + 1 == 40
        assert "SIG40" not in momentum_text
        assert "MR40" not in mean_reversion_text
        assert "FAC40" not in factor_text

    @patch("src.agents.strategy.engine.check_budget", return_value=True)
    @patch("src.agents.strategy.engine.log_cost")
    def test_synthesize_with_claude(self, mock_log_cost, mock_budget, db_session):
        engine = StrategyEngine()
        engine.settings._config.setdefault("research", {})["enabled"] = False

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "market_assessment": "Bullish market conditions",
            "decisions": [{
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "target_allocation_pct": 5.0,
                "conviction": 78,
                "primary_strategy": "momentum",
                "reasoning": "Strong momentum confirmed by news",
                "growth_potential": "HIGH",
                "risk_level": "MEDIUM",
                "catalysts": ["AI growth"],
                "risks": ["Valuation"],
                "exit_conditions": "RSI > 80",
                "upside_target_pct": 15.0,
                "stop_loss_pct": -8.0,
                "expected_holding_period": "3-6 months",
                "news_sentiment_summary": "Positive sentiment",
            }],
            "portfolio_commentary": "Bullish positioning",
        })
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 2000
        mock_response.usage.output_tokens = 500

        engine._client = MagicMock()
        engine._client.messages.create.return_value = mock_response

        sub_results = {
            "momentum": [],
            "mean_reversion": [],
            "factor": [],
            "top_factor": [],
        }

        result = engine.synthesize_with_claude(
            sub_strategy_results=sub_results,
            portfolio_state="Cash: £5000",
            market_regime="BULL",
            analyst_data="Positive analyst consensus",
            news_sentiment="Bullish news sentiment",
            macro_context="Regime: RISK_ON",
            company_profiles="**AAPL** (Apple Inc) | Consumer Electronics\nDesigns and sells smartphones.",
            entry_quality_guards="- AAPL_US_EQ: earnings 2026-04-30 (3 trading days, imminent)",
            system_state="ACTIVE",
            vix=18.0,
            cash_pct=50.0,
            num_positions=3,
            cycle_id="test-cycle",
        )

        assert "decisions" in result
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["ticker"] == "AAPL_US_EQ"
