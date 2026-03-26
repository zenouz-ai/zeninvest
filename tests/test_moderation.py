"""Tests for the moderation panel."""

import json
import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base
from src.agents.moderation.panel import ModerationPanel, ModerationResult
from src.agents.moderation.context import format_market_context
from src.agents.moderation.openai_mod import _normalize_openai_result
from src.agents.moderation.gemini_mod import _normalize_gemini_result
from src.utils.cost_tracker import DegradationLevel


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_db(db_session):
    with patch("src.agents.moderation.panel.get_session", return_value=db_session):
        with patch("src.utils.cost_tracker.get_session", return_value=db_session):
            yield


@pytest.fixture
def panel():
    return ModerationPanel()


@pytest.fixture
def sample_proposal():
    return {
        "ticker": "AAPL_US_EQ",
        "action": "BUY",
        "target_allocation_pct": 5.0,
        "conviction": 78,
        "reasoning": "Strong momentum with good fundamentals",
    }


@pytest.fixture
def sample_market_context():
    """Rich market context dict matching the new moderator API."""
    return {
        "indicators": {
            "current_price": 185.50,
            "rsi_14": 55.3,
            "macd_histogram": 0.45,
            "macd_bullish_crossover": False,
            "macd_bearish_crossover": False,
            "above_50ma": True,
            "below_lower_bb": False,
            "ma_20": 183.20,
            "obv": 24500000.0,
            "obv_rising_5d": True,
            "volume_sma_ratio_20": 1.65,
        },
        "fundamentals": {
            "trailing_pe": 28.5,
            "pb_ratio": 45.0,
            "roe": 0.175,
            "profit_margin": 0.265,
            "debt_equity": 1.76,
            "earnings_growth": 0.08,
            "earnings_momentum_qoq": 0.05,
            "sector": "Technology",
            "market_cap": 2800000000000,
        },
        "macro": {
            "vix": 18.5,
            "market_regime": "BULL",
            "sp500_above_200ma": True,
            "proactive_regime": "RISK_ON",
            "proactive_confidence": 0.82,
            "proactive_top_signals": [{"signal_type": "volatility", "signal_text": "VIX at 18.5"}],
            "macro_action_plan": {"summary": "Constructive backdrop with selective tech tailwinds."},
        },
        "sub_strategies": {
            "momentum": {"action": "BUY", "score": 72, "reasoning": "RSI in sweet spot | Above 50MA | RS vs S&P: 1.12"},
            "mean_reversion": {"action": "HOLD", "score": 15, "reasoning": "No mean reversion opportunity"},
            "factor": {
                "composite_score": 58.0,
                "value_score": 30.0,
                "quality_score": 65.0,
                "momentum_score": 72.0,
                "reasoning": "Strong margins (26.5%) | RS vs S&P: 1.12",
            },
        },
        "analyst_data": {
            "recommendation": {"buy": 30, "hold": 8, "sell": 2, "consensus": "BUY"},
            "insider": {"mspr": 0.15},
        },
        "news_sentiment": "[Bullish +0.234] Apple reports record Q1 revenue (Reuters)",
    }


