"""Sequential baseline timing exercise for all scheduled job categories."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.utils.timed_job import run_timed_job

logger = get_logger("observability.baseline")

_BASELINE_PATH = Path("data/latency_baseline_latest.json")


def _sleep_between_jobs(seconds: float = 30.0) -> None:
    time.sleep(seconds)


def _job_macro_scan() -> dict[str, Any]:
    from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
    from src.agents.market_data.finnhub_client import FinnhubClient
    from src.agents.market_data.macro_intelligence import run_proactive_macro_scan
    from src.utils.config import get_settings

    if not get_settings().macro_proactive_scan_enabled:
        return {"status": "skipped", "reason": "macro_proactive_scan_disabled"}
    result = run_proactive_macro_scan(
        alpha_vantage=AlphaVantageClient(),
        finnhub=FinnhubClient(),
    )
    return {"status": "completed", "state_id": result.get("state_id"), "regime": result.get("regime")}


def _job_instrument_refresh() -> dict[str, Any]:
    from src.agents.execution.t212_client import T212Client
    from src.agents.market_data.data_fetcher import DataFetcher

    client = T212Client()
    instruments = client.get_instruments()
    client.close()
    fetcher = DataFetcher()
    count = fetcher.refresh_universe(instruments)
    fetcher.close()
    return {"status": "completed", "instruments_refreshed": count}


def _job_shadow_join() -> dict[str, Any]:
    from src.learning.evaluation.outcome_join import join_shadow_outcomes

    return join_shadow_outcomes()


def _job_daily_snapshot() -> dict[str, Any]:
    from src.agents.reporting.daily_report import generate_daily_report

    path = generate_daily_report()
    return {"status": "completed", "report_path": str(path)}


def _job_refresh() -> dict[str, Any]:
    from src.orchestrator.main import Orchestrator

    orch = Orchestrator(dry_run=False)
    try:
        return orch.run_intraday_refresh()
    finally:
        orch.close()


def _job_cycle(*, dry_run: bool) -> dict[str, Any]:
    from src.orchestrator.main import Orchestrator

    orch = Orchestrator(dry_run=dry_run)
    try:
        return orch.run_cycle()
    finally:
        orch.close()


def run_latency_baseline(*, dry_run: bool = True, include_learning: bool = False) -> dict[str, Any]:
    """Run each job category sequentially and persist a summary JSON artifact."""
    started_at = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    jobs: list[tuple[str, str, Any, dict[str, Any]]] = [
        ("macro_scan", "macro_scan", _job_macro_scan, {}),
        ("instrument_refresh", "instrument_refresh", _job_instrument_refresh, {}),
        ("shadow_outcome_join", "shadow_outcome_join", _job_shadow_join, {}),
        ("daily_snapshot", "daily_snapshot", _job_daily_snapshot, {}),
        ("intraday_refresh", "refresh", _job_refresh, {}),
        ("analysis_cycle", "dry_run" if dry_run else "manual", lambda: _job_cycle(dry_run=dry_run), {}),
    ]

    if include_learning:
        jobs.extend(
            [
                (
                    "learning_export",
                    "learning_export",
                    lambda: __import__("src.learning.export", fromlist=["run_learning_export"]).run_learning_export(),
                    {},
                ),
            ]
        )

    for job_id, run_type, func, kwargs in jobs:
        logger.info("Baseline job starting: %s", job_id)
        try:
            outcome = run_timed_job(job_id, run_type, func, **kwargs)
            results.append({"job_id": job_id, "run_type": run_type, "status": "completed", "outcome": outcome})
        except Exception as exc:
            logger.warning("Baseline job %s failed: %s", job_id, exc)
            results.append(
                {
                    "job_id": job_id,
                    "run_type": run_type,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        _sleep_between_jobs()

    completed_at = datetime.now(timezone.utc)
    payload = {
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "dry_run": dry_run,
        "include_learning": include_learning,
        "jobs": results,
    }
    _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BASELINE_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("Latency baseline complete — wrote %s", _BASELINE_PATH)
    return payload


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run latency baseline timing exercise")
    parser.add_argument("--live", action="store_true", help="Run live analysis cycle instead of dry-run")
    parser.add_argument("--include-learning", action="store_true")
    args = parser.parse_args()
    summary = run_latency_baseline(dry_run=not args.live, include_learning=args.include_learning)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
