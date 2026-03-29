import axios from 'axios'
import type {
  ChatSessionDetail,
  ChatSessionSummary,
  CommandStats,
  ExecutionQuality,
  Event,
  EvolutionArtifact,
  EvolutionDeployment,
  EvolutionPlan,
  EvolutionRequestDetail,
  EvolutionRequestSummary,
  EvolutionRun,
  Instrument,
  InstrumentDetail,
  GuidanceSnapshot,
  MacroHeadline,
  MacroState,
  MacroSummary,
  Order,
  PortfolioSnapshot,
  PortfolioHistoryStart,
  PublicGuidanceSnapshot,
  PublicMacroState,
  PublicOpportunityPreview,
  PublicPortfolioHistoryPoint,
  PublicPortfolioSnapshot,
  PublicRunSummary,
  PublicUniverseItem,
  Run,
  CycleContextSnapshot,
  SlackCommand,
  StopLossCurrent,
  StrategyChangeEpisode,
  UniverseBubbleItem,
} from '../types'
import { clearDashboardAuthRequired, setDashboardAuthRequired } from '../utils/authErrorBridge'

// Use relative paths when VITE_API_URL unset: same-origin in prod (FastAPI serves frontend)
const API_BASE_URL = import.meta.env.VITE_API_URL ?? ''

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

function isApiPath(url: string | undefined): boolean {
  return typeof url === 'string' && url.includes('/api/')
}

function isProtectedApiPath(url: string | undefined): boolean {
  if (!isApiPath(url)) return false
  return !(url?.includes('/api/public/') || url?.includes('/api/auth/'))
}

api.interceptors.response.use(
  (response) => {
    const url = response.config.url ?? ''
    if (isProtectedApiPath(url) && response.status >= 200 && response.status < 300) {
      clearDashboardAuthRequired()
    }
    return response
  },
  (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      const url = error.config?.url ?? ''
      if ((status === 401 || status === 403) && isProtectedApiPath(url)) {
        setDashboardAuthRequired(true)
      }
    }
    return Promise.reject(error)
  }
)

export interface AuthSession {
  authenticated: boolean
  username: string | null
  expires_at?: number | null
}

export const authApi = {
  me: async (): Promise<AuthSession> => {
    const response = await api.get('/api/auth/me')
    return response.data
  },
  login: async (username: string, password: string): Promise<AuthSession> => {
    const response = await api.post('/api/auth/login', { username, password })
    clearDashboardAuthRequired()
    return response.data
  },
  logout: async (): Promise<AuthSession> => {
    const response = await api.post('/api/auth/logout')
    clearDashboardAuthRequired()
    return response.data
  },
}

export const publicApi = {
  getUniverse: async (params?: { limit?: number }): Promise<PublicUniverseItem[]> => {
    const response = await api.get('/api/public/universe', { params })
    return response.data
  },
  getDailyCosts: async (params?: { days?: number }): Promise<any[]> => {
    const response = await api.get('/api/public/costs/daily', { params })
    return response.data
  },
  getMonthlyCosts: async (params?: { months?: number }): Promise<any[]> => {
    const response = await api.get('/api/public/costs/monthly', { params })
    return response.data
  },
  getPerformanceMetrics: async (): Promise<any | null> => {
    const response = await api.get('/api/public/performance/metrics')
    return response.data
  },
  getPortfolioCurrent: async (): Promise<PublicPortfolioSnapshot | null> => {
    const response = await api.get('/api/public/portfolio')
    return response.data
  },
  getPortfolioHistory: async (params?: { limit?: number }): Promise<PublicPortfolioHistoryPoint[]> => {
    const response = await api.get('/api/public/portfolio/history', { params })
    return response.data
  },
  getRuns: async (params?: { limit?: number }): Promise<PublicRunSummary[]> => {
    const response = await api.get('/api/public/runs', { params })
    return response.data
  },
  getOpportunity: async (params?: { limit?: number }): Promise<PublicOpportunityPreview[]> => {
    const response = await api.get('/api/public/opportunity', { params })
    return response.data
  },
  getMacroState: async (): Promise<PublicMacroState | null> => {
    const response = await api.get('/api/public/macro/state')
    return response.data
  },
  getMacroStateHistory: async (days = 7): Promise<PublicMacroState[]> => {
    const response = await api.get('/api/public/macro/state/history', { params: { days } })
    return response.data
  },
  getMacroHeadlines: async (days = 7, category = 'all'): Promise<MacroHeadline[]> => {
    const response = await api.get('/api/public/macro/headlines', { params: { days, category } })
    return response.data
  },
  getMacroSummary: async (): Promise<MacroSummary> => {
    const response = await api.get('/api/public/macro/summary')
    return response.data
  },
  getGuidanceLatest: async (): Promise<PublicGuidanceSnapshot | null> => {
    const response = await api.get('/api/public/insights/guidance/latest')
    return response.data
  },
  getGuidanceHistory: async (days = 14): Promise<PublicGuidanceSnapshot[]> => {
    const response = await api.get('/api/public/insights/guidance/history', { params: { days } })
    return response.data
  },
  getDoc: async (docKey: string): Promise<string> => {
    const response = await api.get(`/api/public/docs/${docKey}`, {
      responseType: 'text',
    })
    return response.data
  },
}

