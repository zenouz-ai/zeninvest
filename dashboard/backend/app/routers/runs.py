"""Runs router - run history and metadata."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.utils.config import get_settings

from ..database import Run
from ..schemas import RunCreateSchema, RunSchema

router = APIRouter()
settings = get_settings()


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
    """Trigger a manual run (placeholder for future integration)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    # TODO: Integrate with orchestrator to trigger a manual cycle
    return {"message": "Manual run trigger not yet implemented"}
