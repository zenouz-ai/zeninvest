"""Helpers for persisting and querying per-run dataset audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func

from src.data.database import get_session
from src.data.models import (
    CostLog,
    CycleContextSnapshot,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroState,
    MarketDataCache,
    ModerationLog,
    NewsSentimentCache,
    OpportunityQueue,
    OpportunityScoreSnapshot,
    PerformanceMetric,
    PortfolioSnapshot,
    ResearchLog,
    RiskDecision,
    StopLossAdjustment,
    StrategyDecision,
    StrategyChangeEpisode,
    TradeOutcome,
)
from src.utils.logger import get_logger

from ..database import Run, RunDatasetAudit

logger = get_logger("dashboard.run_audit")


DATASET_COUNT_MODELS: dict[str, tuple[type[Any], str | None]] = {
    "portfolio_snapshot": (PortfolioSnapshot, "timestamp"),
    "market_data_cache": (MarketDataCache, "timestamp"),
    "news_sentiment_cache": (NewsSentimentCache, "timestamp"),
    "opportunity_queue_warm": (OpportunityQueue, "updated_at"),
    "stop_loss_maintenance": (StopLossAdjustment, "timestamp"),
    "trade_outcomes": (TradeOutcome, "created_at"),
    "performance_metrics": (PerformanceMetric, "created_at"),
    "instrument_screening": (Instrument, "updated_at"),
    "strategy_decisions": (StrategyDecision, "timestamp"),
    "moderation_logs": (ModerationLog, "timestamp"),
    "risk_decisions": (RiskDecision, "timestamp"),
    "opportunity_score_snapshots": (OpportunityScoreSnapshot, "timestamp"),
    "opportunity_queue": (OpportunityQueue, "updated_at"),
    "macro_state": (MacroState, "timestamp"),
    "macro_headlines": (MacroHeadline, "fetched_at"),
    "guidance_snapshots": (GuidanceSnapshot, "timestamp"),
    "cycle_context_snapshots": (CycleContextSnapshot, "captured_at"),
    "strategy_change_episodes": (StrategyChangeEpisode, "effective_start_at"),
    "research_logs": (ResearchLog, "created_at"),
    "cost_logs": (CostLog, "timestamp"),
}


@dataclass
class DatasetSnapshot:
    """Row-count snapshot for a dataset before or after a run."""

    rows: int | None
    latest_timestamp: datetime | None


def ensure_run_record(
    *,
    cycle_id: str,
    run_type: str,
    started_at: datetime,
    status: str = "running",
) -> int | None:
    """Get or create a Run row and return its id."""
    session = get_session()
    try:
        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
        if run is None:
            run = Run(
                cycle_id=cycle_id,
                run_type=run_type,
                started_at=started_at,
                status=status,
            )
            session.add(run)
            session.flush()
        elif run.started_at is None:
            run.started_at = started_at
            run.status = status
        session.commit()
        return int(run.id)
    except Exception as exc:
        session.rollback()
        logger.warning("Failed to ensure run record for audit persistence: %s", exc, exc_info=True)
        return None
    finally:
        session.close()


def dataset_snapshot(dataset_key: str) -> DatasetSnapshot:
    """Return the current row count and latest timestamp for a dataset."""
    model_info = DATASET_COUNT_MODELS.get(dataset_key)
    if model_info is None:
        return DatasetSnapshot(rows=None, latest_timestamp=None)

    model, timestamp_attr = model_info
    session = get_session()
    try:
        rows = session.query(func.count()).select_from(model).scalar()
        latest_timestamp = None
        if timestamp_attr is not None:
            latest_timestamp = session.query(func.max(getattr(model, timestamp_attr))).scalar()
        return DatasetSnapshot(
            rows=int(rows or 0),
            latest_timestamp=latest_timestamp,
        )
    except Exception as exc:
        logger.debug("Dataset snapshot failed for %s: %s", dataset_key, exc)
        return DatasetSnapshot(rows=None, latest_timestamp=None)
    finally:
        session.close()


def write_run_dataset_audits(
    *,
    cycle_id: str,
    run_type: str,
    entries: list[dict[str, Any]],
) -> list[RunDatasetAudit]:
    """Replace and persist the audit entries for a run."""
    session = get_session()
    try:
        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
        if run is None:
            run = Run(
                cycle_id=cycle_id,
                run_type=run_type,
                started_at=datetime.now(timezone.utc),
                status="running",
            )
            session.add(run)
            session.flush()

        session.query(RunDatasetAudit).filter(RunDatasetAudit.run_id == run.id).delete()

        records: list[RunDatasetAudit] = []
        for entry in entries:
            record = RunDatasetAudit(
                run_id=run.id,
                cycle_id=cycle_id,
                run_type=run_type,
                dataset_key=str(entry["dataset_key"]),
                status=str(entry["status"]),
                started_at=entry.get("started_at") or datetime.now(timezone.utc),
                completed_at=entry.get("completed_at"),
                source_timestamp=entry.get("source_timestamp"),
                rows_before=entry.get("rows_before"),
                rows_after=entry.get("rows_after"),
                delta_rows=entry.get("delta_rows"),
                metadata_json=entry.get("metadata_json"),
                error_message=entry.get("error_message"),
            )
            session.add(record)
            records.append(record)

        session.commit()
        return records
    except Exception as exc:
        session.rollback()
        logger.warning("Failed to persist run dataset audits for %s: %s", cycle_id, exc, exc_info=True)
        return []
    finally:
        session.close()


def summarize_audit_entries(entries: list[dict[str, Any]] | list[RunDatasetAudit]) -> dict[str, Any]:
    """Aggregate counts and dataset keys by audit status."""
    summary = {
        "datasets_total": 0,
        "succeeded": 0,
        "failed": 0,
        "partial": 0,
        "skipped": 0,
        "degraded": False,
        "failed_keys": [],
        "partial_keys": [],
    }
    for entry in entries:
        status = str(getattr(entry, "status", None) if not isinstance(entry, dict) else entry.get("status") or "")
        dataset_key = str(
            getattr(entry, "dataset_key", None) if not isinstance(entry, dict) else entry.get("dataset_key") or ""
        )
        if not status or not dataset_key:
            continue
        summary["datasets_total"] += 1
        if status in {"succeeded", "failed", "partial", "skipped"}:
            summary[status] += 1
        if status == "failed":
            summary["failed_keys"].append(dataset_key)
        elif status == "partial":
            summary["partial_keys"].append(dataset_key)

    summary["degraded"] = bool(summary["failed"] or summary["partial"])
    return summary


def get_run_audit_summary(*, cycle_id: str) -> dict[str, Any] | None:
    """Return an aggregate summary for a run's dataset audits."""
    session = get_session()
    try:
        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
        if run is None:
            return None
        entries = (
            session.query(RunDatasetAudit)
            .filter(RunDatasetAudit.run_id == run.id)
            .order_by(RunDatasetAudit.dataset_key.asc())
            .all()
        )
        if not entries:
            return None
        return summarize_audit_entries(entries)
    except Exception as exc:
        logger.debug("Failed to compute run audit summary for %s: %s", cycle_id, exc)
        return None
    finally:
        session.close()
