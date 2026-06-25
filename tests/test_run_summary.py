"""Tests for run summary merge helper."""

from datetime import datetime, timezone

from src.utils.run_summary import merge_run_summary


def test_merge_preserves_phase_timing_from_orchestrator():
    existing = {"duration_seconds": 100, "stocks_screened": 30}
    result = {
        "phase_timing": {"screening": {"seconds": 120.0}},
        "audit_summary": {"datasets_total": 5},
        "order_sync": {"updated_total": 1},
        "stocks_screened": 30,
    }
    merged = merge_run_summary(existing, result, duration_seconds=540.0)
    assert merged["phase_timing"]["screening"]["seconds"] == 120.0
    assert merged["audit_summary"]["datasets_total"] == 5
    assert merged["order_sync"]["updated_total"] == 1
    assert merged["duration_seconds"] == 540.0


def test_merge_scheduler_counts_with_rich_orchestrator_fields():
    existing = {
        "phase_timing": {"strategy": {"seconds": 250.0}},
        "step_timing": {"order_sync": 12.0},
    }
    result = {
        "stocks_screened": 30,
        "stocks_reviewed": 12,
        "num_trades": 2,
        "rejected_stocks": [],
    }
    merged = merge_run_summary(
        existing,
        {**result, "decisions_made": 12, "num_rejected": 0},
        duration_seconds=600.0,
    )
    assert merged["phase_timing"]["strategy"]["seconds"] == 250.0
    assert merged["step_timing"]["order_sync"] == 12.0
    assert merged["num_trades"] == 2
    assert merged["duration_seconds"] == 600.0


def test_merge_sanitizes_nested_datetime_values_for_json_columns():
    ts = datetime(2026, 6, 21, 21, 4, 20, tzinfo=timezone.utc)
    merged = merge_run_summary(
        None,
        {
            "order_sync": {"last_broker_sync_at": ts},
            "slow_calls": [{"service": "t212", "started_at": ts}],
        },
        duration_seconds=12.5,
        extra={"completed_at": ts},
    )

    assert merged["order_sync"]["last_broker_sync_at"] == ts.isoformat()
    assert merged["slow_calls"][0]["started_at"] == ts.isoformat()
    assert merged["completed_at"] == ts.isoformat()
