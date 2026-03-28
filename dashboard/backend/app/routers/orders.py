"""Orders router - order history and operational health."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, desc, or_

from src.agents.execution.order_manager import OrderManager
from src.data.database import get_session
from src.data.models import Order
from src.utils.config import get_settings
from src.utils.logger import get_logger

from ..database import Run
from ..schemas import FailedOrderHealthSchema, OrderSchema, OrdersHealthSchema

logger = get_logger("dashboard.orders")
router = APIRouter()
settings = get_settings()
_RECENT_REFRESH_REUSE_WINDOW_SECONDS = 120


@router.get("/", response_model=list[OrderSchema])
async def get_orders(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ticker: str | None = Query(default=None),
    action: str | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Get order history with filtering and pagination."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(Order)

        if ticker:
            query = query.filter(Order.ticker == ticker)

        if action:
            query = query.filter(Order.action == action)

        if status:
            query = query.filter(Order.status == status)

        if start_date:
            query = query.filter(Order.timestamp >= start_date)

        if end_date:
            query = query.filter(Order.timestamp <= end_date)

        orders = query.order_by(desc(Order.timestamp)).offset(offset).limit(limit).all()
        return orders
    finally:
        session.close()


def _classify_failed_order(
    *,
    failed_order: Order,
    window_days: int,
) -> str:
    """Classify a failed order as active_unresolved, archived_unresolved, or resolved."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    failed_ts = failed_order.timestamp
    # SQLite commonly returns naive datetimes even when app logic uses UTC.
    if failed_ts.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=None)

    session = get_session()
    try:
        # Do not treat a later dry_run as resolving a live broker failure.
        later_resolution = (
            session.query(Order.id)
            .filter(
                Order.ticker == failed_order.ticker,
                Order.action == failed_order.action,
                Order.order_type == failed_order.order_type,
                Order.timestamp > failed_order.timestamp,
                or_(
                    Order.status.in_(["filled", "cancelled"]),
                    and_(
                        Order.status.in_(["pending", "submitting"]),
                        Order.t212_order_id.isnot(None),
                    ),
                ),
            )
            .first()
        )
        if later_resolution is not None:
            return "resolved"
        if failed_ts >= cutoff:
            return "active_unresolved"
        return "archived_unresolved"
    finally:
        session.close()


