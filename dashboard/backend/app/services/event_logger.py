"""Event logger service for non-blocking event emission.

This service can be imported by the agent modules to log events to the dashboard.
All logging is non-blocking and fail-open (never blocks the pipeline).
"""

import logging
import threading
import time
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any

from src.data.database import get_session
from src.utils.config import get_settings

from ..database import EventsLog

logger = logging.getLogger(__name__)
settings = get_settings()

# Thread-safe queue for event logging
_event_queue: Queue[dict[str, Any]] = Queue()
_logger_thread: threading.Thread | None = None
_logger_running = False


def _logger_worker():
    """Background worker thread that processes event queue."""
    global _logger_running
    _logger_running = True

    while _logger_running:
        try:
            # Get event from queue (blocking with timeout)
            event_data = _event_queue.get(timeout=1.0)

            if not settings.dashboard_enabled or not settings.dashboard_events_enabled:
                _event_queue.task_done()
                continue

            session = get_session()
            try:
                event = EventsLog(
                    timestamp=event_data.get("timestamp", datetime.now(timezone.utc)),
                    event_type=event_data["event_type"],
                    source=event_data["source"],
                    message=event_data["message"],
                    metadata_json=event_data.get("metadata_json"),
                )
                session.add(event)
                session.commit()
            except Exception as e:
                logger.error(f"Failed to log dashboard event: {e}", exc_info=True)
                session.rollback()
            finally:
                session.close()

            _event_queue.task_done()

        except Empty:
            # Timeout - continue loop (this is expected)
            continue
        except Exception as e:
            # Other error - log and continue
            logger.debug(f"Event logger worker error (continuing): {e}")
            continue


def start_event_logger():
    """Start the background event logger thread."""
    global _logger_thread
    if _logger_thread is None or not _logger_thread.is_alive():
        _logger_thread = threading.Thread(target=_logger_worker, daemon=True, name="DashboardEventLogger")
        _logger_thread.start()
        logger.info("Dashboard event logger started")


def stop_event_logger():
    """Stop the background event logger thread."""
    global _logger_running, _logger_thread
    _logger_running = False
    if _logger_thread:
        _logger_thread.join(timeout=2.0)
        _logger_thread = None
        logger.info("Dashboard event logger stopped")


def flush_events(timeout_seconds: float = 5.0) -> None:
    """Wait for all queued events to be processed.
    
    Args:
        timeout_seconds: Maximum time to wait for queue to empty.
    """
    if _event_queue.empty():
        return
    
    start = time.time()
    while not _event_queue.empty() and (time.time() - start) < timeout_seconds:
        time.sleep(0.1)
    
    if not _event_queue.empty():
        logger.warning(f"Event queue not empty after {timeout_seconds}s timeout ({_event_queue.qsize()} events remaining)")


def log_event(
    event_type: str,
    source: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Log an event to the dashboard (non-blocking, fail-open).

    Args:
        event_type: Type of event (e.g., "run_started", "decision_made", "order_placed")
        source: Source module (e.g., "scheduler", "strategy", "execution")
        message: Human-readable message
        metadata: Optional JSON-serializable metadata dict
        timestamp: Optional timestamp (defaults to now)
    """
    if not settings.dashboard_enabled or not settings.dashboard_events_enabled:
        return

    # Ensure logger thread is running
    if _logger_thread is None or not _logger_thread.is_alive():
        start_event_logger()

    try:
        _event_queue.put_nowait(
            {
                "event_type": event_type,
                "source": source,
                "message": message,
                "metadata_json": metadata,
                "timestamp": timestamp or datetime.now(timezone.utc),
            }
        )
    except Exception as e:
        # Fail-open: log error but don't raise
        logger.warning(f"Failed to queue dashboard event: {e}", exc_info=True)
