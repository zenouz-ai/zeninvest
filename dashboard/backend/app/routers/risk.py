"""Risk router — risk_decisions."""

from fastapi import APIRouter, HTTPException

from src.data.database import get_session
from src.data.models import RiskDecision
from src.utils.config import get_settings

from ..schemas import RiskDecisionSchema

router = APIRouter()
settings = get_settings()


@router.get("/{cycle_id}", response_model=list[RiskDecisionSchema])
async def get_risk_by_cycle(cycle_id: str):
    """Risk decisions for a cycle."""
    if not settings.dashboard_enabled:
        raise HTTPException(status_code=503, detail="Dashboard is disabled")

    session = get_session()
    try:
        rows = (
            session.query(RiskDecision)
            .filter(RiskDecision.cycle_id == cycle_id)
            .order_by(RiskDecision.ticker)
            .all()
        )
        return rows
    finally:
        session.close()
