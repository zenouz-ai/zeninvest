"""Filters for learning dataset decision rows."""

from __future__ import annotations

from sqlalchemy.orm import Query, Session

from dashboard.backend.app.database import Run
from src.data.models import StrategyDecision

SIMULATED_RUN_TYPE = "dry_run"
# Learning datasets use realized live pipeline cycles only (legacy rows without runs kept).
LIVE_RUN_TYPES = ("scheduled", "manual", "slack_command")


def eligible_strategy_decisions_query(session: Session) -> Query:
    """Strategy decisions from live trading cycles only (excludes dry_run and maintenance runs)."""
    return (
        session.query(StrategyDecision)
        .outerjoin(Run, Run.cycle_id == StrategyDecision.cycle_id)
        .filter((Run.run_type.is_(None)) | (Run.run_type.in_(LIVE_RUN_TYPES)))
    )


def is_live_trading_run_type(run_type: str | None) -> bool:
    """True when a run type should feed learning datasets."""
    return run_type is None or run_type in LIVE_RUN_TYPES


def count_dry_run_cycles(session: Session) -> int:
    """Number of runs tagged dry_run (for audit reporting)."""
    return int(session.query(Run).filter(Run.run_type == SIMULATED_RUN_TYPE).count())
