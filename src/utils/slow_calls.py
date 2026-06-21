"""Roll up slow external API calls from api_logs for run summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc

from src.data.database import get_session
from src.data.models import ApiLog


def fetch_slow_calls_for_cycle(
    cycle_id: str,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    min_duration_ms: float = 1000.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return slow api_logs rows during a run window, newest first."""
    if started_at is None:
        return []
    session = get_session()
    try:
        end = completed_at or datetime.now(timezone.utc)
        rows = (
            session.query(ApiLog)
            .filter(
                ApiLog.timestamp >= started_at,
                ApiLog.timestamp <= end,
                ApiLog.duration_ms.isnot(None),
                ApiLog.duration_ms >= min_duration_ms,
            )
            .order_by(desc(ApiLog.duration_ms), desc(ApiLog.timestamp))
            .limit(limit)
            .all()
        )
        return [
            {
                "service": row.service,
                "endpoint": row.endpoint,
                "method": row.method,
                "duration_ms": float(row.duration_ms or 0),
                "status_code": row.status_code,
                "cycle_id": cycle_id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            }
            for row in rows
        ]
    except Exception:
        return []
    finally:
        session.close()


def aggregate_slow_calls(
    *,
    days: int = 7,
    min_duration_ms: float = 1000.0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Aggregate slow api_logs by service+endpoint over a window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    session = get_session()
    try:
        rows = (
            session.query(ApiLog)
            .filter(
                ApiLog.timestamp >= cutoff,
                ApiLog.duration_ms.isnot(None),
                ApiLog.duration_ms >= min_duration_ms,
            )
            .all()
        )
        buckets: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            key = (str(row.service or "unknown"), str(row.endpoint or ""))
            buckets.setdefault(key, []).append(float(row.duration_ms or 0))

        def _p95(values: list[float]) -> float:
            if not values:
                return 0.0
            ordered = sorted(values)
            idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
            return ordered[idx]

        summary = [
            {
                "service": service,
                "endpoint": endpoint,
                "count": len(durations),
                "avg_duration_ms": round(sum(durations) / len(durations), 1),
                "p95_duration_ms": round(_p95(durations), 1),
                "max_duration_ms": round(max(durations), 1),
            }
            for (service, endpoint), durations in buckets.items()
        ]
        summary.sort(key=lambda item: item["p95_duration_ms"], reverse=True)
        return summary[:limit]
    except Exception:
        return []
    finally:
        session.close()
