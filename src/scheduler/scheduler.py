"""APScheduler-based job scheduler for the investment agent."""

import signal
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import create_engine, inspect, text

from src.data.database import DATABASE_URL
from src.runtime import (
    DUPLICATE_INSTANCE_EXIT_CODE,
    RuntimeLockHeldError,
    acquire_runtime_lock,
)
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.run_summary import merge_run_summary
from src.utils.scheduling import (
    analysis_cycle_day_of_week,
    analysis_cycle_job_ids,
    analysis_cycle_specs,
    intraday_refresh_job_ids,
    intraday_refresh_specs,
)

logger = get_logger("scheduler")

# Dashboard event logger (fail-open import)
log_event: Callable[..., None] | None
try:
    from dashboard.backend.app.services.event_logger import log_event as _log_event
    from dashboard.backend.app.database import Run
    from src.data.database import get_session as get_db_session
    log_event = _log_event
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    log_event = None


def _sync_prefixed_jobs(database_url: str, prefix: str, desired_ids: set[str]) -> set[str]:
    """Remove stale persisted scheduler jobs for a given prefix and return desired IDs."""
    # APScheduler persists cron jobs in apscheduler_jobs. When cadence changes
    # (for example fixed UTC 08:00/12:00/16:00 -> market-session 10:00/12:30/15:15 ET),
    # replace_existing only updates matching IDs and leaves obsolete rows behind.
    # Prune those rows directly before recreating the live scheduler.
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    try:
        if not inspect(engine).has_table("apscheduler_jobs"):
            return desired_ids
        with engine.begin() as conn:
            stale_ids = [
                row[0]
                for row in conn.execute(
                    text("SELECT id FROM apscheduler_jobs WHERE id LIKE :pattern"),
                    {"pattern": f"{prefix}_%"},
                )
                if row[0] not in desired_ids
            ]
            for job_id in stale_ids:
                logger.info(f"Removing stale scheduler job: {job_id}")
                conn.execute(
                    text("DELETE FROM apscheduler_jobs WHERE id = :job_id"),
                    {"job_id": job_id},
                )
    finally:
        engine.dispose()

    return desired_ids


