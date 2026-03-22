"""State machine transition integration coverage for US-7.4."""

from dashboard.backend.app.database import Run

from src.data.models import PortfolioSnapshot, SystemState


def test_live_account_transitions_to_cautious_and_completes(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    probe = orchestrator_test_harness.build_orchestrator(dry_run=False, decisions=[])
    cautious = probe.settings.cautious_drawdown_pct
    halt = probe.settings.halt_drawdown_pct
    drawdown_pct = cautious + ((halt - cautious) / 2)
    current_value = 10_000.0 * (1 - drawdown_pct / 100)

    orchestrator_test_harness.seed_state(
        state="ACTIVE",
        peak_portfolio_value=10_000.0,
        current_drawdown_pct=0.0,
    )
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data={
            "cash": current_value,
            "total_value": current_value,
            "invested": 0.0,
            "positions": [],
            "num_positions": 0,
            "daily_pnl_pct": 0.0,
            "total_return_pct": ((current_value / 10_000.0) - 1) * 100,
            "alpha_pct": 0.0,
        },
    )

    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()
    run = orchestrator_db_session.query(Run).filter(Run.cycle_id == result["cycle_id"]).one()

    assert result["status"] == "completed"
    assert state.state == "CAUTIOUS"
    assert state.current_drawdown_pct >= cautious
    assert run.status == "completed"


def test_live_account_halt_drawdown_liquidates_and_exits_early(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    probe = orchestrator_test_harness.build_orchestrator(dry_run=False, decisions=[])
    halt = probe.settings.halt_drawdown_pct
    current_value = 10_000.0 * (1 - (halt + 5.0) / 100)

    orchestrator_test_harness.seed_state(
        state="ACTIVE",
        peak_portfolio_value=10_000.0,
        current_drawdown_pct=0.0,
    )
    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data={
            "cash": current_value,
            "total_value": current_value,
            "invested": 0.0,
            "positions": [],
            "num_positions": 0,
            "daily_pnl_pct": 0.0,
            "total_return_pct": ((current_value / 10_000.0) - 1) * 100,
            "alpha_pct": 0.0,
        },
    )

    liquidated = {"called": False}
    orchestrator._order_manager.liquidate_all = lambda: liquidated.__setitem__("called", True) or {
        "status": "ok",
        "orders": [],
    }

    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()
    snapshot = orchestrator_db_session.query(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).first()
    run = orchestrator_db_session.query(Run).filter(Run.cycle_id == result["cycle_id"]).one()

    assert result["status"] == "halted_drawdown"
    assert liquidated["called"] is True
    assert state.state == "HALTED"
    assert snapshot is not None
    assert snapshot.state == "HALTED"
    assert run.status == "halted_drawdown"


def test_manual_reset_recovers_halted_state(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    orchestrator_test_harness.seed_state(
        state="HALTED",
        peak_portfolio_value=10_000.0,
        current_drawdown_pct=41.0,
        paused=True,
    )
    state_machine = orchestrator_test_harness.build_state_machine()

    state_machine.reset_peak_to_current(7_100.0)

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()

    assert state.state == "ACTIVE"
    assert state.peak_portfolio_value == 7_100.0
    assert state.current_drawdown_pct == 0.0
    assert state.paused is False
