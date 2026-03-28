"""Shared scheduling helpers for market-session and legacy UTC cycle plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.utils.market_holidays import is_us_market_holiday

if TYPE_CHECKING:
    from src.utils.config import Settings


_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class AnalysisCycleSpec:
    """Concrete scheduler spec for one analysis-cycle trigger."""

    job_id: str
    clock_time: str
    hour: int
    minute: int
    timezone: tzinfo
    weekday: int | None = None


def parse_clock_time(value: str) -> tuple[int, int]:
    """Parse a HH:MM string into integer hour/minute components."""
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid clock time: {value!r}")
    return int(parts[0]), int(parts[1])


def format_clock_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def uses_market_session_schedule(settings: Settings) -> bool:
    """True when analysis cycles should follow a timezone-aware market session."""
    return settings.cycle_frequency == "intraday" and settings.schedule_mode == "market_session"


def analysis_cycle_day_of_week(settings: Settings) -> str:
    """Return APScheduler cron day-of-week string from market_days config."""
    days = sorted({int(day) for day in settings.market_days if 0 <= int(day) <= 6})
    if not days:
        return "mon-fri"
    return ",".join(_WEEKDAY_NAMES[day] for day in days)


def analysis_cycle_specs(settings: Settings) -> list[AnalysisCycleSpec]:
    """Return analysis-cycle scheduler specs for the configured cadence."""
    if uses_market_session_schedule(settings):
        zone = ZoneInfo(settings.schedule_timezone)
        times = settings.cycle_times_local
    else:
        zone = timezone.utc
        times = settings.cycle_times_utc

    specs: list[AnalysisCycleSpec] = []
    for raw_time in times:
        hour, minute = parse_clock_time(raw_time)
        specs.append(
            AnalysisCycleSpec(
                job_id=f"analysis_cycle_{hour:02d}{minute:02d}",
                clock_time=format_clock_time(hour, minute),
                hour=hour,
                minute=minute,
                timezone=zone,
            )
        )
    return specs


def analysis_cycle_job_ids(settings: Settings) -> set[str]:
    """Return desired persisted analysis-cycle job IDs."""
    return {spec.job_id for spec in analysis_cycle_specs(settings)}


def _is_within_regular_market_session_clock(hour: int, minute: int) -> bool:
    """True when a local clock time falls within the 09:30-16:00 NYSE core session."""
    candidate = time(hour, minute)
    return time(9, 30) <= candidate < time(16, 0)


def intraday_refresh_specs(settings: Settings) -> list[AnalysisCycleSpec]:
    """Return derived intraday refresh jobs around configured cycle times."""
    enabled_raw = getattr(settings, "intraday_refresh_enabled", False)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else False
    if not enabled or not uses_market_session_schedule(settings):
        return []

    zone = ZoneInfo(settings.schedule_timezone)
    refresh_minutes: set[int] = set()
    pre_raw = getattr(settings, "intraday_refresh_pre_cycle_offset_minutes", 10)
    post_raw = getattr(settings, "intraday_refresh_post_cycle_offset_minutes", 10)
    pre = abs(int(pre_raw)) if isinstance(pre_raw, (int, float)) else 10
    post = abs(int(post_raw)) if isinstance(post_raw, (int, float)) else 10

    for raw_time in settings.cycle_times_local:
        hour, minute = parse_clock_time(raw_time)
        base_minutes = hour * 60 + minute
        for candidate_minutes in (base_minutes - pre, base_minutes + post):
            if candidate_minutes < 0 or candidate_minutes >= 24 * 60:
                continue
            refresh_hour, refresh_minute = divmod(candidate_minutes, 60)
            if not _is_within_regular_market_session_clock(refresh_hour, refresh_minute):
                continue
            refresh_minutes.add(candidate_minutes)

    specs: list[AnalysisCycleSpec] = []
    for candidate_minutes in sorted(refresh_minutes):
        refresh_hour, refresh_minute = divmod(candidate_minutes, 60)
        specs.append(
            AnalysisCycleSpec(
                job_id=f"intraday_refresh_{refresh_hour:02d}{refresh_minute:02d}",
                clock_time=format_clock_time(refresh_hour, refresh_minute),
                hour=refresh_hour,
                minute=refresh_minute,
                timezone=zone,
            )
        )

    weekend_enabled_raw = getattr(settings, "intraday_refresh_weekend_enabled", False)
    weekend_enabled = weekend_enabled_raw if isinstance(weekend_enabled_raw, bool) else False
    if weekend_enabled:
        weekend_time_raw = getattr(settings, "intraday_refresh_weekend_time_local", "17:00")
        weekend_hour, weekend_minute = parse_clock_time(str(weekend_time_raw))
        weekend_days_raw = getattr(settings, "intraday_refresh_weekend_days", [5, 6])
        weekend_days = (
            sorted({int(day) for day in weekend_days_raw if 0 <= int(day) <= 6})
            if isinstance(weekend_days_raw, list)
            else [5, 6]
        )
        for weekday in weekend_days:
            specs.append(
                AnalysisCycleSpec(
                    job_id=f"intraday_refresh_{_WEEKDAY_NAMES[weekday]}_{weekend_hour:02d}{weekend_minute:02d}",
                    clock_time=format_clock_time(weekend_hour, weekend_minute),
                    hour=weekend_hour,
                    minute=weekend_minute,
                    timezone=zone,
                    weekday=weekday,
                )
            )

    return specs


def intraday_refresh_job_ids(settings: Settings) -> set[str]:
    """Return desired persisted intraday refresh job IDs."""
    return {spec.job_id for spec in intraday_refresh_specs(settings)}


def resolved_refresh_times_local(settings: Settings) -> list[str]:
    """Return configured local refresh clock labels."""
    labels: list[str] = []
    for spec in intraday_refresh_specs(settings):
        if spec.weekday is None:
            labels.append(spec.clock_time)
        else:
            labels.append(f"{spec.clock_time} {_WEEKDAY_NAMES[spec.weekday].title()}")
    return labels


def _is_refresh_schedule_date(settings: Settings, spec: AnalysisCycleSpec, candidate_day: date) -> bool:
    """True when a refresh spec is eligible to run on the candidate local date."""
    if spec.weekday is not None:
        return candidate_day.weekday() == spec.weekday
    return _is_eligible_schedule_date(settings, candidate_day)


def _is_eligible_schedule_date(settings: Settings, candidate_day: date) -> bool:
    """True when a date is a configured market day and not a skipped market holiday."""
    market_days = {int(day) for day in settings.market_days if 0 <= int(day) <= 6}
    if market_days and candidate_day.weekday() not in market_days:
        return False
    if settings.skip_market_holidays and is_us_market_holiday(candidate_day):
        return False
    return True


def _first_schedule_date_local(settings: Settings, now_utc: datetime) -> date | None:
    if uses_market_session_schedule(settings):
        zone = ZoneInfo(settings.schedule_timezone)
        now_local = now_utc.astimezone(zone)
        specs = analysis_cycle_specs(settings)
        for day_offset in range(0, 8):
            candidate_day = now_local.date() + timedelta(days=day_offset)
            if not _is_eligible_schedule_date(settings, candidate_day):
                continue
            if day_offset > 0:
                return candidate_day
            for spec in specs:
                candidate_local = datetime(
                    candidate_day.year,
                    candidate_day.month,
                    candidate_day.day,
                    spec.hour,
                    spec.minute,
                    tzinfo=zone,
                )
                if candidate_local.astimezone(timezone.utc) > now_utc:
                    return candidate_day
        return None

    for day_offset in range(0, 8):
        candidate_day = now_utc.date() + timedelta(days=day_offset)
        if not _is_eligible_schedule_date(settings, candidate_day):
            continue
        return candidate_day

    return None


def resolved_cycle_times_utc(settings: Settings, now_utc: datetime | None = None) -> list[str]:
    """Return UTC clock labels for the next eligible market day."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if not uses_market_session_schedule(settings):
        return settings.cycle_times_utc

    zone = ZoneInfo(settings.schedule_timezone)
    target_day = _first_schedule_date_local(settings, now_utc)
    if target_day is None:
        return []

    resolved: list[str] = []
    for spec in analysis_cycle_specs(settings):
        candidate_local = datetime(
            target_day.year,
            target_day.month,
            target_day.day,
            spec.hour,
            spec.minute,
            tzinfo=zone,
        )
        resolved.append(candidate_local.astimezone(timezone.utc).strftime("%H:%M"))
    return resolved


