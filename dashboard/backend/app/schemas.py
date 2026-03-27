"""Pydantic schemas for API request/response models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventSchema(BaseModel):
    """Event log entry schema."""

    id: int
    timestamp: datetime
    event_type: str
    source: str
    message: str
    metadata_json: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class RunSchema(BaseModel):
    """Run metadata schema."""

    id: int
    cycle_id: str
    run_type: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    summary_json: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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
    sold_live_qty: float = 0.0
    sold_dry_run_qty: float = 0.0
    research_calls: int = 0
    research_calls_latest_cycle: int = 0


class PositionSchema(BaseModel):
    """Portfolio position schema."""

    ticker: str
    quantity: float
    value_gbp: float
    pnl_gbp: float
    pnl_pct: float
    sector: str | None = None
    profit_lock_status: str | None = None
    profit_lock_required_price_gbp: float | None = None
    profit_lock_stop_price_gbp: float | None = None
    profit_lock_protected_qty: float | None = None

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class PortfolioHistoryStartSchema(BaseModel):
    """Anchor timestamp for the portfolio history chart."""

    timestamp: datetime | None


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
    t212_order_id: str | None = None
    warning_note: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class FailedOrderHealthSchema(BaseModel):
    """Failed order entry used for unresolved health alerts."""

    id: int
    timestamp: datetime
    ticker: str
    action: str
    order_type: str
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrdersHealthSchema(BaseModel):
    """Orders health summary for dashboard alerts and troubleshooting."""

    failed_open_count: int
    failed_recent: list[FailedOrderHealthSchema]
    pending_local_count: int
    pending_live_count: int
    stale_pending_count: int
    reconciled_pending_count: int = 0
    unresolved_window_days: int = 7
    last_reconciled_at: datetime
    live_fetch_error: str | None = None


# --- Decisions / Moderation / Risk ---


class StrategyDecisionSchema(BaseModel):
    """Strategy decision entry."""

    id: int
    timestamp: datetime
    cycle_id: str
    ticker: str
    action: str
    target_allocation_pct: float | None
    risk_parity_target_allocation_pct: float | None = None
    risk_parity_trailing_vol_pct: float | None = None
    risk_parity_applied: bool | None = None
    conviction: int | None
    primary_strategy: str | None
    reasoning: str | None
    growth_potential: str | None
    risk_level: str | None
    stop_loss_pct: float | None
    expected_holding_period: str | None

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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
    metadata_json: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OpportunityConfigSchema(BaseModel):
    """Opportunity pipeline config (thresholds, TTL) for dashboard display."""

    queue_ttl_cycles: int
    immediate_threshold_z: float


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class StopLossCurrentSchema(BaseModel):
    """Current stop level for a position."""

    ticker: str
    stop_price: float | None
    source: str  # order, adjustment, or unknown
    profit_lock_status: str | None = None
    profit_lock_required_price_gbp: float | None = None
    profit_lock_stop_price_gbp: float | None = None
    profit_lock_protected_qty: float | None = None


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

    model_config = ConfigDict(from_attributes=True)


# --- Costs ---


class CostDailySchema(BaseModel):
    """Daily cost breakdown by provider, with API vs LLM vs Research split."""

    date: str
    anthropic_gbp: float
    openai_gbp: float
    google_gbp: float
    total_gbp: float  # LLM only (anthropic + openai + google)
    llm_cost_gbp: float = 0.0   # same as total_gbp
    api_cost_gbp: float = 0.0   # estimated from api_logs
    research_cost_gbp: float = 0.0  # agentic research (from research_logs.cost_usd → GBP)


class CostMonthlySchema(BaseModel):
    """Monthly cumulative cost with API vs LLM vs Research split."""

    year_month: str
    total_gbp: float  # llm + api + research
    by_provider: dict[str, float]
    llm_cost_gbp: float = 0.0   # sum of LLM providers
    api_cost_gbp: float = 0.0   # estimated from api_logs
    research_cost_gbp: float = 0.0  # agentic research (from research_logs.cost_usd → GBP)


class CostForCycleSchema(BaseModel):
    """Cost for a single run (cycle)."""

    cycle_id: str
    total_gbp: float
    by_provider: dict[str, float]


class DegradationSchema(BaseModel):
    """Current degradation state (derived or persisted)."""

    level: str  # full, no_gemini, no_gpt4o, no_strategy, halted
    message: str | None = None


class PublicCostDailySchema(BaseModel):
    """Sanitized daily aggregate cost summary for public dashboard views."""

    date: str
    total_gbp: float
    llm_cost_gbp: float = 0.0
    api_cost_gbp: float = 0.0
    research_cost_gbp: float = 0.0


class PublicCostMonthlySchema(BaseModel):
    """Sanitized monthly aggregate cost summary for public dashboard views."""

    year_month: str
    total_gbp: float
    llm_cost_gbp: float = 0.0
    api_cost_gbp: float = 0.0
    research_cost_gbp: float = 0.0


class AuthLoginRequestSchema(BaseModel):
    """Operator login request payload."""

    username: str
    password: str


class AuthSessionSchema(BaseModel):
    """Operator session status payload."""

    authenticated: bool
    username: str | None = None
    expires_at: int | None = None


# --- System ---


class SystemStateSchema(BaseModel):
    """System state (ACTIVE/CAUTIOUS/HALTED)."""

    state: str
    paused: bool
    current_drawdown_pct: float | None = None
    peak_portfolio_value: float | None = None
    halted_recovery_streak: int = 0
    halted_auto_recovery_target: int | None = None
    peak_inflation_warning_note: str | None = None
    last_cycle_at: datetime | None = None


# --- API usage ---


class ApiUsageDailySchema(BaseModel):
    """Daily API call counts and error rates by service."""

    date: str
    by_service: dict[str, dict[str, Any]]  # service -> {calls, errors, error_rate}


# --- Macro / World News ---


class MacroHeadlineSchema(BaseModel):
    """Persisted macro headline."""

    id: int
    headline: str
    source: str
    published_at: datetime
    url: str | None = None
    category: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MacroSignalSchema(BaseModel):
    """Macro signal audit log entry."""

    id: int
    timestamp: datetime
    state_id: int | None = None
    signal_type: str
    signal_text: str
    source: str
    confidence_score: float
    regime: str

    model_config = ConfigDict(from_attributes=True)


class MacroStateSchema(BaseModel):
    """Proactive macro state snapshot."""

    id: int
    timestamp: datetime
    regime: str
    confidence_score: float
    source: str
    top_signals: list[dict[str, Any]] = []
    action_plan: dict[str, Any] = {}
    sector_summary: str | None = None
    economic_highlights: str | None = None


class MacroSummarySchema(BaseModel):
    """Compact macro summary for Dashboard Home card."""

    regime: str | None = None
    confidence_score: float | None = None
    top_signal: str | None = None
    headline_count_7d: int = 0
    category_counts: dict[str, int] = {}
    last_updated: str | None = None
