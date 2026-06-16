"""Filters for learning dataset decision rows."""

from __future__ import annotations

from sqlalchemy.orm import Query, Session

from dashboard.backend.app.database import Run
from src.data.models import StrategyDecision

SIMULATED_RUN_TYPE = "dry_run"


def eligible_strategy_decisions_query(session: Session) -> Query:
    """Strategy decisions excluding dry-run cycles (legacy cycles without runs kept)."""
    return (
        session.query(StrategyDecision)
        .outerjoin(Run, Run.cycle_id == StrategyDecision.cycle_id)
        .filter((Run.run_type.is_(None)) | (Run.run_type != SIMULATED_RUN_TYPE))
    )


def count_dry_run_cycles(session: Session) -> int:
    """Number of runs tagged dry_run (for audit reporting)."""
    return int(session.query(Run).filter(Run.run_type == SIMULATED_RUN_TYPE).count())