def _run_intraday_refresh() -> None:
    """Run the lightweight broker/data refresh workflow."""
    from src.orchestrator.main import Orchestrator

    refresh_start_time = datetime.now(timezone.utc)
    refresh_id = None

    if DASHBOARD_AVAILABLE and log_event is not None:
        try:
            refresh_id = f"refresh_{refresh_start_time.strftime('%Y%m%d_%H%M%S')}"
            log_event(
                event_type="run_started",
                source="scheduler",
                message="Scheduled intraday refresh starting",
                metadata={
                    "cycle_id": refresh_id,
                    "run_type": "refresh",
                    "started_at": refresh_start_time.isoformat(),
                },
            )
            try:
                session = get_db_session()
                try:
                    run = Run(
                        cycle_id=refresh_id,
                        run_type="refresh",
                        started_at=refresh_start_time,
                        status="running",
                    )
                    session.add(run)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()
            except Exception as e:
                logger.debug(f"Failed to create refresh Run record (fail-open): {e}", exc_info=True)
        except Exception:  # nosec B110
            pass

    logger.info("Scheduled intraday refresh starting...")
    orchestrator = Orchestrator(dry_run=False)
    try:
        result = orchestrator.run_intraday_refresh(scheduled_refresh_id=refresh_id)
        refresh_id = result.get("cycle_id", refresh_id)
        logger.info(
            "Intraday refresh completed: %s — orders_updated=%s positions=%s",
            result.get("status"),
            result.get("orders_updated_total", 0),
            result.get("positions_refreshed", 0),
        )
        if DASHBOARD_AVAILABLE and log_event is not None:
            try:
                refresh_end_time = datetime.now(timezone.utc)
                duration_seconds = (refresh_end_time - refresh_start_time).total_seconds()
                log_event(
                    event_type="run_completed",
                    source="scheduler",
                    message=(
                        "Scheduled intraday refresh completed: "
                        f"{result.get('status')} — orders_updated={result.get('orders_updated_total', 0)}"
                    ),
                    metadata={
                        "cycle_id": refresh_id,
                        "run_type": "refresh",
                        "status": result.get("status", "completed"),
                        "duration_seconds": duration_seconds,
                        "orders_updated_total": result.get("orders_updated_total", 0),
                        "positions_refreshed": result.get("positions_refreshed", 0),
                        "market_data_tickers_warmed": result.get("market_data_tickers_warmed", 0),
                        "stop_adjustments": result.get("stop_adjustments", 0),
                        "deterministic_exits": result.get("deterministic_exits", 0),
                    },
                )
                try:
                    session = get_db_session()
                    try:
                        run = session.query(Run).filter(Run.cycle_id == refresh_id).first()
                        if run:
                            run.completed_at = refresh_end_time
                            run.status = result.get("status", "completed")
                            run.summary_json = merge_run_summary(
                                run.summary_json,
                                result,
                                duration_seconds=duration_seconds,
                            )
                            session.commit()
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as e:
                    logger.warning(f"Failed to update refresh Run record (fail-open): {e}", exc_info=True)
            except Exception:  # nosec B110
                pass
    except Exception as e:
        logger.error(f"Scheduled intraday refresh failed: {e}")
        if DASHBOARD_AVAILABLE and log_event is not None:
            try:
                refresh_end_time = datetime.now(timezone.utc)
                duration_seconds = (refresh_end_time - refresh_start_time).total_seconds()
                log_event(
                    event_type="run_completed",
                    source="scheduler",
                    message=f"Scheduled intraday refresh failed: {str(e)}",
                    metadata={
                        "cycle_id": refresh_id,
                        "run_type": "refresh",
                        "status": "failed",
                        "duration_seconds": duration_seconds,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                try:
                    session = get_db_session()
                    try:
                        run = session.query(Run).filter(Run.cycle_id == refresh_id).first()
                        if run:
                            run.completed_at = refresh_end_time
                            run.status = "failed"
                            run.summary_json = merge_run_summary(
                                run.summary_json,
                                {
                                    "error_type": type(e).__name__,
                                    "error_message": str(e),
                                },
                                duration_seconds=duration_seconds,
                            )
                            session.commit()
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as ex:
                    logger.warning(f"Failed to update refresh Run record to failed (fail-open): {ex}", exc_info=True)


            except Exception:  # nosec B110
                pass
    finally:
        orchestrator.close()


def _run_analysis_cycle() -> None:
    """Run a full analysis/trading cycle."""
    from src.agents.notifications import NotificationService
    from src.orchestrator.main import Orchestrator
    from src.utils.market_holidays import is_us_market_holiday

    # Skip cycle on US market holidays (NYSE closed)
    settings = get_settings()
    if settings.skip_market_holidays:
        today = datetime.now(timezone.utc).date()
        if is_us_market_holiday(today):
            logger.info(f"US market holiday ({today}) — skipping analysis cycle")
            return

    cycle_start_time = datetime.now(timezone.utc)
    cycle_id = None
    
    # Log run_started event
    if DASHBOARD_AVAILABLE and log_event is not None:
        try:
            cycle_id = f"scheduled_{cycle_start_time.strftime('%Y%m%d_%H%M%S')}"
            log_event(
                event_type="run_started",
                source="scheduler",
                message=f"Scheduled analysis cycle starting",
                metadata={
                    "cycle_id": cycle_id,
                    "run_type": "scheduled",
                    "started_at": cycle_start_time.isoformat(),
                },
            )
            # Create run record
            try:
                session = get_db_session()
                try:
                    run = Run(
                        cycle_id=cycle_id,
                        run_type="scheduled",
                        started_at=cycle_start_time,
                        status="running",
                    )
                    session.add(run)
                    session.commit()
                    logger.debug(f"Created Run record for scheduled cycle {cycle_id}")
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()
            except Exception as e:
                logger.debug(f"Failed to create Run record (fail-open): {e}", exc_info=True)
        except Exception:  # nosec B110
            pass  # Fail-open: dashboard logging must not block
    
    logger.info("Scheduled analysis cycle starting...")
    orchestrator = Orchestrator(dry_run=False)
    notifications = NotificationService()
    
    try:
        result = orchestrator.run_cycle(scheduled_cycle_id=cycle_id)
        cycle_id = result.get("cycle_id", cycle_id)
        logger.info(f"Cycle completed: {result.get('status')} — {result.get('num_trades', 0)} trades")

        # Surface skipped cycles (lock held by an overrunning refresh/cycle) so this
        # failure mode is never silent again.
        if result.get("status") == "skipped_locked":
            lock_details = result.get("lock_details") or {}
            lock_metadata = lock_details.get("metadata") or {}
            logger.warning(
                "Scheduled cycle %s was SKIPPED — orchestrator-cycle lock held by pid=%s (%s). "
                "A refresh/cycle likely overran into this slot.",
                cycle_id,
                lock_details.get("pid"),
                lock_metadata.get("cycle_id"),
            )
            try:
                notifications.emit_cycle_skipped_locked(
                    cycle_id=cycle_id,
                    payload={
                        "cycle_id": cycle_id,
                        "dry_run": False,
                        "stage": "scheduler_analysis_cycle",
                        "lock_path": result.get("lock_path"),
                        "lock_owner_pid": lock_details.get("pid"),
                        "lock_owner_cycle_id": lock_metadata.get("cycle_id"),
                    },
                )
            except Exception as notify_err:  # nosec B110
                logger.debug(f"Skipped-cycle notification failed (fail-open): {notify_err}")
        
        # Log run_completed event
        if DASHBOARD_AVAILABLE and log_event is not None:
            try:
                cycle_end_time = datetime.now(timezone.utc)
                duration_seconds = (cycle_end_time - cycle_start_time).total_seconds()
                log_event(
                    event_type="run_completed",
                    source="scheduler",
                    message=f"Scheduled cycle completed: {result.get('status')} — {result.get('num_trades', 0)} trades",
                    metadata={
                        "cycle_id": cycle_id,
                        "run_type": "scheduled",
                        "status": result.get("status", "completed"),
                        "duration_seconds": duration_seconds,
                        "stocks_screened": result.get("stocks_screened", 0),
                        "stocks_reviewed": result.get("stocks_reviewed", 0),
                        "num_trades": result.get("num_trades", 0),
                        "num_rejected": len(result.get("rejected_stocks", [])),
                    },
                )
                # Update run record
                try:
                    session = get_db_session()
                    try:
                        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                        if run:
                            run.completed_at = cycle_end_time
                            run.status = result.get("status", "completed")
                            run.summary_json = merge_run_summary(
                                run.summary_json,
                                {
                                    **result,
                                    "decisions_made": result.get("stocks_reviewed", 0),
                                },
                                duration_seconds=duration_seconds,
                            )
                            session.commit()
                            logger.debug(f"Updated Run record for scheduled cycle {cycle_id}")
                        else:
                            logger.debug(f"Run record not found for cycle {cycle_id}")
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as e:
                    logger.warning(f"Failed to update Run record to completed (fail-open): {e}", exc_info=True)
            except Exception:  # nosec B110
                pass  # Fail-open
        
    except Exception as e:
        logger.error(f"Scheduled cycle failed: {e}")
        
        # Log run_completed with error
        if DASHBOARD_AVAILABLE and log_event is not None:
            try:
                cycle_end_time = datetime.now(timezone.utc)
                duration_seconds = (cycle_end_time - cycle_start_time).total_seconds()
                log_event(
                    event_type="run_completed",
                    source="scheduler",
                    message=f"Scheduled cycle failed: {str(e)}",
                    metadata={
                        "cycle_id": cycle_id,
                        "run_type": "scheduled",
                        "status": "failed",
                        "duration_seconds": duration_seconds,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
                # Update run record
                try:
                    session = get_db_session()
                    try:
                        run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                        if run:
                            run.completed_at = cycle_end_time
                            run.status = "failed"
                            run.summary_json = merge_run_summary(
                                run.summary_json,
                                {
                                    "error_type": type(e).__name__,
                                    "error_message": str(e),
                                },
                                duration_seconds=duration_seconds,
                            )
                            session.commit()
                            logger.debug(f"Updated Run record to failed for cycle {cycle_id}")
                        else:
                            logger.debug(f"Run record not found for failed cycle {cycle_id}")
                    except Exception:
                        session.rollback()
                        raise
                    finally:
                        session.close()
                except Exception as ex:
                    logger.warning(f"Failed to update Run record to failed (fail-open): {ex}", exc_info=True)
            except Exception:  # nosec B110
                pass  # Fail-open
        
        notifications.emit_critical_cycle_failure(
            cycle_id=cycle_id,
            payload={
                "cycle_id": cycle_id,
                "dry_run": False,
                "stage": "scheduler_analysis_cycle",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "trace_id": f"scheduler_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            },
            source="scheduler",
        )
    finally:
        orchestrator.close()


def _run_daily_snapshot() -> None:
    """Generate daily snapshot and report."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.agents.reporting.daily_report import generate_daily_report

        path = generate_daily_report()
        return {"report_path": str(path)}

    run_timed_job("daily_snapshot", "daily_snapshot", _impl)


def _run_strategy_episode_scan(days: int = 7) -> None:
    """Scan recent git history and auto-publish strategy change episodes."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.agents.attribution.service import StrategyAttributionService

        svc = StrategyAttributionService()
        episode_list = svc.backfill_recent_episodes(days=days, auto_confirm=True)
        return {"episodes_published": len(episode_list or []), "lookback_days": days}

    run_timed_job("strategy_episode_scan", "strategy_episode_scan", _impl)


def _seed_episodes_if_empty() -> None:
    """On first startup, backfill 30 days of git history if no episodes exist."""
    from src.data.database import get_session
    from src.data.models import StrategyChangeEpisode
    session = get_session()
    try:
        count = session.query(StrategyChangeEpisode).count()
    finally:
        session.close()
    if count == 0:
        logger.info("No strategy episodes found — running initial 30-day backfill")
        _run_strategy_episode_scan(days=30)

def _run_weekly_report() -> None:
    """Generate weekly report."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.agents.reporting.weekly_report import generate_weekly_report

        path = generate_weekly_report()
        return {"report_path": str(path)}

    run_timed_job("weekly_report", "weekly_report", _impl)


def _run_learning_export() -> None:
    """Weekly learning dataset export (audit + build + memory JSONL)."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.learning.export import run_learning_export

        return run_learning_export()

    run_timed_job("learning_export", "learning_export", _impl)


def _run_learning_evaluate() -> None:
    """Weekly champion/challenger counterfactual evaluation."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.learning.evaluation.counterfactual import run_counterfactual_evaluation

        result = run_counterfactual_evaluation(write_report=True)
        try:
            from src.learning.evaluation.alerts import emit_learning_alerts_if_needed

            alert_result = emit_learning_alerts_if_needed()
            result = {**result, "learning_alerts": alert_result}
        except Exception as exc:
            logger.warning("Learning alert check failed (non-fatal): %s", exc)
        return result

    run_timed_job("learning_evaluate", "learning_evaluate", _impl)


def _run_shadow_outcome_join() -> None:
    """Daily job: mature shadow scores with trade outcomes."""
    from src.utils.timed_job import run_timed_job
    from src.learning.evaluation.outcome_join import join_shadow_outcomes

    def _impl() -> dict[str, Any]:
        result = join_shadow_outcomes()
        try:
            from src.learning.evaluation.alerts import emit_learning_alerts_if_needed

            alert_result = emit_learning_alerts_if_needed()
            result = {**result, "learning_alerts": alert_result}
        except Exception as exc:
            logger.warning("Learning alert check failed (non-fatal): %s", exc)
        return result

    run_timed_job("shadow_outcome_join", "shadow_outcome_join", _impl)


def _refresh_instruments() -> None:
    """Refresh instrument universe from T212."""
    from src.utils.timed_job import run_timed_job

    def _impl() -> dict[str, Any]:
        from src.agents.execution.t212_client import T212Client
        from src.agents.market_data.data_fetcher import DataFetcher

        client = T212Client()
        instruments = client.get_instruments()
        client.close()
        fetcher = DataFetcher()
        count = fetcher.refresh_universe(instruments)
        fetcher.close()
        return {"instruments_refreshed": count}

    run_timed_job("instrument_refresh", "instrument_refresh", _impl)


def _enrich_universe() -> None:
    """Batch-enrich instruments missing sector/market_cap (Finnhub + Brave/Gemini fallback)."""
    from src.utils.timed_job import run_timed_job

    if not get_settings().batch_enrichment_enabled:
        logger.debug("Batch enrichment disabled, skipping enrich_universe job")
        return

    def _impl() -> dict[str, Any]:
        from src.agents.market_data.data_fetcher import DataFetcher

        fetcher = DataFetcher()
        backlog_before = fetcher.count_enrichment_backlog()
        count = fetcher.enrich_instruments_batch()
        backlog_after = fetcher.count_enrichment_backlog()
        fetcher.close()
        if count == 0 and backlog_after > 0:
            logger.warning(
                "Batch enrichment enriched 0 instruments but backlog remains at %d",
                backlog_after,
            )
        return {
            "instruments_enriched": count,
            "enrichment_backlog_remaining": backlog_after,
            "enrichment_backlog_before": backlog_before,
        }

    run_timed_job("enrich_universe", "enrich_universe", _impl)


def _run_macro_scan() -> None:
    """Run proactive macro scan and persist macro state for later cycle use."""
    from src.utils.timed_job import run_timed_job

    if not get_settings().macro_proactive_scan_enabled:
        logger.debug("Proactive macro scan disabled, skipping macro_scan job")
        return

    def _impl() -> dict[str, Any]:
        from src.agents.market_data.alpha_vantage_client import AlphaVantageClient
        from src.agents.market_data.finnhub_client import FinnhubClient
        from src.agents.market_data.macro_intelligence import run_proactive_macro_scan

        result = run_proactive_macro_scan(
            alpha_vantage=AlphaVantageClient(),
            finnhub=FinnhubClient(),
        )
        return {"state_id": result.get("state_id"), "regime": result.get("regime")}

    run_timed_job("macro_scan", "macro_scan", _impl)


def create_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    settings = get_settings()

    jobstores = {
        "default": SQLAlchemyJobStore(url=DATABASE_URL),
    }

    desired_cycle_job_ids = _sync_prefixed_jobs(DATABASE_URL, "analysis_cycle", analysis_cycle_job_ids(settings))
    desired_refresh_job_ids = _sync_prefixed_jobs(DATABASE_URL, "intraday_refresh", intraday_refresh_job_ids(settings))

    scheduler = BlockingScheduler(jobstores=jobstores)

    # Analysis cycle: configured schedule, weekday-filtered and timezone-aware when enabled
    for spec in analysis_cycle_specs(settings):
        scheduler.add_job(
            _run_analysis_cycle,
            "cron",
            hour=spec.hour,
            minute=spec.minute,
            day_of_week=analysis_cycle_day_of_week(settings),
            timezone=spec.timezone,
            id=spec.job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )

    logger.debug(f"Active analysis cycle jobs: {sorted(desired_cycle_job_ids)}")

    for spec in intraday_refresh_specs(settings):
        scheduler.add_job(
            _run_intraday_refresh,
            "cron",
            hour=spec.hour,
            minute=spec.minute,
            day_of_week=spec.weekday if spec.weekday is not None else analysis_cycle_day_of_week(settings),
            timezone=spec.timezone,
            id=spec.job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )

    logger.debug(f"Active intraday refresh jobs: {sorted(desired_refresh_job_ids)}")

    # Daily snapshot: 21:30 UTC
    scheduler.add_job(
        _run_daily_snapshot,
        "cron",
        hour=21,
        minute=30,
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    # Weekly report: Friday 22:00 UTC
    scheduler.add_job(
        _run_weekly_report,
        "cron",
        day_of_week="fri",
        hour=22,
        minute=0,
        id="weekly_report",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    # Instrument refresh: Sunday 12:00 UTC
    scheduler.add_job(
        _refresh_instruments,
        "cron",
        day_of_week="sun",
        hour=12,
        minute=0,
        id="instrument_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    # Batch enrichment: daily 06:00 UTC (enriches instruments missing sector/market_cap)
    if get_settings().batch_enrichment_enabled:
        scheduler.add_job(
            _enrich_universe,
            "cron",
            hour=6,
            minute=0,
            id="enrich_universe",
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )

    if bool(getattr(settings, "macro_proactive_scan_enabled", False)):
        scan_time = str(getattr(settings, "macro_scan_time_utc", "06:00"))
        macro_hour, macro_minute = map(int, scan_time.split(":"))
        scheduler.add_job(
            _run_macro_scan,
            "cron",
            hour=macro_hour,
            minute=macro_minute,
            id="macro_scan",
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )

    # Daily strategy episode git scan: 02:00 UTC (off-market, low load)
    scheduler.add_job(
        _run_strategy_episode_scan,
        "cron",
        hour=2,
        minute=0,
        id="strategy_episode_scan",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    if getattr(settings, "learning_export_enabled", False) is True:
        export_day = str(getattr(settings, "learning_export_day_of_week", "sun"))
        export_time = str(getattr(settings, "learning_export_time_utc", "13:00"))
        export_hour, export_minute = map(int, export_time.split(":"))
        scheduler.add_job(
            _run_learning_export,
            "cron",
            day_of_week=export_day,
            hour=export_hour,
            minute=export_minute,
            id="learning_export",
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
        logger.info(
            "Registered learning_export job (%s %02d:%02d UTC)",
            export_day,
            export_hour,
            export_minute,
        )

    if getattr(settings, "learning_evaluate_enabled", False) is True:
        eval_day = str(getattr(settings, "learning_evaluate_day_of_week", "sun"))
        eval_time = str(getattr(settings, "learning_evaluate_time_utc", "14:00"))
        eval_hour, eval_minute = map(int, eval_time.split(":"))
        scheduler.add_job(
            _run_learning_evaluate,
            "cron",
            day_of_week=eval_day,
            hour=eval_hour,
            minute=eval_minute,
            id="learning_evaluate",
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
        logger.info(
            "Registered learning_evaluate job (%s %02d:%02d UTC)",
            eval_day,
            eval_hour,
            eval_minute,
        )

    scheduler.add_job(
        _run_shadow_outcome_join,
        "cron",
        hour=22,
        minute=30,
        id="shadow_outcome_join",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    return scheduler


def run_scheduler() -> None:
    """Run the scheduler with graceful shutdown."""
    try:
        service_lock = acquire_runtime_lock(
            "scheduler",
            metadata={"service": "scheduler"},
        )
    except RuntimeLockHeldError as exc:
        logger.error(
            "Another scheduler instance is already running (lock=%s owner=%s)",
            exc.lock_path,
            exc.details.get("pid"),
        )
        sys.exit(DUPLICATE_INSTANCE_EXIT_CODE)

    scheduler = create_scheduler()

    def _shutdown(signum: int, frame: object) -> None:
        logger.info(f"Received signal {signum}, shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Investment Agent Scheduler starting...")
    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.id}: {job.trigger}")

    _seed_episodes_if_empty()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
    finally:
        service_lock.release()


if __name__ == "__main__":
    run_scheduler()
