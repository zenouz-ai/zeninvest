"""SQLAlchemy ORM models for all database tables."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class SystemState(Base):
    """Persisted orchestrator state machine."""

    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, CAUTIOUS, HALTED
    peak_portfolio_value = Column(Float, nullable=True)
    current_drawdown_pct = Column(Float, default=0.0)
    halted_recovery_streak = Column(Integer, nullable=False, default=0)
    last_cycle_at = Column(DateTime, nullable=True)
    daily_loss_halt_until = Column(DateTime, nullable=True)
    paused = Column(Boolean, default=False)
    peak_inflation_warning_note = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)


class Instrument(Base):
    """Cached instrument data from Trading 212."""

    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=True)
    currency = Column(String(10), nullable=True)
    exchange = Column(String(50), nullable=True)
    sector = Column(String(100), nullable=True)
    industry = Column(String(150), nullable=True)
    market_cap = Column(Float, nullable=True)
    business_summary = Column(Text, nullable=True)
    isin = Column(String(20), nullable=True)
    type = Column(String(50), nullable=True)
    min_trade_quantity = Column(Float, nullable=True)
    max_open_quantity = Column(Float, nullable=True)
    last_screened_at = Column(DateTime, nullable=True)
    data_available = Column(Boolean, default=True)  # False = yfinance can't fetch (delisted/invalid)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class HaltedInstrument(Base):
    """Time-bounded denial list of tickers the broker rejected (P4-4, US-7.5).

    Distinct from ``Instrument.data_available`` (permanent / yfinance can't fetch):
    this records transient T212 BUY rejections (HTTP 400/403) so the pipeline skips
    re-attempting the same ticker for a TTL window (default 24h) instead of wasting
    an API call and repeating the failure every cycle. Restart-safe (architecture
    rule #9 — persist truth). BUY-only; SELLs/protective stops are never blocked.
    """

    __tablename__ = "halted_instruments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), unique=True, nullable=False, index=True)
    reason = Column(String(100), nullable=False)
    status_code = Column(Integer, nullable=True)
    halted_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    halted_until = Column(DateTime, nullable=False, index=True)
    hit_count = Column(Integer, nullable=False, default=1)
    last_error = Column(Text, nullable=True)


class PortfolioSnapshot(Base):
    """Periodic snapshot of portfolio state."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    total_value_gbp = Column(Float, nullable=False)
    cash_gbp = Column(Float, nullable=False)
    invested_gbp = Column(Float, nullable=False)
    pnl_gbp = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)
    benchmark_value = Column(Float, nullable=True)
    benchmark_pnl_pct = Column(Float, nullable=True)
    alpha_pct = Column(Float, nullable=True)
    num_positions = Column(Integer, nullable=False)
    positions_json = Column(Text, nullable=True)  # JSON blob of all positions
    state = Column(String(20), nullable=False, default="ACTIVE")


class Order(Base):
    """All orders placed through the system."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "(action = 'BUY' AND quantity > 0) OR (action IN ('SELL', 'REDUCE') AND quantity < 0)",
            name="ck_orders_quantity_sign_by_action",
        ),
        CheckConstraint(
            "conviction IS NULL OR (conviction >= 0 AND conviction <= 100)",
            name="ck_orders_conviction_range",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    ticker = Column(String(50), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY, SELL, REDUCE
    order_type = Column(String(20), nullable=False)  # market, limit, stop
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # average filled price
    decision_price = Column(Float, nullable=True)
    limit_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    value_gbp = Column(Float, nullable=True)
    filled_quantity = Column(Float, nullable=True)
    remaining_quantity = Column(Float, nullable=True)
    slippage_bps = Column(Float, nullable=True)
    t212_order_id = Column(String(100), nullable=True, index=True)
    resubmitted_from_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, filled, cancelled, failed
    strategy = Column(String(50), nullable=True)
    conviction = Column(Integer, nullable=True)
    moderation_result = Column(String(20), nullable=True)
    risk_result = Column(String(20), nullable=True)
    warning_note = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    journal_path = Column(String(500), nullable=True)
    dedup_key = Column(String(200), nullable=True, index=True)


class StrategyDecision(Base):
    """Strategy agent decisions log."""

    __tablename__ = "strategy_decisions"
    __table_args__ = (
        CheckConstraint(
            "conviction IS NULL OR (conviction >= 0 AND conviction <= 100)",
            name="ck_strategy_decisions_conviction_range",
        ),
        CheckConstraint(
            "target_allocation_pct IS NULL OR (target_allocation_pct >= 0 AND target_allocation_pct <= 100)",
            name="ck_strategy_decisions_target_allocation_range",
        ),
        CheckConstraint(
            "risk_parity_target_allocation_pct IS NULL OR (risk_parity_target_allocation_pct >= 0 AND risk_parity_target_allocation_pct <= 100)",
            name="ck_strategy_decisions_risk_parity_allocation_range",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=False, index=True)
    ticker = Column(String(50), nullable=False)
    action = Column(String(10), nullable=False)
    target_allocation_pct = Column(Float, nullable=True)
    risk_parity_target_allocation_pct = Column(Float, nullable=True)
    risk_parity_trailing_vol_pct = Column(Float, nullable=True)
    risk_parity_applied = Column(Boolean, nullable=True)
    conviction = Column(Integer, nullable=True)
    primary_strategy = Column(String(50), nullable=True)
    reasoning = Column(Text, nullable=True)
    growth_potential = Column(String(10), nullable=True)
    risk_level = Column(String(10), nullable=True)
    catalysts_json = Column(Text, nullable=True)
    risks_json = Column(Text, nullable=True)
    exit_conditions = Column(Text, nullable=True)
    upside_target_pct = Column(Float, nullable=True)
    stop_loss_pct = Column(Float, nullable=True)
    expected_holding_period = Column(String(50), nullable=True)
    news_sentiment_summary = Column(Text, nullable=True)
    market_assessment = Column(Text, nullable=True)
    portfolio_commentary = Column(Text, nullable=True)
    raw_response_json = Column(Text, nullable=True)
    prompt_hash = Column(String(64), nullable=True)


class ModerationLog(Base):
    """Moderation panel decisions."""

    __tablename__ = "moderation_logs"
    __table_args__ = (
        CheckConstraint(
            "growth_score IS NULL OR (growth_score >= 1 AND growth_score <= 10)",
            name="ck_moderation_logs_growth_score_range",
        ),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 1 AND risk_score <= 10)",
            name="ck_moderation_logs_risk_score_range",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 1 AND confidence_score <= 10)",
            name="ck_moderation_logs_confidence_score_range",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=False, index=True)
    ticker = Column(String(50), nullable=False)
    moderator = Column(String(50), nullable=False)  # gpt-4o, gemini-2.0-flash, strategy
    verdict = Column(String(20), nullable=False)  # AGREE, DISAGREE, MODIFY
    reasoning = Column(Text, nullable=True)
    growth_score = Column(Integer, nullable=True)
    risk_score = Column(Integer, nullable=True)
    confidence_score = Column(Integer, nullable=True)
    modifications_json = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_gbp = Column(Float, nullable=True)
    prompt_hash = Column(String(64), nullable=True)

    # Consensus result (filled on final row per cycle/ticker)
    consensus = Column(String(20), nullable=True)  # APPROVED, BLOCKED, CAUTION

    # Committee debate telemetry: rounds executed for this decision (1 = opening
    # one-shot only), and whether this moderator's verdict changed between its
    # opening argument and its post-rebuttal final verdict.
    debate_rounds = Column(Integer, nullable=True)
    verdict_changed_in_debate = Column(Boolean, nullable=True)


class RiskDecision(Base):
    """Risk agent decisions."""

    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint(
            "proposed_allocation_pct IS NULL OR (proposed_allocation_pct >= 0 AND proposed_allocation_pct <= 100)",
            name="ck_risk_decisions_proposed_allocation_range",
        ),
        CheckConstraint(
            "adjusted_allocation_pct IS NULL OR (adjusted_allocation_pct >= 0 AND adjusted_allocation_pct <= 100)",
            name="ck_risk_decisions_adjusted_allocation_range",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=False, index=True)
    ticker = Column(String(50), nullable=False)
    proposed_action = Column(String(10), nullable=False)
    proposed_allocation_pct = Column(Float, nullable=True)
    verdict = Column(String(20), nullable=False)  # APPROVE, REJECT, RESIZE
    adjusted_allocation_pct = Column(Float, nullable=True)
    rules_checked_json = Column(Text, nullable=True)
    triggered_rules_json = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    portfolio_state_json = Column(Text, nullable=True)


class MarketDataCache(Base):
    """Cached market data (OHLCV, fundamentals, indicators)."""

    __tablename__ = "market_data_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), nullable=False, index=True)
    data_type = Column(String(50), nullable=False)  # ohlcv, fundamentals, indicators, macro
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    data_json = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True)


class ResearchCache(Base):
    """Durable research result cache (US-9.4).

    Replaces the former in-memory dict so research results survive process
    restarts and dedupe across cycles. Keyed by sha256(ticker|tool|query).
    """

    __tablename__ = "research_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(64), nullable=False, unique=True, index=True)
    ticker = Column(String(50), nullable=False)
    tool = Column(String(50), nullable=False)
    results_json = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class NewsSentimentCache(Base):
    """Cached news sentiment data from Finnhub and Alpha Vantage."""

    __tablename__ = "news_sentiment_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), nullable=True, index=True)  # NULL for market-wide
    source = Column(String(50), nullable=False)  # finnhub, alpha_vantage
    data_type = Column(String(50), nullable=False)  # news_sentiment, analyst_rec, price_target, insider, market_news
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    data_json = Column(Text, nullable=False)
    buzz_score = Column(Float, nullable=True)
    bullish_pct = Column(Float, nullable=True)
    bearish_pct = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class MacroState(Base):
    """Persisted proactive macro scan snapshot for cycle-time context injection."""

    __tablename__ = "macro_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    regime = Column(String(20), nullable=False)  # RISK_ON, RISK_OFF, NEUTRAL
    confidence_score = Column(Float, nullable=False, default=0.0)
    source = Column(String(50), nullable=False, default="scheduled_scan")
    top_signals_json = Column(Text, nullable=False, default="[]")
    action_plan_json = Column(Text, nullable=True)
    sector_summary = Column(Text, nullable=True)
    economic_highlights = Column(Text, nullable=True)
    raw_payload_json = Column(Text, nullable=True)


class MacroSignalLog(Base):
    """Normalized audit log of proactive macro signals."""

    __tablename__ = "macro_signal_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    # Intentionally not a ForeignKey — allows independent cleanup/archival
    state_id = Column(Integer, nullable=True, index=True)
    signal_type = Column(String(50), nullable=False)
    signal_text = Column(Text, nullable=False)
    source = Column(String(50), nullable=False, default="scheduled_scan")
    confidence_score = Column(Float, nullable=False, default=0.0)
    regime = Column(String(20), nullable=False)


class MacroHeadline(Base):
    """Persistent archive of macro-economic headlines from Finnhub."""

    __tablename__ = "macro_headlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    headline = Column(Text, nullable=False)
    source = Column(String(100), nullable=False)
    published_at = Column(DateTime, nullable=False, index=True)
    url = Column(Text, nullable=True)
    category = Column(String(50), nullable=True, index=True)
    fetched_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    cycle_id = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_macro_headlines_dedup", "headline", "published_at", unique=True),
    )


class OpportunityScoreSnapshot(Base):
    """Per-cycle Universal Opportunity Value (UOV) scores per ticker."""

    __tablename__ = "opportunity_score_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=False, index=True)
    ticker = Column(String(50), nullable=False, index=True)
    action = Column(String(10), nullable=True)
    stage = Column(String(50), nullable=True)
    is_tradable = Column(Boolean, nullable=False, default=False)
    uov_raw = Column(Float, nullable=False, default=0.0)
    uov_z = Column(Float, nullable=False, default=0.0)
    uov_final = Column(Float, nullable=False, default=0.0)
    uov_ewma = Column(Float, nullable=False, default=0.0)
    previous_uov_ewma = Column(Float, nullable=True)
    momentum_score = Column(Float, nullable=True)
    mean_reversion_score = Column(Float, nullable=True)
    factor_composite_score = Column(Float, nullable=True)
    factor_quality_score = Column(Float, nullable=True)
    factor_value_score = Column(Float, nullable=True)
    conviction = Column(Integer, nullable=True)
    expected_holding_period = Column(String(50), nullable=True)
    gpt_verdict = Column(String(20), nullable=True)
    gemini_growth_score = Column(Integer, nullable=True)
    gemini_risk_score = Column(Integer, nullable=True)
    gemini_confidence_score = Column(Integer, nullable=True)
    moderation_consensus = Column(String(20), nullable=True)
    risk_verdict = Column(String(20), nullable=True)
    news_sentiment_score = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)


class OpportunityQueue(Base):
    """Active queue of UOV-ranked BUY opportunities pending execution."""

    __tablename__ = "opportunity_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(50), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_cycle_id = Column(String(50), nullable=True, index=True)
    queued_cycles = Column(Integer, nullable=False, default=1)
    last_uov_z = Column(Float, nullable=False, default=0.0)
    last_uov_final = Column(Float, nullable=False, default=0.0)
    last_uov_ewma = Column(Float, nullable=False, default=0.0)
    action = Column(String(10), nullable=False, default="BUY")
    reason = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    queue_status = Column(String(20), nullable=False, default="QUEUED")  # QUEUED | EXECUTING | EXECUTED


class ApiLog(Base):
    """Log of all API requests and responses."""

    __tablename__ = "api_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    service = Column(String(50), nullable=False)  # t212, finnhub, alpha_vantage, yfinance
    method = Column(String(10), nullable=False)
    endpoint = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=True)
    request_body = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)
    error = Column(Text, nullable=True)


class ResearchLog(Base):
    """Audit trail for agentic research tool calls."""

    __tablename__ = "research_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(String(50), nullable=True, index=True)
    chat_session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    chat_turn_id = Column(Integer, ForeignKey("chat_turns.id", ondelete="SET NULL"), nullable=True, index=True)
    member = Column(String(30), nullable=False)  # strategy, skeptic, risk
    ticker = Column(String(50), nullable=True, index=True)
    tool_name = Column(String(50), nullable=False)
    query = Column(Text, nullable=True)
    num_results = Column(Integer, nullable=True)
    results_json = Column(Text, nullable=True)
    provider = Column(String(30), nullable=True)  # brave, tavily, sec
    cost_usd = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    cache_hit = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_research_logs_member_ticker", "member", "ticker"),)


class CostLog(Base):
    """LLM API cost tracking."""

    __tablename__ = "cost_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    chat_session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    chat_turn_id = Column(Integer, ForeignKey("chat_turns.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(50), nullable=False)  # anthropic, openai, google
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_gbp = Column(Float, nullable=False, default=0.0)
    cycle_id = Column(String(50), nullable=True, index=True)
    purpose = Column(String(100), nullable=True)  # strategy, moderation, etc.
    # Atomic cost budget (P4-1, US-7.5). NULL = normal logged cost; "pending" =
    # reserved estimate counting toward spend pre-call; "settled" = reconciled to
    # actual cost after the call. Orphaned "pending" rows are swept on crash.
    reservation_state = Column(String(20), nullable=True, index=True)


class NotificationLog(Base):
    """Outbound notification send attempts and outcomes."""

    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    event_id = Column(String(64), nullable=False, index=True)
    cycle_id = Column(String(50), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False)
    channel = Column(String(20), nullable=False, index=True)
    recipient = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False)  # sent, failed, skipped, deduped
    attempt_number = Column(Integer, nullable=False, default=0)
    dedup_key = Column(String(200), nullable=False, index=True)
    payload_hash = Column(String(64), nullable=False)
    error_message = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=True)


class PerformanceMetric(Base):
    """Daily and rolling performance metrics from portfolio snapshots and orders."""

    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, nullable=False, index=True)  # date of the metric (UTC midnight)
    sharpe_30d = Column(Float, nullable=True)
    sharpe_60d = Column(Float, nullable=True)
    sharpe_90d = Column(Float, nullable=True)
    sortino_30d = Column(Float, nullable=True)
    sortino_60d = Column(Float, nullable=True)
    sortino_90d = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    calmar_ratio = Column(Float, nullable=True)
    win_rate_momentum = Column(Float, nullable=True)
    win_rate_mean_reversion = Column(Float, nullable=True)
    win_rate_factor = Column(Float, nullable=True)
    alpha_vs_spy_pct = Column(Float, nullable=True)
    num_trades = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class StopLossAdjustment(Base):
    """Audit trail for stop-loss reassessments, trailing ratchets, and limit orders."""

    __tablename__ = "stop_loss_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=True, index=True)
    ticker = Column(String(50), nullable=False, index=True)
    adjustment_type = Column(String(30), nullable=False)  # reassess, trailing, limit_order
    old_stop_price = Column(Float, nullable=True)
    new_stop_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    high_water_mark = Column(Float, nullable=True)
    atr_value = Column(Float, nullable=True)
    tier_gain_trigger_pct = Column(Float, nullable=True)
    tier_min_lock_pct = Column(Float, nullable=True)
    tier_rule_label = Column(String(50), nullable=True)
    trigger_reason = Column(String(100), nullable=True)  # volatility_adjust, trailing_ratchet, limit_dip
    t212_cancelled_order_id = Column(String(100), nullable=True)
    t212_new_order_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # placed, cancelled, failed, dry_run, skipped


class TradeOutcome(Base):
    """Per-trade P&L linking BUY to SELL/REDUCE with conviction and moderator linkage."""

    __tablename__ = "trade_outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    buy_order_id = Column(Integer, nullable=True, index=True)  # first/primary BUY order closed (FIFO)
    sell_order_id = Column(Integer, nullable=False, index=True)  # the SELL/REDUCE order
    ticker = Column(String(50), nullable=False, index=True)
    buy_timestamp = Column(DateTime, nullable=True)
    sell_timestamp = Column(DateTime, nullable=False)
    holding_days = Column(Float, nullable=True)
    buy_value_gbp = Column(Float, nullable=False)
    sell_value_gbp = Column(Float, nullable=False)
    pnl_gbp = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)
    conviction = Column(Integer, nullable=True)
    strategy = Column(String(50), nullable=True)
    moderation_result = Column(String(20), nullable=True)
    risk_result = Column(String(20), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class GuidanceSnapshot(Base):
    """Point-in-time market guidance snapshot used by a cycle."""

    __tablename__ = "guidance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    cycle_id = Column(String(50), nullable=False, index=True)
    mode = Column(String(20), nullable=False, default="active")
    status = Column(String(20), nullable=False, default="active")  # active, stale, failed
    regime = Column(String(20), nullable=False, default="NEUTRAL")
    confidence_score = Column(Float, nullable=False, default=0.0)
    freshness_hours = Column(Float, nullable=True)
    rationale = Column(Text, nullable=True)
    prompt_summary = Column(Text, nullable=True)
    bias_payload_json = Column(Text, nullable=True)
    evidence_summary_json = Column(Text, nullable=True)
    raw_payload_json = Column(Text, nullable=True)


class GuidanceSectorScore(Base):
    """Per-sector guidance score attached to a guidance snapshot."""

    __tablename__ = "guidance_sector_scores"
    __table_args__ = (
        UniqueConstraint("guidance_snapshot_id", "sector", name="uq_guidance_sector_scores_snapshot_sector"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guidance_snapshot_id = Column(Integer, ForeignKey("guidance_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    sector = Column(String(100), nullable=False, index=True)
    score = Column(Float, nullable=False, default=0.0)
    label = Column(String(20), nullable=False, default="neutral")  # favored, neutral, avoid
    rationale = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)


class CycleContextSnapshot(Base):
    """Per-cycle context, guidance influence, and attribution metadata."""

    __tablename__ = "cycle_context_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(String(50), nullable=False, unique=True, index=True)
    run_type = Column(String(20), nullable=False, default="scheduled")
    captured_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    repo_sha = Column(String(100), nullable=True)
    config_hash = Column(String(64), nullable=True)
    strategy_prompt_hash = Column(String(64), nullable=True)
    strategy_fingerprint_hash = Column(String(64), nullable=True)
    risk_fingerprint_hash = Column(String(64), nullable=True)
    execution_fingerprint_hash = Column(String(64), nullable=True)
    guidance_snapshot_id = Column(Integer, ForeignKey("guidance_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    guidance_mode = Column(String(20), nullable=True)
    prompt_guidance_summary = Column(Text, nullable=True)
    applied_screening_bias_json = Column(Text, nullable=True)
    pre_guidance_candidate_count = Column(Integer, nullable=True)
    post_guidance_candidate_count = Column(Integer, nullable=True)
    pre_guidance_sector_distribution_json = Column(Text, nullable=True)
    post_guidance_sector_distribution_json = Column(Text, nullable=True)
    active_strategy_episode_ids_json = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )


class StrategyChangeEpisode(Base):
    """Human-reviewed strategy change episode for observational attribution."""

    __tablename__ = "strategy_change_episodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), nullable=False, default="proposed", index=True)  # proposed, confirmed, rejected
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=False)
    change_type = Column(String(30), nullable=False, index=True)
    review_confidence = Column(Float, nullable=True)
    commit_start_sha = Column(String(100), nullable=True)
    commit_end_sha = Column(String(100), nullable=True)
    effective_start_at = Column(DateTime, nullable=False, index=True)
    effective_end_at = Column(DateTime, nullable=True, index=True)
    confirmed_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )


class StrategyChangeEvidence(Base):
    """Commit-level evidence for a proposed or confirmed strategy episode."""

    __tablename__ = "strategy_change_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    episode_id = Column(Integer, ForeignKey("strategy_change_episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    commit_sha = Column(String(100), nullable=False, index=True)
    committed_at = Column(DateTime, nullable=False, index=True)
    author_name = Column(String(200), nullable=True)
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    affected_files_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class SlackCommandLog(Base):
    """Audit log for Slack-triggered trade commands (US-1.6)."""

    __tablename__ = "slack_command_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    channel_id = Column(String(100), nullable=True)
    user_id = Column(String(100), nullable=True)
    thread_ts = Column(String(50), nullable=True)
    raw_message = Column(Text, nullable=False)
    parsed_intent_json = Column(Text, nullable=True)
    ticker = Column(String(50), nullable=True, index=True)
    action = Column(String(20), nullable=True)
    cycle_id = Column(String(100), nullable=True, index=True)
    order_id = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False, default="received")
    command_kind = Column(String(20), nullable=True)
    execution_mode = Column(String(20), nullable=True)
    target_order_class = Column(String(20), nullable=True)
    target_tickers_json = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    response_message = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)


class ChatSession(Base):
    """Conversational trading session (US-1.9)."""

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), nullable=False, default="active")
    channel_type = Column(String(20), nullable=False)  # origin channel
    channel_session_key = Column(String(100), nullable=True)
    user_id = Column(String(100), nullable=True)
    title = Column(String(200), nullable=True)
    last_channel_type = Column(String(20), nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_activity_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)
    context_json = Column(Text, nullable=True)
    linked_cycle_id = Column(String(100), nullable=True)
    previous_session_id = Column(Integer, nullable=True)


class ChatTurn(Base):
    """Individual turn in a conversational trading session (US-1.9)."""

    __tablename__ = "chat_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", name="uq_chat_turns_session_id_turn_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False, default=0)
    role = Column(String(20), nullable=False)
    channel_type = Column(String(20), nullable=True)
    message_text = Column(Text, nullable=True)
    intent_json = Column(Text, nullable=True)
    resolution_json = Column(Text, nullable=True)
    response_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ChatAction(Base):
    """Proposed or executed conversational action attached to a session."""

    __tablename__ = "chat_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_id = Column(Integer, ForeignKey("chat_turns.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="draft", index=True)
    title = Column(String(200), nullable=True)
    ticker = Column(String(50), nullable=True, index=True)
    payload_json = Column(Text, nullable=True)
    preview_text = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    requires_confirmation = Column(Boolean, nullable=False, default=False)
    rejection_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)


class ChatResearchLog(Base):
    """Research trace emitted during conversational turns."""

    __tablename__ = "chat_research_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_id = Column(Integer, ForeignKey("chat_turns.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_name = Column(String(50), nullable=False)
    provider = Column(String(50), nullable=True)
    query = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    cache_hit = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ChatWorkflowStep(Base):
    """Operator-safe workflow trace for an individual conversational turn."""

    __tablename__ = "chat_workflow_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_id = Column(Integer, ForeignKey("chat_turns.id", ondelete="SET NULL"), nullable=True, index=True)
    step_key = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="running", index=True)
    label = Column(String(120), nullable=True)
    detail = Column(Text, nullable=True)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    tool_name = Column(String(50), nullable=True)
    cost_gbp = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    detail_json = Column(Text, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )


class IntentDetectionCache(Base):
    """Persistent cache of successful LLM intent detections."""

    __tablename__ = "intent_detection_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(64), nullable=False, unique=True, index=True)
    normalized_message = Column(Text, nullable=False)
    example_message = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, default="claude")
    intent_kind = Column(String(20), nullable=False, index=True)
    intent_json = Column(Text, nullable=False)
    hit_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    last_used_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EvolutionRequest(Base):
    """Operator-requested software evolution workflow (US-1.10)."""

    __tablename__ = "evolution_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(40), nullable=False, default="DRAFT", index=True)
    source_channel = Column(String(20), nullable=False, default="dashboard")
    requested_by = Column(String(100), nullable=True, index=True)
    title = Column(String(200), nullable=True)
    request_text = Column(Text, nullable=False)
    objective = Column(Text, nullable=True)
    risk_class = Column(String(10), nullable=True, index=True)
    latest_plan_version = Column(Integer, nullable=False, default=0)
    touched_areas_json = Column(Text, nullable=True)
    excluded_areas_json = Column(Text, nullable=True)
    assumptions_json = Column(Text, nullable=True)
    clarification_questions_json = Column(Text, nullable=True)
    required_validations_json = Column(Text, nullable=True)
    current_run_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )


class EvolutionMessage(Base):
    """Conversation and audit messages attached to an evolution request."""

    __tablename__ = "evolution_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)  # operator, planner, system
    message_type = Column(String(30), nullable=False, default="comment")
    message_text = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EvolutionPlan(Base):
    """Structured plan snapshot for an evolution request."""

    __tablename__ = "evolution_plans"
    __table_args__ = (
        UniqueConstraint("request_id", "version", name="uq_evolution_plans_request_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(40), nullable=False)
    summary = Column(Text, nullable=False)
    change_spec_json = Column(Text, nullable=False)
    repo_context_json = Column(Text, nullable=False)
    implementation_steps_json = Column(Text, nullable=False)
    validation_matrix_json = Column(Text, nullable=False)
    risk_policy_json = Column(Text, nullable=False)
    phase_capabilities_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EvolutionRun(Base):
    """Workflow run records for planning, build, validation, and deployment phases."""

    __tablename__ = "evolution_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_kind = Column(String(30), nullable=False)  # planning, build, validation, deploy
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed, blocked
    summary_json = Column(Text, nullable=True)
    worker_label = Column(String(100), nullable=True)
    branch_name = Column(String(100), nullable=True)
    commit_sha = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime, nullable=True)


class EvolutionArtifact(Base):
    """Persisted artifacts produced by the evolution workflow."""

    __tablename__ = "evolution_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        Integer,
        ForeignKey("evolution_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_type = Column(String(50), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class EvolutionApproval(Base):
    """Approval decisions and blocked attempts for gated evolution phases."""

    __tablename__ = "evolution_approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approval_type = Column(String(20), nullable=False)  # build, deploy
    status = Column(String(20), nullable=False, default="requested")
    requested_by = Column(String(100), nullable=True)
    decided_by = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    decided_at = Column(DateTime, nullable=True)


class LearningRun(Base):
    """Persisted record of a trade-outcome learning pipeline run (US-2.1, US-6.1, US-6.3).

    Stores metadata for one execution of the learning CLI (``python -m
    src.learning.cli train ...``). Heavy artifacts live on disk under
    ``data/learning/`` and are pointed to via ``artifact_paths_json``.
    """

    __tablename__ = "learning_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=False, unique=True, index=True)
    dataset_version = Column(String(20), nullable=False, index=True)
    model_kind = Column(String(50), nullable=False)  # calibrator, gbm, stall, bundle
    status = Column(String(20), nullable=False, default="completed")  # completed, failed
    rows = Column(Integer, nullable=False, default=0)
    label_distribution_json = Column(Text, nullable=True)
    metrics_json = Column(Text, nullable=True)
    artifact_paths_json = Column(Text, nullable=True)
    checksum = Column(String(128), nullable=True)
    is_champion = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class LearningExportRun(Base):
    """Persisted record of a scheduled or manual learning dataset export."""

    __tablename__ = "learning_export_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=False, unique=True, index=True)
    dataset_version = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="completed")
    rows = Column(Integer, nullable=False, default=0)
    text_corpus_rows = Column(Integer, nullable=False, default=0)
    label_distribution_json = Column(Text, nullable=True)
    artifact_paths_json = Column(Text, nullable=True)
    checksum = Column(String(128), nullable=True)
    duration_sec = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class LearningEvaluationRun(Base):
    """Persisted champion/challenger counterfactual evaluation run."""

    __tablename__ = "learning_evaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(100), nullable=False, unique=True, index=True)
    dataset_version = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="completed")
    n_rows = Column(Integer, nullable=False, default=0)
    closed_trades = Column(Integer, nullable=False, default=0)
    metrics_json = Column(Text, nullable=True)
    gates_json = Column(Text, nullable=True)
    artifact_run_id = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class DecisionShadowScore(Base):
    """Per-cycle shadow challenger recommendation (no live influence)."""

    __tablename__ = "decision_shadow_scores"
    __table_args__ = (
        Index("ix_shadow_scores_cycle_ticker", "cycle_id", "ticker"),
        Index("ix_shadow_scores_policy_ts", "policy_id", "decision_ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id = Column(String(100), nullable=False, index=True)
    ticker = Column(String(50), nullable=False, index=True)
    decision_ts = Column(DateTime, nullable=False, index=True)
    champion_action = Column(String(30), nullable=False)
    policy_id = Column(String(50), nullable=False, index=True)
    recommended_action = Column(String(30), nullable=False)
    scores_json = Column(Text, nullable=True)
    artifact_run_ids_json = Column(Text, nullable=True)
    outcome_json = Column(Text, nullable=True)
    matured_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class EvolutionDeployment(Base):
    """Deployment and rollback records for later evolution phases."""

    __tablename__ = "evolution_deployments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer,
        ForeignKey("evolution_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approval_id = Column(
        Integer,
        ForeignKey("evolution_approvals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    environment = Column(String(50), nullable=False, default="production")
    status = Column(String(20), nullable=False, default="pending")
    deploy_ref = Column(String(200), nullable=True)
    rollback_ref = Column(String(200), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )
