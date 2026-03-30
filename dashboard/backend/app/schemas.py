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
    run_type: str = Field(default="scheduled", pattern="^(scheduled|manual|dry_run|slack_command|refresh)$")
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
    decision_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    value_gbp: float | None
    filled_quantity: float | None = None
    remaining_quantity: float | None = None
    slippage_bps: float | None = None
    status: str
    strategy: str | None
    conviction: int | None
    t212_order_id: str | None = None
    resubmitted_from_order_id: int | None = None
    warning_note: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ExecutionQualitySummarySchema(BaseModel):
    """Execution-quality aggregate for one slice of market orders."""

    count: int
    mean_bps: float | None = None
    p50_bps: float | None = None
    p95_bps: float | None = None
    best_bps: float | None = None
    worst_bps: float | None = None


class RecentPartialFillSchema(BaseModel):
    """Recent order with an unfilled remainder."""

    id: int
    timestamp: datetime
    ticker: str
    action: str
    requested_quantity: float
    filled_quantity: float
    remaining_quantity: float
    status: str
    strategy: str | None = None
    resubmission_eligible: bool
    resubmitted_from_order_id: int | None = None


class ExecutionQualitySchema(BaseModel):
    """Execution quality rollup plus open partial fills."""

    window_days: int
    warning_threshold_bps: float
    warning_min_fills: int
    warning_breached: bool
    warning_message: str | None = None
    overall: ExecutionQualitySummarySchema
    buy: ExecutionQualitySummarySchema
    exit: ExecutionQualitySummarySchema
    recent_partial_fills: list[RecentPartialFillSchema]


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
    active_failed_count: int
    archived_failed_count: int = 0
    failed_recent: list[FailedOrderHealthSchema]
    archived_failed_recent: list[FailedOrderHealthSchema] = []
    pending_local_count: int
    pending_live_count: int
    stale_pending_count: int
    reconciled_pending_count: int = 0
    unresolved_window_days: int = 7
    last_reconciled_at: datetime
    live_fetch_error: str | None = None
    history_fetch_error: str | None = None
    last_broker_sync_at: datetime | None = None
    last_history_sync_at: datetime | None = None
    last_live_pending_sync_at: datetime | None = None
    history_fetch_error_at: datetime | None = None
    live_fetch_error_at: datetime | None = None
    last_refresh_completed_at: datetime | None = None
    last_refresh_status: str | None = None
    last_refresh_summary: dict[str, Any] | None = None


class RunDatasetAuditSchema(BaseModel):
    """Per-run dataset audit entry."""

    id: int
    run_id: int
    cycle_id: str
    run_type: str
    dataset_key: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    source_timestamp: datetime | None = None
    rows_before: int | None = None
    rows_after: int | None = None
    delta_rows: int | None = None
    metadata_json: dict[str, Any] | None = None
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


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
    tier_gain_trigger_pct: float | None = None
    tier_min_lock_pct: float | None = None
    tier_rule_label: str | None = None
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


class PublicUniverseItemSchema(BaseModel):
    """Public-safe universe table row."""

    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap_bucket: str
    status: str
    last_screened_at: datetime | None


class PublicPortfolioPositionSchema(BaseModel):
    """Public-safe portfolio holding summary."""

    ticker: str
    sector: str | None = None
    allocation_pct: float
    pnl_band: str
    protection_status: str


class PublicPortfolioSectorSchema(BaseModel):
    """Public-safe sector allocation summary."""

    sector: str
    allocation_pct: float


class PublicPortfolioProtectionSchema(BaseModel):
    """Aggregate protection-state counts for public portfolio views."""

    protected_count: int = 0
    needs_lock_count: int = 0
    exit_required_count: int = 0
    inactive_count: int = 0


class PublicPortfolioSnapshotSchema(BaseModel):
    """Public-safe portfolio snapshot."""

    timestamp: datetime
    num_positions: int
    positions_visible: int
    cash_pct: float
    invested_pct: float
    value_index: float
    pnl_band: str
    positions: list[PublicPortfolioPositionSchema]
    sector_allocations: list[PublicPortfolioSectorSchema]
    protection_summary: PublicPortfolioProtectionSchema


class PublicPortfolioHistoryPointSchema(BaseModel):
    """Public-safe normalized portfolio history point."""

    timestamp: datetime
    value_index: float


class PublicRunSummarySchema(BaseModel):
    """Public-safe run summary."""

    started_at: datetime
    completed_at: datetime | None
    run_type: str
    status: str
    duration_seconds: float | None = None
    stocks_screened: int | None = None
    decisions_made: int | None = None
    orders_placed: int | None = None
    audit_status: str = "healthy"
    audit_degraded: bool = False