class TestConsensusLogic:
    def test_all_agree(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "AGREE"},
            gemini_result={"verdict": "AGREE"},
            conviction=78,
            moderators_available=2,
        )
        assert result == "APPROVED"

    def test_two_agree_one_disagree(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "AGREE"},
            gemini_result={"verdict": "DISAGREE"},
            conviction=78,
            moderators_available=2,
        )
        assert result == "CAUTION"

    def test_two_disagree(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "DISAGREE"},
            conviction=78,
            moderators_available=2,
        )
        assert result == "BLOCKED"

    def test_high_risk_plus_one_disagree_is_caution(self, panel):
        """High risk + single moderator disagree → CAUTION (not BLOCKED)."""
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "AGREE", "high_risk_flag": True},
            conviction=78,
            moderators_available=2,
        )
        assert result == "CAUTION"

    def test_high_risk_plus_both_disagree_is_blocked(self, panel):
        """High risk + both moderators disagree → BLOCKED."""
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "DISAGREE", "high_risk_flag": True},
            conviction=78,
            moderators_available=2,
        )
        assert result == "BLOCKED"

    def test_high_risk_via_scores_needs_margin(self, panel):
        """Risk must exceed growth by >2 to trigger high_risk flag."""
        # risk=8, growth=4 → diff=4 > 2 → high_risk, but only 1 disagree → CAUTION
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "AGREE", "risk_score": 8, "growth_score": 4},
            conviction=78,
            moderators_available=2,
        )
        assert result == "CAUTION"

    def test_risk_slightly_above_growth_no_flag(self, panel):
        """Risk exceeding growth by <=2 does NOT trigger high_risk."""
        # risk=6, growth=5 → diff=1 ≤ 2 → no high_risk → normal 2/3 agree → CAUTION
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "AGREE", "risk_score": 6, "growth_score": 5},
            conviction=78,
            moderators_available=2,
        )
        assert result == "CAUTION"

    def test_one_moderator_agree_high_conviction(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "AGREE"},
            gemini_result=None,
            conviction=80,
            moderators_available=1,
        )
        assert result == "APPROVED"

    def test_one_moderator_agree_low_conviction(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "AGREE"},
            gemini_result=None,
            conviction=55,
            moderators_available=1,
        )
        assert result == "CAUTION"

    def test_one_moderator_disagree(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result=None,
            conviction=90,
            moderators_available=1,
        )
        assert result == "BLOCKED"

    def test_zero_moderators_high_conviction(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result=None,
            gemini_result=None,
            conviction=90,
            moderators_available=0,
        )
        assert result == "APPROVED"


class TestModeratorNormalization:
    def test_openai_normalizes_dict_modifications(self):
        result = _normalize_openai_result(
            {
                "verdict": "MODIFY",
                "confidence_score": 7,
                "reasoning": "Trim size",
                "modifications": {"target_allocation_pct": "5.5", "stop_loss_pct": -6},
            },
            ticker="AAPL_US_EQ",
            cycle_id="cycle-test",
        )
        assert result["modifications"] == {"target_allocation_pct": 5.5, "stop_loss_pct": -6.0}

    def test_openai_parses_json_string_modifications(self):
        result = _normalize_openai_result(
            {
                "verdict": "MODIFY",
                "confidence_score": 7,
                "reasoning": "Trim size",
                "modifications": json.dumps({"target_allocation_pct": 4.0}),
            },
            ticker="AAPL_US_EQ",
            cycle_id="cycle-test",
        )
        assert result["modifications"] == {"target_allocation_pct": 4.0}

    def test_openai_drops_plain_string_modifications(self, caplog):
        result = _normalize_openai_result(
            {
                "verdict": "MODIFY",
                "confidence_score": 7,
                "reasoning": "Trim size",
                "modifications": "reduce allocation to 5%",
            },
            ticker="AAPL_US_EQ",
            cycle_id="cycle-test",
        )
        assert result["modifications"] is None
        assert "Ignoring malformed gpt-4o modifications" in caplog.text

    @pytest.mark.parametrize("raw_value", [[1, 2, 3], 9])
    def test_openai_drops_non_dict_modifications(self, raw_value, caplog):
        result = _normalize_openai_result(
            {
                "verdict": "MODIFY",
                "confidence_score": 7,
                "reasoning": "Trim size",
                "modifications": raw_value,
            },
            ticker="AAPL_US_EQ",
            cycle_id="cycle-test",
        )
        assert result["modifications"] is None
        assert "Ignoring malformed gpt-4o modifications" in caplog.text

    def test_gemini_normalizes_dict_modifications(self):
        result = _normalize_gemini_result(
            {
                "verdict": "MODIFY",
                "growth_score": 7,
                "risk_score": 5,
                "confidence_score": 6,
                "assessment": "Reduce size",
                "modifications": {"stop_loss_pct": "-5.5"},
            },
            ticker="MSFT_US_EQ",
            cycle_id="cycle-test",
            moderator="gemini-2.5-flash",
        )
        assert result["modifications"] == {"stop_loss_pct": -5.5}

    def test_gemini_parses_json_string_modifications(self):
        result = _normalize_gemini_result(
            {
                "verdict": "MODIFY",
                "growth_score": 7,
                "risk_score": 5,
                "confidence_score": 6,
                "assessment": "Reduce size",
                "modifications": json.dumps({"target_allocation_pct": 3}),
            },
            ticker="MSFT_US_EQ",
            cycle_id="cycle-test",
            moderator="gemini-2.5-flash",
        )
        assert result["modifications"] == {"target_allocation_pct": 3.0}

    def test_gemini_drops_plain_string_modifications(self, caplog):
        result = _normalize_gemini_result(
            {
                "verdict": "MODIFY",
                "growth_score": 7,
                "risk_score": 5,
                "confidence_score": 6,
                "assessment": "Reduce size",
                "modifications": "tighten stop to -5%",
            },
            ticker="MSFT_US_EQ",
            cycle_id="cycle-test",
            moderator="gemini-2.5-flash",
        )
        assert result["modifications"] is None
        assert "Ignoring malformed gemini-2.5-flash modifications" in caplog.text

    @pytest.mark.parametrize("raw_value", [[1, 2, 3], 9])
    def test_gemini_drops_non_dict_modifications(self, raw_value, caplog):
        result = _normalize_gemini_result(
            {
                "verdict": "MODIFY",
                "growth_score": 7,
                "risk_score": 5,
                "confidence_score": 6,
                "assessment": "Reduce size",
                "modifications": raw_value,
            },
            ticker="MSFT_US_EQ",
            cycle_id="cycle-test",
            moderator="gemini-2.5-flash",
        )
        assert result["modifications"] is None
        assert "Ignoring malformed gemini-2.5-flash modifications" in caplog.text