def _coerce_datetime(value: object) -> datetime | None:
    """Convert a stored ISO string or datetime into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _recent_refresh_sync_summary(latest_refresh: Run | None) -> dict[str, object] | None:
    """Reuse a just-completed refresh sync summary instead of hammering T212 again."""
    if latest_refresh is None or latest_refresh.completed_at is None:
        return None
    completed_at = _coerce_datetime(latest_refresh.completed_at)
    if completed_at is None:
        return None
    age_seconds = (datetime.now(timezone.utc) - completed_at).total_seconds()
    if age_seconds > _RECENT_REFRESH_REUSE_WINDOW_SECONDS:
        return None

    summary = latest_refresh.summary_json if isinstance(latest_refresh.summary_json, dict) else None
    if not summary:
        return None
    sync_summary = summary.get("order_sync")
    if not isinstance(sync_summary, dict):
        return None

    return {
        "pending_local_count": int(sync_summary.get("pending_local_count", 0) or 0),
        "pending_live_count": int(sync_summary.get("pending_live_count", 0) or 0),
        "stale_pending_count": int(sync_summary.get("stale_pending_count", 0) or 0),
        "reconciled_pending_count": int(sync_summary.get("reconciled_pending_count", 0) or 0),
        "filled_count": int(sync_summary.get("filled_count", 0) or 0),
        "cancelled_count": int(sync_summary.get("cancelled_count", 0) or 0),
        "failed_count": int(sync_summary.get("failed_count", 0) or 0),
        "updated_total": int(sync_summary.get("updated_total", 0) or 0),
        "history_fetch_error": sync_summary.get("history_fetch_error"),
        "live_fetch_error": sync_summary.get("live_fetch_error"),
        "last_broker_sync_at": _coerce_datetime(sync_summary.get("last_broker_sync_at")) or completed_at,
        "last_history_sync_at": _coerce_datetime(sync_summary.get("last_history_sync_at")) or completed_at,
        "last_live_pending_sync_at": _coerce_datetime(sync_summary.get("last_live_pending_sync_at")) or completed_at,
        "history_fetch_error_at": _coerce_datetime(sync_summary.get("history_fetch_error_at")),
        "live_fetch_error_at": _coerce_datetime(sync_summary.get("live_fetch_error_at")),
    }


@router.get("/health", response_model=OrdersHealthSchema)
async def get_orders_health(
    unresolved_window_days: int = Query(default=7, ge=1, le=30),
    reconcile_pending: bool = Query(default=True),
):
    """Summarize unresolved failed orders and stale pending order counts."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        try:
            latest_refresh = (
                session.query(Run)
                .filter(Run.run_type == "refresh")
                .order_by(desc(Run.completed_at), desc(Run.started_at))
                .first()
            )
        except Exception:
            latest_refresh = None
    finally:
        session.close()

    reconciled = {
        "pending_local_count": 0,
        "pending_live_count": 0,
        "stale_pending_count": 0,
        "reconciled_pending_count": 0,
        "live_fetch_error": None,
    }
    broker_sync_at = None
    history_sync_at = None
    live_pending_sync_at = None
    history_fetch_error_at = None
    live_fetch_error_at = None
    if reconcile_pending:
        recent_refresh_reconciled = _recent_refresh_sync_summary(latest_refresh)
        if recent_refresh_reconciled is not None:
            reconciled = recent_refresh_reconciled
            broker_sync_at = reconciled.get("last_broker_sync_at")
            history_sync_at = reconciled.get("last_history_sync_at")
            live_pending_sync_at = reconciled.get("last_live_pending_sync_at")
            history_fetch_error_at = reconciled.get("history_fetch_error_at")
            live_fetch_error_at = reconciled.get("live_fetch_error_at")
        else:
            try:
                manager = OrderManager(dry_run=False)
                reconciled_candidate = manager.sync_orders_with_t212()
                if isinstance(reconciled_candidate, dict):
                    reconciled = reconciled_candidate
                else:
                    reconciled = manager.reconcile_pending_stop_orders_with_t212()
                broker_sync_at = reconciled.get("last_broker_sync_at")
                history_sync_at = reconciled.get("last_history_sync_at")
                live_pending_sync_at = reconciled.get("last_live_pending_sync_at")
                history_fetch_error_at = reconciled.get("history_fetch_error_at")
                live_fetch_error_at = reconciled.get("live_fetch_error_at")
            except Exception as e:
                logger.error("Failed to reconcile pending stops: %s", e)
                reconciled["live_fetch_error"] = str(e)
                reconciled["history_fetch_error"] = str(e)
                history_fetch_error_at = datetime.now(timezone.utc)
                live_fetch_error_at = history_fetch_error_at
    else:
        session = get_session()
        try:
            pending_local = (
                session.query(Order.id)
                .filter(Order.status.in_(["pending", "submitting"]))
                .count()
            )
        finally:
            session.close()
        reconciled["pending_local_count"] = pending_local

    session = get_session()
    try:
        failed_orders = (
            session.query(Order)
            .filter(Order.status == "failed")
            .order_by(desc(Order.timestamp))
            .all()
        )
    finally:
        session.close()

    active_unresolved: list[Order] = []
    archived_unresolved: list[Order] = []
    for order in failed_orders:
        classification = _classify_failed_order(
            failed_order=order,
            window_days=unresolved_window_days,
        )
        if classification == "active_unresolved":
            active_unresolved.append(order)
        elif classification == "archived_unresolved":
            archived_unresolved.append(order)

    failed_recent = [
        FailedOrderHealthSchema(
            id=order.id,
            timestamp=order.timestamp,
            ticker=order.ticker,
            action=order.action,
            order_type=order.order_type,
            error_message=order.error_message,
        )
        for order in active_unresolved[:10]
    ]
    archived_failed_recent = [
        FailedOrderHealthSchema(
            id=order.id,
            timestamp=order.timestamp,
            ticker=order.ticker,
            action=order.action,
            order_type=order.order_type,
            error_message=order.error_message,
        )
        for order in archived_unresolved[:10]
    ]

    return OrdersHealthSchema(
        failed_open_count=len(active_unresolved),
        active_failed_count=len(active_unresolved),
        archived_failed_count=len(archived_unresolved),
        failed_recent=failed_recent,
        archived_failed_recent=archived_failed_recent,
        pending_local_count=int(reconciled.get("pending_local_count", 0)),
        pending_live_count=int(reconciled.get("pending_live_count", 0)),
        stale_pending_count=int(reconciled.get("stale_pending_count", 0)),
        reconciled_pending_count=int(reconciled.get("reconciled_pending_count", 0)),
        unresolved_window_days=unresolved_window_days,
        last_reconciled_at=datetime.now(timezone.utc),
        live_fetch_error=reconciled.get("live_fetch_error"),
        history_fetch_error=reconciled.get("history_fetch_error"),
        last_broker_sync_at=broker_sync_at,
        last_history_sync_at=history_sync_at,
        last_live_pending_sync_at=live_pending_sync_at,
        history_fetch_error_at=history_fetch_error_at,
        live_fetch_error_at=live_fetch_error_at,
        last_refresh_completed_at=latest_refresh.completed_at if latest_refresh else None,
        last_refresh_status=latest_refresh.status if latest_refresh else None,
        last_refresh_summary=latest_refresh.summary_json if latest_refresh else None,
    )


@router.get("/{order_id}", response_model=OrderSchema)
async def get_order(order_id: int):
    """Get a specific order by ID.

    Declared after static paths like ``/health`` so ``GET /orders/health`` is not
    matched as ``order_id=\"health\"`` (which would yield 422).
    """
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    finally:
        session.close()
