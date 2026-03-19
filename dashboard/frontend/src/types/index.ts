// API Response Types
export interface Event {
  id: number
  timestamp: string
  event_type: string
  source: string
  message: string
  metadata_json?: Record<string, any>
}

export interface Run {
  id: number
  cycle_id: string
  run_type: 'scheduled' | 'manual' | 'dry_run' | 'slack_command'
  started_at: string
  completed_at: string | null
  status: 'running' | 'completed' | 'failed'
  summary_json?: {
    num_trades?: number
    num_rejected?: number
    duration_seconds?: number
    stocks_reviewed?: number
    decisions_made?: number
    orders_placed?: number
  }
}

export interface Instrument {
  ticker: string
  name: string
  sector: string
  industry: string
  market_cap: number
  last_screened_at: string | null
  data_available: boolean
}

export interface UniverseBubbleItem extends Instrument {
  investigated: boolean
  uov_raw: number | null
  uov_z: number | null
  uov_ewma: number | null
  decision_count: number
  buy_count: number
  sell_count: number
  reduce_count: number
  hold_count: number
  hold_qty: number
  sold_qty: number
  research_calls: number
}

/** Single moderator output in committee */
export interface ModerationEntry {
  moderator: string
  verdict: string
  reasoning?: string
  growth_score?: number
  risk_score?: number
  confidence_score?: number
  consensus?: string
}

/** Full strategy LLM output */
export interface StrategyFull {
  action: string
  conviction?: number
  primary_strategy?: string
  reasoning?: string
  timestamp: string
  growth_potential?: string
  risk_level?: string
  exit_conditions?: string
  news_sentiment_summary?: string
  market_assessment?: string
  portfolio_commentary?: string
  stop_loss_pct?: number
  expected_holding_period?: string
  upside_target_pct?: number
  raw_response_json?: unknown
}

/** Full risk LLM output */
export interface RiskFull {
  verdict: string
  reasoning?: string
  adjusted_allocation_pct?: number
  triggered_rules_json?: string
  rules_checked_json?: string
  triggered_rules?: unknown
}

/** Single agentic research call made during a cycle for a ticker */
export interface ResearchCall {
  member: string
  tool_name: string
  query: string
  num_results: number | null
  provider: string | null
  cache_hit: boolean
  latency_ms: number | null
  cost_usd: number | null
  results_summary: string | null
  created_at: string | null
}

export interface InstrumentDetail extends Instrument {
  label: string | null
  last_decision: {
    cycle_id?: string
    strategy?: StrategyFull
    moderation?: ModerationEntry[] | null
    risk?: RiskFull
    research?: ResearchCall[] | null
    execution_summary?: {
      last_buy?: {
        timestamp: string
        status: string
        quantity: number
      }
      last_sell?: {
        timestamp: string
        status: string
        quantity: number
      }
    }
  } | null
}

export interface Position {
  ticker: string
  quantity: number
  value_gbp: number
  pnl_gbp: number
  pnl_pct: number
  sector: string | null
}

export interface PortfolioSnapshot {
  timestamp: string
  total_value_gbp: number
  cash_gbp: number
  invested_gbp: number
  pnl_gbp: number
  pnl_pct: number
  num_positions: number
  positions: Position[]
}

export interface Order {
  id: number
  timestamp: string
  ticker: string
  action: 'BUY' | 'SELL' | 'REDUCE'
  order_type: string
  quantity: number
  price: number | null
  limit_price?: number | null
  stop_price?: number | null
  value_gbp: number | null
  status: string
  strategy: string | null
  conviction: number | null
  t212_order_id?: string | null
  error_message?: string | null
}

// Utility function to clean ticker format for display
export function cleanTicker(ticker: string): string {
  return ticker.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '').replace(/\._/g, '.')
}
