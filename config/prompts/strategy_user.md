Analyze the data and make allocation decisions. Weigh what is decision-relevant; section notes are orientation, not rules.

Output schema is defined in the system message. Respond with ONLY valid JSON.

## BATCH FOCUS
{batch_focus}

## CURRENT PORTFOLIO STATE
{portfolio_state}

## MARKET REGIME: {market_regime}
BULL favors momentum and active buying; BEAR favors selective buying; SIDEWAYS favors factor quality and patience.

## COMPANY PROFILES
{company_profiles}

## STRATEGY PROPOSALS
Each line: TICKER: ACTION (score 0-100) — reasoning or score only for low-signal names.

### Momentum (weight: {momentum_weight})
{momentum_proposals}

### Mean Reversion (weight: {mean_reversion_weight})
{mean_reversion_proposals}

### Factor (weight: {factor_weight})
{factor_proposals}

## ANALYST DATA (Finnhub)
{analyst_data}

## NEWS SENTIMENT
{news_sentiment}

## PROACTIVE MACRO CONTEXT
{macro_context}

## ENTRY QUALITY GUARDS
{entry_quality_guards}

## CURRENT RISK BUDGET
- System State: {system_state}
- VIX: {vix}
- Cash: {cash_pct:.1f}%
- Max position size: {max_position_pct}%
- Positions: {num_positions}/{max_positions}

## CURRENT POSITION P&L
{position_pnl}

## STRATEGY PERFORMANCE HISTORY
{strategy_performance}

## UOV SWAP CONTEXT (optional)
{uov_swap_context}

## TICKERS TO DECIDE (output exactly one decision per ticker)
{tickers_to_decide}

## CONSTRAINTS
- Max {max_positions} positions
- Min {min_position_pct}% / Max {max_position_pct}% per position
- Min {cash_floor_pct}% cash buffer
- {state_constraints}
- {pre_earnings_policy}
- You MUST include every ticker above in your decisions array. No exceptions.
