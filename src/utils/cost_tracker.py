"""LLM API cost tracking, budget enforcement, and graceful degradation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import NamedTuple

from sqlalchemy import func

from src.data.database import get_session, write_transaction
from src.data.models import CostLog
from src.utils.chat_cost_context import current_chat_cost_context
from src.utils.error_codes import ErrorCode
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

# Embedding models priced per 1M tokens (USD). text-embedding-3-small ≈ $0.02/1M;
# reusing the openai chat rate ($2.50/1M) would overstate cost ~125x.
EMBEDDING_COST_RATES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}

# Daily-spend categories matched on CostLog.purpose. Chat spend uses
# purpose="conversation_*"; embeddings use purpose="embedding". These have their
# own daily caps and are kept OFF the per-provider trading daily budgets (they
# still count toward the global monthly cap).
CHAT_PURPOSE_PREFIX = "conversation_"
EMBEDDING_PURPOSE = "embedding"

# Atomic cost-budget reservation states (P4-1, US-7.5). A "pending" row is an
# estimated reservation that counts toward spend until it is settled to the
# actual cost or released. See reserve_budget/settle_reservation/budget_guard.
RESERVATION_PENDING = "pending"
RESERVATION_SETTLED = "settled"


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


def estimate_cost(provider: str, input_text: str = "", max_output_tokens: int = 0) -> float:
    """Rough pre-call cost estimate (GBP) for sizing a budget reservation.

    Approximates input tokens at ~4 chars/token and assumes the call may use its
    full ``max_output_tokens``. Over-estimating is the safe direction (reserves
    conservatively); settlement corrects to the actual cost after the call.
    """
    est_input_tokens = max(len(input_text) // 4, 1)
    return calculate_cost(provider, est_input_tokens, max_output_tokens)


def calculate_embedding_cost(model: str, tokens: int) -> float:
    """Calculate cost in GBP for an embedding call (single token bucket)."""
    rate = EMBEDDING_COST_RATES.get(model)
    if rate is None:
        logger.warning(f"Unknown embedding model {model}, assuming zero cost")
        return 0.0
    total_usd = (tokens / 1_000_000) * rate
    return round(total_usd * USD_TO_GBP, 6)


def log_embedding_cost(
    tokens: int,
    model: str = "text-embedding-3-small",
    cycle_id: str | None = None,
) -> CostResult:
    """Log an embedding API call cost to the database (purpose='embedding')."""
    cost_gbp = calculate_embedding_cost(model, tokens)
    bound_session_id, bound_turn_id = current_chat_cost_context()

    session = get_session()
    try:
        entry = CostLog(
            timestamp=datetime.now(timezone.utc),
            chat_session_id=bound_session_id,
            chat_turn_id=bound_turn_id,
            provider=Provider.OPENAI.value,
            model=model,
            input_tokens=tokens,
            output_tokens=0,
            cost_gbp=cost_gbp,
            cycle_id=cycle_id,
            purpose=EMBEDDING_PURPOSE,
        )
        session.add(entry)
        session.commit()
        logger.info(f"Embedding cost logged: {model} - {tokens}tok = £{cost_gbp:.4f}")
    finally:
        session.close()

    return CostResult(
        input_tokens=tokens,
        output_tokens=0,
        cost_gbp=cost_gbp,
        provider=Provider.OPENAI.value,
        model=model,
    )


def log_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cycle_id: str | None = None,
    purpose: str | None = None,
    chat_session_id: int | None = None,
    chat_turn_id: int | None = None,
) -> CostResult:
    """Log an LLM API call cost to the database."""
    cost_gbp = calculate_cost(provider, input_tokens, output_tokens)
    bound_session_id, bound_turn_id = current_chat_cost_context()
    if chat_session_id is None:
        chat_session_id = bound_session_id
    if chat_turn_id is None:
        chat_turn_id = bound_turn_id

    session = get_session()
    try:
        entry = CostLog(
            timestamp=datetime.now(timezone.utc),
            chat_session_id=chat_session_id,
            chat_turn_id=chat_turn_id,
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


def get_daily_spend(provider: str | None = None, exclude_categories: bool = False) -> float:
    """Get total spend today in GBP, optionally filtered by provider.

    When ``exclude_categories`` is True, chat (``conversation_*``) and embedding
    (``embedding``) purposes are excluded so they do not consume the per-provider
    trading daily budgets (they have their own daily caps).
    """
    session = get_session()
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = session.query(func.coalesce(func.sum(CostLog.cost_gbp), 0.0)).filter(
            CostLog.timestamp >= today_start
        )
        if provider:
            query = query.filter(CostLog.provider == provider)
        if exclude_categories:
            query = query.filter(
                func.coalesce(CostLog.purpose, "").notlike(CHAT_PURPOSE_PREFIX + "%"),
                func.coalesce(CostLog.purpose, "") != EMBEDDING_PURPOSE,
            )
        return float(query.scalar())
    finally:
        session.close()


def get_category_daily_spend(category: str) -> float:
    """Get today's spend in GBP for a purpose category ('chat' or 'embedding')."""
    session = get_session()
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = session.query(func.coalesce(func.sum(CostLog.cost_gbp), 0.0)).filter(
            CostLog.timestamp >= today_start
        )
        if category == "chat":
            query = query.filter(CostLog.purpose.like(CHAT_PURPOSE_PREFIX + "%"))
        elif category == "embedding":
            query = query.filter(CostLog.purpose == EMBEDDING_PURPOSE)
        else:
            logger.warning(f"Unknown spend category {category!r}; returning 0.0")
            return 0.0
        return float(query.scalar())
    finally:
        session.close()


