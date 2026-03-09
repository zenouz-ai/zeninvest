"""Orders router - order history."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import Order
from src.utils.config import get_settings

from ..schemas import OrderSchema

router = APIRouter()
settings = get_settings()


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


@router.get("/{order_id}", response_model=OrderSchema)
async def get_order(order_id: int):
    """Get a specific order by ID."""
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
