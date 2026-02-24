"""APScheduler-based job scheduler for the investment agent."""

import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from src.data.database import DATABASE_URL
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("scheduler")


def _run_analysis_cycle() -> None:
    """Run a full analysis/trading cycle."""
    from src.orchestrator.main import Orchestrator
    logger.info("Scheduled analysis cycle starting...")
    orchestrator = Orchestrator(dry_run=False)
    try:
        result = orchestrator.run_cycle()
        logger.info(f"Cycle completed: {result.get('status')} — {result.get('num_trades', 0)} trades")
    except Exception as e:
        logger.error(f"Scheduled cycle failed: {e}")
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
