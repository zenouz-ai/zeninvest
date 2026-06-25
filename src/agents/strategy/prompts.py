"""Prompt templates for Claude strategy synthesis."""

from src.utils.config import get_settings
from src.utils.prompt_loader import get_prompt_hash, load_prompt_file

STRATEGY_SYSTEM_PROMPT = load_prompt_file("strategy_system.md")
STRATEGY_USER_PROMPT = load_prompt_file("strategy_user.md")


def get_strategy_system_prompt() -> str:
    return load_prompt_file("strategy_system.md")


def get_strategy_user_prompt_template() -> str:
    return load_prompt_file("strategy_user.md")


def build_strategy_prompt(
    portfolio_state: str,
    market_regime: str,
    momentum_proposals: str,
    mean_reversion_proposals: str,
    factor_proposals: str,
    analyst_data: str,
    news_sentiment: str,
    macro_context: str,
    company_profiles: str,
    entry_quality_guards: str,
    tickers_to_decide: str,
    system_state: str,
    vix: float | None,
    cash_pct: float,
    max_position_pct: float,
    num_positions: int,
    max_positions: int,
    momentum_weight: float,
    mean_reversion_weight: float,
    factor_weight: float,
    uov_swap_context: str = "",
    position_pnl: str = "",
    strategy_performance: str = "",
    batch_focus: str = "Full universe review",
) -> str:
    """Build the full strategy prompt for Claude."""
    settings = get_settings()
    state_constraints = ""
    if system_state == "CAUTIOUS":
        state_constraints = "CAUTIOUS MODE: No new positions. Max 8% per position. Only add to winners."
    elif system_state == "HALTED":
        state_constraints = "HALTED: DO NOT propose any trades. System is liquidating."
    else:
        state_constraints = "Normal operation."
    pre_earnings_policy = (
        "Avoid_pre_earnings is enabled: for new entries, prefer HOLD/QUEUED over BUY when earnings are within the configured pre-earnings window unless the upside case is unusually strong."
        if settings.avoid_pre_earnings
        else "Avoid_pre_earnings is disabled: treat earnings timing as informational context only."
    )

    return STRATEGY_USER_PROMPT.format(
        batch_focus=batch_focus,
        portfolio_state=portfolio_state,
        market_regime=market_regime,
        company_profiles=company_profiles,
        entry_quality_guards=entry_quality_guards or "No entry-quality guardrail data available.",
        tickers_to_decide=tickers_to_decide or "None",
        momentum_proposals=momentum_proposals,
        mean_reversion_proposals=mean_reversion_proposals,
        factor_proposals=factor_proposals,
        analyst_data=analyst_data,
        news_sentiment=news_sentiment,
        macro_context=macro_context or "No persisted proactive macro state available.",
        system_state=system_state,
        vix=vix or "N/A",
        cash_pct=cash_pct,
        max_position_pct=max_position_pct,
        min_position_pct=settings.min_position_pct,
        cash_floor_pct=settings.cash_floor_pct,
        num_positions=num_positions,
        max_positions=max_positions,
        momentum_weight=momentum_weight,
        mean_reversion_weight=mean_reversion_weight,
        factor_weight=factor_weight,
        uov_swap_context=uov_swap_context or "No prior UOV swap signals available.",
        position_pnl=position_pnl or "No open positions.",
        strategy_performance=strategy_performance or "Insufficient trade history for strategy performance metrics.",
        state_constraints=state_constraints,
        pre_earnings_policy=pre_earnings_policy,
    )


def get_strategy_prompt_hash(model_name: str) -> str:
    """Return a stable hash for the static strategy prompt surface."""
    return get_prompt_hash(
        "strategy_system.md",
        "strategy_user.md",
        extra={"model": model_name},
    )