def resolved_refresh_times_utc(settings: Settings, now_utc: datetime | None = None) -> list[str]:
    """Return UTC clock labels for the next eligible refresh day."""
    now_utc = now_utc or datetime.now(timezone.utc)
    specs = intraday_refresh_specs(settings)
    if not specs:
        return []

    zone = ZoneInfo(settings.schedule_timezone)
    now_local = now_utc.astimezone(zone)
    for day_offset in range(0, 8):
        candidate_day = now_local.date() + timedelta(days=day_offset)
        resolved: list[str] = []
        for spec in specs:
            if not _is_refresh_schedule_date(settings, spec, candidate_day):
                continue
            candidate_local = datetime(
                candidate_day.year,
                candidate_day.month,
                candidate_day.day,
                spec.hour,
                spec.minute,
                tzinfo=zone,
            )
            candidate_utc = candidate_local.astimezone(timezone.utc)
            if candidate_utc <= now_utc:
                continue
            resolved.append(candidate_utc.strftime("%H:%M"))
        if resolved:
            return resolved
    return []


def next_scheduled_run_utc(settings: Settings, now_utc: datetime | None = None) -> datetime | None:
    """Return the next scheduled analysis cycle in UTC."""
    now_utc = now_utc or datetime.now(timezone.utc)
    specs = analysis_cycle_specs(settings)

    if uses_market_session_schedule(settings):
        zone = ZoneInfo(settings.schedule_timezone)
        now_local = now_utc.astimezone(zone)
        for day_offset in range(0, 8):
            candidate_day = now_local.date() + timedelta(days=day_offset)
            if not _is_eligible_schedule_date(settings, candidate_day):
                continue
            for spec in specs:
                candidate_local = datetime(
                    candidate_day.year,
                    candidate_day.month,
                    candidate_day.day,
                    spec.hour,
                    spec.minute,
                    tzinfo=zone,
                )
                candidate_utc = candidate_local.astimezone(timezone.utc)
                if candidate_utc > now_utc:
                    return candidate_utc
        return None

    for spec in specs:
        candidate_utc = now_utc.replace(
            hour=spec.hour,
            minute=spec.minute,
            second=0,
            microsecond=0,
        )
        if candidate_utc > now_utc and _is_eligible_schedule_date(settings, candidate_utc.date()):
            return candidate_utc

    for day_offset in range(1, 8):
        candidate_day = now_utc.date() + timedelta(days=day_offset)
        if not _is_eligible_schedule_date(settings, candidate_day):
            continue
        first_spec = specs[0]
        return datetime(
            candidate_day.year,
            candidate_day.month,
            candidate_day.day,
            first_spec.hour,
            first_spec.minute,
            tzinfo=timezone.utc,
        )

    return None


