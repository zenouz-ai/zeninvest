"""Tests for batched strategy synthesis and token helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.strategy.engine import StrategyEngine
from src.agents.strategy.momentum import MomentumSignal
from src.agents.strategy.mean_reversion import MeanReversionSignal
from src.agents.strategy.factor import FactorScore
from src.data.models import Base


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
    with patch("src.agents.strategy.engine.get_session", return_value=db_session):
        yield


def _sub_results(tickers: list[str]) -> dict:
    momentum = [
        MomentumSignal(ticker=t, action="HOLD", score=50.0, reasoning="test", indicators={})
        for t in tickers
    ]
    mean_reversion = [
        MeanReversionSignal(
            ticker=t, action="HOLD", score=40.0, reasoning="test", indicators={}, fundamentals={},
        )
        for t in tickers
    ]
    factor = [
        FactorScore(
            ticker=t,
            composite_score=45.0,
            value_score=40.0,
            quality_score=50.0,
            momentum_score=45.0,
            reasoning="test",
            components={},
        )
        for t in tickers
    ]
    return {
        "momentum": momentum,
        "mean_reversion": mean_reversion,
        "factor": factor,
        "top_factor": factor,
    }


def test_estimate_max_tokens_scales_with_tickers():
    assert StrategyEngine._estimate_max_tokens(1) >= 1024
    assert StrategyEngine._estimate_max_tokens(50) <= 8192


def test_canonical_ranked_tickers_orders_by_score():
    engine = StrategyEngine()
    subs = _sub_results(["LOW_US_EQ", "HIGH_US_EQ"])
    subs["momentum"][0].score = 10.0
    subs["momentum"][1].score = 90.0
    ranked = engine._canonical_ranked_tickers(subs)
    assert ranked[0] == "HIGH_US_EQ"


@patch.object(StrategyEngine, "_run_synthesis_for_tickers")
def test_batched_synthesis_merges_positions_and_candidates(mock_run):
    engine = StrategyEngine()
    mock_run.side_effect = [
        {"decisions": [{"ticker": "AAPL_US_EQ", "action": "HOLD", "conviction": 50, "exit_trigger_type": "none"}], "market_assessment": "pos"},
        {"decisions": [{"ticker": "MSFT_US_EQ", "action": "BUY", "conviction": 80, "exit_trigger_type": "none", "target_allocation_pct": 5.0}], "market_assessment": "cand"},
    ]
    subs = _sub_results(["AAPL_US_EQ", "MSFT_US_EQ"])
    result = engine.synthesize_with_claude_batched(
        sub_strategy_results=subs,
        portfolio_state="{}",
        market_regime="BULL",
        analyst_data="",
        news_sentiment="",
        macro_context="",
        company_profiles="",
        entry_quality_guards="",
        system_state="ACTIVE",
        vix=None,
        cash_pct=10.0,
        num_positions=1,
        cycle_id="test_cycle",
        position_tickers=["AAPL_US_EQ"],
        candidate_tickers=["MSFT_US_EQ"],
    )
    assert len(result["decisions"]) == 2
    assert mock_run.call_count == 2


@patch.object(StrategyEngine, "_run_synthesis_for_tickers")
def test_batched_positions_failure_returns_error(mock_run):
    engine = StrategyEngine()
    mock_run.return_value = {"error": "json_truncated", "decisions": [], "batch": "positions"}
    subs = _sub_results(["AAPL_US_EQ"])
    result = engine.synthesize_with_claude_batched(
        sub_strategy_results=subs,
        portfolio_state="{}",
        market_regime="BULL",
        analyst_data="",
        news_sentiment="",
        macro_context="",
        company_profiles="",
        entry_quality_guards="",
        system_state="ACTIVE",
        vix=None,
        cash_pct=10.0,
        num_positions=1,
        cycle_id="test_cycle",
        position_tickers=["AAPL_US_EQ"],
        candidate_tickers=["MSFT_US_EQ"],
    )
    assert result.get("error") == "json_truncated"


def test_repair_truncated_json_salvages_partial_decisions():
    partial = (
        '{"market_assessment": "ok", "decisions": ['
        '{"ticker": "AAPL_US_EQ", "action": "HOLD", "conviction": 50, '
        '"exit_trigger_type": "none", "reasoning": "hold"}'
    )
    result = StrategyEngine._repair_truncated_json(partial)
    assert result is not None
    assert len(result.get("decisions", [])) >= 1


def test_merge_batch_results_combines_decisions():
    left = {"decisions": [{"ticker": "A"}], "portfolio_commentary": "left"}
    right = {"decisions": [{"ticker": "B"}], "portfolio_commentary": "right"}
    merged = StrategyEngine._merge_batch_results(left, right)
    assert len(merged["decisions"]) == 2


def test_strategy_output_json_schema_anthropic_compatible():
    from src.agents.strategy.engine import STRATEGY_OUTPUT_JSON_SCHEMA

    assert STRATEGY_OUTPUT_JSON_SCHEMA["additionalProperties"] is False
    decision_schema = STRATEGY_OUTPUT_JSON_SCHEMA["properties"]["decisions"]["items"]
    assert decision_schema["additionalProperties"] is False
    assert "ticker" in decision_schema["properties"]
