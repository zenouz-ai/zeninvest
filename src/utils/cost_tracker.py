"""LLM API cost tracking, budget enforcement, and graceful degradation."""

from datetime import datetime, timedelta
from enum import Enum
from typing import NamedTuple

from sqlalchemy import func

from src.data.database import get_session
from src.data.models import CostLog
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("cost_tracker")


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


# Cost per 1M tokens in USD, then converted to GBP at call time
# Using approximate USD/GBP rate of 0.79
USD_TO_GBP = 0.79

COST_RATES: dict[str, dict[str, float]] = {
    # provider -> {input_per_1m_usd, output_per_1m_usd}
    "anthropic": {"input_per_1m": 3.0, "output_per_1m": 15.0},
    "openai": {"input_per_1m": 2.50, "output_per_1m": 10.0},
    "google": {"input_per_1m": 0.10, "output_per_1m": 0.40},
}


class CostResult(NamedTuple):
    """Result of a cost calculation."""
    input_tokens: int
    output_tokens: int
    cost_gbp: float
    provider: str
    model: str


class BudgetStatus(NamedTuple):
    """Current budget status for a provider."""
    provider: str
    daily_spent_gbp: float
    daily_limit_gbp: float
    daily_remaining_gbp: float
    daily_pct_used: float
    monthly_spent_gbp: float
    monthly_limit_gbp: float
    monthly_remaining_gbp: float
    monthly_pct_used: float
    is_over_daily: bool
    is_over_monthly: bool
    is_at_alert_threshold: bool


class DegradationLevel(str, Enum):
    """Levels of graceful degradation."""
    FULL = "full"  # All providers available
    NO_GEMINI = "no_gemini"  # Skip Gemini (cheapest first to preserve)
    NO_GPT4O = "no_gpt4o"  # Skip GPT-4o too
    NO_STRATEGY = "no_strategy"  # Skip entire strategy cycle
    HALTED = "halted"  # All budgets exceeded


