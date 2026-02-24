"""Orchestrator state machine — persisted in SQLite."""

from datetime import datetime, timedelta
from typing import Any

from src.data.database import get_session
from src.data.models import SystemState
from src.utils.logger import get_logger

logger = get_logger("state_machine")


class StateMachine:
    """Manages the orchestrator system state.

    States:
    - ACTIVE: Normal, full risk budget
    - CAUTIOUS: >5% drawdown. Max 8% per position, no new positions, only add to winners
    - HALTED: >15% drawdown. Liquidate all, stop, alert
    """

    VALID_STATES = {"ACTIVE", "CAUTIOUS", "HALTED"}

    def __init__(self) -> None:
        self._ensure_state_exists()

    def _ensure_state_exists(self) -> None:
        """Ensure a system state row exists in the database."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                state = SystemState(
                    state="ACTIVE",
                    peak_portfolio_value=None,
                    current_drawdown_pct=0.0,
                    paused=False,
                    updated_at=datetime.utcnow(),
                )
                session.add(state)
                session.commit()
                logger.info("Initialized system state to ACTIVE")
        finally:
            session.close()

    def get_state(self) -> dict[str, Any]:
        """Get the current system state."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return {"state": "ACTIVE", "paused": False}
            return {
                "state": state.state,
                "peak_portfolio_value": state.peak_portfolio_value,
                "current_drawdown_pct": state.current_drawdown_pct,
                "last_cycle_at": state.last_cycle_at,
                "daily_loss_halt_until": state.daily_loss_halt_until,
                "paused": state.paused,
                "notes": state.notes,
            }
        finally:
            session.close()

    @property
    def current_state(self) -> str:
        return self.get_state()["state"]

    @property
    def is_paused(self) -> bool:
        return self.get_state().get("paused", False)

    def transition(self, new_state: str, notes: str | None = None) -> None:
        """Transition to a new state."""
        if new_state not in self.VALID_STATES:
            raise ValueError(f"Invalid state: {new_state}. Must be one of {self.VALID_STATES}")

        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            old_state = state.state
            state.state = new_state
            state.notes = notes
            state.updated_at = datetime.utcnow()
            session.commit()
            logger.info(f"State transition: {old_state} -> {new_state}" + (f" ({notes})" if notes else ""))
        finally:
            session.close()

    def update_peak(self, current_value: float) -> None:
        """Update peak portfolio value if new high."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            if state.peak_portfolio_value is None or current_value > state.peak_portfolio_value:
                state.peak_portfolio_value = current_value
                state.updated_at = datetime.utcnow()
                session.commit()
                logger.info(f"New portfolio peak: {current_value:.2f}")
        finally:
            session.close()

    def update_drawdown(self, drawdown_pct: float) -> None:
        """Update current drawdown percentage."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            state.current_drawdown_pct = drawdown_pct
            state.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

    def record_cycle(self) -> None:
        """Record that a cycle has completed."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            state.last_cycle_at = datetime.utcnow()
            state.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

    def set_daily_loss_halt(self) -> None:
        """Set 24-hour halt on new buys after daily loss threshold."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            state.daily_loss_halt_until = datetime.utcnow() + timedelta(hours=24)
            state.updated_at = datetime.utcnow()
            session.commit()
            logger.warning("Daily loss halt activated for 24 hours")
        finally:
            session.close()

    def pause(self) -> None:
        """Pause the system."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            state.paused = True
            state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("System PAUSED")
        finally:
            session.close()

    def resume(self) -> None:
        """Resume the system."""
        session = get_session()
        try:
            state = session.query(SystemState).first()
            if state is None:
                return
            state.paused = False
            state.updated_at = datetime.utcnow()
            session.commit()
            logger.info("System RESUMED")
        finally:
            session.close()
