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

export interface PortfolioSnapshot {
  id: number
  snapshot_date: string
  total_value: number
  cash_balance: number
  positions_json: Record<string, {
    ticker: string
    quantity: number
    avg_price: number
    current_price: number
    value: number
    pnl: number
    pnl_pct: number
  }>
}

export interface Order {
  id: number
  ticker: string
  action: 'BUY' | 'SELL' | 'REDUCE'
  quantity: number
  price: number | null
  status: 'filled' | 'pending' | 'failed' | 'dry_run'
  filled_at: string | null
  cycle_id: string
  dry_run: boolean
}

// Utility function to clean ticker format for display
export function cleanTicker(ticker: string): string {
  return ticker.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '').replace(/\._/g, '.')
}
