"""Helpers for merging orchestrator run results into runs.summary_json."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Fields written by the orchestrator that the scheduler must preserve when updating runs.
ORCHESTRATOR_SUMMARY_KEYS: tuple[str, ...] = (
    "stocks_screened",
    "stocks_reviewed",
    "decisions_made",
    "num_trades",
    "num_rejected",
    "phase_timing",
    "step_timing",
    "slow_calls",
    "audit_summary",
    "order_sync",
    "orders_updated_total",
    "positions_refreshed",
    "market_data_tickers_warmed",
    "stop_adjustments",
    "deterministic_exits",
    "cost_summary",
    "rejected_by_action",
    "error_type",
    "error_message",
    "job_id",
    "instruments_enriched",
    "enrichment_backlog_remaining",
    "enrichment_backlog_before",
)


def merge_run_summary(
    existing: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    duration_seconds: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge orchestrator/scheduler fields without dropping rich timing metadata."""
    merged: dict[str, Any] = dict(existing or {})
    for key in ORCHESTRATOR_SUMMARY_KEYS:
        value = result.get(key)
        if value is not None:
            merged[key] = _json_safe(value)
    if extra:
        merged.update({key: _json_safe(value) for key, value in extra.items()})
    merged["duration_seconds"] = duration_seconds
    return merged


def _json_safe(value: Any) -> Any:
    """Return a value safe for SQLAlchemy JSON columns."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
