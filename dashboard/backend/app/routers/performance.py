"""Performance router — performance_metrics."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import PerformanceMetric
from src.utils.config import get_settings

from ..schemas import PerformanceMetricSchema

router = APIRouter()
settings = get_settings()


@router.get("/metrics", response_model=PerformanceMetricSchema | None)
async def get_latest_metrics():
    """Latest performance metrics snapshot."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        row = (
            session.query(PerformanceMetric)
            .order_by(desc(PerformanceMetric.snapshot_date))
            .first()
        )
        return row
    finally:
        session.close()


@router.get("/history", response_model=list[PerformanceMetricSchema])
async def get_metrics_history(
    limit: int = Query(default=90, ge=1, le=365),
    offset: int = Query(default=0, ge=0),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Historical performance metrics for charting."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(PerformanceMetric)
        if start_date:
            query = query.filter(PerformanceMetric.snapshot_date >= start_date)
        if end_date:
            query = query.filter(PerformanceMetric.snapshot_date <= end_date)
        rows = (
            query.order_by(desc(PerformanceMetric.snapshot_date))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows
    finally:
        session.close()