class TestModerationResultResilience:
    def test_modifications_ignores_malformed_payloads(self, caplog):
        result = ModerationResult(
            ticker="AAPL_US_EQ",
            consensus="CAUTION",
            strategy_verdict="AGREE",
            gpt4o_verdict={"verdict": "MODIFY", "modifications": "reduce allocation to 5%"},
            gemini_verdict={"verdict": "MODIFY", "modifications": {"target_allocation_pct": 4.0}},
            moderators_available=2,
        )

        assert result.modifications == {"target_allocation_pct": 4.0}
        assert "Ignoring malformed gpt-4o modifications" in caplog.text

    def test_zero_moderators_low_conviction(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result=None,
            gemini_result=None,
            conviction=65,
            moderators_available=0,
        )
        assert result == "BLOCKED"


class TestFullReview:
    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    @patch("src.agents.moderation.panel.gemini_mod.review_trade")
    def test_full_approval(
        self, mock_gemini, mock_openai, mock_degradation,
        panel, sample_proposal, sample_market_context,
    ):
        mock_degradation.return_value = DegradationLevel.FULL
        mock_openai.return_value = {"verdict": "AGREE", "reasoning": "Looks good", "available": True}
        mock_gemini.return_value = {
            "verdict": "AGREE", "growth_score": 7, "risk_score": 4,
            "confidence_score": 7, "assessment": "Solid thesis", "available": True,
        }

        result = panel.review_trade(
            sample_proposal, "Portfolio context", sample_market_context, 78, "cycle-1",
        )
        assert result.consensus == "APPROVED"
        assert result.moderators_available == 2

        # Verify moderators received the rich market_context dict
        mock_openai.assert_called_once()
        call_args = mock_openai.call_args
        assert call_args[0][2] == sample_market_context  # 3rd positional arg
        mock_gemini.assert_called_once()
        call_args = mock_gemini.call_args
        assert call_args[0][2] == sample_market_context

    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    @patch("src.agents.moderation.panel.gemini_mod.review_trade")
    def test_blocked_by_both(
        self, mock_gemini, mock_openai, mock_degradation,
        panel, sample_proposal, sample_market_context,
    ):
        mock_degradation.return_value = DegradationLevel.FULL
        mock_openai.return_value = {"verdict": "DISAGREE", "reasoning": "Too risky", "available": True}
        mock_gemini.return_value = {
            "verdict": "DISAGREE", "growth_score": 3, "risk_score": 8,
            "confidence_score": 3, "assessment": "Poor thesis", "available": True,
        }

        result = panel.review_trade(
            sample_proposal, "Portfolio context", sample_market_context, 78, "cycle-1",
        )
        assert result.consensus == "BLOCKED"

    @patch("src.agents.moderation.panel.get_degradation_level")
    def test_no_moderators_fallback(
        self, mock_degradation, panel, sample_proposal, sample_market_context,
    ):
        mock_degradation.return_value = DegradationLevel.HALTED
        sample_proposal["conviction"] = 90

        result = panel.review_trade(
            sample_proposal, "Portfolio context", sample_market_context, 90, "cycle-1",
        )
        assert result.moderators_available == 0
        assert result.consensus == "APPROVED"  # conviction 90 > 70

    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    def test_single_moderator(
        self, mock_openai, mock_degradation,
        panel, sample_proposal, sample_market_context,
    ):
        mock_degradation.return_value = DegradationLevel.NO_GEMINI
        mock_openai.return_value = {"verdict": "AGREE", "reasoning": "Good", "available": True}

        result = panel.review_trade(
            sample_proposal, "Portfolio context", sample_market_context, 80, "cycle-1",
        )
        assert result.moderators_available == 1
        assert result.consensus == "APPROVED"


