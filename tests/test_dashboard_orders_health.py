"""Tests for dashboard orders health endpoint logic."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.backend.app.routers.orders import get_orders_health
from src.data.models import Base, Order


def test_orders_health_excludes_resolved_old_failures():
    """Old failed orders with later success should not be unresolved."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add_all([
        Order(
            ticker="VRTX_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-1.0,
            status="failed",
            error_message="older failure",
            timestamp=now - timedelta(days=10),
        ),
        Order(
            ticker="VRTX_US_EQ",
            action="SELL",
            order_type="market",
            quantity=-1.0,
            status="filled",
            timestamp=now - timedelta(days=9),
        ),
        Order(
            ticker="MU_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-1.0,
            status="failed",
            error_message="recent unresolved",
            timestamp=now - timedelta(days=1),
        ),
    ])
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager.reconcile_pending_stop_orders_with_t212",
        return_value={
            "pending_local_count": 3,
            "pending_live_count": 1,
            "stale_pending_count": 2,
            "reconciled_pending_count": 2,
            "live_fetch_error": None,
        },
    ):
        mock_settings.dashboard_enabled = True
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert len(result.failed_recent) == 1
    assert result.failed_recent[0].ticker == "MU_US_EQ"
    assert result.pending_local_count == 3
    assert result.pending_live_count == 1
    assert result.stale_pending_count == 2
    assert result.reconciled_pending_count == 2


def test_orders_health_fail_open_when_live_fetch_fails():
    """Endpoint should still return unresolved failures when live pending fetch fails."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    seed.add(
        Order(
            ticker="JNJ_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-1.0,
            status="failed",
            error_message="retry error",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager.reconcile_pending_stop_orders_with_t212",
        return_value={
            "pending_local_count": 5,
            "pending_live_count": 0,
            "stale_pending_count": 0,
            "reconciled_pending_count": 0,
            "live_fetch_error": "rate limited",
        },
    ):
        mock_settings.dashboard_enabled = True
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert result.live_fetch_error == "rate limited"
    assert result.pending_local_count == 5
