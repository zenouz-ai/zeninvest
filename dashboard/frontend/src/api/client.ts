import axios from 'axios'
import type { Event, Run, Instrument, InstrumentDetail, PortfolioSnapshot, Order, UniverseBubbleItem } from '../types'

// Use relative paths when VITE_API_URL unset: same-origin in prod (FastAPI serves frontend)
const API_BASE_URL = import.meta.env.VITE_API_URL ?? ''

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Events API
export const eventsApi = {
  list: async (params?: {
    limit?: number
    offset?: number
    event_type?: string
    source?: string
    start_date?: string
    end_date?: string
  }): Promise<Event[]> => {
    const response = await api.get('/api/events/', { params })
    return response.data
  },
  
  getById: async (id: number): Promise<Event> => {
    const response = await api.get(`/api/events/${id}`)
    return response.data
  },
}

// Status API (includes system state for badge)
export const statusApi = {
  get: async (): Promise<{
    next_run_utc: string | null
    cycle_times_utc: string[]
    cycle_frequency: string
    state?: string
    paused?: boolean
  }> => {
    const response = await api.get('/api/status/')
    return response.data
  },
}

// Runs API
export const runsApi = {
  triggerDryRun: async (): Promise<{ message: string; status: string }> => {
    const response = await api.post('/api/runs/trigger')
    return response.data
  },
  triggerLiveRun: async (): Promise<{ message: string; status: string }> => {
    const response = await api.post('/api/runs/trigger-live')
    return response.data
  },
  list: async (params?: {
    limit?: number
    offset?: number
    run_type?: string
    status?: string
  }): Promise<Run[]> => {
    const response = await api.get('/api/runs/', { params })
    return response.data
  },
  
  getById: async (id: number): Promise<Run> => {
    const response = await api.get(`/api/runs/${id}`)
    return response.data
  },
  
  getByCycleId: async (cycleId: string): Promise<Run | null> => {
    try {
      const response = await api.get(`/api/runs/cycle/${cycleId}`)
      return response.data
    } catch (err: any) {
      if (err?.response?.status === 404) return null
      throw err
    }
  },
  getDiff: async (
    fromCycleId: string,
    toCycleId: string
  ): Promise<{
    from_cycle_id: string
    to_cycle_id: string
    new_positions: string[]
    closed_positions: string[]
    size_changes: { ticker: string; from_qty: number; to_qty: number }[]
  }> => {
    const response = await api.get('/api/runs/diff', {
      params: { from_cycle_id: fromCycleId, to_cycle_id: toCycleId },
    })
    return response.data
  },
}

// Universe API
export const universeApi = {
  list: async (params?: {
    limit?: number
    offset?: number
    sector?: string
    search?: string
  }): Promise<Instrument[]> => {
    const response = await api.get('/api/universe/', { params })
    return response.data
  },
  
  getByTicker: async (ticker: string): Promise<InstrumentDetail> => {
    const response = await api.get(`/api/universe/${ticker}`)
    return response.data
  },

  getBubble: async (params?: { limit?: number }): Promise<UniverseBubbleItem[]> => {
    const response = await api.get('/api/universe/bubble', { params: params ?? { limit: 1000 } })
    return response.data
  },
}

// Portfolio API
export const portfolioApi = {
  current: async (): Promise<PortfolioSnapshot | null> => {
    try {
      const response = await api.get('/api/portfolio/')
      return response.data
    } catch (err: any) {
      if (err?.response?.status === 404) return null
      throw err
    }
  },
  
  history: async (params?: {
    limit?: number
    offset?: number
    start_date?: string
    end_date?: string
  }): Promise<PortfolioSnapshot[]> => {
    const response = await api.get('/api/portfolio/history', { params })
    return response.data
  },
}

// Opportunity API
export const opportunityApi = {
  listScores: async (params?: { limit?: number; offset?: number; cycle_id?: string; ticker?: string }): Promise<any[]> => {
    const response = await api.get('/api/opportunity/scores/', { params })
    return response.data
  },
  getScoresByCycle: async (cycleId: string): Promise<any[]> => {
    const response = await api.get(`/api/opportunity/scores/${cycleId}`)
    return response.data
  },
  getQueue: async (): Promise<any[]> => {
    const response = await api.get('/api/opportunity/queue/')
    return response.data
  },
  getConfig: async (): Promise<{ queue_ttl_cycles: number; immediate_threshold_z: number }> => {
    const response = await api.get('/api/opportunity/config/')
    return response.data
  },
  getHistoryByTicker: async (ticker: string, params?: { limit?: number; offset?: number }): Promise<any[]> => {
    const response = await api.get(`/api/opportunity/history/${ticker}`, { params })
    return response.data
  },
}