class TestContextFormatter:
    """Test the shared context formatting logic."""

    def test_format_full_context(self, sample_market_context):
        text = format_market_context(sample_market_context)
        assert "Technical Indicators" in text
        assert "RSI(14): 55.3" in text
        assert "OBV: 24500000" in text
        assert "Volume vs 20-day avg: 1.65x" in text
        assert "Fundamentals" in text
        assert "P/E: 28.5" in text
        assert "Market Conditions" in text
        assert "BULL" in text
        assert "VIX: 18.5" in text
        assert "RISK_ON" in text
        assert "Constructive backdrop" in text
        assert "Sub-Strategy Signals" in text
        assert "Momentum: BUY" in text
        assert "Analyst" in text
        assert "News Sentiment" in text

    def test_format_empty_context(self):
        text = format_market_context({})
        assert text == ""

    def test_format_partial_context(self):
        ctx = {
            "indicators": {"rsi_14": 25.0, "current_price": 100.0},
            "macro": {"vix": 32.0, "market_regime": "BEAR"},
        }
        text = format_market_context(ctx)
        assert "RSI(14): 25.0 (oversold)" in text
        assert "VIX: 32.0 (high)" in text
        assert "BEAR" in text
        # Should not have fundamentals section
        assert "Fundamentals" not in text

    def test_format_indicators_labels(self):
        """Test RSI labels are correctly assigned."""
        # Oversold
        ctx = {"indicators": {"rsi_14": 25.0, "current_price": 50.0}}
        assert "oversold" in format_market_context(ctx)

        # Overbought
        ctx = {"indicators": {"rsi_14": 75.0, "current_price": 50.0}}
        assert "overbought" in format_market_context(ctx)

        # Neutral
        ctx = {"indicators": {"rsi_14": 50.0, "current_price": 50.0}}
        assert "neutral" in format_market_context(ctx)

    def test_format_vix_labels(self):
        """Test VIX severity labels."""
        assert "low" in format_market_context({"macro": {"vix": 12.0}})
        assert "normal" in format_market_context({"macro": {"vix": 18.0}})
        assert "elevated" in format_market_context({"macro": {"vix": 28.0}})
        assert "extreme" in format_market_context({"macro": {"vix": 40.0}})

    def test_format_bollinger_band_oversold_label(self):
        ctx = {"indicators": {"below_lower_bb": True, "current_price": 50.0}}
        text = format_market_context(ctx)
        assert "Yes (oversold)" in text

    def test_format_macd_crossover_signals(self):
        ctx = {"indicators": {"macd_bullish_crossover": True, "current_price": 50.0}}
        text = format_market_context(ctx)
        assert "Bullish crossover (buy signal)" in text

        ctx = {"indicators": {"macd_bearish_crossover": True, "current_price": 50.0}}
        text = format_market_context(ctx)
        assert "Bearish crossover (sell signal)" in text
