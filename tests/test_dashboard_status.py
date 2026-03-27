"""Dashboard status API tests for schedule metadata and next-run resolution."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.routers import status as status_router
from dashboard.backend.app.routers import system as system_router
from src.data.models import Base, SystemState


def test_status_api_exposes_market_session_schedule_metadata(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(status_router.router, prefix="/api/status")

    class FakeSettings:
        dashboard_enabled = True
        cycle_frequency = "intraday"
        cycle_times_local = ["10:00", "12:30", "15:15"]
        schedule_mode = "market_session"
        schedule_timezone = "America/New_York"
        halted_auto_recovery_consecutive_cycles = 3

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
    assert payload["halted_recovery_streak"] == 0
    assert payload["halted_auto_recovery_target"] == 3
    assert payload["peak_inflation_warning_note"] is None


def test_system_state_api_exposes_hardening_fields(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/system")

    class FakeSettings:
        dashboard_enabled = True
        halted_auto_recovery_consecutive_cycles = 3

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        SystemState(
            state="HALTED",
            paused=False,
            current_drawdown_pct=28.0,
            peak_portfolio_value=10_000.0,
            halted_recovery_streak=2,
            peak_inflation_warning_note="Peak inflation warning: review --reset-peak",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(system_router, "settings", FakeSettings())
    monkeypatch.setattr(system_router, "get_session", lambda: Session())

    client = TestClient(app)
    response = client.get("/api/system/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "HALTED"
    assert payload["halted_recovery_streak"] == 2
    assert payload["halted_auto_recovery_target"] == 3
    assert payload["peak_inflation_warning_note"] == "Peak inflation warning: review --reset-peak"