// Outcomes API
export const outcomesApi = {
  list: async (params?: { limit?: number; offset?: number; ticker?: string }): Promise<any[]> => {
    const response = await api.get('/api/outcomes/', { params })
    return response.data
  },
  getStats: async (): Promise<{ total_trades: number; win_rate_pct: number; avg_pnl_pct: number; avg_holding_days: number; best_trade_pct: number | null; worst_trade_pct: number | null }> => {
    const response = await api.get('/api/outcomes/stats')
    return response.data
  },
}

// Stop-loss API
export const stopLossApi = {
  getCurrent: async (): Promise<{ ticker: string; stop_price: number | null; source: string }[]> => {
    const response = await api.get('/api/stop-loss/current')
    return response.data
  },
  getAdjustments: async (params?: { limit?: number; offset?: number; ticker?: string }): Promise<any[]> => {
    const response = await api.get('/api/stop-loss/adjustments', { params })
    return response.data
  },
}

// Performance API
export const performanceApi = {
  getMetrics: async (): Promise<any | null> => {
    const response = await api.get('/api/performance/metrics')
    return response.data
  },
  getHistory: async (params?: { limit?: number; offset?: number }): Promise<any[]> => {
    const response = await api.get('/api/performance/history', { params })
    return response.data
  },
}

// Costs API
export const costsApi = {
  getDaily: async (params?: { days?: number }): Promise<any[]> => {
    const response = await api.get('/api/costs/daily', { params })
    return response.data
  },
  getMonthly: async (params?: { months?: number }): Promise<any[]> => {
    const response = await api.get('/api/costs/monthly', { params })
    return response.data
  },
  getForCycle: async (cycleId: string): Promise<{ cycle_id: string; total_gbp: number; by_provider: Record<string, number> }> => {
    const response = await api.get('/api/costs/for-cycle', { params: { cycle_id: cycleId } })
    return response.data
  },
  getDegradation: async (): Promise<{ level: string; message?: string }> => {
    const response = await api.get('/api/costs/degradation')
    return response.data
  },
}

// Dashboard API (monthly summary, run feed)
export const dashboardApi = {
  getMonthlySummary: async (year: number, month: number): Promise<{
    year: number
    month: number
    year_month: string
    runs_count: number
    cost_gbp: number
    llm_cost_gbp: number
    api_cost_gbp: number
    portfolio_start_gbp: number | null
    portfolio_end_gbp: number | null
    pnl_gbp: number | null
    cumul_screened: number
    cumul_investigated: number
    cumul_uninvestigated: number
    cumul_orders: number
    new_investigated_this_month: number
  }> => {
    const response = await api.get('/api/dashboard/monthly-summary', { params: { year, month } })
    return response.data
  },
  getRunFeed: async (params?: { limit?: number }): Promise<Array<{
    run: Run
    decisions: Array<{
      id: number
      cycle_id: string
      ticker: string
      action: string
      conviction: number | null
      reasoning: string | null
      primary_strategy: string | null
      [key: string]: unknown
    }>
    orders: Order[]
  }>> => {
    const response = await api.get('/api/dashboard/run-feed', { params: params ?? { limit: 20 } })
    return response.data
  },
}

// Orders API
export const ordersApi = {
  list: async (params?: {
    limit?: number
    offset?: number
    ticker?: string
    status?: string
    cycle_id?: string
  }): Promise<Order[]> => {
    const response = await api.get('/api/orders/', { params })
    return response.data
  },
  
  getById: async (id: number): Promise<Order> => {
    const response = await api.get(`/api/orders/${id}`)
    return response.data
  },
}

// System API (state, pause, resume, reset-peak)
export const systemApi = {
  resetPeak: async (): Promise<{ message: string; state: string; current_value: number }> => {
    const response = await api.post('/api/system/reset-peak')
    return response.data
  },
}

export default api