def get_monthly_spend() -> float:
    """Get total spend this month in GBP across all providers."""
    session = get_session()
    try:
        now = datetime.now(timezone.utc)
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
    # Exclude chat/embedding purposes so they don't consume trading provider budgets.
    daily_spent = get_daily_spend(provider, exclude_categories=True)
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
        logger.warning(
            f"[{ErrorCode.COST_MONTHLY_HALT}] Monthly budget exceeded: "
            f"£{status.monthly_spent_gbp:.2f}/£{status.monthly_limit_gbp:.2f}"
        )
        return False

    if status.is_over_daily:
        logger.warning(
            f"[{ErrorCode.COST_DAILY_CAP_EXCEEDED}] {provider} daily budget exceeded: "
            f"£{status.daily_spent_gbp:.2f}/£{status.daily_limit_gbp:.2f}"
        )
        return False

    if status.is_at_alert_threshold:
        logger.warning(
            f"{provider} approaching budget limit: "
            f"daily {status.daily_pct_used:.0f}%, monthly {status.monthly_pct_used:.0f}%"
        )

    return True


def check_category_budget(category: str) -> bool:
    """Check if a spend category ('chat'/'embedding') is within budget.

    Returns True if OK to proceed. Respects the global monthly cap first, then the
    category's own daily cap. Independent of the per-provider trading budgets.
    """
    settings = get_settings()

    caps = {
        "chat": settings.conversation_chat_llm_daily_budget_gbp,
        "embedding": settings.learning_embedding_daily_budget_gbp,
    }
    cap = caps.get(category)
    if cap is None:
        logger.warning(f"Unknown spend category {category!r}; denying")
        return False

    # Fail-open guardrail: a budget check must never crash the path it protects.
    # If spend cannot be read (e.g. transient DB error), allow the call to proceed.
    try:
        monthly_spent = get_monthly_spend()
        if monthly_spent >= settings.total_monthly_gbp:
            logger.warning(
                f"[{ErrorCode.COST_MONTHLY_HALT}] Monthly budget exceeded: "
                f"£{monthly_spent:.2f}/£{settings.total_monthly_gbp:.2f} — blocking {category} spend"
            )
            return False

        spent = get_category_daily_spend(category)
    except Exception as exc:
        logger.debug(f"{category} budget check unavailable, failing open: {exc}")
        return True

    if spent >= cap:
        logger.warning(
            f"[{ErrorCode.COST_DAILY_CAP_EXCEEDED}] {category} daily budget exceeded: "
            f"£{spent:.4f}/£{cap:.2f}"
        )
        return False
    return True


def check_chat_budget() -> bool:
    """Check if conversational LLM spend is within its daily cap."""
    return check_category_budget("chat")


def check_embedding_budget() -> bool:
    """Check if embedding spend is within its daily cap."""
    return check_category_budget("embedding")


