"""Tests for scheduler configuration and 3-cycle setup."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from src.scheduler.scheduler import create_scheduler
from src.utils.config import Settings


def test_scheduler_creates_jobs_from_cycle_times_utc() -> None:
    """Scheduler creates one analysis_cycle job per cycle_times_utc entry."""
    mock_settings = MagicMock()
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
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
    assert "analysis_cycle_0800" in ids
    assert "analysis_cycle_1200" in ids
    assert "analysis_cycle_1600" in ids


def test_scheduler_jobs_have_max_instances_one() -> None:
    """All scheduler jobs must have max_instances=1 to prevent concurrent cycles."""
    mock_settings = MagicMock()
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
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


def test_config_cycle_frequency_intraday() -> None:
    """When cycle_frequency is intraday, cycle_times_utc returns 3 times."""
    config = {
        "trading": {
            "cycle_frequency": "intraday",
            "cycle_times_utc": ["08:00", "12:00", "16:00"],
        },
    }
    settings = Settings(config)
    assert settings.cycle_times_utc == ["08:00", "12:00", "16:00"]
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
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
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
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.trading = {}
    mock_settings.batch_enrichment_enabled = False
    mock_settings.macro_proactive_scan_enabled = False
    mock_settings.macro_scan_time_utc = "06:00"

    with patch("src.scheduler.scheduler.get_settings", return_value=mock_settings):
        with patch("src.scheduler.scheduler.DATABASE_URL", "sqlite:///:memory:"):
            scheduler = create_scheduler()

    assert all(j.id != "macro_scan" for j in scheduler.get_jobs())


def test_scheduler_removes_stale_analysis_cycle_jobs_when_cadence_changes(tmp_path: Path) -> None:
    """Persisted 07:00/19:00 jobs should be removed when config switches to intraday."""
    standard_settings = MagicMock()
    standard_settings.cycle_times_utc = ["07:00", "19:00"]
    standard_settings.trading = {}
    standard_settings.batch_enrichment_enabled = False
    standard_settings.macro_proactive_scan_enabled = False
    standard_settings.macro_scan_time_utc = "06:00"

    intraday_settings = MagicMock()
    intraday_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
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
    assert cycle_job_ids == {"analysis_cycle_0800", "analysis_cycle_1200", "analysis_cycle_1600"}
