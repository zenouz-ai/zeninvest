"""Runs router - run history and metadata."""

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import PortfolioSnapshot, StrategyDecision
from src.utils.config import get_settings

from ..database import Run
from ..schemas import RunCreateSchema, RunSchema

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Runs "running" longer than this are considered stale and may be reconciled
_STALE_RUN_THRESHOLD_MINUTES = 15


def _reconcile_stale_runs(session: Session) -> int:
    """Mark runs stuck in 'running' as completed when strategy_decisions exist.
    Returns count of runs reconciled."""
    threshold = datetime.now(timezone.utc) - timedelta(minutes=_STALE_RUN_THRESHOLD_MINUTES)
    stale = (
        session.query(Run)
        .filter(Run.status == "running", Run.started_at < threshold)
        .all()
    )
    reconciled = 0
    for run in stale:
        decision_count = session.query(StrategyDecision).filter(StrategyDecision.cycle_id == run.cycle_id).count()
        if decision_count > 0:
            last_ts = (
                session.query(func.max(StrategyDecision.timestamp))
                .filter(StrategyDecision.cycle_id == run.cycle_id)
                .scalar()
            )
            run.completed_at = last_ts or run.started_at
            run.status = "completed"
            summary = dict(run.summary_json) if isinstance(run.summary_json, dict) else {}
            summary["num_rejected"] = summary.get("num_rejected", decision_count)
            if run.completed_at and run.started_at:
                summary["duration_seconds"] = (run.completed_at - run.started_at).total_seconds()
            run.summary_json = summary
            reconciled += 1
            logger.info("Reconciled stale run %s to completed (%d decisions)", run.cycle_id, decision_count)
    if reconciled:
        session.commit()
    return reconciled


def _get_snapshot_for_run(session: Session, run: Run) -> PortfolioSnapshot | None:
    """Get portfolio snapshot closest to run completion."""
    if not run.completed_at:
        return None
    snap = (
        session.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.timestamp >= run.completed_at)
        .order_by(PortfolioSnapshot.timestamp.asc())
        .first()
    )
    if snap:
        return snap
    return (
        session.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.timestamp <= run.completed_at)
        .order_by(PortfolioSnapshot.timestamp.desc())
        .first()
    )


def _positions_from_snapshot(snapshot: PortfolioSnapshot) -> dict[str, float]:
    """Extract ticker -> quantity from snapshot positions_json."""
    if not snapshot.positions_json:
        return {}
    data = json.loads(snapshot.positions_json)
    return {p.get("ticker", ""): float(p.get("quantity", 0)) for p in data if p.get("ticker")}


def _run_dry_cycle() -> None:
    """Run a dry-run cycle in background (daemon thread)."""
    try:
        from src.orchestrator.main import Orchestrator

        orch = Orchestrator(dry_run=True)
        orch.run_cycle()
        orch.close()
    except Exception as e:
        logger.error("Triggered dry-run failed: %s", e, exc_info=True)


def _run_live_cycle() -> None:
    """Run a live cycle in background (daemon thread)."""
    try:
        from src.orchestrator.main import Orchestrator

        orch = Orchestrator(dry_run=False)
        orch.run_cycle()
        orch.close()
    except Exception as e:
        logger.error("Triggered live run failed: %s", e, exc_info=True)


@router.get("/", response_model=list[RunSchema])
async def get_runs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    run_type: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Get list of runs with pagination and filtering."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        _reconcile_stale_runs(session)
        query = session.query(Run)

        if run_type:
            query = query.filter(Run.run_type == run_type)

        if start_date:
            query = query.filter(Run.started_at >= start_date)

        if end_date:
            query = query.filter(Run.started_at <= end_date)

        runs = query.order_by(desc(Run.started_at)).offset(offset).limit(limit).all()
        return runs
    finally:
        session.close()


@router.get("/diff")
async def get_run_diff(
    from_cycle_id: str = Query(..., description="Earlier cycle ID"),
    to_cycle_id: str = Query(..., description="Later cycle ID"),
):
    """Get position diff between two runs (new, closed, size changes)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        run_from = session.query(Run).filter(Run.cycle_id == from_cycle_id).first()
        run_to = session.query(Run).filter(Run.cycle_id == to_cycle_id).first()
        if not run_from or not run_to:
            raise HTTPException(status_code=404, detail="Run not found")

        snap_from = _get_snapshot_for_run(session, run_from)
        snap_to = _get_snapshot_for_run(session, run_to)

        pos_from = _positions_from_snapshot(snap_from) if snap_from else {}
        pos_to = _positions_from_snapshot(snap_to) if snap_to else {}

        new_positions = [t for t in pos_to if t not in pos_from or pos_from[t] == 0]
        closed_positions = [t for t in pos_from if t not in pos_to or pos_to.get(t, 0) == 0]
        size_changes = []
        for t in set(pos_from) & set(pos_to):
            q_from, q_to = pos_from[t], pos_to[t]
            if abs(q_from - q_to) > 0.0001:
                size_changes.append({"ticker": t, "from_qty": q_from, "to_qty": q_to})

        return {
            "from_cycle_id": from_cycle_id,
            "to_cycle_id": to_cycle_id,
            "new_positions": new_positions,
            "closed_positions": closed_positions,
            "size_changes": size_changes,
        }
    finally:
        session.close()


@router.get("/{run_id}", response_model=RunSchema)
async def get_run(run_id: int):
    """Get a specific run by ID."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        run = session.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run
    finally:
        session.close()


@router.get("/cycle/{cycle_id}", response_model=RunSchema)
async def get_run_by_cycle_id(cycle_id: str):
    """Get a run by cycle_id."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run
    finally:
        session.close()


@router.post("/", response_model=RunSchema)
async def create_run(run_data: RunCreateSchema):
    """Create a new run (typically called by orchestrator)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        run = Run(
            cycle_id=run_data.cycle_id,
            run_type=run_data.run_type,
            started_at=datetime.now(),
            status="running",
            summary_json=run_data.summary_json,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@router.post("/trigger")
async def trigger_manual_run():
    """Trigger a dry-run cycle in the background."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    t = threading.Thread(target=_run_dry_cycle, daemon=True, name="TriggeredDryRun")
    t.start()
    return {"message": "Dry-run cycle triggered in background", "status": "started"}


@router.post("/trigger-live")
async def trigger_live_run():
    """Trigger a live cycle in the background (executes real trades)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    t = threading.Thread(target=_run_live_cycle, daemon=True, name="TriggeredLiveRun")
    t.start()
    return {"message": "Live cycle triggered in background", "status": "started"}
