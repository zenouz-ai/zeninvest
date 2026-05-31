"""Tests for scheduler configuration and 3-cycle setup."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.scheduler.scheduler import create_scheduler
from src.utils.config import Settings
from src.utils.scheduling import (
    current_cycle_clock_time,
    intraday_refresh_specs,
    next_intraday_refresh_utc,
    next_scheduled_run_utc,
    resolved_cycle_times_utc,
    resolved_refresh_times_local,
    resolved_refresh_times_utc,
)


def test_scheduler_creates_jobs_from_market_session_cycle_times() -> None:
    """Scheduler creates one analysis_cycle job per local market-session entry."""
    mock_settings = MagicMock()
    mock_settings.cycle_frequency = "intraday"
    mock_settings.schedule_mode = "market_session"
    mock_settings.schedule_timezone = "America/New_York"
    mock_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.market_days = [0, 1, 2, 3, 4]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = False
    mock_settings.macro_proactive_scan_enabled = False
    mock_settings.macro_scan_time_utc = "06:00"

    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", "sqlite:///:memory:"):
            scheduler = create_scheduler()

    cycle_jobs = [j for j in scheduler.get_jobs() if j.id.startswith("analysis_cycle_")]
    assert len(cycle_jobs) == 3
    ids = {j.id for j in cycle_jobs}
    assert "analysis_cycle_1000" in ids
    assert "analysis_cycle_1230" in ids
    assert "analysis_cycle_1515" in ids
    assert all(str(getattr(job.trigger, "timezone", "")) == "America/New_York" for job in cycle_jobs)


def test_scheduler_jobs_have_max_instances_one() -> None:
    """All scheduler jobs must have max_instances=1 to prevent concurrent cycles."""
    mock_settings = MagicMock()
    mock_settings.cycle_frequency = "intraday"
    mock_settings.schedule_mode = "market_session"
    mock_settings.schedule_timezone = "America/New_York"
    mock_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.market_days = [0, 1, 2, 3, 4]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = True
    mock_settings.macro_proactive_scan_enabled = False
    mock_settings.macro_scan_time_utc = "06:00"

    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", "sqlite:///:memory:"):
            scheduler = create_scheduler()

    for job in scheduler.get_jobs():
        assert job.max_instances == 1, (
            f"Job {job.id} must have max_instances=1 to prevent concurrent execution"
        )


def test_config_cycle_frequency_standard() -> None:
    """When cycle_frequency is standard, cycle_times_utc returns 2 times."""
    config = {"trading": {"cycle_frequency": "standard"}}
    settings = Settings(config)
    assert settings.cycle_times_utc == ["07:00", "19:00"]
    assert settings.cycle_hours == 12
    assert settings.schedule_mode == "fixed_utc"


def test_config_cycle_frequency_intraday() -> None:
    """Intraday defaults to market-session scheduling with explicit local times."""
    config = {
        "trading": {
            "cycle_frequency": "intraday",
            "cycle_times_local": ["10:00", "12:30", "15:15"],
        },
    }
    settings = Settings(config)
    assert settings.schedule_mode == "market_session"
    assert settings.cycle_times_local == ["10:00", "12:30", "15:15"]
    assert settings.cycle_hours == 4


def test_macro_config_accessors_read_values() -> None:
    """Macro planning config exposes explicit typed accessors for US-4.5."""
    settings = Settings(
        {
            "trading": {},
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
            "macro": {
                "proactive_scan_enabled": True,
                "scan_time_utc": "06:15",
                "signal_log_enabled": False,
                "second_order_reasoning_enabled": True,
                "research_routing_mode": "followup_on_materiality",
                "search_provider_policy": "brave_primary_tavily_fallback",
            },
        }
    )

    assert settings.macro_proactive_scan_enabled is True
    assert settings.macro_scan_time_utc == "06:15"
    assert settings.macro_signal_log_enabled is False
    assert settings.macro_second_order_reasoning_enabled is True
    assert settings.macro_research_routing_mode == "followup_on_materiality"
    assert settings.macro_search_provider_policy == "brave_primary_tavily_fallback"


def test_macro_config_accessors_default_safely() -> None:
    """Macro settings default to disabled/static-first when macro block is absent."""
    settings = Settings(
        {
            "trading": {},
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    assert settings.macro_proactive_scan_enabled is False
    assert settings.macro_scan_time_utc == "06:00"
    assert settings.macro_signal_log_enabled is True
    assert settings.macro_second_order_reasoning_enabled is False
    assert settings.macro_research_routing_mode == "static_first"
    assert settings.macro_search_provider_policy == "brave_primary_tavily_fallback"


def test_scheduler_adds_macro_scan_job_when_enabled() -> None:
    """Scheduler should register a dedicated daily macro scan job when enabled."""
    mock_settings = MagicMock()
    mock_settings.cycle_frequency = "intraday"
    mock_settings.schedule_mode = "market_session"
    mock_settings.schedule_timezone = "America/New_York"
    mock_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.market_days = [0, 1, 2, 3, 4]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = False
    mock_settings.macro_proactive_scan_enabled = True
    mock_settings.macro_scan_time_utc = "06:15"

    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", "sqlite:///:memory:"):
            scheduler = create_scheduler()

    macro_job = next((j for j in scheduler.get_jobs() if j.id == "macro_scan"), None)
    assert macro_job is not None


def test_scheduler_omits_macro_scan_job_when_disabled() -> None:
    """Scheduler should not create macro scan job when feature is disabled."""
    mock_settings = MagicMock()
    mock_settings.cycle_frequency = "intraday"
    mock_settings.schedule_mode = "market_session"
    mock_settings.schedule_timezone = "America/New_York"
    mock_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.market_days = [0, 1, 2, 3, 4]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = False
    mock_settings.macro_proactive_scan_enabled = False
    mock_settings.macro_scan_time_utc = "06:00"

    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", "sqlite:///:memory:"):
            scheduler = create_scheduler()

    assert all(j.id != "macro_scan" for j in scheduler.get_jobs())


def test_scheduler_removes_stale_analysis_cycle_jobs_when_cadence_changes(tmp_path: Path) -> None:
    """Persisted UTC jobs should be removed when config switches to market-session IDs."""
    standard_settings = MagicMock()
    standard_settings.cycle_frequency = "intraday"
    standard_settings.schedule_mode = "fixed_utc"
    standard_settings.schedule_timezone = "America/New_York"
    standard_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    standard_settings.cycle_times_utc = ["07:00", "19:00"]
    standard_settings.market_days = [0, 1, 2, 3, 4]
    standard_settings.trading = {}
    standard_settings.batch_enrichment_enabled = False
    standard_settings.macro_proactive_scan_enabled = False
    standard_settings.macro_scan_time_utc = "06:00"

    intraday_settings = MagicMock()
    intraday_settings.cycle_frequency = "intraday"
    intraday_settings.schedule_mode = "market_session"
    intraday_settings.schedule_timezone = "America/New_York"
    intraday_settings.cycle_times_local = ["10:00", "12:30", "15:15"]
    intraday_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    intraday_settings.market_days = [0, 1, 2, 3, 4]
    intraday_settings.trading = {}
    intraday_settings.batch_enrichment_enabled = False
    intraday_settings.macro_proactive_scan_enabled = False
    intraday_settings.macro_scan_time_utc = "06:00"

    db_url = f"sqlite:///{tmp_path / 'scheduler_jobs.db'}"

    with patch("src.scheduler.scheduler.get_settings", return_value=standard_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", db_url):
            create_scheduler()

    with patch("src.scheduler.scheduler.get_settings", return_value=intraday_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", db_url):
            scheduler = create_scheduler()

    cycle_job_ids = {j.id for j in scheduler.get_jobs() if j.id.startswith("analysis_cycle_")}
    assert cycle_job_ids == {"analysis_cycle_1000", "analysis_cycle_1230", "analysis_cycle_1515"}


def test_market_session_schedule_resolves_dst_aware_utc_times() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    now_utc = datetime(2026, 3, 26, 13, 0, tzinfo=timezone.utc)

    assert resolved_cycle_times_utc(settings, now_utc=now_utc) == ["14:00", "16:30", "19:15"]
    assert next_scheduled_run_utc(settings, now_utc=now_utc) == datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc)


def test_scheduler_registers_learning_export_when_enabled(tmp_path: Path) -> None:
    mock_settings = MagicMock()
    mock_settings.cycle_frequency = "standard"
    mock_settings.schedule_mode = "fixed_utc"
    mock_settings.schedule_timezone = "UTC"
    mock_settings.cycle_times_local = ["07:00", "19:00"]
    mock_settings.cycle_times_utc = ["07:00", "19:00"]
    mock_settings.market_days = [0, 1, 2, 3, 4]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = False
    mock_settings.macro_proactive_scan_enabled = False
    mock_settings.macro_scan_time_utc = "06:00"
    mock_settings.learning_export_enabled = True
    mock_settings.learning_export_day_of_week = "sun"
    mock_settings.learning_export_time_utc = "13:00"
    mock_settings.learning_evaluate_enabled = True
    mock_settings.learning_evaluate_day_of_week = "sun"
    mock_settings.learning_evaluate_time_utc = "14:00"

    db_url = f"sqlite:///{tmp_path / 'scheduler_learning.db'}"
    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", db_url):
            scheduler = create_scheduler()

    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "learning_export" in job_ids
    assert "learning_evaluate" in job_ids
    assert "shadow_outcome_join" in job_ids


def test_market_session_schedule_skips_us_market_holidays() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
                "skip_market_holidays": True,
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )


def test_intraday_refresh_specs_derive_pre_post_cycle_market_times() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
            },
            "intraday_refresh": {
                "enabled": True,
                "pre_cycle_offset_minutes": 10,
                "post_cycle_offset_minutes": 10,
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    specs = intraday_refresh_specs(settings)

    assert [spec.job_id for spec in specs] == [
        "intraday_refresh_0950",
        "intraday_refresh_1010",
        "intraday_refresh_1220",
        "intraday_refresh_1240",
        "intraday_refresh_1505",
        "intraday_refresh_1525",
    ]
    assert resolved_refresh_times_local(settings) == ["09:50", "10:10", "12:20", "12:40", "15:05", "15:25"]


def test_intraday_refresh_schedule_resolves_dst_aware_utc_times() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
            },
            "intraday_refresh": {
                "enabled": True,
                "pre_cycle_offset_minutes": 10,
                "post_cycle_offset_minutes": 10,
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    now_utc = datetime(2026, 3, 26, 13, 0, tzinfo=timezone.utc)

    assert resolved_refresh_times_utc(settings, now_utc=now_utc) == [
        "13:50",
        "14:10",
        "16:20",
        "16:40",
        "19:05",
        "19:25",
    ]
    assert next_intraday_refresh_utc(settings, now_utc=now_utc) == datetime(2026, 3, 26, 13, 50, tzinfo=timezone.utc)

    now_utc = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)  # Good Friday

    assert resolved_cycle_times_utc(settings, now_utc=now_utc) == ["14:00", "16:30", "19:15"]
    assert next_scheduled_run_utc(settings, now_utc=now_utc) == datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc)


def test_intraday_refresh_specs_include_weekend_refresh_jobs() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
            },
            "intraday_refresh": {
                "enabled": True,
                "pre_cycle_offset_minutes": 10,
                "post_cycle_offset_minutes": 10,
                "weekend_enabled": True,
                "weekend_time_local": "17:00",
                "weekend_days": [5, 6],
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    specs = intraday_refresh_specs(settings)

    assert [spec.job_id for spec in specs] == [
        "intraday_refresh_0950",
        "intraday_refresh_1010",
        "intraday_refresh_1220",
        "intraday_refresh_1240",
        "intraday_refresh_1505",
        "intraday_refresh_1525",
        "intraday_refresh_sat_1700",
        "intraday_refresh_sun_1700",
    ]
    assert resolved_refresh_times_local(settings) == [
        "09:50",
        "10:10",
        "12:20",
        "12:40",
        "15:05",
        "15:25",
        "17:00 Sat",
        "17:00 Sun",
    ]


def test_next_intraday_refresh_utc_rolls_into_weekend_refreshes() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
                "skip_market_holidays": True,
            },
            "intraday_refresh": {
                "enabled": True,
                "pre_cycle_offset_minutes": 10,
                "post_cycle_offset_minutes": 10,
                "weekend_enabled": True,
                "weekend_time_local": "17:00",
                "weekend_days": [5, 6],
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    friday_after_market = datetime(2026, 3, 27, 20, 0, tzinfo=timezone.utc)
    saturday_evening_after_refresh = datetime(2026, 3, 28, 21, 30, tzinfo=timezone.utc)

    assert resolved_refresh_times_utc(settings, now_utc=friday_after_market) == ["21:00"]
    assert next_intraday_refresh_utc(settings, now_utc=friday_after_market) == datetime(2026, 3, 28, 21, 0, tzinfo=timezone.utc)
    assert resolved_refresh_times_utc(settings, now_utc=saturday_evening_after_refresh) == ["21:00"]
    assert next_intraday_refresh_utc(settings, now_utc=saturday_evening_after_refresh) == datetime(2026, 3, 29, 21, 0, tzinfo=timezone.utc)


def test_fixed_utc_schedule_skips_us_market_holidays() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "standard",
                "schedule_mode": "fixed_utc",
                "cycle_times_utc": ["07:00", "19:00"],
                "market_days": [0, 1, 2, 3, 4],
                "skip_market_holidays": True,
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    now_utc = datetime(2026, 12, 25, 6, 0, tzinfo=timezone.utc)  # Christmas Day

    assert next_scheduled_run_utc(settings, now_utc=now_utc) == datetime(2026, 12, 28, 7, 0, tzinfo=timezone.utc)


def test_current_cycle_clock_time_uses_local_market_session_time() -> None:
    settings = Settings(
        {
            "trading": {
                "cycle_frequency": "intraday",
                "schedule_mode": "market_session",
                "schedule_timezone": "America/New_York",
                "cycle_times_local": ["10:00", "12:30", "15:15"],
                "market_days": [0, 1, 2, 3, 4],
            },
            "risk": {},
            "strategy": {},
            "moderation": {},
            "models": {},
            "data_providers": {},
        }
    )

    assert current_cycle_clock_time(settings, "scheduled_20260325_191501") == "15:15"