export const insightsApi = {
  getLatestGuidance: async (): Promise<GuidanceSnapshot | null> => {
    const response = await api.get('/api/insights/guidance/latest')
    return response.data
  },
  getGuidanceHistory: async (days = 14): Promise<GuidanceSnapshot[]> => {
    const response = await api.get('/api/insights/guidance/history', { params: { days } })
    return response.data
  },
  getGuidanceCycleImpact: async (limit = 30): Promise<CycleContextSnapshot[]> => {
    const response = await api.get('/api/insights/guidance/cycle-impact', { params: { limit } })
    return response.data
  },
  listEpisodes: async (): Promise<StrategyChangeEpisode[]> => {
    const response = await api.get('/api/insights/episodes')
    return response.data
  },
  getEpisode: async (episodeId: number): Promise<StrategyChangeEpisode> => {
    const response = await api.get(`/api/insights/episodes/${episodeId}`)
    return response.data
  },
  backfillEpisodes: async (days = 30): Promise<StrategyChangeEpisode[]> => {
    const response = await api.post('/api/insights/episodes/backfill', { days })
    return response.data
  },
  confirmEpisode: async (
    episodeId: number,
    body?: { title?: string; summary?: string; effective_start_at?: string }
  ): Promise<StrategyChangeEpisode> => {
    const response = await api.post(`/api/insights/episodes/${episodeId}/confirm`, body ?? {})
    return response.data
  },
  rejectEpisode: async (episodeId: number): Promise<StrategyChangeEpisode> => {
    const response = await api.post(`/api/insights/episodes/${episodeId}/reject`, {})
    return response.data
  },
}

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

// Conversational trading API
export const chatApi = {
  listSessions: async (params?: {
    limit?: number
    status?: string
  }): Promise<ChatSessionSummary[]> => {
    const response = await api.get('/api/chat/sessions', { params })
    return response.data
  },
  createSession: async (body?: {
    channel_type?: 'dashboard' | 'slack'
    user_id?: string
    channel_session_key?: string
    title?: string
  }): Promise<ChatSessionDetail> => {
    const response = await api.post('/api/chat/sessions', body ?? { channel_type: 'dashboard' })
    return response.data
  },
  getSession: async (sessionId: number): Promise<ChatSessionDetail> => {
    const response = await api.get(`/api/chat/sessions/${sessionId}`)
    return response.data
  },
  submitTurn: async (
    sessionId: number,
    body: {
      message_text: string
      channel_type?: 'dashboard' | 'slack'
      user_id?: string
      mode?: 'quick' | 'research' | 'committee' | 'trade'
      budget_tier?: 'standard' | 'premium'
    }
  ): Promise<ChatSessionDetail> => {
    const response = await api.post(`/api/chat/sessions/${sessionId}/turns`, body)
    return response.data
  },
  confirmAction: async (
    sessionId: number,
    actionId: number,
    body: { channel_type?: 'dashboard' | 'slack'; expected_version: number }
  ): Promise<ChatSessionDetail> => {
    const response = await api.post(
      `/api/chat/sessions/${sessionId}/actions/${actionId}/confirm`,
      body
    )
    return response.data
  },
  rejectAction: async (
    sessionId: number,
    actionId: number,
    body: { channel_type?: 'dashboard' | 'slack'; expected_version: number }
  ): Promise<ChatSessionDetail> => {
    const response = await api.post(
      `/api/chat/sessions/${sessionId}/actions/${actionId}/reject`,
      body
    )
    return response.data
  },
  endSession: async (sessionId: number): Promise<{ status: string; session_id: number }> => {
    const response = await api.post(`/api/chat/sessions/${sessionId}/end`)
    return response.data
  },
}

