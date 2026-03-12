"""Search API (Brave, Tavily) usage tracking and monthly budget enforcement."""

from datetime import datetime, timezone

from src.data.database import get_session
from src.data.models import ApiLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("search_api_tracker")

# ApiLog.service values for search APIs
SERVICE_BRAVE_SEARCH = "brave_search"
SERVICE_BRAVE_ANSWERS = "brave_answers"
SERVICE_TAVILY = "tavily"


def get_search_api_monthly_count(service: str) -> int:
    """Return the number of API calls this month for the given service."""
    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count = session.query(ApiLog).filter(
            ApiLog.service == service,
            ApiLog.timestamp >= month_start,
        ).count()
        return int(count)
    finally:
        session.close()


def check_search_api_budget(service: str) -> bool:
    """Return True if the service is within its monthly call limit."""
    settings = get_settings()
    limits = {
        SERVICE_BRAVE_SEARCH: settings.brave_search_monthly_calls,
        SERVICE_BRAVE_ANSWERS: settings.brave_answer_monthly_calls,
        SERVICE_TAVILY: settings.tavily_monthly_calls,
    }
    limit = limits.get(service)
    if limit is None:
        logger.warning(f"Unknown search API service '{service}', assuming no limit")
        return True
    count = get_search_api_monthly_count(service)
    if count >= limit:
        logger.warning(
            f"Search API budget exceeded: {service} at {count}/{limit} calls this month"
        )
        return False
    return True


def log_search_api_call(
    service: str,
    endpoint: str,
    status_code: int,
    duration_ms: float,
    method: str = "GET",
    error: str | None = None,
) -> None:
    """Log a search API call to api_logs."""
    session = get_session()
    try:
        session.add(ApiLog(
            timestamp=datetime.now(timezone.utc),
            service=service,
            method=method,
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=duration_ms,
            error=error,
        ))
        session.commit()
    except Exception as e:
        logger.error(f"Failed to log search API call: {e}")
        session.rollback()
    finally:
        session.close()
