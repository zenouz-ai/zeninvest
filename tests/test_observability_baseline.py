"""Tests for latency baseline CLI orchestration."""

from unittest.mock import MagicMock, patch

from src.observability.baseline import run_latency_baseline


def test_run_latency_baseline_dry_run_orchestrates_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.observability.baseline._BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.setattr("src.observability.baseline._sleep_between_jobs", lambda *args, **kwargs: None)

    calls: list[str] = []

    def _fake_timed(job_id, run_type, func, *args, **kwargs):
        calls.append(job_id)
        return {"status": "ok", "job_id": job_id}

    monkeypatch.setattr("src.observability.baseline.run_timed_job", _fake_timed)

    summary = run_latency_baseline(dry_run=True, include_learning=False)

    assert summary["dry_run"] is True
    assert "macro_scan" in calls
    assert "intraday_refresh" in calls
    assert "analysis_cycle" in calls
    assert (tmp_path / "baseline.json").exists()
