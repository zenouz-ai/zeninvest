"""CLI entry point for Slack trade command listener (US-1.6).

Usage:
    poetry run python -m src.agents.notifications.slack_trade_listener
"""

import signal
import sys

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("slack_trade_listener")


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

    def shutdown(*_: object) -> None:
        logger.info("Shutting down Slack trade listener...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Starting Slack trade command listener...")
    listener.start()


if __name__ == "__main__":
    main()
