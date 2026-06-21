"""Latency observability API — schedule map, timing aggregates, slow calls."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.utils.config import get_settings
from src.utils.scheduling import (
    analysis_cycle_day_of_week,
    analysis_cycle_specs,
    intraday_refresh_specs,
    uses_market_session_schedule,
)
from src.utils.slow_calls import aggregate_slow_calls

from src.observability.scorecard import compute_latency_scorecard

from ..database import LatencySpan, Run
from ..schemas import (
    LatencyBaselineResponseSchema,
    LatencyRunSpanSchema,
    LatencyScheduleJobSchema,
    LatencyScheduleSchema,
    LatencySlowCallSchema,
    LatencySummarySchema,
    LatencyTimelineRunSchema,
    LatencyTimelineSchema,
)

router = APIRouter()
settings = get_settings()

FIXED_UTC_JOBS: list[dict[str, Any]] = [
    {"job_id": "strategy_episode_scan", "cron": "02:00 UTC daily", "run_type": "strategy_episode_scan", "category": "daily_utc"},
    {"job_id": "enrich_universe", "cron": "06:00 UTC daily", "run_type": "enrich_universe", "category": "daily_utc"},
    {"job_id": "macro_scan", "cron": "06:00 UTC daily", "run_type": "macro_scan", "category": "daily_utc"},
    {"job_id": "daily_snapshot", "cron": "21:30 UTC daily", "run_type": "daily_snapshot", "category": "daily_utc"},
    {"job_id": "shadow_outcome_join", "cron": "22:30 UTC daily", "run_type": "shadow_outcome_join", "category": "daily_utc"},
    {"job_id": "weekly_report", "cron": "22:00 UTC Fri", "run_type": "weekly_report", "category": "weekly_utc"},
    {"job_id": "instrument_refresh", "cron": "12:00 UTC Sun", "run_type": "instrument_refresh", "category": "weekly_utc"},
    {"job_id": "learning_export", "cron": "13:00 UTC Sun", "run_type": "learning_export", "category": "weekly_utc"},
    {"job_id": "learning_evaluate", "cron": "14:00 UTC Sun", "run_type": "learning_evaluate", "category": "weekly_utc"},
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def _run_duration_seconds(run: Run) -> float:
    summary = run.summary_json if isinstance(run.summary_json, dict) else {}
    if summary.get("duration_seconds") is not None:
        return float(summary["duration_seconds"])
    if run.completed_at and run.started_at:
        return (run.completed_at - run.started_at).total_seconds()
    return 0.0


@router.get("/schedule", response_model=LatencyScheduleSchema)
async def get_latency_schedule() -> LatencyScheduleSchema:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    jobs: list[LatencyScheduleJobSchema] = []
    tz_label = settings.schedule_timezone if uses_market_session_schedule(settings) else "UTC"
    dow = analysis_cycle_day_of_week(settings)

    for spec in analysis_cycle_specs(settings):
        jobs.append(
            LatencyScheduleJobSchema(
                job_id=spec.job_id,
                run_type="scheduled",
                cron=f"{spec.clock_time} {tz_label} ({dow})",
                category="analysis_cycle",
                shares_cycle_lock=True,
            )
        )
    for spec in intraday_refresh_specs(settings):
        jobs.append(
            LatencyScheduleJobSchema(
                job_id=spec.job_id,
                run_type="refresh",
                cron=f"{spec.clock_time} {tz_label} ({dow})",
                category="intraday_refresh",
                shares_cycle_lock=True,
            )
        )
    for item in FIXED_UTC_JOBS:
        jobs.append(LatencyScheduleJobSchema(**item, shares_cycle_lock=False))

    return LatencyScheduleSchema(
        timezone=tz_label,
        cycle_lock_note="Analysis cycles and intraday refresh share orchestrator-cycle.lock",
        jobs=jobs,
    )


@router.get("/summary", response_model=LatencySummarySchema)
async def get_latency_summary(days: int = Query(default=30, ge=1, le=90)) -> LatencySummarySchema:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    session = get_session()
    try:
        runs = (
            session.query(Run)
            .filter(Run.started_at >= cutoff, Run.status.in_(["completed", "failed", "strategy_error"]))
            .order_by(desc(Run.started_at))
            .all()
        )

        by_run_type: dict[str, list[float]] = {}
        phase_buckets: dict[str, list[float]] = {}
        step_buckets: dict[str, list[float]] = {}
        off_hours: list[dict[str, Any]] = []

        for run in runs:
            duration = _run_duration_seconds(run)
            by_run_type.setdefault(run.run_type, []).append(duration)
            summary = run.summary_json if isinstance(run.summary_json, dict) else {}
            for phase, meta in (summary.get("phase_timing") or {}).items():
                if isinstance(meta, dict) and meta.get("seconds") is not None:
                    phase_buckets.setdefault(str(phase), []).append(float(meta["seconds"]))
            for step, seconds in (summary.get("step_timing") or {}).items():
                step_buckets.setdefault(str(step), []).append(float(seconds))
            if run.run_type not in ("scheduled", "manual", "refresh", "dry_run"):
                off_hours.append(
                    {
                        "cycle_id": run.cycle_id,
                        "run_type": run.run_type,
                        "duration_seconds": round(duration, 2),
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "status": run.status,
                    }
                )

        run_type_stats = {
            run_type: {
                "count": len(durations),
                "avg_seconds": round(statistics.mean(durations), 2) if durations else 0,
                "p50_seconds": _percentile(durations, 0.5),
                "p95_seconds": _percentile(durations, 0.95),
            }
            for run_type, durations in by_run_type.items()
        }
        phase_stats = {
            phase: {
                "count": len(vals),
                "p50_seconds": _percentile(vals, 0.5),
                "p95_seconds": _percentile(vals, 0.95),
            }
            for phase, vals in phase_buckets.items()
        }
        step_stats = {
            step: {
                "count": len(vals),
                "p50_seconds": _percentile(vals, 0.5),
                "p95_seconds": _percentile(vals, 0.95),
            }
            for step, vals in step_buckets.items()
        }

        scorecard = compute_latency_scorecard(session, days=days, run_type="scheduled")
        current_scorecard = scorecard.get("current") if isinstance(scorecard.get("current"), dict) else {}

        return LatencySummarySchema(
            days=days,
            run_types=run_type_stats,
            phases=phase_stats,
            steps=step_stats,
            off_hours_jobs=off_hours[:30],
            truncation_rate=current_scorecard.get("truncation_rate"),
            baseline_delta=scorecard.get("baseline_delta"),
            frozen_baseline=scorecard.get("frozen_baseline"),
        )
    finally:
        session.close()


@router.get("/timeline", response_model=LatencyTimelineSchema)
async def get_latency_timeline(
    date_value: date | None = Query(default=None, alias="date"),
) -> LatencyTimelineSchema:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    target = date_value or datetime.now(timezone.utc).date()
    start = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    session = get_session()
    try:
        runs = (
            session.query(Run)
            .filter(Run.started_at >= start, Run.started_at < end)
            .order_by(Run.started_at.asc())
            .all()
        )
        entries: list[LatencyTimelineRunSchema] = []
        lock_warnings: list[str] = []
        prev_lock_run: Run | None = None
        for run in runs:
            if run.run_type in ("scheduled", "refresh", "manual", "dry_run"):
                if prev_lock_run and run.started_at and prev_lock_run.completed_at:
                    if run.started_at < prev_lock_run.completed_at:
                        lock_warnings.append(
                            f"{run.cycle_id} started before {prev_lock_run.cycle_id} finished — possible lock contention"
                        )
                prev_lock_run = run
            entries.append(
                LatencyTimelineRunSchema(
                    cycle_id=run.cycle_id,
                    run_type=run.run_type,
                    status=run.status,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    duration_seconds=round(_run_duration_seconds(run), 2),
                    shares_cycle_lock=run.run_type in ("scheduled", "refresh", "manual", "dry_run"),
                )
            )
        return LatencyTimelineSchema(date=target.isoformat(), runs=entries, lock_warnings=lock_warnings)
    finally:
        session.close()


@router.get("/slow-calls", response_model=list[LatencySlowCallSchema])
async def get_latency_slow_calls(
    days: int = Query(default=7, ge=1, le=90),
    min_duration_ms: float = Query(default=1000.0, ge=100),
) -> list[LatencySlowCallSchema]:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    rows = aggregate_slow_calls(days=days, min_duration_ms=min_duration_ms)
    return [LatencySlowCallSchema(**row) for row in rows]


@router.get("/runs/{run_id}/spans", response_model=list[LatencyRunSpanSchema])
async def get_run_spans(run_id: int) -> list[LatencyRunSpanSchema]:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        spans = (
            session.query(LatencySpan)
            .filter(LatencySpan.run_id == run_id)
            .order_by(LatencySpan.started_at.asc(), LatencySpan.id.asc())
            .all()
        )
        return [
            LatencyRunSpanSchema(
                span_name=span.span_name,
                parent_span=span.parent_span,
                started_at=span.started_at,
                completed_at=span.completed_at,
                duration_ms=span.duration_ms,
                metadata_json=span.metadata_json,
            )
            for span in spans
        ]
    finally:
        session.close()


@router.post("/baseline", response_model=LatencyBaselineResponseSchema)
async def trigger_latency_baseline(
    background_tasks: BackgroundTasks,
    dry_run: bool = Query(default=True),
    include_learning: bool = Query(default=False),
) -> LatencyBaselineResponseSchema:
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    from src.observability.baseline import run_latency_baseline

    background_tasks.add_task(run_latency_baseline, dry_run=dry_run, include_learning=include_learning)
    return LatencyBaselineResponseSchema(
        status="started",
        dry_run=dry_run,
        include_learning=include_learning,
        message="Baseline timing exercise started in background",
    )
