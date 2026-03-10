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
    run_type: str = Field(default="scheduled", pattern="^(scheduled|manual|dry_run|slack_command)$")
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


class UniverseBubbleSchema(BaseModel):
    """Instrument with UOV and investigated flag for bubble viz."""

    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap: float | None
    last_screened_at: datetime | None
    data_available: bool = True
    investigated: bool = False  # has at least one strategy decision
    uov_raw: float | None = None
    uov_z: float | None = None
    uov_ewma: float | None = None
    decision_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    reduce_count: int = 0
    hold_count: int = 0
    hold_qty: float = 0.0
    sold_qty: float = 0.0


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
    limit_price: float | None = None
    stop_price: float | None = None
    value_gbp: float | None
    status: str
    strategy: str | None
    conviction: int | None

    class Config:
        from_attributes = True


# --- Decisions / Moderation / Risk ---


class StrategyDecisionSchema(BaseModel):
    """Strategy decision entry."""

    id: int
    timestamp: datetime
    cycle_id: str
    ticker: str
    action: str
    target_allocation_pct: float | None
    conviction: int | None
    primary_strategy: str | None
    reasoning: str | None
    growth_potential: str | None
    risk_level: str | None
    stop_loss_pct: float | None
    expected_holding_period: str | None

    class Config:
        from_attributes = True


class ModerationLogSchema(BaseModel):
    """Moderation log entry."""

    id: int
    timestamp: datetime
    cycle_id: str
    ticker: str
    moderator: str
    verdict: str
    reasoning: str | None
    growth_score: int | None
    risk_score: int | None
    confidence_score: int | None
    consensus: str | None

    class Config:
        from_attributes = True


class RiskDecisionSchema(BaseModel):
    """Risk decision entry."""

    id: int
    timestamp: datetime
    cycle_id: str
    ticker: str
    proposed_action: str
    proposed_allocation_pct: float | None
    verdict: str
    adjusted_allocation_pct: float | None
    triggered_rules_json: str | None
    reasoning: str | None

    class Config:
        from_attributes = True


class PipelineWaterfallSchema(BaseModel):
    """Pipeline waterfall for a ticker in a cycle: strategy -> moderation -> risk."""

    cycle_id: str
    ticker: str
    strategy: StrategyDecisionSchema | None = None
    moderation: list[ModerationLogSchema] = []
    risk: RiskDecisionSchema | None = None


# --- Opportunity ---


class OpportunityScoreSchema(BaseModel):
    """UOV score snapshot."""

    id: int
    timestamp: datetime
    cycle_id: str
    ticker: str
    action: str | None
    stage: str | None
    is_tradable: bool
    uov_raw: float
    uov_z: float
    uov_final: float
    uov_ewma: float
    conviction: int | None

    class Config:
        from_attributes = True


class OpportunityQueueSchema(BaseModel):
    """Opportunity queue entry."""

    id: int
    ticker: str
    created_at: datetime
    updated_at: datetime
    last_seen_cycle_id: str | None
    queued_cycles: int
    last_uov_z: float
    last_uov_ewma: float
    action: str
    reason: str | None

    class Config:
        from_attributes = True


# --- Trade outcomes ---


class TradeOutcomeSchema(BaseModel):
    """Closed trade outcome (BUY -> SELL/REDUCE)."""

    id: int
    ticker: str
    buy_timestamp: datetime | None
    sell_timestamp: datetime
    holding_days: float | None
    buy_value_gbp: float
    sell_value_gbp: float
    pnl_gbp: float
    pnl_pct: float
    conviction: int | None

    class Config:
        from_attributes = True


class OutcomesStatsSchema(BaseModel):
    """Aggregate trade outcome stats."""

    total_trades: int
    win_rate_pct: float
    avg_pnl_pct: float
    avg_holding_days: float
    best_trade_pct: float | None
    worst_trade_pct: float | None


# --- Stop loss ---


class StopLossAdjustmentSchema(BaseModel):
    """Stop-loss adjustment record."""

    id: int
    timestamp: datetime
    cycle_id: str | None
    ticker: str
    adjustment_type: str
    old_stop_price: float | None
    new_stop_price: float | None
    current_price: float | None
    high_water_mark: float | None
    trigger_reason: str | None
    status: str

    class Config:
        from_attributes = True


class StopLossCurrentSchema(BaseModel):
    """Current stop level for a position."""

    ticker: str
    stop_price: float | None
    source: str  # order, adjustment, or unknown


# --- Performance ---


class PerformanceMetricSchema(BaseModel):
    """Performance metrics snapshot."""

    id: int
    snapshot_date: datetime
    sharpe_30d: float | None
    sharpe_60d: float | None
    sharpe_90d: float | None
    sortino_30d: float | None
    max_drawdown_pct: float | None
    calmar_ratio: float | None
    win_rate_momentum: float | None
    win_rate_mean_reversion: float | None
    win_rate_factor: float | None
    alpha_vs_spy_pct: float | None
    num_trades: int | None

    class Config:
        from_attributes = True


# --- Costs ---


class CostDailySchema(BaseModel):
    """Daily cost breakdown by provider."""

    date: str
    anthropic_gbp: float
    openai_gbp: float
    google_gbp: float
    total_gbp: float


class CostMonthlySchema(BaseModel):
    """Monthly cumulative cost."""

    year_month: str
    total_gbp: float
    by_provider: dict[str, float]


class CostForCycleSchema(BaseModel):
    """Cost for a single run (cycle)."""

    cycle_id: str
    total_gbp: float
    by_provider: dict[str, float]


class DegradationSchema(BaseModel):
    """Current degradation state (derived or persisted)."""

    level: str  # full, no_gemini, no_gpt4o, no_strategy, halted
    message: str | None = None


# --- System ---


class SystemStateSchema(BaseModel):
    """System state (ACTIVE/CAUTIOUS/HALTED)."""

    state: str
    paused: bool
    current_drawdown_pct: float | None = None
    peak_portfolio_value: float | None = None
    last_cycle_at: datetime | None = None


# --- API usage ---


class ApiUsageDailySchema(BaseModel):
    """Daily API call counts and error rates by service."""

    date: str
    by_service: dict[str, dict[str, Any]]  # service -> {calls, errors, error_rate}
