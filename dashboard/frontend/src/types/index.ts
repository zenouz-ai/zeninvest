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
  value_gbp: number | null
  status: string
  strategy: string | null
  conviction: number | null
}

// Utility function to clean ticker format for display
export function cleanTicker(ticker: string): string {
  return ticker.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '').replace(/\._/g, '.')
}
