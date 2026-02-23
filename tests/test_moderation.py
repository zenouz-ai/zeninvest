"""Tests for the moderation panel."""

import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models import Base
from src.agents.moderation.panel import ModerationPanel, ModerationResult
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

    def test_high_risk_plus_disagree(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "AGREE", "high_risk_flag": True},
            conviction=78,
            moderators_available=2,
        )
        assert result == "BLOCKED"

    def test_high_risk_via_scores(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result={"verdict": "DISAGREE"},
            gemini_result={"verdict": "AGREE", "risk_score": 8, "growth_score": 4},
            conviction=78,
            moderators_available=2,
        )
        assert result == "BLOCKED"

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
            conviction=60,
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

    def test_zero_moderators_low_conviction(self, panel):
        result = panel._determine_consensus(
            strategy_verdict="AGREE",
            gpt4o_result=None,
            gemini_result=None,
            conviction=70,
            moderators_available=0,
        )
        assert result == "BLOCKED"


class TestFullReview:
    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    @patch("src.agents.moderation.panel.gemini_mod.review_trade")
    def test_full_approval(self, mock_gemini, mock_openai, mock_degradation, panel, sample_proposal):
        mock_degradation.return_value = DegradationLevel.FULL
        mock_openai.return_value = {"verdict": "AGREE", "reasoning": "Looks good", "available": True}
        mock_gemini.return_value = {
            "verdict": "AGREE", "growth_score": 7, "risk_score": 4,
            "confidence_score": 7, "assessment": "Solid thesis", "available": True,
        }

        result = panel.review_trade(
            sample_proposal, "Portfolio context", "Sentiment data", 78, "cycle-1",
        )
        assert result.consensus == "APPROVED"
        assert result.moderators_available == 2

    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    @patch("src.agents.moderation.panel.gemini_mod.review_trade")
    def test_blocked_by_both(self, mock_gemini, mock_openai, mock_degradation, panel, sample_proposal):
        mock_degradation.return_value = DegradationLevel.FULL
        mock_openai.return_value = {"verdict": "DISAGREE", "reasoning": "Too risky", "available": True}
        mock_gemini.return_value = {
            "verdict": "DISAGREE", "growth_score": 3, "risk_score": 8,
            "confidence_score": 3, "assessment": "Poor thesis", "available": True,
        }

        result = panel.review_trade(
            sample_proposal, "Portfolio context", "Sentiment data", 78, "cycle-1",
        )
        assert result.consensus == "BLOCKED"

    @patch("src.agents.moderation.panel.get_degradation_level")
    def test_no_moderators_fallback(self, mock_degradation, panel, sample_proposal):
        mock_degradation.return_value = DegradationLevel.HALTED
        sample_proposal["conviction"] = 90

        result = panel.review_trade(
            sample_proposal, "Portfolio context", "Sentiment data", 90, "cycle-1",
        )
        assert result.moderators_available == 0
        assert result.consensus == "APPROVED"  # conviction 90 > 85

    @patch("src.agents.moderation.panel.get_degradation_level")
    @patch("src.agents.moderation.panel.openai_mod.review_trade")
    def test_single_moderator(self, mock_openai, mock_degradation, panel, sample_proposal):
        mock_degradation.return_value = DegradationLevel.NO_GEMINI
        mock_openai.return_value = {"verdict": "AGREE", "reasoning": "Good", "available": True}

        result = panel.review_trade(
            sample_proposal, "Portfolio context", "Sentiment data", 80, "cycle-1",
        )
        assert result.moderators_available == 1
        assert result.consensus == "APPROVED"
