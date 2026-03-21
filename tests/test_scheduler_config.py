"""Tests for scheduler configuration and 3-cycle setup."""

from unittest.mock import patch, MagicMock

from src.scheduler.scheduler import create_scheduler
from src.utils.config import Settings


def test_scheduler_creates_jobs_from_cycle_times_utc() -> None:
    """Scheduler creates one analysis_cycle job per cycle_times_utc entry."""
    mock_settings = MagicMock()
    mock_settings.cycle_times_utc = ["08:00", "12:00", "16:00"]
    mock_settings.trading = {}

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
