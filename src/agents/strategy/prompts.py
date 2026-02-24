"""Prompt templates for Claude strategy synthesis."""

STRATEGY_SYSTEM_PROMPT = """You are an expert portfolio manager running an autonomous investment system.
Your goal is to outperform the S&P 500 by 10%+ over 6-12 months. You synthesize signals from
three quantitative strategies (Momentum, Mean Reversion, Factor) along with news sentiment data
to make final portfolio allocation decisions.

You must respond with ONLY valid JSON matching the exact schema specified. No markdown, no explanation outside the JSON."""

STRATEGY_USER_PROMPT = """Analyze the following portfolio state and strategy proposals. Make allocation decisions.

## CURRENT PORTFOLIO STATE
{portfolio_state}

## MARKET REGIME ASSESSMENT
{market_regime}

## STRATEGY PROPOSALS

### Momentum Strategy (weight: {momentum_weight})
{momentum_proposals}

### Mean Reversion Strategy (weight: {mean_reversion_weight})
{mean_reversion_proposals}

### Factor Strategy (weight: {factor_weight})
{factor_proposals}

## NEWS SENTIMENT DATA (Finnhub)
{finnhub_sentiment}

## MARKET-WIDE NEWS SENTIMENT (Alpha Vantage)
{alpha_vantage_sentiment}

## CURRENT RISK BUDGET
- System State: {system_state}
- VIX: {vix}
- Cash: {cash_pct:.1f}%
- Max position size: {max_position_pct}%
- Positions: {num_positions}/{max_positions}

## CONSTRAINTS
- Max 15 positions
- Min 2% / Max {max_position_pct}% per position
- Min 10% cash buffer
- {state_constraints}

Respond with this exact JSON structure:
{{
  "market_assessment": "2-3 sentence market regime with news sentiment context",
  "decisions": [
    {{
      "ticker": "TICKER_ID",
      "action": "BUY|SELL|HOLD|REDUCE",
      "target_allocation_pct": 5.0,
      "conviction": 78,
      "primary_strategy": "momentum|mean_reversion|factor",
      "reasoning": "3-5 sentence rationale incorporating news sentiment",
      "growth_potential": "HIGH|MEDIUM|LOW",
      "risk_level": "HIGH|MEDIUM|LOW",
      "catalysts": ["list of expected catalysts"],
      "risks": ["list of key risks"],
      "exit_conditions": "specific conditions for selling",
      "upside_target_pct": 15.0,
      "stop_loss_pct": -8.0,
      "expected_holding_period": "3-6 months",
      "news_sentiment_summary": "1-sentence summary of current news mood"
    }}
  ],
  "portfolio_commentary": "overall positioning rationale"
}}"""


def build_strategy_prompt(
    portfolio_state: str,
    market_regime: str,
    momentum_proposals: str,
    mean_reversion_proposals: str,
    factor_proposals: str,
    finnhub_sentiment: str,
    alpha_vantage_sentiment: str,
    system_state: str,
    vix: float | None,
    cash_pct: float,
    max_position_pct: float,
    num_positions: int,
    max_positions: int,
    momentum_weight: float,
    mean_reversion_weight: float,
    factor_weight: float,
) -> str:
    """Build the full strategy prompt for Claude."""
    state_constraints = ""
    if system_state == "CAUTIOUS":
        state_constraints = "CAUTIOUS MODE: No new positions. Max 8% per position. Only add to winners."
    elif system_state == "HALTED":
        state_constraints = "HALTED: DO NOT propose any trades. System is liquidating."
    else:
        state_constraints = "Normal operation."

    return STRATEGY_USER_PROMPT.format(
        portfolio_state=portfolio_state,
        market_regime=market_regime,
        momentum_proposals=momentum_proposals,
        mean_reversion_proposals=mean_reversion_proposals,
        factor_proposals=factor_proposals,
        finnhub_sentiment=finnhub_sentiment,
        alpha_vantage_sentiment=alpha_vantage_sentiment,
        system_state=system_state,
        vix=vix or "N/A",
        cash_pct=cash_pct,
        max_position_pct=max_position_pct,
        num_positions=num_positions,
        max_positions=max_positions,
        momentum_weight=momentum_weight,
        mean_reversion_weight=mean_reversion_weight,
        factor_weight=factor_weight,
        state_constraints=state_constraints,
    )
