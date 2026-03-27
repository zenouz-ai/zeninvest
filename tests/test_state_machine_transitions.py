"""State machine transition integration coverage for US-7.4."""

from datetime import datetime, timedelta, timezone

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
    assert state.halted_recovery_streak == 0


def test_halted_auto_recovery_after_three_clean_live_cycles(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    orchestrator_test_harness.seed_state(
        state="HALTED",
        peak_portfolio_value=10_000.0,
        current_drawdown_pct=35.0,
    )
    portfolio_data = {
        "cash": 7_200.0,
        "total_value": 7_200.0,
        "invested": 0.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": -28.0,
        "alpha_pct": 0.0,
    }

    for expected_streak in (1, 2):
        orchestrator = orchestrator_test_harness.build_orchestrator(
            dry_run=False,
            account_type="live",
            decisions=[],
            portfolio_data=portfolio_data,
        )
        result = orchestrator.run_cycle()
        orchestrator_db_session.expire_all()
        state = orchestrator_db_session.query(SystemState).one()
        assert result["status"] == "halted_recovery_pending"
        assert state.state == "HALTED"
        assert state.halted_recovery_streak == expected_streak

    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data=portfolio_data,
    )
    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()

    assert result["status"] == "completed"
    assert state.state == "ACTIVE"
    assert state.halted_recovery_streak == 0


def test_halted_auto_recovery_streak_resets_when_drawdown_worsens(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    orchestrator_test_harness.seed_state(
        state="HALTED",
        peak_portfolio_value=10_000.0,
        current_drawdown_pct=35.0,
    )
    recovery_portfolio = {
        "cash": 7_200.0,
        "total_value": 7_200.0,
        "invested": 0.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": -28.0,
        "alpha_pct": 0.0,
    }
    worse_portfolio = {
        "cash": 6_800.0,
        "total_value": 6_800.0,
        "invested": 0.0,
        "positions": [],
        "num_positions": 0,
        "daily_pnl_pct": 0.0,
        "total_return_pct": -32.0,
        "alpha_pct": 0.0,
    }

    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data=recovery_portfolio,
    )
    orchestrator.run_cycle()

    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data=worse_portfolio,
    )
    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()

    assert result["status"] == "halted_recovery_pending"
    assert state.state == "HALTED"
    assert state.halted_recovery_streak == 0


def test_peak_inflation_warning_is_persisted_without_auto_reset(
    orchestrator_test_harness,
    orchestrator_db_session,
):
    orchestrator_test_harness.seed_state(
        state="ACTIVE",
        peak_portfolio_value=25_000.0,
        current_drawdown_pct=0.0,
    )
    for idx in range(5):
        orchestrator_db_session.add(
            PortfolioSnapshot(
                timestamp=datetime.now(timezone.utc) - timedelta(days=idx + 1),
                total_value_gbp=10_000.0,
                cash_gbp=10_000.0,
                invested_gbp=0.0,
                pnl_gbp=0.0,
                pnl_pct=0.0,
                num_positions=0,
                state="ACTIVE",
            )
        )
    orchestrator_db_session.commit()

    orchestrator = orchestrator_test_harness.build_orchestrator(
        dry_run=False,
        account_type="live",
        decisions=[],
        portfolio_data={
            "cash": 24_000.0,
            "total_value": 24_000.0,
            "invested": 0.0,
            "positions": [],
            "num_positions": 0,
            "daily_pnl_pct": 0.0,
            "total_return_pct": 140.0,
            "alpha_pct": 0.0,
        },
    )

    result = orchestrator.run_cycle()

    orchestrator_db_session.expire_all()
    state = orchestrator_db_session.query(SystemState).one()

    assert result["status"] == "completed"
    assert state.peak_portfolio_value == 25_000.0
    assert state.peak_inflation_warning_note is not None
    assert "Peak inflation warning" in state.peak_inflation_warning_note
