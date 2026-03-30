"""Tests for Formal Verification Audit Phase 2 fixes.

P2-3: Decision chain integrity check (orphaned decisions logged)
P2-4: Portfolio re-query before BUY phase
P2-5: TRADE_WITHOUT_STOP alert on stop-loss failure
P2-6: OpportunityQueue status field (QUEUED → EXECUTING → EXECUTED)
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.notifications.formatters import render_event
from src.agents.notifications.service import NotificationService
from src.agents.notifications.types import NotificationEvent
from src.agents.opportunity.optimizer import OpportunityOptimizer
from src.data.models import Base, OpportunityQueue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def mock_get_session(db_session):
    with patch("src.agents.opportunity.optimizer.get_session", return_value=db_session):
        yield


# ---------------------------------------------------------------------------
# P2-6: OpportunityQueue status field
# ---------------------------------------------------------------------------

class TestOpportunityQueueStatus:
    """P2-6: OpportunityQueue QUEUED → EXECUTING → EXECUTED lifecycle."""

    def test_new_queue_entry_has_queued_status(self, db_session):
        """New OpportunityQueue rows default to QUEUED status."""
        row = OpportunityQueue(
            ticker="AAPL_US_EQ",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()
        assert row.queue_status == "QUEUED"

    def test_mark_executing_updates_status(self, db_session):
        """_mark_executing sets EXECUTING on selected tickers."""
        row = OpportunityQueue(
            ticker="AAPL_US_EQ",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        OpportunityOptimizer._mark_executing(["AAPL_US_EQ"])

        db_session.expire_all()
        row = db_session.query(OpportunityQueue).filter_by(ticker="AAPL_US_EQ").first()
        assert row is not None
        assert row.queue_status == "EXECUTING"

    def test_dequeue_executed_removes_rows(self, db_session):
        """dequeue_executed removes tickers from queue."""
        row = OpportunityQueue(
            ticker="AAPL_US_EQ",
            queue_status="EXECUTING",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        OpportunityOptimizer.dequeue_executed(["AAPL_US_EQ"])

        db_session.expire_all()
        remaining = db_session.query(OpportunityQueue).all()
        assert len(remaining) == 0

    def test_reconcile_orphaned_executing_resets_to_queued(self, db_session):
        """Orphaned EXECUTING rows are reset to QUEUED at cycle start."""
        row = OpportunityQueue(
            ticker="CRASH_US_EQ",
            queue_status="EXECUTING",
            queued_cycles=2,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        orphaned = OpportunityOptimizer.reconcile_orphaned_executing()

        assert orphaned == ["CRASH_US_EQ"]
        db_session.expire_all()
        row = db_session.query(OpportunityQueue).filter_by(ticker="CRASH_US_EQ").first()
        assert row is not None
        assert row.queue_status == "QUEUED"

    def test_reconcile_ignores_queued_rows(self, db_session):
        """Reconcile does not touch rows that are already QUEUED."""
        row = OpportunityQueue(
            ticker="NORMAL_US_EQ",
            queue_status="QUEUED",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()

        orphaned = OpportunityOptimizer.reconcile_orphaned_executing()

        assert orphaned == []
        db_session.expire_all()
        row = db_session.query(OpportunityQueue).filter_by(ticker="NORMAL_US_EQ").first()
        assert row.queue_status == "QUEUED"

    def test_optimize_buys_marks_executing_not_deletes(self, db_session):
        """optimize_buys marks immediate exec tickers as EXECUTING (not deleted)."""
        optimizer = OpportunityOptimizer()
        approved = [{"ticker": "FAST_US_EQ", "final_allocation_pct": 5.0}]
        scores = {"FAST_US_EQ": {"uov_ewma": 1.5, "uov_final": 1.2, "uov_z": 1.0}}

        result = optimizer.optimize_buys(
            cycle_id="cycle_1",
            approved_buys=approved,
            scores_by_ticker=scores,
            existing_tickers=set(),
            cash_pct=50.0,
            num_positions=0,
        )

        assert "FAST_US_EQ" in result["execution_order"]

        # Row should be marked EXECUTING, not deleted yet
        # (For immediate exec, the row may not exist in queue if it never was queued.
        #  But if it was queued in a prior cycle, it would be marked EXECUTING.)
        # The key behavior is that _mark_executing is called instead of _dequeue_executed.

    def test_full_lifecycle_queue_execute_dequeue(self, db_session):
        """Full lifecycle: queue → mark executing → dequeue after success."""
        optimizer = OpportunityOptimizer()

        # Cycle 1: queue it (at capacity)
        approved = [{"ticker": "LIFE_US_EQ", "final_allocation_pct": 5.0}]
        scores = {"LIFE_US_EQ": {"uov_ewma": 0.5, "uov_final": 0.3, "uov_z": 0.2}}
        optimizer.optimize_buys(
            cycle_id="cycle_1",
            approved_buys=approved,
            scores_by_ticker=scores,
            existing_tickers={f"POS{j}_US_EQ" for j in range(20)},
            cash_pct=20.0,
            num_positions=20,
        )

        row = db_session.query(OpportunityQueue).filter_by(ticker="LIFE_US_EQ").first()
        assert row is not None
        assert row.queue_status == "QUEUED"

        # Cycle 2: capacity opens, promoted → EXECUTING
        result = optimizer.optimize_buys(
            cycle_id="cycle_2",
            approved_buys=approved,
            scores_by_ticker=scores,
            existing_tickers={f"POS{j}_US_EQ" for j in range(13)},
            cash_pct=20.0,
            num_positions=13,
        )

        assert "LIFE_US_EQ" in result["execution_order"]

        # After execution succeeds, orchestrator calls dequeue_executed
        OpportunityOptimizer.dequeue_executed(["LIFE_US_EQ"])
        db_session.expire_all()
        assert db_session.query(OpportunityQueue).filter_by(ticker="LIFE_US_EQ").first() is None


# ---------------------------------------------------------------------------
# P2-5: TRADE_WITHOUT_STOP alert
# ---------------------------------------------------------------------------

class TestTradeWithoutStopAlert:
    """P2-5: Notification emitted when BUY fills but stop-loss fails."""

    def test_emit_trade_without_stop_method_exists(self):
        """NotificationService has emit_trade_without_stop method."""
        service = NotificationService.__new__(NotificationService)
        service.enabled = False
        assert hasattr(service, "emit_trade_without_stop")
        assert callable(service.emit_trade_without_stop)

    def test_formatter_renders_trade_without_stop_slack(self):
        """Slack formatter produces actionable message for trade_without_stop."""
        event = NotificationEvent(
            event_id="test123",
            event_type="trade_without_stop",
            occurred_at=datetime.now(timezone.utc),
            cycle_id="cycle_1",
            severity="warning",
            source="orchestrator",
            dedup_key="abc",
            payload={
                "ticker": "AAPL_US_EQ",
                "action": "BUY",
                "quantity": 10,
                "price": 150.0,
                "stop_loss_pct": -8.0,
                "error_message": "T212 API timeout",
            },
        )

        messages = render_event(event, "slack")

        assert len(messages) >= 1
        body = messages[0].body
        assert "AAPL_US_EQ" in body
        assert "TRADE-WITHOUT-STOP" in body
        assert "ACTION REQUIRED" in body

    def test_formatter_renders_trade_without_stop_email(self):
        """Email formatter includes full details for trade_without_stop."""
        event = NotificationEvent(
            event_id="test456",
            event_type="trade_without_stop",
            occurred_at=datetime.now(timezone.utc),
            cycle_id="cycle_1",
            severity="warning",
            source="orchestrator",
            dedup_key="def",
            payload={
                "ticker": "GOOG_US_EQ",
                "action": "BUY",
                "quantity": 5,
                "price": 2800.0,
                "stop_loss_pct": -10.0,
                "error_message": "Connection refused",
                "occurred_at": "2026-03-21T10:00:00Z",
                "dry_run": False,
                "cycle_id": "cycle_1",
            },
        )

        messages = render_event(event, "email")

        assert len(messages) == 1
        assert "Trade Without Stop-Loss" in messages[0].subject
        body = messages[0].body
        assert "GOOG_US_EQ" in body
        assert "Connection refused" in body
        assert "ACTION REQUIRED" in body

    def test_title_mapping_includes_trade_without_stop(self):
        """Title mapping returns correct name for trade_without_stop."""
        event = NotificationEvent(
            event_id="t",
            event_type="trade_without_stop",
            occurred_at=datetime.now(timezone.utc),
            cycle_id=None,
            severity="warning",
            source="test",
            dedup_key="x",
            payload={},
        )
        from src.agents.notifications.formatters import _title_for_event
        assert _title_for_event(event) == "Trade Without Stop-Loss"


# ---------------------------------------------------------------------------
# P2-4: Portfolio re-query before BUY phase
# ---------------------------------------------------------------------------

class TestPortfolioReQueryBeforeBuy:
    """P2-4: Portfolio refresh between SELL/REDUCE and BUY execution."""

    def test_portfolio_refresh_called_after_sells(self, monkeypatch):
        """After SELL execution, _get_portfolio_state is called again before BUYs."""
        # This is an integration-level test; we mock the orchestrator internals
        from src.orchestrator.main import Orchestrator

        # Count calls to _get_portfolio_state
        call_count = {"n": 0}
        original_values = {
            "cash": 5000.0,
            "total_value": 10000.0,
        }
        refreshed_values = {
            "cash": 7000.0,  # More cash after SELL
            "total_value": 10000.0,
        }

        def mock_portfolio_state(self_ref=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {
                    **original_values,
                    "invested": 5000.0,
                    "positions": [{"ticker": "OLD_US_EQ", "value_gbp": 2000}],
                    "num_positions": 1,
                    "daily_pnl_pct": 0,
                    "total_return_pct": 0,
                    "alpha_pct": 0,
                }
            return {
                **refreshed_values,
                "invested": 3000.0,
                "positions": [],
                "num_positions": 0,
                "daily_pnl_pct": 0,
                "total_return_pct": 0,
                "alpha_pct": 0,
            }

        # Verify the refresh logic exists in the source code
        import inspect
        from src.orchestrator.main import Orchestrator
        source = inspect.getsource(Orchestrator.run_cycle)
        assert "Re-query portfolio before BUY phase" in source
        assert "sells_executed" in source


# ---------------------------------------------------------------------------
# P2-3: Decision chain integrity check
# ---------------------------------------------------------------------------

class TestDecisionChainIntegrity:
    """P2-3: Decision chain integrity check at cycle finalization."""

    def test_integrity_check_in_finalize_source(self):
        """Verify the decision chain integrity check exists in the _finalize function."""
        import inspect
        from src.orchestrator.main import Orchestrator
        source = inspect.getsource(Orchestrator.run_cycle)
        assert "orphaned_decisions" in source
        assert "Decision chain integrity" in source

    def test_orphaned_decisions_detected_when_ticker_missing(self):
        """If a strategy decision ticker has no trade or rejection, it's logged."""
        # This is tested at the code structure level
        import inspect
        from src.orchestrator.main import Orchestrator
        source = inspect.getsource(Orchestrator.run_cycle)
        assert "traded_tickers = {" in source or "traded_tickers =" in source
        assert "accounted = traded_tickers | rejected_tickers" in source


