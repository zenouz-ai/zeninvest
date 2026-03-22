"""SQLAlchemy ORM models for all database tables."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
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
    last_cycle_at = Column(DateTime, nullable=True)
    daily_loss_halt_until = Column(DateTime, nullable=True)
    paused = Column(Boolean, default=False)
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    ticker = Column(String(50), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # BUY, SELL, REDUCE
    order_type = Column(String(20), nullable=False)  # market, limit, stop
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # filled price
    limit_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    value_gbp = Column(Float, nullable=True)
    t212_order_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, filled, cancelled, failed
    strategy = Column(String(50), nullable=True)
    conviction = Column(Integer, nullable=True)
    moderation_result = Column(String(20), nullable=True)
    risk_result = Column(String(20), nullable=True)
    error_message = Column(Text, nullable=True)
    journal_path = Column(String(500), nullable=True)
    dedup_key = Column(String(200), nullable=True, index=True)


class StrategyDecision(Base):
    """Strategy agent decisions log."""

    __tablename__ = "strategy_decisions"

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


class ModerationLog(Base):
    """Moderation panel decisions."""

    __tablename__ = "moderation_logs"

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

    # Consensus result (filled on final row per cycle/ticker)
    consensus = Column(String(20), nullable=True)  # APPROVED, BLOCKED, CAUTION


class RiskDecision(Base):
    """Risk agent decisions."""

    __tablename__ = "risk_decisions"

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
    provider = Column(String(50), nullable=False)  # anthropic, openai, google
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_gbp = Column(Float, nullable=False, default=0.0)
    cycle_id = Column(String(50), nullable=True, index=True)
    purpose = Column(String(100), nullable=True)  # strategy, moderation, etc.


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
