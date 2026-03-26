"""Status router - next run, dashboard status."""

from fastapi import APIRouter, HTTPException

from src.utils.config import get_settings
from src.utils.scheduling import next_scheduled_run_utc as compute_next_scheduled_run_utc
from src.utils.scheduling import resolved_cycle_times_utc

router = APIRouter()


def _next_scheduled_run_utc():
    """Compute next scheduled run time in UTC from the shared scheduling helpers."""
    return compute_next_scheduled_run_utc(get_settings())


@router.get("/")
async def get_status():
    """Get dashboard status: next run, cycle config, and system state (ACTIVE/CAUTIOUS/HALTED)."""
    settings = get_settings()
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    next_run = _next_scheduled_run_utc()
    result = {
        "next_run_utc": next_run.isoformat() if next_run else None,
        "cycle_times_utc": resolved_cycle_times_utc(settings),
        "cycle_times_local": settings.cycle_times_local if settings.schedule_mode == "market_session" else [],
        "cycle_frequency": settings.cycle_frequency,
        "schedule_mode": settings.schedule_mode,
        "schedule_timezone": settings.schedule_timezone if settings.schedule_mode == "market_session" else None,
    }
    try:
        from src.data.database import get_session
        from src.data.models import SystemState

        session = get_session()
        try:
            state_row = session.query(SystemState).first()
            if state_row:
                result["state"] = state_row.state
                result["paused"] = state_row.paused
            else:
                result["state"] = "ACTIVE"
                result["paused"] = False
        finally:
            session.close()
    except Exception:
        result["state"] = "ACTIVE"
        result["paused"] = False
    return result
