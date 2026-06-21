Analyze the following data and make allocation decisions. Weigh whatever is decision-relevant; the section notes are orientation, not rules.

## CURRENT PORTFOLIO STATE
{portfolio_state}

## MARKET REGIME: {market_regime}
BULL favors momentum and active buying; BEAR favors selective buying and patient holds over panic exits; SIDEWAYS favors factor quality and patience.

## COMPANY PROFILES
Business descriptions for qualitative judgment (moats, regulatory exposure, sector trends, macro sensitivity).
{company_profiles}

## STRATEGY PROPOSALS
Each line: TICKER: ACTION (score 0-100) — reasoning. Treat scores as evidence strength, not thresholds.

### Momentum (weight: {momentum_weight})
RSI trend, MACD crossovers, relative strength vs S&P 500.
{momentum_proposals}

### Mean Reversion (weight: {mean_reversion_weight})
RSI oversold, below Bollinger Band, with sound fundamentals.
{mean_reversion_proposals}

### Factor (weight: {factor_weight})
Composite of Value, Quality, and Momentum sub-scores.
{factor_proposals}

## ANALYST DATA (Finnhub — recommendations & insider sentiment)
{analyst_data}

## NEWS SENTIMENT (Alpha Vantage — ticker-specific & market-wide)
Use headlines to identify catalysts, risks, and mood the numbers miss.
{news_sentiment}

## PROACTIVE MACRO CONTEXT
Top-down context for second-order impacts on sectors and holdings; it informs framing but should not override stock-specific evidence.
{macro_context}

## ENTRY QUALITY GUARDS
Per-ticker advisory flags (earnings-imminent, duplicate-risk). They weigh on conviction and BUY-vs-HOLD/QUEUED framing, not hard vetoes.
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

## UOV SWAP CONTEXT (optional, from prior cycles)
{uov_swap_context}

## TICKERS TO DECIDE (output exactly one decision per ticker)
{tickers_to_decide}

## CONSTRAINTS
- Max {max_positions} positions (a broad, well-diversified book is expected; do not artificially cap entries below this)
- Min {min_position_pct}% / Max {max_position_pct}% per position
- Min {cash_floor_pct}% cash buffer
- {state_constraints}
- {pre_earnings_policy}
- You MUST include every ticker above in your decisions array. No exceptions.

Respond with this exact JSON structure:
{{
  "market_assessment": "2-3 sentence market regime with news sentiment context",
  "decisions": [
    {{
      "ticker": "TICKER_ID",
      "action": "BUY|SELL|HOLD|REDUCE|QUEUED",
      "target_allocation_pct": 5.0,
      "conviction": 78,
      "primary_strategy": "momentum|mean_reversion|factor",
      "reasoning": "3-5 sentence rationale referencing specific signals, news, and analyst data",
      "growth_potential": "HIGH|MEDIUM|LOW",
      "risk_level": "HIGH|MEDIUM|LOW",
      "catalysts": ["list of expected catalysts from news and analyst data"],
      "risks": ["list of key risks from news and contrarian signals"],
      "exit_conditions": "specific conditions for selling",
      "exit_trigger_type": "none|gain_realization|hard_exit|profit_trim",
      "upside_target_pct": 15.0,
      "stop_loss_pct": -8.0,
      "entry_type": "market",
      "expected_holding_period": "5-30 trading days",
      "news_sentiment_summary": "1-sentence summary of current news mood for this ticker"
    }}
  ],
  "portfolio_commentary": "overall positioning rationale"
}}
