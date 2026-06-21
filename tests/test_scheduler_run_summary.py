"""Tests for scheduler run summary merge behavior."""

from src.utils.run_summary import merge_run_summary


def test_scheduler_style_merge_keeps_orchestrator_timing():
    """Simulates scheduler updating a run after orchestrator wrote rich summary."""
    orchestrator_summary = {
        "phase_timing": {
            "screening": {"seconds": 123.0, "start": "t0", "end": "t1"},
            "strategy": {"seconds": 255.0, "start": "t1", "end": "t2"},
        },
        "audit_summary": {"datasets_total": 19, "succeeded": 15},
        "order_sync": {"updated_total": 1},
        "step_timing": {"broker_sync": 12.0},
    }
    orchestrator_result = {
        "stocks_screened": 30,
        "stocks_reviewed": 12,
        "num_trades": 3,
        "rejected_stocks": [{"ticker": "X"}],
        **orchestrator_summary,
    }
    scheduler_merged = merge_run_summary(
        orchestrator_summary,
        {
            **orchestrator_result,
            "decisions_made": 12,
            "num_rejected": 1,
        },
        duration_seconds=588.0,
    )
    assert scheduler_merged["phase_timing"]["strategy"]["seconds"] == 255.0
    assert scheduler_merged["step_timing"]["broker_sync"] == 12.0
    assert scheduler_merged["audit_summary"]["datasets_total"] == 19
    assert scheduler_merged["duration_seconds"] == 588.0