// Status API (includes system state for badge)
export const statusApi = {
  get: async (): Promise<{
    next_run_utc: string | null
    next_refresh_utc: string | null
    cycle_times_utc: string[]
    cycle_times_local: string[]
    refresh_times_local: string[]
    cycle_frequency: string
    schedule_mode: string
    schedule_timezone: string | null
    state?: string
    paused?: boolean
    halted_recovery_streak?: number
    halted_auto_recovery_target?: number | null
    peak_inflation_warning_note?: string | null
    last_refresh_completed_at?: string | null
    last_refresh_status?: string | null
    last_refresh_summary?: {
      orders_updated_total?: number
      positions_refreshed?: number
      market_data_tickers_warmed?: number
      stop_adjustments?: number
      deterministic_exits?: number
      duration_seconds?: number
      audit_summary?: {
        datasets_total?: number
        succeeded?: number
        failed?: number
        partial?: number
        skipped?: number
        degraded?: boolean
      } | null
    } | null
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
  listAudits: async (params?: {
    run_id?: number
    cycle_id?: string
    run_type?: string
    dataset_key?: string
    limit?: number
  }): Promise<Array<{
    id: number
    run_id: number
    cycle_id: string
    run_type: string
    dataset_key: string
    status: string
    started_at: string
    completed_at?: string | null
    source_timestamp?: string | null
    rows_before?: number | null
    rows_after?: number | null
    delta_rows?: number | null
    metadata_json?: Record<string, any> | null
    error_message?: string | null
  }>> => {
    const response = await api.get('/api/runs/audits', { params })
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
  historyStart: async (): Promise<PortfolioHistoryStart> => {
    const response = await api.get('/api/portfolio/history-start')
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
  getCurrent: async (): Promise<StopLossCurrent[]> => {
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

// Research API
export interface ResearchSummary {
  total_calls: number
  cache_hits: number
  cache_hit_rate: number
  total_cost_usd: number
  avg_latency_ms: number | null
  by_member: Record<string, { calls: number; cost_usd: number }>
  by_tool: Record<string, { calls: number; cost_usd: number }>
  by_provider: Record<string, { calls: number; cost_usd: number }>
}

export const researchApi = {
  getSummary: async (params?: { from_date?: string; to_date?: string }): Promise<ResearchSummary> => {
    const response = await api.get('/api/research/summary', { params })
    return response.data
  },
  getLogs: async (params?: {
    cycle_id?: string
    member?: string
    ticker?: string
    limit?: number
    offset?: number
  }): Promise<any[]> => {
    const response = await api.get('/api/research/logs', { params })
    return response.data
  },
  getByTicker: async (ticker: string, limit?: number): Promise<any[]> => {
    const response = await api.get(`/api/research/ticker/${ticker}`, { params: { limit } })
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
    cumul_uninvestigated_enriched: number
    cumul_uninvestigated_not_enriched: number
    investigated_1_review: number
    investigated_2_reviews: number
    investigated_3plus_reviews: number
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
  health: async (params?: {
    unresolved_window_days?: number
    reconcile_pending?: boolean
  }): Promise<{
    failed_open_count: number
    active_failed_count: number
    archived_failed_count: number
    failed_recent: Array<{
      id: number
      timestamp: string
      ticker: string
      action: string
      order_type: string
      error_message?: string | null
    }>
    archived_failed_recent: Array<{
      id: number
      timestamp: string
      ticker: string
      action: string
      order_type: string
      error_message?: string | null
    }>
    pending_local_count: number
    pending_live_count: number
    stale_pending_count: number
    reconciled_pending_count: number
    unresolved_window_days: number
    last_reconciled_at: string
    live_fetch_error?: string | null
    history_fetch_error?: string | null
    last_broker_sync_at?: string | null
    last_history_sync_at?: string | null
    last_live_pending_sync_at?: string | null
    history_fetch_error_at?: string | null
    live_fetch_error_at?: string | null
    last_refresh_completed_at?: string | null
    last_refresh_status?: string | null
    last_refresh_summary?: Record<string, any> | null
  }> => {
    const response = await api.get('/api/orders/health', { params })
    return response.data
  },
  executionQuality: async (params?: { days?: number }): Promise<ExecutionQuality> => {
    const response = await api.get('/api/orders/execution-quality', { params })
    return response.data
  },
}

// System API (state, pause, resume, reset-peak)
export const systemApi = {
  triggerRefresh: async (): Promise<{ message: string; status: string }> => {
    const response = await api.post('/api/system/trigger-refresh')
    return response.data
  },
  pause: async (): Promise<{ message: string; paused: boolean }> => {
    const response = await api.post('/api/system/pause')
    return response.data
  },
  resume: async (): Promise<{ message: string; paused: boolean }> => {
    const response = await api.post('/api/system/resume')
    return response.data
  },
  resetPeak: async (): Promise<{ message: string; state: string; current_value: number }> => {
    const response = await api.post('/api/system/reset-peak')
    return response.data
  },
  forceSell: async (ticker: string): Promise<{ status: string; ticker: string; quantity?: number; error?: string }> => {
    const response = await api.post(`/api/system/force-sell/${ticker}`)
    return response.data
  },
}

// Macro / World News API
export const macroApi = {
  state: async (): Promise<MacroState | null> => {
    const response = await api.get('/api/macro/state')
    return response.data
  },
  stateHistory: async (days = 7): Promise<MacroState[]> => {
    const response = await api.get('/api/macro/state/history', { params: { days } })
    return response.data
  },
  headlines: async (days = 7, category = 'all'): Promise<MacroHeadline[]> => {
    const response = await api.get('/api/macro/headlines', { params: { days, category } })
    return response.data
  },
  summary: async (): Promise<MacroSummary> => {
    const response = await api.get('/api/macro/summary')
    return response.data
  },
}

// Commands API (Slack trade commands)
export const commandsApi = {
  list: async (params?: {
    limit?: number
    offset?: number
    ticker?: string
    action?: string
    status?: string
  }): Promise<SlackCommand[]> => {
    const response = await api.get('/api/commands/', { params })
    return response.data
  },
  stats: async (): Promise<CommandStats> => {
    const response = await api.get('/api/commands/stats')
    return response.data
  },
}

// Evolution API (Zen Evolution Engine)
export const evolutionApi = {
  listRequests: async (params?: {
    limit?: number
    offset?: number
    status?: string
    risk_class?: string
  }): Promise<EvolutionRequestSummary[]> => {
    const response = await api.get('/api/evolution/requests', { params })
    return response.data
  },
  createRequest: async (message_text: string): Promise<EvolutionRequestDetail> => {
    const response = await api.post('/api/evolution/requests', { message_text })
    return response.data
  },
  getRequest: async (requestId: number): Promise<EvolutionRequestDetail> => {
    const response = await api.get(`/api/evolution/requests/${requestId}`)
    return response.data
  },
  getPlan: async (requestId: number): Promise<EvolutionPlan> => {
    const response = await api.get(`/api/evolution/requests/${requestId}/plan`)
    return response.data
  },
  addMessage: async (requestId: number, message_text: string): Promise<EvolutionRequestDetail> => {
    const response = await api.post(`/api/evolution/requests/${requestId}/messages`, { message_text })
    return response.data
  },
  getRuns: async (requestId: number): Promise<EvolutionRun[]> => {
    const response = await api.get(`/api/evolution/requests/${requestId}/runs`)
    return response.data
  },
  getArtifacts: async (requestId: number, artifact_type?: string): Promise<EvolutionArtifact[]> => {
    const response = await api.get(`/api/evolution/requests/${requestId}/artifacts`, { params: { artifact_type } })
    return response.data
  },
  approveBuild: async (requestId: number, notes?: string): Promise<any> => {
    const response = await api.post(`/api/evolution/requests/${requestId}/approve-build`, { notes })
    return response.data
  },
  approveDeploy: async (requestId: number, notes?: string): Promise<any> => {
    const response = await api.post(`/api/evolution/requests/${requestId}/approve-deploy`, { notes })
    return response.data
  },
  getDeployments: async (requestId: number): Promise<EvolutionDeployment[]> => {
    const response = await api.get(`/api/evolution/requests/${requestId}/deployments`)
    return response.data
  },
}

export default api