def calculate_cost(
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate cost in GBP for a given API call."""
    rates = COST_RATES.get(provider)
    if rates is None:
        logger.warning(f"Unknown provider {provider}, assuming zero cost")
        return 0.0

    input_cost = (input_tokens / 1_000_000) * rates["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * rates["output_per_1m"]
    total_usd = input_cost + output_cost
    return round(total_usd * USD_TO_GBP, 6)


def log_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cycle_id: str | None = None,
    purpose: str | None = None,
) -> CostResult:
    """Log an LLM API call cost to the database."""
    cost_gbp = calculate_cost(provider, input_tokens, output_tokens)

    session = get_session()
    try:
        entry = CostLog(
            timestamp=datetime.utcnow(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_gbp=cost_gbp,
            cycle_id=cycle_id,
            purpose=purpose,
        )
        session.add(entry)
        session.commit()
        logger.info(
            f"Cost logged: {provider}/{model} - "
            f"{input_tokens}in/{output_tokens}out = £{cost_gbp:.4f}"
        )
    finally:
        session.close()

    return CostResult(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_gbp=cost_gbp,
        provider=provider,
        model=model,
    )


def get_daily_spend(provider: str | None = None) -> float:
    """Get total spend today in GBP, optionally filtered by provider."""
    session = get_session()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query = session.query(func.coalesce(func.sum(CostLog.cost_gbp), 0.0)).filter(
            CostLog.timestamp >= today_start
        )
        if provider:
            query = query.filter(CostLog.provider == provider)
        return float(query.scalar())
    finally:
        session.close()


def get_monthly_spend() -> float:
    """Get total spend this month in GBP across all providers."""
    session = get_session()
    try:
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result = session.query(
            func.coalesce(func.sum(CostLog.cost_gbp), 0.0)
        ).filter(CostLog.timestamp >= month_start).scalar()
        return float(result)
    finally:
        session.close()


def get_budget_status(provider: str) -> BudgetStatus:
    """Get comprehensive budget status for a provider."""
    settings = get_settings()

    daily_limits = {
        Provider.ANTHROPIC.value: settings.anthropic_daily_gbp,
        Provider.OPENAI.value: settings.openai_daily_gbp,
        Provider.GOOGLE.value: settings.google_daily_gbp,
    }
    daily_limit = daily_limits.get(provider, 0.0)
    daily_spent = get_daily_spend(provider)
    daily_remaining = max(0.0, daily_limit - daily_spent)
    daily_pct = (daily_spent / daily_limit * 100) if daily_limit > 0 else 100.0

    monthly_spent = get_monthly_spend()
    monthly_limit = settings.total_monthly_gbp
    monthly_remaining = max(0.0, monthly_limit - monthly_spent)
    monthly_pct = (monthly_spent / monthly_limit * 100) if monthly_limit > 0 else 100.0

    alert_threshold = settings.alert_threshold_pct

    return BudgetStatus(
        provider=provider,
        daily_spent_gbp=daily_spent,
        daily_limit_gbp=daily_limit,
        daily_remaining_gbp=daily_remaining,
        daily_pct_used=daily_pct,
        monthly_spent_gbp=monthly_spent,
        monthly_limit_gbp=monthly_limit,
        monthly_remaining_gbp=monthly_remaining,
        monthly_pct_used=monthly_pct,
        is_over_daily=daily_spent >= daily_limit,
        is_over_monthly=monthly_spent >= monthly_limit,
        is_at_alert_threshold=(daily_pct >= alert_threshold or monthly_pct >= alert_threshold),
    )


def check_budget(provider: str) -> bool:
    """Check if a provider is within budget. Returns True if OK to proceed."""
    status = get_budget_status(provider)

    if status.is_over_monthly:
        logger.warning(f"Monthly budget exceeded: £{status.monthly_spent_gbp:.2f}/£{status.monthly_limit_gbp:.2f}")
        return False

    if status.is_over_daily:
        logger.warning(f"{provider} daily budget exceeded: £{status.daily_spent_gbp:.2f}/£{status.daily_limit_gbp:.2f}")
        return False

    if status.is_at_alert_threshold:
        logger.warning(
            f"{provider} approaching budget limit: "
            f"daily {status.daily_pct_used:.0f}%, monthly {status.monthly_pct_used:.0f}%"
        )

    return True


def get_degradation_level() -> DegradationLevel:
    """Determine current degradation level based on all budgets."""
    settings = get_settings()
    monthly_spent = get_monthly_spend()

    if monthly_spent >= settings.total_monthly_gbp:
        logger.error("All budgets exceeded — halting all LLM calls")
        return DegradationLevel.HALTED

    anthropic_ok = check_budget(Provider.ANTHROPIC.value)
    openai_ok = check_budget(Provider.OPENAI.value)
    google_ok = check_budget(Provider.GOOGLE.value)

    if not anthropic_ok:
        logger.error("Anthropic budget exceeded — skipping strategy cycle")
        return DegradationLevel.NO_STRATEGY

    if not openai_ok and not google_ok:
        logger.warning("Both moderator budgets exceeded — running without moderation")
        return DegradationLevel.NO_GPT4O

    if not google_ok:
        logger.info("Google budget exceeded — skipping Gemini moderator")
        return DegradationLevel.NO_GEMINI

    if not openai_ok:
        logger.info("OpenAI budget exceeded — skipping GPT-4o moderator")
        return DegradationLevel.NO_GPT4O

    return DegradationLevel.FULL


def get_cost_summary(days: int = 1) -> dict[str, float]:
    """Get cost summary grouped by provider for the last N days."""
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(
                CostLog.provider,
                func.sum(CostLog.cost_gbp).label("total"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
            )
            .filter(CostLog.timestamp >= since)
            .group_by(CostLog.provider)
            .all()
        )
        summary: dict[str, float] = {}
        total = 0.0
        for row in rows:
            cost = float(row.total or 0)
            summary[row.provider] = cost
            total += cost
        summary["total"] = total
        return summary
    finally:
        session.close()
