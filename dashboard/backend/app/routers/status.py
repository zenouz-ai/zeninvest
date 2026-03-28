"""Status router - next run, dashboard status."""

from fastapi import APIRouter, HTTPException

from src.data.database import get_session
from src.utils.config import get_settings
from src.utils.scheduling import next_intraday_refresh_utc as compute_next_intraday_refresh_utc
from src.utils.scheduling import next_scheduled_run_utc as compute_next_scheduled_run_utc
from src.utils.scheduling import resolved_cycle_times_utc, resolved_refresh_times_local

from ..database import Run

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
    next_refresh = compute_next_intraday_refresh_utc(settings)
    result = {
        "next_run_utc": next_run.isoformat() if next_run else None,
        "next_refresh_utc": next_refresh.isoformat() if next_refresh else None,
        "cycle_times_utc": resolved_cycle_times_utc(settings),
        "cycle_times_local": settings.cycle_times_local if settings.schedule_mode == "market_session" else [],
        "refresh_times_local": resolved_refresh_times_local(settings),
        "cycle_frequency": settings.cycle_frequency,
        "schedule_mode": settings.schedule_mode,
        "schedule_timezone": settings.schedule_timezone if settings.schedule_mode == "market_session" else None,
        "last_refresh_completed_at": None,
        "last_refresh_status": None,
        "last_refresh_summary": None,
    }
    try:
        from src.data.models import SystemState

        session = get_session()
        try:
            state_row = session.query(SystemState).first()
            latest_refresh = (
                session.query(Run)
                .filter(Run.run_type == "refresh")
                .order_by(Run.completed_at.desc(), Run.started_at.desc())
                .first()
            )
            if state_row:
                result["state"] = state_row.state
                result["paused"] = state_row.paused
                result["halted_recovery_streak"] = state_row.halted_recovery_streak or 0
                result["halted_auto_recovery_target"] = settings.halted_auto_recovery_consecutive_cycles
                result["peak_inflation_warning_note"] = state_row.peak_inflation_warning_note
            else:
                result["state"] = "ACTIVE"
                result["paused"] = False
                result["halted_recovery_streak"] = 0
                result["halted_auto_recovery_target"] = settings.halted_auto_recovery_consecutive_cycles
                result["peak_inflation_warning_note"] = None
            if latest_refresh:
                result["last_refresh_completed_at"] = (
                    latest_refresh.completed_at.isoformat() if latest_refresh.completed_at else None
                )
                result["last_refresh_status"] = latest_refresh.status
                result["last_refresh_summary"] = latest_refresh.summary_json
        finally:
            session.close()
    except Exception:
        result["state"] = "ACTIVE"
        result["paused"] = False
        result["halted_recovery_streak"] = 0
        result["halted_auto_recovery_target"] = settings.halted_auto_recovery_consecutive_cycles
        result["peak_inflation_warning_note"] = None
    return result
