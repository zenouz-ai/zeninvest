"""Tests for Universal Opportunity Value scoring."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.opportunity.scorer import OpportunityScorer
from src.data.models import Base


@pytest.fixture
def db_session():
    """Create in-memory SQLite DB session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    """Patch scorer DB session factory."""
    with patch("src.agents.opportunity.scorer.get_session", return_value=db_session):
        yield


def _sub_results():
    return {
        "momentum": [
            SimpleNamespace(ticker="AAPL_US_EQ", score=82),
            SimpleNamespace(ticker="GOOG_US_EQ", score=68),
            SimpleNamespace(ticker="MSFT_US_EQ", score=55),
        ],
        "mean_reversion": [
            SimpleNamespace(ticker="AAPL_US_EQ", score=60),
            SimpleNamespace(ticker="GOOG_US_EQ", score=40),
            SimpleNamespace(ticker="MSFT_US_EQ", score=30),
        ],
        "factor": [
            SimpleNamespace(ticker="AAPL_US_EQ", composite_score=78, quality_score=81, value_score=62),
            SimpleNamespace(ticker="GOOG_US_EQ", composite_score=52, quality_score=48, value_score=54),
            SimpleNamespace(ticker="MSFT_US_EQ", composite_score=50, quality_score=50, value_score=50),
        ],
    }


def _stocks_data():
    return [
        {"ticker": "AAPL_US_EQ", "fundamentals": {"market_cap": 3_000_000_000_000}},
        {"ticker": "GOOG_US_EQ", "fundamentals": {"market_cap": 2_000_000_000_000}},
        {"ticker": "MSFT_US_EQ", "fundamentals": {"market_cap": 2_500_000_000_000}},
    ]


def test_score_cycle_tradable_and_reject_floor():
    scorer = OpportunityScorer()
    evaluations = [
        {
            "ticker": "AAPL_US_EQ",
            "action": "BUY",
            "stage": "approved",
            "decision": {"conviction": 84, "expected_holding_period": "3-6 months"},
            "moderation": {
                "gpt4o_verdict": {"verdict": "AGREE"},
                "gemini_verdict": {"growth_score": 8, "risk_score": 4, "confidence_score": 7},
            },
            "moderation_consensus": "APPROVED",
            "risk_verdict": "APPROVE",
            "reason": "strong setup",
            "final_allocation_pct": 6.0,
        },
        {
            "ticker": "GOOG_US_EQ",
            "action": "BUY",
            "stage": "risk_reject",
            "decision": {"conviction": 77, "expected_holding_period": "3 months"},
            "moderation": {
                "gpt4o_verdict": {"verdict": "AGREE"},
                "gemini_verdict": {"growth_score": 7, "risk_score": 6, "confidence_score": 6},
            },
            "moderation_consensus": "CAUTION",
            "risk_verdict": "REJECT",
            "reason": "risk reject",
            "final_allocation_pct": None,
        },
        {
            "ticker": "MSFT_US_EQ",
            "action": "HOLD",
            "stage": "strategy_hold",
            "decision": {"conviction": 60, "expected_holding_period": "1 month"},
            "moderation": {},
            "moderation_consensus": None,
            "risk_verdict": None,
            "reason": "hold",
            "final_allocation_pct": None,
        },
    ]

    scored = scorer.score_cycle(
        cycle_id="cycle_1",
        evaluations=evaluations,
        sub_results=_sub_results(),
        stocks_data=_stocks_data(),
        per_ticker_news={
            "AAPL": "Ticker avg sentiment: +0.250 (Bullish: 3, Bearish: 0, Articles: 4)",
            "GOOG": "Ticker avg sentiment: -0.150 (Bullish: 1, Bearish: 2, Articles: 3)",
        },
    )
    by_ticker = {s.ticker: s for s in scored}

    assert by_ticker["AAPL_US_EQ"].is_tradable is True
    assert by_ticker["AAPL_US_EQ"].uov_final > 0
    assert by_ticker["GOOG_US_EQ"].is_tradable is False
    assert by_ticker["GOOG_US_EQ"].uov_final <= 0
    assert by_ticker["MSFT_US_EQ"].uov_final <= 0


def test_score_cycle_ewma_uses_previous_value():
    scorer = OpportunityScorer()
    evaluations = [
        {
            "ticker": "AAPL_US_EQ",
            "action": "BUY",
            "stage": "approved",
            "decision": {"conviction": 80, "expected_holding_period": "3-6 months"},
            "moderation": {
                "gpt4o_verdict": {"verdict": "AGREE"},
                "gemini_verdict": {"growth_score": 8, "risk_score": 4, "confidence_score": 7},
            },
            "moderation_consensus": "APPROVED",
            "risk_verdict": "APPROVE",
            "reason": "first",
            "final_allocation_pct": 6.0,
        },
    ]

    first = scorer.score_cycle(
        cycle_id="cycle_1",
        evaluations=evaluations,
        sub_results=_sub_results(),
        stocks_data=_stocks_data(),
        per_ticker_news={"AAPL": "Ticker avg sentiment: +0.200 (Bullish: 2, Bearish: 0, Articles: 2)"},
    )
    second = scorer.score_cycle(
        cycle_id="cycle_2",
        evaluations=evaluations,
        sub_results=_sub_results(),
        stocks_data=_stocks_data(),
        per_ticker_news={"AAPL": "Ticker avg sentiment: +0.200 (Bullish: 2, Bearish: 0, Articles: 2)"},
    )

    assert len(first) == 1
    assert len(second) == 1
    assert second[0].previous_uov_ewma == pytest.approx(first[0].uov_ewma)
