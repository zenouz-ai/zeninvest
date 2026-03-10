"""System router — state, trigger, pause, resume."""

from fastapi import APIRouter, HTTPException

from src.data.database import get_session
from src.data.models import SystemState
from src.utils.config import get_settings

from ..schemas import SystemStateSchema

router = APIRouter()
settings = get_settings()


@router.get("/state", response_model=SystemStateSchema)
async def get_system_state():
    """Current system state (ACTIVE/CAUTIOUS/HALTED), paused, drawdown."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        row = session.query(SystemState).first()
        if not row:
            return SystemStateSchema(state="ACTIVE", paused=False)
        return SystemStateSchema(
            state=row.state,
            paused=row.paused,
            current_drawdown_pct=row.current_drawdown_pct,
            peak_portfolio_value=row.peak_portfolio_value,
            last_cycle_at=row.last_cycle_at,
        )
    finally:
        session.close()


@router.post("/trigger-cycle")
async def trigger_cycle():
    """Trigger a manual dry-run cycle (same as POST /api/runs/trigger)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    import threading

    from .runs import _run_dry_cycle

    t = threading.Thread(target=_run_dry_cycle, daemon=True, name="TriggeredDryRun")
    t.start()
    return {"message": "Dry-run cycle triggered in background", "status": "started"}


@router.post("/pause")
async def pause_system():
    """Pause trading (no new cycles execute until resumed)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    from src.orchestrator.state_machine import StateMachine

    sm = StateMachine()
    sm.pause()
    return {"message": "System paused", "paused": True}


@router.post("/resume")
async def resume_system():
    """Resume trading."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    from src.orchestrator.state_machine import StateMachine

    sm = StateMachine()
    sm.resume()
    return {"message": "System resumed", "paused": False}
