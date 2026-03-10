"""Status router - next run, dashboard status."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException

from src.utils.config import get_settings

router = APIRouter()
settings = get_settings()


def _next_scheduled_run_utc() -> datetime | None:
    """Compute next scheduled run time in UTC from cycle_times_utc and market_days."""
    now = datetime.now(timezone.utc)
    times = settings.cycle_times_utc
    market_days = set(settings.market_days)  # 0=Mon, 4=Fri

    # Parse HH:MM strings to (hour, minute)
    def parse_time(s: str) -> tuple[int, int]:
        parts = s.split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0

    parsed_times = [parse_time(t) for t in times]

    # Check today's remaining runs
    for h, m in parsed_times:
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now and now.weekday() in market_days:
            return cand

    # Check next market days
    for day_offset in range(1, 8):
        next_day = now.date() + timedelta(days=day_offset)
        if next_day.weekday() in market_days:
            for h, m in parsed_times:
                cand = datetime(next_day.year, next_day.month, next_day.day, h, m, 0, tzinfo=timezone.utc)
                return cand

    return None


@router.get("/")
async def get_status():
    """Get dashboard status including next scheduled run."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    next_run = _next_scheduled_run_utc()
    return {
        "next_run_utc": next_run.isoformat() if next_run else None,
        "cycle_times_utc": settings.cycle_times_utc,
        "cycle_frequency": settings.cycle_frequency,
    }
