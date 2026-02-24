"""Logging setup for the investment agent."""

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)


def setup_logger(
    name: str = "investment_agent",
    level: int = logging.INFO,
    log_file: str | None = None,
) -> logging.Logger:
    """Create and configure a logger with Rich console and file handlers."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Rich console handler
    console = Console(stderr=True)
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(level)
    console_fmt = logging.Formatter("%(message)s", datefmt="[%X]")
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = str(_LOG_DIR / f"{name}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "investment_agent") -> logging.Logger:
    """Get an existing logger or create one."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
