"""Ensure read-only run list endpoints do not mutate stale runs."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run
from dashboard.backend.app.routers.runs import get_runs
from src.data.models import Base


def test_get_runs_does_not_reconcile_stale_runs():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    stale_started = datetime.now(timezone.utc) - timedelta(minutes=30)
    seed.add(
        Run(
            cycle_id="stale-cycle-1",
            run_type="cycle",
            started_at=stale_started,
            status="running",
            summary_json={},
        )
    )
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.runs.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.runs.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        asyncio.run(get_runs(limit=10, offset=0, run_type=None, start_date=None, end_date=None))

    verify = Session()
    try:
        row = verify.query(Run).filter(Run.cycle_id == "stale-cycle-1").one()
        assert row.status == "running"
        assert row.completed_at is None
    finally:
        verify.close()
