Analyze the following data and make allocation decisions.

## CURRENT PORTFOLIO STATE
{portfolio_state}

## MARKET REGIME: {market_regime}
Interpretation: BULL = trending up (favor momentum and active buying). BEAR = risk-off (favor selective buying and patient holds over panic exits).
SIDEWAYS = mixed signals (favor factor quality, selective mean reversion, and patience).

## COMPANY PROFILES
Use these business descriptions to assess qualitative factors: competitive moats, regulatory exposure,
sector trends, and how macro news might impact each company's revenue streams.
{company_profiles}

## STRATEGY PROPOSALS
Each line: TICKER: ACTION (score: 0-100) — reasoning. Scores 80+ are very strong. Scores 65-79 are actionable when confirmed by catalyst, valuation, or other signals. Scores below 65 can still support BUY if the stock is clearly underpriced with credible upside.

### Momentum Strategy (weight: {momentum_weight})
Signals: RSI trend, MACD crossovers, relative strength vs S&P 500.
{momentum_proposals}

### Mean Reversion Strategy (weight: {mean_reversion_weight})
Signals: RSI oversold (<30), below Bollinger Band, with sound fundamentals.
{mean_reversion_proposals}

### Factor Strategy (weight: {factor_weight})
Composite: Value(30%) + Quality(30%) + Momentum(40%). V=value, Q=quality, M=momentum sub-scores.
{factor_proposals}

## ANALYST DATA (Finnhub — recommendations & insider sentiment)
Buy/hold/sell counts reflect Wall Street consensus. Insider MSPR > 0 = insiders buying (mildly bullish).
{analyst_data}

## NEWS SENTIMENT (Alpha Vantage — ticker-specific & market-wide)
Format: [Sentiment ±score] Headline (Source). Score > +0.15 = bullish. Score < -0.15 = bearish.
Use headlines to identify catalysts, risks, and market mood that numbers cannot capture.
{news_sentiment}

## PROACTIVE MACRO CONTEXT
Use this persisted macro state and action plan as top-down context for second-order impacts
on sectors and holdings. It should inform conviction and risk framing, but not override
stock-specific evidence by itself.
{macro_context}

## ENTRY QUALITY GUARDS
Use these per-ticker guardrails before proposing new BUYs. Earnings-imminent and duplicate-risk
flags are advisory, not deterministic vetoes, but they should materially influence conviction and
whether a ticker is better expressed as BUY versus HOLD/QUEUED.
{entry_quality_guards}

## CURRENT RISK BUDGET
- System State: {system_state}
- VIX: {vix} (>25 = elevated volatility, reduce position sizes; >35 = extreme, max 5%)
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
- Max 15 positions
- Min 2% / Max {max_position_pct}% per position
- Min 10% cash buffer
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
