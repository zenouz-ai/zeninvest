"""CLI entry point for Slack trade command listener (US-1.6).

Usage:
    poetry run python -m src.agents.notifications.slack_trade_listener
"""

import signal
import sys
import threading

from src.runtime import (
    DUPLICATE_INSTANCE_EXIT_CODE,
    RuntimeLockHeldError,
    acquire_runtime_lock,
)
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("slack_trade_listener")

# Module-level shutdown event shared with the listener
_shutdown_event = threading.Event()


def main() -> None:
    settings = get_settings()

    if not settings.slack_trade_commands_enabled:
        logger.error("Slack trade commands are disabled in config (notifications.slack_trade_commands.enabled: false)")
        sys.exit(0)

    if not settings.slack_app_token:
        logger.error("SLACK_APP_TOKEN environment variable is required")
        sys.exit(1)

    if not settings.slack_bot_token:
        logger.error("SLACK_BOT_TOKEN environment variable is required")
        sys.exit(1)

    from src.agents.notifications.slack_listener import SlackTradeListener

    listener = SlackTradeListener()
    service_lock = None

    def shutdown(*_: object) -> None:
        logger.info("Shutting down Slack trade listener...")
        _shutdown_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        service_lock = acquire_runtime_lock(
            "slack-listener",
            metadata={"service": "slack-listener"},
        )
    except RuntimeLockHeldError as exc:
        logger.error(
            "Another Slack listener instance is already running (lock=%s owner=%s)",
            exc.lock_path,
            exc.details.get("pid"),
        )
        sys.exit(DUPLICATE_INSTANCE_EXIT_CODE)

    logger.info("Starting Slack trade command listener...")
    try:
        listener.start(shutdown_event=_shutdown_event)
        logger.info("Slack trade listener stopped.")
    finally:
        if service_lock is not None:
            service_lock.release()


if __name__ == "__main__":
    main()
