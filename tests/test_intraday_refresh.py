"""Tests for the intraday broker/data refresh workflow."""

from __future__ import annotations

from pathlib import Path

import src.orchestrator.main as orchestrator_module
from src.runtime.locking import RuntimeLockHeldError


class _FakeLock:
    def release(self) -> None:
        return None


class _FakeStateMachine:
    def get_state(self) -> dict[str, str]:
        return {"state": "ACTIVE"}


def test_intraday_refresh_skips_when_cycle_lock_is_held(monkeypatch) -> None:
    def _raise_lock(*args, **kwargs):
        raise RuntimeLockHeldError(lock_name="orchestrator-cycle", lock_path=Path("lock"))

    monkeypatch.setattr(
        orchestrator_module,
        "acquire_runtime_lock",
        _raise_lock,
    )
    monkeypatch.setattr(orchestrator_module, "StateMachine", _FakeStateMachine)

    orch = orchestrator_module.Orchestrator(dry_run=False)
    try:
        result = orch.run_intraday_refresh()
    finally:
        orch.close()

    assert result["status"] == "skipped_locked"


def test_intraday_refresh_updates_snapshot_and_warms_market_data(monkeypatch) -> None:
    monkeypatch.setenv("T212_API_KEY", "ci_test_key")
    monkeypatch.setenv("T212_API_SECRET", "ci_test_secret")
    monkeypatch.setattr(orchestrator_module, "DASHBOARD_AVAILABLE", False)
    monkeypatch.setattr(orchestrator_module, "StateMachine", _FakeStateMachine)
    monkeypatch.setattr(orchestrator_module, "acquire_runtime_lock", lambda *args, **kwargs: _FakeLock())
    monkeypatch.setattr(orchestrator_module, "update_trade_outcomes", lambda: None)
    monkeypatch.setattr(orchestrator_module, "update_performance_metrics", lambda: None)

    orch = orchestrator_module.Orchestrator(dry_run=False)
    snapshot_calls: list[tuple[dict, str]] = []

    portfolio_data = {
        "cash": 2500.0,
        "total_value": 12_500.0,
        "invested": 10_000.0,
        "positions": [
            {
                "instrument": {"ticker": "AAPL_US_EQ"},
                "quantity": 2.0,
                "currentPrice": 100.0,
                "walletImpact": {"currentValue": 200.0, "unrealizedProfitLoss": 40.0, "totalCost": 160.0},
            }
        ],
        "num_positions": 1,
        "daily_pnl_pct": 0.0,
        "total_return_pct": 5.0,
        "alpha_pct": 0.0,
    }

    monkeypatch.setattr(orch.order_manager, "sync_orders_with_t212", lambda: {"updated_total": 1})
    monkeypatch.setattr(orch, "_get_portfolio_state", lambda: portfolio_data)
    monkeypatch.setattr(orch, "_save_snapshot", lambda data, state: snapshot_calls.append((data, state)))
    monkeypatch.setattr(orch, "_get_intraday_refresh_tickers", lambda data: ["AAPL_US_EQ", "MSFT_US_EQ"])
    monkeypatch.setattr(
        orch,
        "_warm_intraday_refresh_market_data",
        lambda tickers: [
            {"ticker": "AAPL_US_EQ", "indicators": {"atr_14": 5.0}, "fundamentals": {}},
            {"ticker": "MSFT_US_EQ", "indicators": {"atr_14": 4.0}, "fundamentals": {}},
        ],
    )
    monkeypatch.setattr(orch.stop_loss_manager, "place_missing_stops", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch.stop_loss_manager, "reassess_stops", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch.stop_loss_manager, "apply_trailing_stops", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch.stop_loss_manager, "enforce_profit_locks", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch, "_build_profit_lock_context", lambda *args, **kwargs: {})

    try:
        result = orch.run_intraday_refresh()
    finally:
        orch.close()

    assert result["status"] == "completed"
    assert result["positions_refreshed"] == 1
    assert result["market_data_tickers_warmed"] == 2
    assert len(snapshot_calls) == 2