def next_intraday_refresh_utc(settings: Settings, now_utc: datetime | None = None) -> datetime | None:
    """Return the next derived intraday refresh trigger in UTC."""
    now_utc = now_utc or datetime.now(timezone.utc)
    specs = intraday_refresh_specs(settings)
    if not specs:
        return None

    zone = ZoneInfo(settings.schedule_timezone)
    now_local = now_utc.astimezone(zone)
    for day_offset in range(0, 8):
        candidate_day = now_local.date() + timedelta(days=day_offset)
        for spec in specs:
            if not _is_refresh_schedule_date(settings, spec, candidate_day):
                continue
            candidate_local = datetime(
                candidate_day.year,
                candidate_day.month,
                candidate_day.day,
                spec.hour,
                spec.minute,
                tzinfo=zone,
            )
            candidate_utc = candidate_local.astimezone(timezone.utc)
            if candidate_utc > now_utc:
                return candidate_utc
    return None


def parse_cycle_started_at_utc(cycle_id: str | None) -> datetime | None:
    """Best-effort parse of cycle IDs into UTC start timestamps."""
    if not cycle_id:
        return None
    parts = str(cycle_id).split("_")
    if len(parts) < 3:
        return None

    date_part = parts[1]
    time_part = parts[2]
    if len(date_part) != 8 or not date_part.isdigit():
        return None

    digits = "".join(ch for ch in time_part if ch.isdigit())
    try:
        if len(digits) >= 6:
            parsed = datetime.strptime(f"{date_part}{digits[:6]}", "%Y%m%d%H%M%S")
        elif len(digits) >= 4:
            parsed = datetime.strptime(f"{date_part}{digits[:4]}", "%Y%m%d%H%M")
        else:
            return None
    except ValueError:
        return None

    return parsed.replace(tzinfo=timezone.utc)


def current_cycle_clock_time(settings: Settings, cycle_id: str | None, now_utc: datetime | None = None) -> str:
    """Return the active cycle clock label in configured schedule time."""
    reference_utc = parse_cycle_started_at_utc(cycle_id) or now_utc or datetime.now(timezone.utc)
    if uses_market_session_schedule(settings):
        return reference_utc.astimezone(ZoneInfo(settings.schedule_timezone)).strftime("%H:%M")
    return reference_utc.astimezone(timezone.utc).strftime("%H:%M")


def is_within_regular_market_session(settings: Settings, now_utc: datetime | None = None) -> bool:
    """True when the timestamp is inside the 09:30-16:00 NYSE core session."""
    now_utc = now_utc or datetime.now(timezone.utc)
    local_dt = now_utc.astimezone(ZoneInfo(settings.schedule_timezone))
    local_time = local_dt.timetz().replace(tzinfo=None)
    return time(9, 30) <= local_time < time(16, 0)
