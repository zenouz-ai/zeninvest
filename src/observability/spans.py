"""Persist SpanRecorder rows to latency_spans."""

from __future__ import annotations

from typing import Any

from src.data.database import get_session
from src.utils.logger import get_logger

logger = get_logger("observability.spans")

_DASHBOARD_AVAILABLE = False
_LatencySpan = None
_Run = None

try:
    from dashboard.backend.app.database import LatencySpan as _LatencySpanModel
    from dashboard.backend.app.database import Run as _RunModel

    _DASHBOARD_AVAILABLE = True
    _LatencySpan = _LatencySpanModel
    _Run = _RunModel
except ImportError:
    pass


def persist_latency_spans(
    *,
    cycle_id: str,
    run_type: str,
    span_rows: list[dict[str, Any]],
    job_id: str | None = None,
) -> int:
    """Write span rows for a run. Returns number of rows inserted."""
    if not _DASHBOARD_AVAILABLE or _LatencySpan is None or not span_rows:
        return 0

    session = get_session()
    inserted = 0
    try:
        run_id = None
        if _Run is not None:
            run = session.query(_Run).filter(_Run.cycle_id == cycle_id).first()
            if run is not None:
                run_id = run.id

        for row in span_rows:
            session.add(
                _LatencySpan(
                    run_id=run_id,
                    cycle_id=cycle_id,
                    run_type=run_type,
                    job_id=job_id,
                    span_name=str(row.get("span_name") or ""),
                    parent_span=row.get("parent_span"),
                    started_at=row.get("started_at"),
                    completed_at=row.get("completed_at"),
                    duration_ms=int(row.get("duration_ms") or 0),
                    metadata_json=row.get("metadata_json"),
                )
            )
            inserted += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("Failed to persist latency spans (fail-open): %s", exc)
        return 0
    finally:
        session.close()
    return inserted
