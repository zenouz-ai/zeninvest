"""Tests for UOV execution optimizer and queueing behavior."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.opportunity.optimizer import OpportunityOptimizer
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
    """Patch optimizer DB session factory."""
    with patch("src.agents.opportunity.optimizer.get_session", return_value=db_session):
        yield


def test_optimizer_executes_top_ranked_and_queues_rest():
    optimizer = OpportunityOptimizer()
    approved = [
        {"ticker": "AAPL_US_EQ", "final_allocation_pct": 8.0},
        {"ticker": "GOOG_US_EQ", "final_allocation_pct": 8.0},
    ]
    scores = {
        "AAPL_US_EQ": {"uov_ewma": 1.4, "uov_final": 1.2, "uov_z": 1.1},
        "GOOG_US_EQ": {"uov_ewma": 0.5, "uov_final": 0.4, "uov_z": 0.3},
    }

    result = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{i}_US_EQ" for i in range(14)},
        cash_pct=20.0,
        num_positions=14,
    )

    assert result["execution_order"] == ["AAPL_US_EQ"]
    assert any(q["ticker"] == "GOOG_US_EQ" for q in result["queued_candidates"])


def test_optimizer_promotes_persistent_queue_on_second_cycle():
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "GOOG_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"GOOG_US_EQ": {"uov_ewma": 0.6, "uov_final": 0.4, "uov_z": 0.3}}

    first = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{i}_US_EQ" for i in range(15)},
        cash_pct=20.0,
        num_positions=15,
    )
    assert "GOOG_US_EQ" not in first["execution_order"]
    assert any(q["ticker"] == "GOOG_US_EQ" for q in first["queued_candidates"])

    second = optimizer.optimize_buys(
        cycle_id="cycle_2",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{i}_US_EQ" for i in range(14)},
        cash_pct=20.0,
        num_positions=14,
    )
    assert "GOOG_US_EQ" in second["execution_order"]


def test_optimizer_swap_suggestion_threshold():
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "NVDA_US_EQ", "final_allocation_pct": 5.0}]
    scores = {
        "HOLD_US_EQ": {"uov_ewma": 0.1, "uov_final": 0.1, "uov_z": 0.0},
        "NVDA_US_EQ": {"uov_ewma": 1.3, "uov_final": 1.0, "uov_z": 0.9},
    }

    result = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={"HOLD_US_EQ"},
        cash_pct=20.0,
        num_positions=1,
    )

    assert result["swap_candidates"]
    assert result["swap_candidates"][0]["candidate_ticker"] == "NVDA_US_EQ"
    assert result["swap_candidates"][0]["delta"] >= 1.0
