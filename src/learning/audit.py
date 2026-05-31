"""Schema and data-availability audit for the learning pipeline.

Run before building the dataset:

    poetry run python -m src.learning.audit

Reports row counts, time ranges, label-class feasibility, and missing-data
shares for the feature groups defined in :mod:`src.learning.spec`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import (
    CycleContextSnapshot,
    GuidanceSnapshot,
    Instrument,
    MacroHeadline,
    MacroSignalLog,
    MacroState,
    MarketDataCache,
    ModerationLog,
    OpportunityScoreSnapshot,
    Order,
    PortfolioSnapshot,
    ResearchLog,
    RiskDecision,
    StopLossAdjustment,
    StrategyDecision,
    TradeOutcome,
)
from src.learning.spec import DatasetSpec, get_default_spec
from src.utils.logger import get_logger

logger = get_logger("learning.audit")


@dataclass
class TableAudit:
    """Audit result for one source table."""

    table: str
    rows: int
    first_ts: str | None
    last_ts: str | None
    notes: list[str]


@dataclass
class AuditReport:
    """Top-level audit report."""

    generated_at: str
    spec_version: str
    tables: list[TableAudit]
    eligible_rows: int
    closed_trades: int
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "spec_version": self.spec_version,
            "tables": [asdict(t) for t in self.tables],
            "eligible_rows": self.eligible_rows,
            "closed_trades": self.closed_trades,
            "summary": self.summary,
        }


def _ts_range(session: Session, model: Any, ts_col_name: str = "timestamp") -> tuple[str | None, str | None]:
    col = getattr(model, ts_col_name)
    row = session.query(func.min(col), func.max(col)).one()
    first, last = row
    return (
        first.isoformat() if isinstance(first, datetime) else None,
        last.isoformat() if isinstance(last, datetime) else None,
    )


def _count(session: Session, model: Any) -> int:
    value = session.query(func.count()).select_from(model).scalar()
    return int(value or 0)


def run_audit(
    session: Session | None = None,
    spec: DatasetSpec | None = None,
) -> AuditReport:
    """Build an audit report for the configured spec."""
    spec = spec or get_default_spec()
    own_session = session is None
    if session is None:
        session = get_session()
    try:
        audits: list[TableAudit] = []
        for model, ts_col, notes in (
            (StrategyDecision, "timestamp", []),
            (ModerationLog, "timestamp", []),
            (RiskDecision, "timestamp", []),
            (OpportunityScoreSnapshot, "timestamp", []),
            (Order, "timestamp", []),
            (TradeOutcome, "sell_timestamp", ["only filled/dry-run sells are matched"]),
            (PortfolioSnapshot, "timestamp", []),
            (StopLossAdjustment, "timestamp", []),
            (MacroState, "timestamp", []),
            (GuidanceSnapshot, "timestamp", []),
            (MarketDataCache, "timestamp", ["lite_analysis vs full_analysis varies by cycle"]),
            (ResearchLog, "created_at", []),
            (Instrument, "updated_at", []),
            (MacroHeadline, "published_at", []),
            (MacroSignalLog, "timestamp", []),
            (CycleContextSnapshot, "captured_at", []),
        ):
            try:
                rows = _count(session, model)
                first_ts, last_ts = _ts_range(session, model, ts_col)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("audit failed for %s: %s", model.__tablename__, exc)
                rows = 0
                first_ts = None
                last_ts = None
                notes = list(notes) + [f"audit_error: {exc}"]
            audits.append(
                TableAudit(
                    table=model.__tablename__,
                    rows=rows,
                    first_ts=first_ts,
                    last_ts=last_ts,
                    notes=list(notes),
                )
            )

        # Eligible decision rows for the dataset.
        eligible_rows = int(
            session.query(func.count())
            .select_from(StrategyDecision)
            .filter(StrategyDecision.action.in_(spec.row_actions))
            .scalar()
            or 0
        )
        closed_trades = _count(session, TradeOutcome)

        # Per-action distribution for context.
        per_action_rows = dict(
            session.query(StrategyDecision.action, func.count())
            .group_by(StrategyDecision.action)
            .all()
        )

        # Coverage hints: how many decisions have a moderation row?
        decisions_with_moderation = int(
            session.query(func.count())
            .select_from(
                session.query(ModerationLog.cycle_id, ModerationLog.ticker)
                .group_by(ModerationLog.cycle_id, ModerationLog.ticker)
                .subquery()
            )
            .scalar()
            or 0
        )

        summary = {
            "per_action_rows": {str(k): int(v) for k, v in per_action_rows.items()},
            "decisions_with_moderation": decisions_with_moderation,
            "row_actions": list(spec.row_actions),
            "feature_groups": list(spec.feature_groups),
            "horizons_days": list(spec.labels.horizons_days),
        }

        return AuditReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            spec_version=spec.version,
            tables=audits,
            eligible_rows=eligible_rows,
            closed_trades=closed_trades,
            summary=summary,
        )
    finally:
        if own_session:
            session.close()


def main() -> int:
    report = run_audit()
    payload = report.to_dict()
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
