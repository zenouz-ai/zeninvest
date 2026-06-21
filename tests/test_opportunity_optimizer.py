"""Tests for UOV execution optimizer and queueing behavior."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.opportunity.optimizer import OpportunityOptimizer
from src.data.models import Base
from src.utils.config import get_settings


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
    cap = get_settings().max_positions
    approved = [{"ticker": "GOOG_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"GOOG_US_EQ": {"uov_ewma": 0.6, "uov_final": 0.4, "uov_z": 0.3}}

    # Cycle 1: book full to capacity -> GOOG cannot execute, queues.
    first = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{i}_US_EQ" for i in range(cap)},
        cash_pct=20.0,
        num_positions=cap,
    )
    assert "GOOG_US_EQ" not in first["execution_order"]
    assert any(q["ticker"] == "GOOG_US_EQ" for q in first["queued_candidates"])

    # Cycle 2: a few slots free up -> GOOG executes.
    second = optimizer.optimize_buys(
        cycle_id="cycle_2",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{i}_US_EQ" for i in range(cap - 6)},
        cash_pct=20.0,
        num_positions=cap - 6,
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


def test_optimizer_queue_ttl_expires_after_max_cycles():
    """Queued ticker is dropped after queue_ttl_cycles exceeded."""
    optimizer = OpportunityOptimizer()
    cap = get_settings().max_positions
    ttl = get_settings().opportunity_queue_ttl_cycles
    approved = [{"ticker": "SLOW_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"SLOW_US_EQ": {"uov_ewma": 0.2, "uov_final": 0.1, "uov_z": 0.05}}

    # Run ttl + 1 cycles at full capacity so the queued ticker ages out and expires.
    dropped_at_any_cycle = False
    for i in range(1, ttl + 2):
        result = optimizer.optimize_buys(
            cycle_id=f"cycle_{i}",
            approved_buys=approved,
            scores_by_ticker=scores,
            existing_tickers={f"POS{j}_US_EQ" for j in range(cap)},  # Full capacity
            cash_pct=20.0,
            num_positions=cap,
        )
        if any(
            d["ticker"] == "SLOW_US_EQ" and d["reason"] == "queue_ttl_expired"
            for d in result["dropped_queue"]
        ):
            dropped_at_any_cycle = True

    assert dropped_at_any_cycle, "Ticker should have been dropped from queue after TTL expiry"


def test_optimizer_rejection_details_below_queue_threshold():
    """Ticker below queue_threshold_z gets structured rejection."""
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "WEAK_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"WEAK_US_EQ": {"uov_ewma": -0.5, "uov_final": -0.3, "uov_z": -0.4}}

    result = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers=set(),
        cash_pct=20.0,
        num_positions=0,
    )

    assert "WEAK_US_EQ" not in result["execution_order"]
    assert "WEAK_US_EQ" in result["rejection_details"]
    detail = result["rejection_details"]["WEAK_US_EQ"]
    assert detail["reason_code"] == "below_queue"


def test_optimizer_capacity_gated_rejection():
    """Queued ticker at capacity gets capacity_gated reason."""
    optimizer = OpportunityOptimizer()
    cap = get_settings().max_positions
    approved = [{"ticker": "CAP_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"CAP_US_EQ": {"uov_ewma": 0.2, "uov_final": 0.1, "uov_z": 0.1}}

    # Cycle 1: queue it (at capacity)
    optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{j}_US_EQ" for j in range(cap)},
        cash_pct=20.0,
        num_positions=cap,
    )

    # Cycle 2: still at capacity — should be capacity_gated
    result = optimizer.optimize_buys(
        cycle_id="cycle_2",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{j}_US_EQ" for j in range(cap)},
        cash_pct=20.0,
        num_positions=cap,
    )

    assert "CAP_US_EQ" in result["rejection_details"]
    assert result["rejection_details"]["CAP_US_EQ"]["reason_code"] == "capacity_gated"


def test_optimizer_no_swap_when_no_existing_positions():
    """No swap suggestions when portfolio is empty."""
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "AAPL_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"AAPL_US_EQ": {"uov_ewma": 1.5, "uov_final": 1.2, "uov_z": 1.1}}

    result = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers=set(),
        cash_pct=50.0,
        num_positions=0,
    )

    assert result["swap_candidates"] == []
    assert "AAPL_US_EQ" in result["execution_order"]


def test_optimizer_cash_floor_blocks_execution():
    """Insufficient cash prevents immediate execution."""
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "AAPL_US_EQ", "final_allocation_pct": 12.0}]
    scores = {"AAPL_US_EQ": {"uov_ewma": 1.5, "uov_final": 1.2, "uov_z": 1.1}}

    result = optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers=set(),
        cash_pct=11.0,  # cash_floor=10, remaining=1.0 — not enough for 12%
        num_positions=0,
    )

    # Should be queued, not executed
    assert "AAPL_US_EQ" not in result["execution_order"]


def test_optimizer_dequeues_executed_tickers():
    """Executed tickers are removed from queue."""
    optimizer = OpportunityOptimizer()
    approved = [{"ticker": "EXEC_US_EQ", "final_allocation_pct": 5.0}]
    scores = {"EXEC_US_EQ": {"uov_ewma": 0.5, "uov_final": 0.3, "uov_z": 0.2}}

    # Cycle 1: queue it (at capacity)
    optimizer.optimize_buys(
        cycle_id="cycle_1",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{j}_US_EQ" for j in range(15)},
        cash_pct=20.0,
        num_positions=15,
    )

    # Cycle 2: capacity frees up — should promote and dequeue
    result = optimizer.optimize_buys(
        cycle_id="cycle_2",
        approved_buys=approved,
        scores_by_ticker=scores,
        existing_tickers={f"POS{j}_US_EQ" for j in range(13)},
        cash_pct=20.0,
        num_positions=13,
    )

    assert "EXEC_US_EQ" in result["execution_order"]
    # No longer in queue
    assert not any(q["ticker"] == "EXEC_US_EQ" for q in result["queued_candidates"])
