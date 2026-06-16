"""Tests for the stagnation-exit deterministic SELL rule.

The rule sells positions whose profit-per-day-held is below a configurable
floor after a minimum holding period, so cash can recycle into more
productive tickers. It bypasses moderation/risk, similar to the small-
position cleanup and profit-lock unprotected exit paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data.models import Base, Order
from src.orchestrator.main import Orchestrator
from src.utils.cost_tracker import DegradationLevel


class _NoopNotifications:
    def emit_cycle_run_summary(self, **kwargs) -> None:
        return None

    def emit_state_transition(self, **kwargs) -> None:
        return None

    def emit_trade_instruction_approved(self, **kwargs) -> None:
        return None

    def emit_trade_execution_result(self, **kwargs) -> None:
        return None

    def emit_trade_without_stop(self, **kwargs) -> None:
        return None

    def emit_order_adjustment(self, **kwargs) -> None:
        return None

    def emit_critical_cycle_failure(self, **kwargs) -> None:
        return None


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _patch_get_session(db_session):
    targets = [
        "src.data.database.get_session",
        "src.orchestrator.main.get_session",
        "src.orchestrator.state_machine.get_session",
        "src.agents.execution.order_manager.get_session",
        "src.agents.execution.stop_loss_manager.get_session",
        "src.agents.execution.t212_client.get_session",
        "src.agents.notifications.service.get_session",
        "src.agents.strategy.engine.get_session",
        "src.utils.cost_tracker.get_session",
    ]
    patches = []
    for target in targets:
        try:
            p = patch(target, return_value=db_session)
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            continue
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def _patch_runtime_cycle_lock():
    class _DummyLock:
        def release(self) -> None:
            return None

    with patch("src.orchestrator.main.acquire_runtime_lock", return_value=_DummyLock()):
        yield


@pytest.fixture(autouse=True)
def _restore_trading_settings():
    """Snapshot & restore the shared Settings.trading dict around each test.

    `_configure_stagnation` mutates the cached Settings singleton so its
    changes would otherwise leak into unrelated test modules that rely on
    authoritative defaults (e.g. `small_position_cleanup_value_gbp`).
    """
    from src.utils.config import get_settings

    trading = get_settings()._config.get("trading", {})
    snapshot = dict(trading)
    try:
        yield
    finally:
        trading.clear()
        trading.update(snapshot)


def _configure_stagnation(
    orchestrator: Orchestrator,
    *,
    enabled: bool = True,
    min_days: float = 5.0,
    min_ppd_pct: float = 0.5,
    grace_pnl_pct: float | None = None,
) -> None:
    trading = orchestrator.settings._config.setdefault("trading", {})
    trading["stagnation_exit_enabled"] = enabled
    trading["stagnation_min_days"] = min_days
    trading["stagnation_use_pace_threshold"] = False
    trading["stagnation_min_profit_per_day_pct"] = min_ppd_pct
    trading["stagnation_grace_pnl_pct"] = grace_pnl_pct
    trading["small_position_cleanup_enabled"] = True
    trading["small_position_cleanup_value_gbp"] = 200.0


# ---------------------------------------------------------------------------
# YAML defaults — lock in the tuned thresholds so future drift is caught.
# ---------------------------------------------------------------------------


def test_stagnation_yaml_defaults_are_tuned_for_fewer_sells() -> None:
    """Pace-aligned defaults (ADR-005): stagnation floor inherits learning winner threshold."""
    from src.utils.config import Settings

    settings = Settings()

    assert settings.stagnation_exit_enabled is True
    assert settings.stagnation_min_days == pytest.approx(12.0)
    assert settings.stagnation_use_pace_threshold is True
    assert settings.stagnation_min_profit_per_day_pct == pytest.approx(0.25)
    assert settings.stagnation_grace_by_pace is True
    assert settings.stagnation_grace_pnl_pct is None
    assert settings.slow_bleed_exit_enabled is True
    assert settings.pace_aware_sell_enabled is False


# ---------------------------------------------------------------------------
# _stagnation_exit_reason — unit-level coverage of the eligibility predicate.
# ---------------------------------------------------------------------------


def test_stagnation_reason_fires_for_stale_flat_position() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Held 10 days, pnl 2% => 0.2%/day < 0.5%/day floor => qualifies.
    position = {"value_gbp": 500.0, "pnl_pct": 2.0, "held_hours": 24.0 * 10}

    result = orchestrator._stagnation_exit_reason(position)

    assert result is not None
    detail, metrics = result
    assert "stagnation sell" in detail.lower()
    assert metrics["held_days"] == pytest.approx(10.0)
    assert metrics["profit_per_day_pct"] == pytest.approx(0.2)
    assert metrics["min_profit_per_day_pct"] == 0.5


def test_stagnation_reason_fires_for_stale_loser() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Held 7 days, pnl -3% => -0.43%/day, clearly below floor => qualifies.
    position = {"value_gbp": 500.0, "pnl_pct": -3.0, "held_hours": 24.0 * 7}

    result = orchestrator._stagnation_exit_reason(position)

    assert result is not None
    _, metrics = result
    assert metrics["profit_per_day_pct"] < 0


def test_stagnation_reason_skips_fresh_position() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Held only 2 days => below min_days.
    position = {"value_gbp": 500.0, "pnl_pct": -20.0, "held_hours": 24.0 * 2}

    assert orchestrator._stagnation_exit_reason(position) is None


def test_stagnation_reason_skips_fast_winner() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Held 6 days, pnl 12% => 2%/day > 0.5%/day floor => keep running.
    position = {"value_gbp": 500.0, "pnl_pct": 12.0, "held_hours": 24.0 * 6}

    assert orchestrator._stagnation_exit_reason(position) is None


def test_stagnation_reason_skips_when_disabled() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, enabled=False)

    position = {"value_gbp": 500.0, "pnl_pct": -5.0, "held_hours": 24.0 * 30}

    assert orchestrator._stagnation_exit_reason(position) is None


def test_stagnation_reason_exempts_clear_winners_via_grace() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(
        orchestrator,
        min_days=5.0,
        min_ppd_pct=0.5,
        grace_pnl_pct=25.0,
    )

    # Held 60 days, pnl 30% => 0.5%/day, borderline on floor, but grace(25%)
    # exempts strong winners so profit-lock / trailing logic can manage them.
    position = {"value_gbp": 500.0, "pnl_pct": 30.0, "held_hours": 24.0 * 60}

    assert orchestrator._stagnation_exit_reason(position) is None


def test_stagnation_reason_skips_when_held_hours_missing() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator)

    assert orchestrator._stagnation_exit_reason({"pnl_pct": -5.0, "held_hours": None}) is None
    assert orchestrator._stagnation_exit_reason({"pnl_pct": -5.0}) is None
    assert orchestrator._stagnation_exit_reason({"pnl_pct": -5.0, "held_hours": 0}) is None


# ---------------------------------------------------------------------------
# _apply_deterministic_exit_overrides — post-strategy decision flipping.
# ---------------------------------------------------------------------------


def test_apply_deterministic_overrides_flips_hold_to_stagnation_sell() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    decision = {
        "ticker": "ABC_US_EQ",
        "action": "HOLD",
        "conviction": 10,
        "reasoning": "Sideways price action",
    }
    position_context = {
        "ABC_US_EQ": {
            "value_gbp": 500.0,  # above small-cleanup threshold
            "pnl_pct": 1.0,
            "held_hours": 24.0 * 10,
        }
    }

    orchestrator._apply_deterministic_exit_overrides(
        decisions=[decision],
        position_context=position_context,
        cycle_id="cycle_test",
    )

    assert decision["action"] == "SELL"
    assert decision["deterministic_exit_reason_code"] == "stagnation_exit"
    assert decision["exit_trigger_type"] == "hard_exit"
    assert decision["conviction"] >= 80
    assert "stagnation_metrics" in decision
    assert decision["stagnation_metrics"]["held_days"] == pytest.approx(10.0)


def test_small_cleanup_takes_precedence_over_stagnation() -> None:
    """A sub-threshold holding that is also stagnant must be tagged as
    small_position_cleanup (value-based) so reporting stays consistent.
    """
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    decision = {
        "ticker": "TINY_US_EQ",
        "action": "HOLD",
        "conviction": 10,
        "reasoning": "Dust",
    }
    position_context = {
        "TINY_US_EQ": {
            "value_gbp": 150.0,  # below cleanup threshold
            "pnl_pct": 1.0,
            "held_hours": 24.0 * 30,  # also stagnant
        }
    }

    orchestrator._apply_deterministic_exit_overrides(
        decisions=[decision],
        position_context=position_context,
        cycle_id="cycle_test",
    )

    assert decision["action"] == "SELL"
    assert decision["deterministic_exit_reason_code"] == "small_position_cleanup"


def test_stagnation_does_not_touch_active_winner() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    decision = {
        "ticker": "WIN_US_EQ",
        "action": "HOLD",
        "conviction": 75,
        "reasoning": "Let winner run",
    }
    position_context = {
        "WIN_US_EQ": {
            "value_gbp": 1_000.0,
            "pnl_pct": 18.0,
            "held_hours": 24.0 * 6,
        }
    }

    orchestrator._apply_deterministic_exit_overrides(
        decisions=[decision],
        position_context=position_context,
        cycle_id="cycle_test",
    )

    assert decision["action"] == "HOLD"
    assert "deterministic_exit_reason_code" not in decision


# ---------------------------------------------------------------------------
# _plan_pre_strategy_cleanup_candidates — pre-strategy candidate planner.
# ---------------------------------------------------------------------------


def test_plan_cleanup_candidates_emits_stagnation_for_aged_holdings(db_session) -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Seed a BUY order far enough in the past so held_hours reflects stagnation.
    db_session.add(
        Order(
            ticker="OLD_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10,
            price=20.0,
            value_gbp=200.0,
            status="filled",
            timestamp=datetime.now(timezone.utc) - timedelta(days=20),
        )
    )
    db_session.commit()

    # pnl_pct is recomputed as pnl_gbp / total_cost * 100 inside
    # _normalize_position_for_snapshot, so pick pnl_gbp=4 / total_cost=200 = 2%
    # and let the 20-day holding yield 0.1%/day < 0.5% floor.
    portfolio_data = {
        "invested": 204.0,
        "total_return_pct": 0.0,
        "positions": [
            {
                "ticker": "OLD_US_EQ",
                "quantity": 10,
                "currentPrice": 20.4,
                "averagePrice": 20.0,
                "value_gbp": 204.0,
                "pnl_gbp": 4.0,
            }
        ],
    }

    candidates = orchestrator._plan_pre_strategy_cleanup_candidates(
        portfolio_data=portfolio_data,
        cycle_id="cycle_test",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["ticker"] == "OLD_US_EQ"
    assert candidate["decision"]["deterministic_exit_reason_code"] == "stagnation_exit"
    assert candidate["decision"]["exit_trigger_type"] == "hard_exit"
    assert "stagnation_metrics" in candidate
    assert candidate["stagnation_metrics"]["held_days"] == pytest.approx(20.0, rel=0.05)


def test_plan_cleanup_candidates_prefers_small_cleanup_when_both_apply(db_session) -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    db_session.add(
        Order(
            ticker="DUST_US_EQ",
            action="BUY",
            order_type="market",
            quantity=2,
            price=30.0,
            value_gbp=60.0,
            status="filled",
            timestamp=datetime.now(timezone.utc) - timedelta(days=15),
        )
    )
    db_session.commit()

    # Small holding (<200 GBP) + would also qualify as stagnant.
    portfolio_data = {
        "invested": 61.0,
        "total_return_pct": 0.0,
        "positions": [
            {
                "ticker": "DUST_US_EQ",
                "quantity": 2,
                "currentPrice": 30.5,
                "averagePrice": 30.0,
                "value_gbp": 61.0,  # below cleanup threshold
                "pnl_gbp": 1.0,     # ~1.6% pnl_pct over 15 days => stagnant
            }
        ],
    }

    candidates = orchestrator._plan_pre_strategy_cleanup_candidates(
        portfolio_data=portfolio_data,
        cycle_id="cycle_test",
    )

    assert len(candidates) == 1
    assert candidates[0]["decision"]["deterministic_exit_reason_code"] == "small_position_cleanup"


# ---------------------------------------------------------------------------
# Risk / guardrail whitelisting — the new code must bypass min-holding and
# min-positions gates and pass the SELL guardrail without hitting the profit
# floor (this is the whole point of the rule).
# ---------------------------------------------------------------------------


def test_stagnation_exit_bypasses_min_holding_period() -> None:
    orchestrator = Orchestrator(dry_run=True)

    stagnation_decision = {
        "action": "SELL",
        "deterministic_exit_reason_code": "stagnation_exit",
        "exit_trigger_type": "hard_exit",
    }
    ordinary_sell = {
        "action": "SELL",
        "exit_trigger_type": "gain_realization",
    }

    assert orchestrator._should_skip_min_holding_for_decision(stagnation_decision) is True
    assert orchestrator._should_skip_min_holding_for_decision(ordinary_sell) is False


def test_stagnation_exit_bypasses_min_positions_floor() -> None:
    stagnation_decision = {
        "action": "SELL",
        "deterministic_exit_reason_code": "stagnation_exit",
        "exit_trigger_type": "hard_exit",
    }

    assert Orchestrator._should_skip_min_positions_for_decision(stagnation_decision) is True


def test_stagnation_exit_passes_sell_guardrail_below_profit_floor() -> None:
    """Confirms the new rule bypasses sell_min_profit_pct — this is the
    whole reason we need a separate reason code instead of gain_realization.
    """
    orchestrator = Orchestrator(dry_run=True)

    decision = {
        "ticker": "FLAT_US_EQ",
        "action": "SELL",
        "exit_trigger_type": "hard_exit",
        "deterministic_exit_reason_code": "stagnation_exit",
    }
    position_context = {"FLAT_US_EQ": {"pnl_pct": -1.0}}

    allowed, reason_code, reason_detail = orchestrator._evaluate_sell_guardrail(
        ticker="FLAT_US_EQ",
        decision=decision,
        position_context=position_context,
    )

    assert allowed is True
    assert reason_code is None
    assert reason_detail is None


def test_stagnation_exit_is_in_profit_lock_bypass_codes() -> None:
    assert "stagnation_exit" in Orchestrator._profit_lock_bypass_codes()


def test_stagnation_exit_display_action() -> None:
    assert Orchestrator._display_trade_action("SELL", "stagnation_exit") == "SELL_STAGNATION"
    assert Orchestrator._display_trade_action("SELL", "small_position_cleanup") == "SELL_CLEAN_UP"
    assert Orchestrator._display_trade_action("SELL", "gain_realization") == "SELL"


def test_stagnation_exit_human_reason_mapping() -> None:
    from src.agents.notifications.formatters import _human_reason

    human = _human_reason("stagnation_exit")
    assert "profit-per-day-held" in human
    assert "stagnation" in human


# ---------------------------------------------------------------------------
# End-to-end: pre-strategy cleanup path bypasses moderation/risk and uses
# live broker quantity (parity with the small_position_cleanup integration).
# ---------------------------------------------------------------------------


def test_pre_strategy_cleanup_executes_stagnation_sell_with_live_quantity(db_session, monkeypatch) -> None:
    buy_time = datetime.now(timezone.utc) - timedelta(days=12)
    db_session.add(
        Order(
            ticker="STAG_US_EQ",
            action="BUY",
            order_type="market",
            quantity=10,
            price=40.0,
            value_gbp=400.0,
            status="filled",
            timestamp=buy_time,
        )
    )
    db_session.commit()

    orchestrator = Orchestrator(dry_run=True)
    orchestrator.notification_service = _NoopNotifications()
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.5)

    # Ensure the portfolio-wide profit-lock step finds nothing so the path
    # focuses on stagnation.
    orchestrator._stop_loss_manager = SimpleNamespace(
        _get_pending_stops=lambda: {},
        enforce_profit_locks=lambda *args, **kwargs: [],
    )
    orchestrator._t212_client = SimpleNamespace(get_position=lambda ticker: {"quantity": 9.5})

    # pnl_pct comes from pnl_gbp / (avg_price * qty) = 4 / (40*10) = 1%
    # Over 12 days that is ~0.083%/day, far below the 0.5%/day floor, so the
    # ticker qualifies for stagnation while staying below the 10% profit-lock
    # threshold (which would otherwise race ahead and tag it differently).
    portfolio_data = {
        "invested": 404.0,
        "total_return_pct": 0.0,
        "alpha_pct": 0.0,
        "positions": [
            {
                "ticker": "STAG_US_EQ",
                "quantity": 10,
                "currentPrice": 40.4,
                "averagePrice": 40.0,
                "value_gbp": 404.0,  # above cleanup threshold
                "pnl_gbp": 4.0,
            }
        ],
    }

    captured: dict = {}

    def fake_execute_trade(cycle_id, decision, action, ticker, **kwargs):
        captured["ticker"] = ticker
        captured["action"] = action
        captured["quantity_override"] = kwargs["quantity_override"]
        captured["moderation"] = kwargs["mod_result"].consensus
        captured["risk"] = kwargs["risk_verdict"].verdict
        captured["reason_code"] = decision.get("deterministic_exit_reason_code")
        captured["stagnation_metrics"] = decision.get("stagnation_metrics")
        return {
            "ticker": ticker,
            "action": action,
            "execution": {"status": "dry_run"},
            "moderation": kwargs["mod_result"].consensus,
            "risk": kwargs["risk_verdict"].verdict,
            "reason_code": decision.get("deterministic_exit_reason_code"),
            "stagnation_metrics": decision.get("stagnation_metrics"),
        }

    orchestrator._execute_trade = fake_execute_trade

    result: dict = {"rejected_stocks": [], "trades": [], "order_adjustments": []}
    opportunity_evaluations: list[dict] = []

    cleanup_tickers = orchestrator._execute_pre_strategy_cleanup_sells(
        cycle_id="cycle_stag",
        portfolio_data=portfolio_data,
        current_value=1_000.0,
        cash_gbp=550.0,
        existing_tickers={"STAG_US_EQ"},
        market_regime="BULL",
        vix=18.0,
        macro={},
        analyst_data_map={},
        av_broad_sentiment={},
        result=result,
        opportunity_evaluations=opportunity_evaluations,
    )

    assert "STAG_US_EQ" in cleanup_tickers
    assert captured["ticker"] == "STAG_US_EQ"
    assert captured["action"] == "SELL"
    assert captured["quantity_override"] == 9.5
    assert captured["moderation"] == "BYPASSED"
    assert captured["risk"] == "BYPASSED"
    assert captured["reason_code"] == "stagnation_exit"
    assert captured["stagnation_metrics"] is not None
    assert captured["stagnation_metrics"]["held_days"] == pytest.approx(12.0, rel=0.05)
    assert len(opportunity_evaluations) == 1
    assert opportunity_evaluations[0]["moderation_consensus"] == "BYPASSED"


def test_slow_bleed_exit_fires_before_stagnation_min_days() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=12.0, min_ppd_pct=0.25)
    trading = orchestrator.settings._config.setdefault("trading", {})
    trading["slow_bleed_exit_enabled"] = True
    trading["slow_bleed_min_days"] = 10.0

    position = {"pnl_pct": -2.0, "held_hours": 11 * 24}
    result = orchestrator._pace_deterministic_exit_reason(position)
    assert result is not None
    code, detail, metrics = result
    assert code == "slow_bleed_exit"
    assert "slow-bleed" in detail.lower()
    assert metrics["stall_min_gain_per_day_pct"] == pytest.approx(-0.05)


def test_stagnation_grace_by_pace_skips_winner_pace() -> None:
    orchestrator = Orchestrator(dry_run=True)
    _configure_stagnation(orchestrator, min_days=5.0, min_ppd_pct=0.25)
    trading = orchestrator.settings._config.setdefault("trading", {})
    trading["stagnation_grace_by_pace"] = True

    position = {"pnl_pct": 5.0, "held_hours": 20 * 24}
    assert orchestrator._stagnation_exit_reason(position) is None


def test_pace_aware_sell_passes_below_absolute_floor() -> None:
    orchestrator = Orchestrator(dry_run=True)
    trading = orchestrator.settings._config.setdefault("trading", {})
    trading["pace_aware_sell_enabled"] = True
    trading["sell_min_profit_pct"] = 10.0

    decision = {
        "action": "SELL",
        "exit_trigger_type": "gain_realization",
    }
    position_context = {
        "AAPL_US_EQ": {"pnl_pct": 4.0, "held_hours": 16 * 24},
    }
    ok, code, _reason = orchestrator._evaluate_sell_guardrail(
        ticker="AAPL_US_EQ",
        decision=decision,
        position_context=position_context,
    )
    assert ok is True
    assert code is None
