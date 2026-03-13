"""APScheduler-based job scheduler for the investment agent."""

import signal
import sys
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from src.data.database import DATABASE_URL
from src.utils.config import get_settings
from src.utils.logger import get_logger

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


def _run_analysis_cycle() -> None:
    """Run a full analysis/trading cycle."""
    from src.agents.notifications import NotificationService
    from src.orchestrator.main import Orchestrator
    
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
                run = Run(
                    cycle_id=cycle_id,
                    run_type="scheduled",
                    started_at=cycle_start_time,
                    status="running",
                )
                session.add(run)
                session.commit()
                session.close()
                logger.debug(f"Created Run record for scheduled cycle {cycle_id}")
            except Exception as e:
                logger.debug(f"Failed to create Run record (fail-open): {e}", exc_info=True)
        except Exception:
            pass  # Fail-open: dashboard logging must not block
    
    logger.info("Scheduled analysis cycle starting...")
    orchestrator = Orchestrator(dry_run=False)
    notifications = NotificationService()
    
    try:
        result = orchestrator.run_cycle(scheduled_cycle_id=cycle_id)
        cycle_id = result.get("cycle_id", cycle_id)
        logger.info(f"Cycle completed: {result.get('status')} — {result.get('num_trades', 0)} trades")
        
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
                        "num_trades": result.get("num_trades", 0),
                        "num_rejected": len(result.get("rejected_stocks", [])),
                    },
                )
                # Update run record
                try:
                    session = get_db_session()
                    run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                    if run:
                        run.completed_at = cycle_end_time
                        run.status = result.get("status", "completed")
                        run.summary_json = {
                            "num_trades": result.get("num_trades", 0),
                            "num_rejected": len(result.get("rejected_stocks", [])),
                            "duration_seconds": duration_seconds,
                        }
                        session.commit()
                        logger.debug(f"Updated Run record for scheduled cycle {cycle_id}")
                    else:
                        logger.debug(f"Run record not found for cycle {cycle_id}")
                    session.close()
                except Exception as e:
                    logger.debug(f"Failed to update Run record (fail-open): {e}", exc_info=True)
            except Exception:
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
                    run = session.query(Run).filter(Run.cycle_id == cycle_id).first()
                    if run:
                        run.completed_at = cycle_end_time
                        run.status = "failed"
                        run.summary_json = {
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "duration_seconds": duration_seconds,
                        }
                        session.commit()
                        logger.debug(f"Updated Run record to failed for cycle {cycle_id}")
                    else:
                        logger.debug(f"Run record not found for failed cycle {cycle_id}")
                    session.close()
                except Exception as ex:
                    logger.debug(f"Failed to update Run record (fail-open): {ex}", exc_info=True)
            except Exception:
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
    from src.agents.reporting.daily_report import generate_daily_report
    logger.info("Generating daily report...")
    try:
        path = generate_daily_report()
        logger.info(f"Daily report: {path}")
    except Exception as e:
        logger.error(f"Daily report failed: {e}")


def _run_weekly_report() -> None:
    """Generate weekly report."""
    from src.agents.reporting.weekly_report import generate_weekly_report
    logger.info("Generating weekly report...")
    try:
        path = generate_weekly_report()
        logger.info(f"Weekly report: {path}")
    except Exception as e:
        logger.error(f"Weekly report failed: {e}")


def _refresh_instruments() -> None:
    """Refresh instrument universe from T212."""
    from src.agents.execution.t212_client import T212Client
    from src.agents.market_data.data_fetcher import DataFetcher
    logger.info("Refreshing instrument universe...")
    try:
        client = T212Client()
        instruments = client.get_instruments()
        client.close()

        fetcher = DataFetcher()
        count = fetcher.refresh_universe(instruments)
        fetcher.close()
        logger.info(f"Refreshed {count} instruments")
    except Exception as e:
        logger.error(f"Instrument refresh failed: {e}")


def _enrich_universe() -> None:
    """Batch-enrich instruments missing sector/market_cap (Finnhub + Brave/Gemini fallback)."""
    from src.agents.market_data.data_fetcher import DataFetcher
    if not get_settings().batch_enrichment_enabled:
        logger.debug("Batch enrichment disabled, skipping enrich_universe job")
        return
    logger.info("Running batch universe enrichment...")
    try:
        fetcher = DataFetcher()
        count = fetcher.enrich_instruments_batch()
        fetcher.close()
        logger.info(f"Batch enrichment updated {count} instruments")
    except Exception as e:
        logger.error(f"Batch enrichment failed: {e}")


def create_scheduler() -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    settings = get_settings()

    jobstores = {
        "default": SQLAlchemyJobStore(url=DATABASE_URL),
    }

    scheduler = BlockingScheduler(jobstores=jobstores)

    # Analysis cycle: 07:00 and 19:00 UTC, Mon-Fri
    for cycle_time in settings.cycle_times_utc:
        hour, minute = map(int, cycle_time.split(":"))
        scheduler.add_job(
            _run_analysis_cycle,
            "cron",
            hour=hour,
            minute=minute,
            day_of_week="mon-fri",
            id=f"analysis_cycle_{hour:02d}{minute:02d}",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    # Daily snapshot: 21:30 UTC
    scheduler.add_job(
        _run_daily_snapshot,
        "cron",
        hour=21,
        minute=30,
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
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
        )

    return scheduler


def run_scheduler() -> None:
    """Run the scheduler with graceful shutdown."""
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

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    run_scheduler()