# --- Atomic cost budget (P4-1, US-7.5) ---------------------------------------
#
# The legacy pattern (check_budget -> call -> log_cost) has a TOCTOU gap: two
# concurrent threads (scheduled cycle, scheduler refresh, dashboard chat) can each
# pass check_budget() before either logs, overspending the cap. reserve_budget
# closes this by inserting a "pending" CostLog row inside the process-wide write
# lock, so the increment is atomic: a serialized later caller sees the reservation
# in the spend total. Pending rows are settled to actual cost after the call, or
# released on failure, or swept if orphaned by a crash. Opt-in via
# settings.atomic_budget_enabled; budget_guard preserves the legacy path when off.


def reserve_budget(
    provider: str,
    estimated_gbp: float,
    *,
    model: str = "",
    purpose: str | None = None,
    cycle_id: str | None = None,
) -> int | None:
    """Atomically reserve budget for a provider call. Returns reservation id or None.

    Holds the write lock across the spend read and the reservation insert so two
    concurrent callers cannot both pass the cap. Returns None (deny) when the
    provider is already over its daily limit or the global monthly cap is hit.
    """
    settings = get_settings()
    daily_limits = {
        Provider.ANTHROPIC.value: settings.anthropic_daily_gbp,
        Provider.OPENAI.value: settings.openai_daily_gbp,
        Provider.GOOGLE.value: settings.google_daily_gbp,
    }
    daily_limit = daily_limits.get(provider, 0.0)
    from src.data.database import get_write_lock, session_scope

    with get_write_lock():
        monthly_spent = get_monthly_spend()
        if monthly_spent >= settings.total_monthly_gbp:
            logger.warning(
                f"[{ErrorCode.COST_MONTHLY_HALT}] Monthly budget exceeded: "
                f"£{monthly_spent:.2f}/£{settings.total_monthly_gbp:.2f} — denying {provider} reservation"
            )
            return None
        daily_spent = get_daily_spend(provider, exclude_categories=True)
        if daily_spent >= daily_limit:
            logger.warning(
                f"[{ErrorCode.COST_DAILY_CAP_EXCEEDED}] {provider} daily budget exceeded: "
                f"£{daily_spent:.2f}/£{daily_limit:.2f} — denying reservation"
            )
            return None
        with session_scope() as session:
            entry = CostLog(
                timestamp=datetime.now(timezone.utc),
                provider=provider,
                model=model or "reservation",
                input_tokens=0,
                output_tokens=0,
                cost_gbp=round(max(estimated_gbp, 0.0), 6),
                cycle_id=cycle_id,
                purpose=purpose,
                reservation_state=RESERVATION_PENDING,
            )
            session.add(entry)
            session.flush()
            return int(entry.id)


def settle_reservation(
    reservation_id: int,
    actual_gbp: float,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
) -> None:
    """Reconcile a pending reservation to the call's actual cost."""
    with write_transaction() as session:
        row = session.get(CostLog, reservation_id)
        if row is None or row.reservation_state != RESERVATION_PENDING:
            return
        row.cost_gbp = round(max(actual_gbp, 0.0), 6)
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        if model:
            row.model = model
        row.reservation_state = RESERVATION_SETTLED


def release_reservation(reservation_id: int) -> None:
    """Delete a pending reservation (call failed or was skipped)."""
    with write_transaction() as session:
        row = session.get(CostLog, reservation_id)
        if row is not None and row.reservation_state == RESERVATION_PENDING:
            session.delete(row)


