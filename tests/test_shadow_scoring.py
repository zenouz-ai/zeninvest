"""Tests for live shadow scoring."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.data.database import engine, get_session
from src.data.models import Base, DecisionShadowScore
from src.learning.evaluation.outcome_join import join_shadow_outcomes, shadow_summary
from src.learning.evaluation.shadow import ShadowEvaluator


@pytest.fixture
def shadow_env(monkeypatch):
    monkeypatch.setenv("INVESTMENT_AGENT_USE_INMEMORY_DB", "1")
    monkeypatch.setenv("DASHBOARD_INSECURE_DEV_MODE", "true")
    monkeypatch.setattr(
        "src.learning.evaluation.shadow.get_settings",
        lambda: type(
            "S",
            (),
            {
                "learning_shadow_scoring_enabled": True,
                "learning_shadow_policies": ["challenger_gbm", "challenger_combined"],
                "learning_gbm_veto_threshold": 0.35,
                "learning_memory_veto_threshold": 0.5,
                "learning_embeddings_enabled": False,
            },
        )(),
    )
    Base.metadata.create_all(bind=engine)
    session = get_session()
    try:
        session.query(DecisionShadowScore).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = get_session()
    try:
        session.query(DecisionShadowScore).delete()
        session.commit()
    finally:
        session.close()


def test_shadow_evaluator_persists_scores(shadow_env) -> None:
    evaluator = ShadowEvaluator()
    results = evaluator.score_cycle(
        cycle_id="cycle-shadow-1",
        pending_buys=[
            {
                "ticker": "AAPL_US_EQ",
                "conviction": 85,
                "decision": {"reasoning": "Strong momentum", "conviction": 85},
            }
        ],
        macro_regime="RISK_ON",
    )
    assert len(results) == 2
    session = get_session()
    try:
        count = session.query(DecisionShadowScore).count()
        assert count == 2
    finally:
        session.close()


def test_shadow_summary_empty(shadow_env) -> None:
    summary = shadow_summary(days=30)
    assert summary["total_scores"] == 0


def test_shadow_outcome_join_no_crash(shadow_env) -> None:
    evaluator = ShadowEvaluator()
    evaluator.score_cycle(
        cycle_id="cycle-shadow-2",
        pending_buys=[{"ticker": "MSFT_US_EQ", "conviction": 30, "decision": {"reasoning": "weak"}}],
    )
    result = join_shadow_outcomes(lookback_days=90)
    assert result["status"] == "completed"
