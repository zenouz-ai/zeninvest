"""Tests for dashboard orders health endpoint logic."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.app.database import Base as DashboardBase, Run
from dashboard.backend.app.routers import orders as orders_router
from dashboard.backend.app.routers.orders import get_orders_health
from src.data.models import Base, Order


def test_orders_health_excludes_resolved_old_failures():
    """Old failed orders with later success should not be unresolved."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        mock_om_cls.return_value.reconcile_pending_stop_orders_with_t212.return_value = {
            "pending_local_count": 3,
            "pending_live_count": 1,
            "stale_pending_count": 2,
            "reconciled_pending_count": 2,
            "live_fetch_error": None,
            "history_fetch_error": None,
        }
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert result.active_failed_count == 1
    assert result.archived_failed_count == 0
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
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        mock_om_cls.return_value.reconcile_pending_stop_orders_with_t212.return_value = {
            "pending_local_count": 5,
            "pending_live_count": 0,
            "stale_pending_count": 0,
            "reconciled_pending_count": 0,
            "live_fetch_error": "rate limited",
            "history_fetch_error": None,
        }
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert result.active_failed_count == 1
    assert result.live_fetch_error == "rate limited"
    assert result.pending_local_count == 5


def test_orders_health_dry_run_does_not_resolve_failed():
    """A later dry_run order must not clear an unresolved failed live-style row."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add_all([
        Order(
            ticker="X_US_EQ",
            action="BUY",
            order_type="market",
            quantity=1.0,
            status="failed",
            error_message="live fail",
            timestamp=now - timedelta(days=2),
        ),
        Order(
            ticker="X_US_EQ",
            action="BUY",
            order_type="market",
            quantity=1.0,
            status="dry_run",
            timestamp=now - timedelta(days=1),
        ),
    ])
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        mock_om_cls.return_value.reconcile_pending_stop_orders_with_t212.return_value = {
            "pending_local_count": 0,
            "pending_live_count": 0,
            "stale_pending_count": 0,
            "reconciled_pending_count": 0,
            "live_fetch_error": None,
            "history_fetch_error": None,
        }
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert result.active_failed_count == 1
    assert result.failed_recent[0].ticker == "X_US_EQ"


def test_orders_health_archives_old_unresolved_failures():
    """Failed orders older than the alert window should remain auditable but leave the active alert count."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add_all([
        Order(
            ticker="OLD_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-1.0,
            status="failed",
            error_message="stale broker error",
            timestamp=now - timedelta(days=9),
        ),
        Order(
            ticker="NEW_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-1.0,
            status="failed",
            error_message="fresh broker error",
            timestamp=now - timedelta(days=2),
        ),
    ])
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        mock_om_cls.return_value.reconcile_pending_stop_orders_with_t212.return_value = {
            "pending_local_count": 0,
            "pending_live_count": 0,
            "stale_pending_count": 0,
            "reconciled_pending_count": 0,
            "live_fetch_error": None,
            "history_fetch_error": None,
        }
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 1
    assert result.active_failed_count == 1
    assert result.archived_failed_count == 1
    assert result.failed_recent[0].ticker == "NEW_US_EQ"
    assert result.archived_failed_recent[0].ticker == "OLD_US_EQ"


def test_orders_health_resolves_failed_when_later_live_pending_order_exists():
    """A later live pending replacement order should clear the earlier failed alert."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    now = datetime.now(timezone.utc)
    seed.add_all([
        Order(
            ticker="CVE_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-5.0,
            status="failed",
            error_message="stop placement failed",
            timestamp=now - timedelta(hours=2),
        ),
        Order(
            ticker="CVE_US_EQ",
            action="SELL",
            order_type="stop",
            quantity=-5.0,
            status="pending",
            t212_order_id="broker-stop-123",
            timestamp=now - timedelta(hours=1),
        ),
    ])
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        mock_om_cls.return_value.reconcile_pending_stop_orders_with_t212.return_value = {
            "pending_local_count": 1,
            "pending_live_count": 1,
            "stale_pending_count": 0,
            "reconciled_pending_count": 0,
            "live_fetch_error": None,
            "history_fetch_error": None,
        }
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.failed_open_count == 0
    assert result.active_failed_count == 0
    assert result.archived_failed_count == 0


def test_orders_health_reuses_recent_refresh_sync_summary_without_broker_call():
    """A just-finished refresh should be reused instead of immediately re-syncing the broker again."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    DashboardBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    completed_at = datetime.now(timezone.utc) - timedelta(seconds=20)
    seed.add(
        Run(
            cycle_id="refresh_recent",
            run_type="refresh",
            started_at=completed_at - timedelta(minutes=1),
            completed_at=completed_at,
            status="completed",
            summary_json={
                "order_sync": {
                    "pending_local_count": 4,
                    "pending_live_count": 4,
                    "stale_pending_count": 0,
                    "reconciled_pending_count": 0,
                    "filled_count": 0,
                    "cancelled_count": 0,
                    "failed_count": 0,
                    "updated_total": 0,
                    "history_fetch_error": None,
                    "live_fetch_error": None,
                    "last_broker_sync_at": completed_at.isoformat(),
                    "last_history_sync_at": completed_at.isoformat(),
                    "last_live_pending_sync_at": completed_at.isoformat(),
                    "history_fetch_error_at": None,
                    "live_fetch_error_at": None,
                }
            },
        )
    )
    seed.commit()
    seed.close()

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings, patch(
        "dashboard.backend.app.routers.orders.OrderManager"
    ) as mock_om_cls:
        mock_settings.dashboard_enabled = True
        result = asyncio.run(get_orders_health(unresolved_window_days=7, reconcile_pending=True))

    assert result.pending_local_count == 4
    assert result.pending_live_count == 4
    assert result.last_broker_sync_at is not None
    mock_om_cls.assert_not_called()


def test_orders_list_serializes_warning_note():
    """Orders API should expose warning_note for off-hours order annotations."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    seed.add(
        Order(
            ticker="AAPL_US_EQ",
            action="BUY",
            order_type="market",
            quantity=2.0,
            status="pending",
            warning_note="Placed outside market hours",
            timestamp=datetime.now(timezone.utc),
        )
    )
    seed.commit()
    seed.close()

    app = FastAPI()
    app.include_router(orders_router.router, prefix="/api/orders")

    with patch("dashboard.backend.app.routers.orders.get_session", side_effect=lambda: Session()), patch(
        "dashboard.backend.app.routers.orders.settings"
    ) as mock_settings:
        mock_settings.dashboard_enabled = True
        client = TestClient(app)
        response = client.get("/api/orders/")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["warning_note"] == "Placed outside market hours"