def sweep_stale_reservations(max_age_minutes: int = 10) -> int:
    """Delete orphaned pending reservations (crash recovery). Returns count removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    with write_transaction() as session:
        rows = (
            session.query(CostLog)
            .filter(
                CostLog.reservation_state == RESERVATION_PENDING,
                CostLog.timestamp < cutoff,
            )
            .all()
        )
        count = len(rows)
        for row in rows:
            session.delete(row)
    if count:
        logger.warning(f"Swept {count} stale cost reservation(s) older than {max_age_minutes}m")
    return count


class BudgetGuard:
    """Handle yielded by budget_guard: gate a call and settle its actual cost.

    ``approved`` mirrors check_budget()==True. ``settle(in, out)`` records the
    actual cost: settling the reservation (atomic mode) or calling log_cost
    (legacy mode). Idempotent.
    """

    def __init__(
        self,
        *,
        approved: bool,
        reservation_id: int | None,
        provider: str,
        model: str,
        purpose: str | None,
        cycle_id: str | None,
        atomic: bool,
    ) -> None:
        self.approved = approved
        self.reservation_id = reservation_id
        self._provider = provider
        self._model = model
        self._purpose = purpose
        self._cycle_id = cycle_id
        self._atomic = atomic
        self._settled = False
        self.cost_result: CostResult | None = None

    def settle(
        self, input_tokens: int, output_tokens: int, *, model: str | None = None
    ) -> CostResult:
        """Record the actual cost of the completed call."""
        used_model = model or self._model or "unknown"
        if self._settled and self.cost_result is not None:
            return self.cost_result
        self._settled = True
        if self._atomic and self.reservation_id is not None:
            cost = calculate_cost(self._provider, input_tokens, output_tokens)
            settle_reservation(
                self.reservation_id,
                cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=used_model,
            )
            self.cost_result = CostResult(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_gbp=cost,
                provider=self._provider,
                model=used_model,
            )
        else:
            self.cost_result = log_cost(
                self._provider,
                used_model,
                input_tokens,
                output_tokens,
                cycle_id=self._cycle_id,
                purpose=self._purpose,
            )
        return self.cost_result


@contextmanager
def budget_guard(
    provider: str,
    estimated_gbp: float = 0.0,
    *,
    model: str = "",
    purpose: str | None = None,
    cycle_id: str | None = None,
) -> Iterator[BudgetGuard]:
    """Unified budget gate. Atomic reserve/settle when enabled, else check/log.

    Usage::

        with budget_guard(provider, est, model=m, purpose=p) as guard:
            if not guard.approved:
                return degraded
            resp = call()
            guard.settle(resp.input_tokens, resp.output_tokens)
    """
    settings = get_settings()
    atomic = settings.atomic_budget_enabled
    reservation_id: int | None = None
    if atomic:
        reservation_id = reserve_budget(
            provider, estimated_gbp, model=model, purpose=purpose, cycle_id=cycle_id
        )
        approved = reservation_id is not None
    else:
        approved = check_budget(provider)
    guard = BudgetGuard(
        approved=approved,
        reservation_id=reservation_id,
        provider=provider,
        model=model,
        purpose=purpose,
        cycle_id=cycle_id,
        atomic=atomic,
    )
    try:
        yield guard
    finally:
        # Release an unsettled reservation so a skipped/failed call leaves no phantom spend.
        if atomic and reservation_id is not None and not guard._settled:
            release_reservation(reservation_id)


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
        # Only GPT-4o is over budget; Gemini is still available.
        # Use NO_GPT4O so moderation panel skips GPT-4o and keeps Gemini.
        logger.info("OpenAI budget exceeded — skipping GPT-4o moderator (Gemini still available)")
        return DegradationLevel.NO_GPT4O

    return DegradationLevel.FULL


def get_cost_summary(days: int = 1) -> dict[str, float]:
    """Get cost summary grouped by provider for the last N days."""
    session = get_session()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        # Exclude pending reservations from reporting so transient estimates don't
        # skew dashboards (they still count toward live budget checks until settled).
        not_pending = func.coalesce(CostLog.reservation_state, "") != RESERVATION_PENDING
        rows = (
            session.query(
                CostLog.provider,
                func.sum(CostLog.cost_gbp).label("total"),
                func.sum(CostLog.input_tokens).label("input_tokens"),
                func.sum(CostLog.output_tokens).label("output_tokens"),
            )
            .filter(CostLog.timestamp >= since, not_pending)
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

        # Category breakdown by purpose (chat = conversation_*, embedding = embedding).
        chat_total = (
            session.query(func.coalesce(func.sum(CostLog.cost_gbp), 0.0))
            .filter(
                CostLog.timestamp >= since,
                CostLog.purpose.like(CHAT_PURPOSE_PREFIX + "%"),
                not_pending,
            )
            .scalar()
        )
        embedding_total = (
            session.query(func.coalesce(func.sum(CostLog.cost_gbp), 0.0))
            .filter(CostLog.timestamp >= since, CostLog.purpose == EMBEDDING_PURPOSE, not_pending)
            .scalar()
        )
        summary["chat"] = float(chat_total or 0)
        summary["embedding"] = float(embedding_total or 0)
        return summary
    finally:
        session.close()
