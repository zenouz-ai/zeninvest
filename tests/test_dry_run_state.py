"""Test that dry-run mode does not mutate system state or skip screening."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, SystemState
from src.orchestrator.main import Orchestrator

# Import dashboard Base to create its tables too
try:
    from dashboard.backend.app.database import Base as DashboardBase
except ImportError:
    DashboardBase = None


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    if DashboardBase is not None:
        DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def patch_all_get_session(db_session):
    """Patch get_session everywhere it's imported from."""
    targets = [
        "src.data.database.get_session",
        "src.orchestrator.state_machine.get_session",
        "src.orchestrator.main.get_session",
        "src.utils.cost_tracker.get_session",
        "src.agents.notifications.service.get_session",
        "src.agents.execution.order_manager.get_session",
        "src.agents.execution.stop_loss_manager.get_session",
        "src.agents.execution.t212_client.get_session",
        "src.agents.moderation.panel.get_session",
        "src.agents.risk.risk_manager.get_session",
        "src.agents.strategy.engine.get_session",
        "src.agents.market_data.data_fetcher.get_session",
        "src.agents.reporting.performance_tracker.get_session",
        "src.agents.reporting.trade_outcome_tracker.get_session",
        "src.agents.opportunity.scorer.get_session",
        "src.agents.opportunity.optimizer.get_session",
    ]
    patches = []
    for target in targets:
        try:
            p = patch(target, return_value=db_session)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield
    for p in patches:
        p.stop()


def _build_orchestrator(portfolio_value=9300.0):
    """Create a dry-run orchestrator with mocked deps and a drawdown-triggering portfolio."""
    orchestrator = Orchestrator(dry_run=True)

    # Replace notification service with dummy
    orchestrator.notification_service = SimpleNamespace(
        emit_cycle_run_summary=lambda **kw: None,
        emit_state_transition=lambda **kw: None,
        emit_trade_instruction_approved=lambda **kw: None,
        emit_trade_execution_result=lambda **kw: None,
        emit_critical_cycle_failure=lambda **kw: None,
    )

    orchestrator.settings._config.setdefault("opportunity", {})["enabled"] = False

    # Portfolio that would trigger CAUTIOUS (7% drawdown from peak of 10000)
    orchestrator._get_portfolio_state = lambda: {
        "cash": portfolio_value,
        "total_value": portfolio_value,
        "invested": 0.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": ((portfolio_value / 10000) - 1) * 100,
        "alpha_pct": 0.0,
    }

    # Track whether screening was called and with what state
    screening_called = {"value": False, "system_state": None}

    def mock_fetch_stocks_data(current_positions, exclude_tickers=None, system_state="ACTIVE"):
        screening_called["value"] = True
        screening_called["system_state"] = system_state
        return [
            {
                "ticker": "AAPL_US_EQ",
                "name": "Apple Inc.",
                "indicators": {"current_price": 180},
                "fundamentals": {
                    "industry": "Consumer Electronics",
                    "market_cap": 2_800_000_000_000,
                    "business_summary": "Apple",
                    "trailing_pe": 28,
                },
            },
        ]

    orchestrator._fetch_stocks_data = mock_fetch_stocks_data

    orchestrator.data_fetcher = SimpleNamespace(
        get_macro_data=lambda: {"vix": 18, "market_regime": "BULL"},
        get_cached_news_sentiment=lambda ticker, source, data_type: None,
        cache_news_sentiment=lambda *a, **kw: None,
        get_analyst_data_cached=lambda ticker: {},
        alpha_vantage=SimpleNamespace(get_broad_market_sentiment=lambda: {}),
        get_market_news_sentiment=lambda **kw: {"articles": [], "total_articles": 0},
        close=lambda: None,
    )

    orchestrator.strategy_engine = SimpleNamespace(
        run_sub_strategies=lambda stocks_data, existing_tickers: {
            "momentum": [], "mean_reversion": [], "top_factor": [], "factor": [],
        },
        synthesize_with_claude=lambda **kw: {"decisions": [], "market_assessment": ""},
    )

    orchestrator.moderation_panel = SimpleNamespace(review_trade=lambda **kw: None)
    orchestrator.risk_manager = SimpleNamespace(
        evaluate_trade=lambda **kw: None,
        get_drawdown_state=lambda current_value, peak_value: (
            "CAUTIOUS" if peak_value > 0 and ((peak_value - current_value) / peak_value) * 100 >= 5 else "ACTIVE"
        ),
    )
    orchestrator._order_manager = SimpleNamespace(
        execute_market_order=lambda **kw: {"status": "dry_run"},
    )

    return orchestrator, screening_called


def test_dry_run_does_not_mutate_state_or_skip_screening(db_session, monkeypatch):
    """Dry-run should not persist state changes and should always screen stocks."""
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    # Seed system state with peak=10000, ACTIVE
    ss = SystemState(
        state="ACTIVE",
        peak_portfolio_value=10000.0,
        current_drawdown_pct=0.0,
        paused=False,
    )
    db_session.add(ss)
    db_session.commit()

    orchestrator, screening_called = _build_orchestrator(portfolio_value=9300.0)

    result = orchestrator.run_cycle()

    # Bug B fix: screening was called (not skipped by CAUTIOUS)
    assert screening_called["value"], "Screening should have been called in dry-run"
    assert screening_called["system_state"] == "ACTIVE", (
        f"system_state passed to _fetch_stocks_data should be ACTIVE in dry-run, "
        f"got {screening_called['system_state']}"
    )

    # Bug A fix: DB state not mutated
    db_session.expire_all()
    state = db_session.query(SystemState).first()
    assert state.state == "ACTIVE", f"State should still be ACTIVE, got {state.state}"
    assert state.peak_portfolio_value == 10000.0, (
        f"Peak should still be 10000.0, got {state.peak_portfolio_value}"
    )
    assert state.current_drawdown_pct == 0.0, (
        f"Drawdown should still be 0.0, got {state.current_drawdown_pct}"
    )

    # Cycle should complete successfully
    assert result["status"] == "completed"


def test_dry_run_logs_would_trigger_cautious(db_session, monkeypatch, caplog):
    """Dry-run should log what state would be triggered without persisting."""
    monkeypatch.setattr("src.orchestrator.main.get_cost_summary", lambda days=1: {})

    ss = SystemState(
        state="ACTIVE",
        peak_portfolio_value=10000.0,
        current_drawdown_pct=0.0,
        paused=False,
    )
    db_session.add(ss)
    db_session.commit()

    orchestrator, _ = _build_orchestrator(portfolio_value=9300.0)

    import logging
    with caplog.at_level(logging.INFO):
        orchestrator.run_cycle()

    # Should log that CAUTIOUS would have been triggered
    assert any("would trigger CAUTIOUS" in msg for msg in caplog.messages), (
        f"Expected dry-run CAUTIOUS warning in logs, got: {caplog.messages}"
    )
