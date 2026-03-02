"""SQLAlchemy ORM models for all database tables."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
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
    market_cap = Column(Float, nullable=True)
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
