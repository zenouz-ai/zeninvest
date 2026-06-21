"""Production latency scorecard — US-9.12."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from dashboard.backend.app.database import Run
from src.data.database import get_session

# Frozen Jun 2026 baseline (fixtures/dev snapshot) — see docs/AGENTIC_TRANSFORMATION_PLAN.md
FROZEN_BASELINE = {
    "captured_at": "2026-06-14",
    "run_type": "scheduled",
    "p50_seconds": 545.0,
    "p95_seconds": 900.0,
    "truncation_rate": 0.07,
    "note": "Pre US-9.5 parallel moderation; fixture snapshot n=191",
}

TRUNCATION_THRESHOLD_SECONDS = 895.0
INCLUDED_STATUSES = ("completed", "failed", "strategy_error")
DEFAULT_SCORECARD_PATH = Path("data/baseline/agentic_scorecard.json")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def _run_duration_seconds(run: Run) -> float:
    summary = run.summary_json if isinstance(run.summary_json, dict) else {}
    if summary.get("duration_seconds") is not None:
        return float(summary["duration_seconds"])
    if run.completed_at and run.started_at:
        return (run.completed_at - run.started_at).total_seconds()
    return 0.0


def compute_latency_scorecard(
    session: Session,
    *,
    days: int = 30,
    run_type: str = "scheduled",
) -> dict[str, Any]:
    """Compute p50/p95 and truncation rate for a run_type over a window."""
    captured_at = datetime.now(timezone.utc)
    cutoff = captured_at - timedelta(days=days)
    runs = (
        session.query(Run)
        .filter(
            Run.started_at >= cutoff,
            Run.run_type == run_type,
            Run.status.in_(INCLUDED_STATUSES),
        )
        .all()
    )
    durations = [_run_duration_seconds(r) for r in runs]
    truncated = sum(1 for d in durations if d >= TRUNCATION_THRESHOLD_SECONDS)
    n = len(durations)
    stats = {
        "run_type": run_type,
        "window_days": days,
        "count": n,
        "avg_seconds": round(sum(durations) / n, 2) if n else None,
        "p50_seconds": _percentile(durations, 0.5) if n else None,
        "p95_seconds": _percentile(durations, 0.95) if n else None,
        "truncation_rate": round(truncated / n, 4) if n else None,
        "truncated_count": truncated,
    }
    baseline_delta: dict[str, float | None] = {
        "p50_seconds": None,
        "p95_seconds": None,
        "truncation_rate": None,
    }
    if n and stats["p50_seconds"] is not None:
        baseline_delta["p50_seconds"] = round(stats["p50_seconds"] - FROZEN_BASELINE["p50_seconds"], 2)
    if n and stats["p95_seconds"] is not None:
        baseline_delta["p95_seconds"] = round(stats["p95_seconds"] - FROZEN_BASELINE["p95_seconds"], 2)
    if n and stats["truncation_rate"] is not None:
        baseline_delta["truncation_rate"] = round(
            stats["truncation_rate"] - FROZEN_BASELINE["truncation_rate"], 4
        )
    return {
        "captured_at": captured_at.isoformat(),
        "window": {
            "days": days,
            "run_type": run_type,
            "cutoff_at": cutoff.isoformat(),
            "included_statuses": list(INCLUDED_STATUSES),
            "truncation_threshold_seconds": TRUNCATION_THRESHOLD_SECONDS,
        },
        "frozen_baseline": FROZEN_BASELINE,
        "current": stats,
        "baseline_delta": baseline_delta,
    }


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def write_scorecard(
    payload: dict[str, Any],
    path: Path | None = None,
) -> str:
    out = path or DEFAULT_SCORECARD_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload["git_commit"] = _git_commit()
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out)


def run_scorecard(
    *,
    days: int = 30,
    run_type: str = "scheduled",
    write: bool = True,
    output_path: Path | None = None,
) -> dict[str, Any]:
    session = get_session()
    try:
        payload = compute_latency_scorecard(session, days=days, run_type=run_type)
    finally:
        session.close()
    if write:
        payload["scorecard_path"] = write_scorecard(payload, output_path)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Production latency scorecard (US-9.12)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--run-type", default="scheduled")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_SCORECARD_PATH))
    args = parser.parse_args()
    result = run_scorecard(
        days=args.days,
        run_type=args.run_type,
        write=not args.no_write,
        output_path=Path(args.output) if not args.no_write else None,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