class PublicOpportunityPreviewSchema(BaseModel):
    """Public-safe opportunity preview row."""

    ticker: str
    name: str | None = None
    sector: str | None = None
    stage: str
    action: str
    score_band: str
    last_updated: datetime


class PublicMacroStateSchema(BaseModel):
    """Public-safe macro state snapshot."""

    timestamp: datetime
    regime: str
    confidence_score: float
    top_signals: list[dict[str, Any]] = []
    action_plan: dict[str, Any] = {}
    sector_summary: str | None = None
    economic_highlights: str | None = None


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


class GuidanceSectorScoreSchema(BaseModel):
    """Guidance sector tilt for one snapshot."""

    sector: str
    score: float
    label: str
    rationale: str | None = None
    evidence: list[str] = []


class PublicGuidanceSectorScoreSchema(BaseModel):
    """Public-safe guidance sector tilt."""

    sector: str
    label: str
    rationale: str | None = None


class PublicGuidanceSnapshotSchema(BaseModel):
    """Sanitized market guidance snapshot for anonymous viewers."""

    timestamp: datetime
    mode: str
    status: str
    regime: str
    confidence_score: float
    freshness_hours: float | None = None
    rationale: str | None = None
    prompt_summary: str | None = None
    sector_scores: list[PublicGuidanceSectorScoreSchema] = []


class GuidanceSnapshotSchema(BaseModel):
    """Persisted guidance snapshot used by a cycle."""

    id: int
    cycle_id: str
    timestamp: datetime
    mode: str
    status: str
    regime: str
    confidence_score: float
    freshness_hours: float | None = None
    rationale: str | None = None
    prompt_summary: str | None = None
    bias_payload: dict[str, Any] = {}
    evidence_summary: dict[str, Any] = {}
    sector_scores: list[GuidanceSectorScoreSchema] = []


class CycleContextSnapshotSchema(BaseModel):
    """Per-cycle context and guidance-attribution metadata."""

    cycle_id: str
    run_type: str
    captured_at: datetime
    repo_sha: str | None = None
    config_hash: str | None = None
    strategy_prompt_hash: str | None = None
    strategy_fingerprint_hash: str | None = None
    risk_fingerprint_hash: str | None = None
    execution_fingerprint_hash: str | None = None
    guidance_snapshot_id: int | None = None
    guidance_mode: str | None = None
    prompt_guidance_summary: str | None = None
    applied_screening_bias: dict[str, Any] = {}
    pre_guidance_candidate_count: int | None = None
    post_guidance_candidate_count: int | None = None
    pre_guidance_sector_distribution: dict[str, int] = {}
    post_guidance_sector_distribution: dict[str, int] = {}
    active_strategy_episode_ids: list[int] = []


class EpisodeImpactSummarySchema(BaseModel):
    """Observational pre/post summary for one confirmed episode."""

    window_1d_cycles: int
    window_7d_cycles: int
    window_30d_cycles: int
    pre_cycle_count: int
    post_cycle_count: int
    screening_conversion_delta: float
    low_sample_warning: bool
    overlap_warning: bool
    observational_only: bool = True


class StrategyChangeEvidenceSchema(BaseModel):
    """Commit evidence attached to a strategy episode."""

    id: int
    commit_sha: str
    committed_at: datetime
    author_name: str | None = None
    title: str
    summary: str | None = None
    affected_files: list[str] = []


class StrategyChangeEpisodeSchema(BaseModel):
    """Strategy change episode summary/detail schema."""

    id: int
    status: str
    title: str
    summary: str
    change_type: str
    review_confidence: float = 0.0
    commit_start_sha: str | None = None
    commit_end_sha: str | None = None
    effective_start_at: datetime
    effective_end_at: datetime | None = None
    confirmed_at: datetime | None = None
    rejected_at: datetime | None = None
    notes: str | None = None
    evidence: list[StrategyChangeEvidenceSchema] = []
    impact_summary: EpisodeImpactSummarySchema | None = None


class EpisodeBackfillRequestSchema(BaseModel):
    """Optional override for git backfill window."""

    days: int = Field(default=30, ge=1, le=90)


class EpisodeReviewRequestSchema(BaseModel):
    """Operator review payload for confirm/reject."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    summary: str | None = Field(default=None, min_length=3, max_length=5000)
    effective_start_at: datetime | None = None
