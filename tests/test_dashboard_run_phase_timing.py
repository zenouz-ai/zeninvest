"""Ensure run API schemas preserve observability fields in summary_json."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run
from dashboard.backend.app.routers.runs import _build_run_schema
from src.data.models import Base


def test_build_run_schema_preserves_phase_timing():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    phase_timing = {
        "screening": {"start": "2026-06-14T08:00:00+00:00", "end": "2026-06-14T08:02:00+00:00", "seconds": 120.0},
        "strategy": {"seconds": 300.0},
    }
    session.add(
        Run(
            cycle_id="timing-cycle",
            run_type="scheduled",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            status="completed",
            summary_json={
                "duration_seconds": 540.0,
                "phase_timing": phase_timing,
            },
        )
    )
    session.commit()
    run = session.query(Run).filter(Run.cycle_id == "timing-cycle").one()

    schema = _build_run_schema(session, run)
    assert schema.summary_json is not None
    assert schema.summary_json["phase_timing"] == phase_timing
    session.close()
