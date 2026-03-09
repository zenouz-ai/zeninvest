"""Portfolio router - current holdings and portfolio history."""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.data.database import get_session
from src.data.models import PortfolioSnapshot, Instrument
from src.utils.config import get_settings

from ..schemas import PortfolioSnapshotSchema, PositionSchema

router = APIRouter()
settings = get_settings()


@router.get("/", response_model=PortfolioSnapshotSchema)
async def get_portfolio():
    """Get current portfolio snapshot (latest)."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        snapshot = (
            session.query(PortfolioSnapshot)
            .order_by(desc(PortfolioSnapshot.timestamp))
            .first()
        )

        if not snapshot:
            raise HTTPException(status_code=404, detail="No portfolio snapshot found")

        # Parse positions JSON
        positions_data = json.loads(snapshot.positions_json) if snapshot.positions_json else []
        positions = []
        for pos_data in positions_data:
            # Get sector from instrument if available
            instrument = session.query(Instrument).filter(Instrument.ticker == pos_data.get("ticker")).first()
            sector = instrument.sector if instrument else None

            positions.append(
                PositionSchema(
                    ticker=pos_data.get("ticker", ""),
                    quantity=pos_data.get("quantity", 0.0),
                    value_gbp=pos_data.get("value_gbp", 0.0),
                    pnl_gbp=pos_data.get("pnl_gbp", 0.0),
                    pnl_pct=pos_data.get("pnl_pct", 0.0),
                    sector=sector,
                )
            )

        return PortfolioSnapshotSchema(
            timestamp=snapshot.timestamp,
            total_value_gbp=snapshot.total_value_gbp,
            cash_gbp=snapshot.cash_gbp,
            invested_gbp=snapshot.invested_gbp,
            pnl_gbp=snapshot.pnl_gbp,
            pnl_pct=snapshot.pnl_pct,
            num_positions=snapshot.num_positions,
            positions=positions,
        )
    finally:
        session.close()


@router.get("/history", response_model=list[PortfolioSnapshotSchema])
async def get_portfolio_history(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
):
    """Get portfolio history with pagination."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        query = session.query(PortfolioSnapshot)

        if start_date:
            query = query.filter(PortfolioSnapshot.timestamp >= start_date)

        if end_date:
            query = query.filter(PortfolioSnapshot.timestamp <= end_date)

        snapshots = query.order_by(desc(PortfolioSnapshot.timestamp)).offset(offset).limit(limit).all()

        result = []
        for snapshot in snapshots:
            positions_data = json.loads(snapshot.positions_json) if snapshot.positions_json else []
            positions = []
            for pos_data in positions_data:
                instrument = session.query(Instrument).filter(Instrument.ticker == pos_data.get("ticker")).first()
                sector = instrument.sector if instrument else None

                positions.append(
                    PositionSchema(
                        ticker=pos_data.get("ticker", ""),
                        quantity=pos_data.get("quantity", 0.0),
                        value_gbp=pos_data.get("value_gbp", 0.0),
                        pnl_gbp=pos_data.get("pnl_gbp", 0.0),
                        pnl_pct=pos_data.get("pnl_pct", 0.0),
                        sector=sector,
                    )
                )

            result.append(
                PortfolioSnapshotSchema(
                    timestamp=snapshot.timestamp,
                    total_value_gbp=snapshot.total_value_gbp,
                    cash_gbp=snapshot.cash_gbp,
                    invested_gbp=snapshot.invested_gbp,
                    pnl_gbp=snapshot.pnl_gbp,
                    pnl_pct=snapshot.pnl_pct,
                    num_positions=snapshot.num_positions,
                    positions=positions,
                )
            )

        return result
    finally:
        session.close()
