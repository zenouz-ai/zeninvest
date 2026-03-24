"""Production-safe dashboard server entrypoint."""

from __future__ import annotations

import os
import sys

import uvicorn

from src.runtime import (
    DUPLICATE_INSTANCE_EXIT_CODE,
    RuntimeLockHeldError,
    acquire_runtime_lock,
)
from src.utils.logger import get_logger

from .app.main import app

logger = get_logger("dashboard_server")


def main() -> None:
    """Run the dashboard API as a single locked process."""
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))

    try:
        service_lock = acquire_runtime_lock(
            "api",
            metadata={"service": "api", "port": port},
        )
    except RuntimeLockHeldError as exc:
        logger.error(
            "Another dashboard API instance is already running (lock=%s owner=%s)",
            exc.lock_path,
            exc.details.get("pid"),
        )
        sys.exit(DUPLICATE_INSTANCE_EXIT_CODE)

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            workers=1,
            log_level="info",
        )
    finally:
        service_lock.release()


if __name__ == "__main__":
    main()
