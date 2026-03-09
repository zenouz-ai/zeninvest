"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventSchema(BaseModel):
    """Event log entry schema."""

    id: int
    timestamp: datetime
    event_type: str
    source: str
    message: str
    metadata_json: dict[str, Any] | None = None

    class Config:
        from_attributes = True


class RunSchema(BaseModel):
    """Run metadata schema."""

    id: int
    cycle_id: str
    run_type: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    summary_json: dict[str, Any] | None = None

    class Config:
        from_attributes = True


class RunCreateSchema(BaseModel):
    """Schema for creating a new run."""

    cycle_id: str
    run_type: str = Field(default="scheduled", pattern="^(scheduled|manual|slack_command)$")
    summary_json: dict[str, Any] | None = None


class InstrumentSchema(BaseModel):
    """Instrument/universe entry schema."""

    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap: float | None
    last_screened_at: datetime | None
    data_available: bool = True

    class Config:
        from_attributes = True


class InstrumentDetailSchema(InstrumentSchema):
    """Extended instrument schema with committee reasoning."""

    last_decision: dict[str, Any] | None = None  # Latest strategy/moderation/risk decision
    label: str | None = None  # buy/sell/hold/watch computed from last decision


class PositionSchema(BaseModel):
    """Portfolio position schema."""

    ticker: str
    quantity: float
    value_gbp: float
    pnl_gbp: float
    pnl_pct: float
    sector: str | None = None

    class Config:
        from_attributes = True


class PortfolioSnapshotSchema(BaseModel):
    """Portfolio snapshot schema."""

    timestamp: datetime
    total_value_gbp: float
    cash_gbp: float
    invested_gbp: float
    pnl_gbp: float
    pnl_pct: float
    num_positions: int
    positions: list[PositionSchema]

    class Config:
        from_attributes = True


class OrderSchema(BaseModel):
    """Order schema."""

    id: int
    timestamp: datetime
    ticker: str
    action: str
    order_type: str
    quantity: float
    price: float | None
    value_gbp: float | None
    status: str
    strategy: str | None
    conviction: int | None

    class Config:
        from_attributes = True
