"""Dashboard status API tests for schedule metadata and next-run resolution."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.backend.app.routers import status as status_router


def test_status_api_exposes_market_session_schedule_metadata(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(status_router.router, prefix="/api/status")

    class FakeSettings:
        dashboard_enabled = True
        cycle_frequency = "intraday"
        cycle_times_local = ["10:00", "12:30", "15:15"]
        schedule_mode = "market_session"
        schedule_timezone = "America/New_York"

    monkeypatch.setattr(status_router, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(status_router, "_next_scheduled_run_utc", lambda: None)
    monkeypatch.setattr(status_router, "resolved_cycle_times_utc", lambda settings: ["14:00", "16:30", "19:15"])

    client = TestClient(app)
    response = client.get("/api/status/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_mode"] == "market_session"
    assert payload["schedule_timezone"] == "America/New_York"
    assert payload["cycle_times_local"] == ["10:00", "12:30", "15:15"]
    assert payload["cycle_times_utc"] == ["14:00", "16:30", "19:15"]
