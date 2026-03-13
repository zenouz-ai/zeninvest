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


@router.post("/reset-peak")
async def reset_peak():
    """Reset peak to current portfolio value and transition to ACTIVE.
    Use when CAUTIOUS was triggered incorrectly (e.g. peak inflated by data glitch).
    """
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    from src.agents.execution.order_manager import OrderManager
    from src.orchestrator.state_machine import StateMachine

    try:
        om = OrderManager()
        state = om.get_portfolio_state()
        om.close()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to get portfolio: {e}") from e

    if state.get("error"):
        raise HTTPException(status_code=502, detail=f"Portfolio error: {state['error']}")

    summary = state.get("account_summary") or {}
    total_raw = summary.get("totalValue")
    if total_raw is not None:
        current = float(total_raw)
    else:
        cash_data = state.get("cash", {})
        positions = state.get("positions", [])
        if isinstance(cash_data, dict):
            cash = float(cash_data.get("free", cash_data.get("availableToTrade", 0)))
            reserved = float(cash_data.get("reservedForOrders", cash_data.get("reserved", 0)))
        else:
            cash = float(cash_data)
            reserved = 0.0
        invested = sum(
            float(p.get("currentPrice", 0)) * float(p.get("quantity", 0))
            for p in positions
        )
        current = cash + invested + reserved

    if current <= 0:
        raise HTTPException(status_code=400, detail="Portfolio value is 0 or missing")

    sm = StateMachine()
    sm.reset_peak_to_current(current)
    return {"message": "Peak reset to current value", "state": "ACTIVE", "current_value": current}