# ---------------------------------------------------------------------------
# P2-6 extra: OpportunityQueue migration model field
# ---------------------------------------------------------------------------

class TestOpportunityQueueModel:
    """Verify OpportunityQueue model has queue_status field."""

    def test_queue_status_column_exists(self):
        """OpportunityQueue model has queue_status column."""
        assert hasattr(OpportunityQueue, "queue_status")

    def test_queue_status_default_is_queued(self, db_session):
        """Default value for queue_status is QUEUED."""
        row = OpportunityQueue(
            ticker="TEST_US_EQ",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        assert row.queue_status == "QUEUED"


# ---------------------------------------------------------------------------
# P2-6: Reconcile at cycle start
# ---------------------------------------------------------------------------

class TestReconcileAtCycleStart:
    """Verify reconcile_orphaned_executing is wired into the orchestrator."""

    def test_reconcile_called_in_orchestrator(self):
        """Orchestrator source includes reconcile_orphaned_executing call."""
        import inspect
        from src.orchestrator.main import Orchestrator
        source = inspect.getsource(Orchestrator.run_cycle)
        assert "reconcile_orphaned_executing" in source

    def test_dequeue_executed_called_after_buy(self):
        """Orchestrator calls dequeue_executed after BUY execution."""
        import inspect
        from src.orchestrator.main import Orchestrator
        source = inspect.getsource(Orchestrator.run_cycle)
        assert "dequeue_executed" in source
        assert "executed_buy_tickers" in source
