import React, { useEffect, useState, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { runsApi, portfolioApi, eventsApi, statusApi, costsApi, dashboardApi, ordersApi, universeApi, systemApi, performanceApi, macroApi } from '../api/client'
import type { Run, PortfolioSnapshot, Event, Order, InstrumentDetail, MacroSummary } from '../types'
import { safeFormat } from '../utils/date'
import { cleanTicker } from '../types'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'
import { DashboardSkeleton } from '../components/Skeleton'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { useAsyncData } from '../hooks/useAsyncData'
import { FreshnessIndicator } from '../components/FreshnessIndicator'
import type { SseConnectionState } from '../hooks/useSSE'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { PnlCurrency, PnlValue } from '../components/PnlDisplay'

function formatCountdown(isoString: string): string {
  const target = new Date(isoString)
  const now = new Date()
  const diffMs = target.getTime() - now.getTime()
  if (diffMs <= 0) return '—'
  const h = Math.floor(diffMs / 3600000)
  const m = Math.floor((diffMs % 3600000) / 60000)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

type RunFeedEntry = {
  run: Run
  decisions: Array<{ id: number; cycle_id: string; ticker: string; action: string; conviction: number | null; reasoning: string | null; primary_strategy: string | null; [key: string]: unknown }>
  orders: Order[]
}

type MonthlySummary = {
  runs_count: number
  cost_gbp: number
  llm_cost_gbp: number
  api_cost_gbp: number
  portfolio_start_gbp: number | null
  portfolio_end_gbp: number | null
  pnl_gbp: number | null
  new_investigated_this_month?: number
  cumul_screened?: number
  cumul_investigated?: number
  cumul_uninvestigated?: number
  cumul_uninvestigated_enriched?: number
  cumul_uninvestigated_not_enriched?: number
  investigated_1_review?: number
  investigated_2_reviews?: number
  investigated_3plus_reviews?: number
  cumul_orders?: number
}

/** Small inline error + retry for a section */
function SectionError({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-loss">{error}</span>
      <button type="button" onClick={onRetry} className="text-accent hover:underline text-xs">Retry</button>
    </div>
  )
}

interface DashboardProps {
  sseEvents: Event[]
  sseConnectionState: SseConnectionState
}

export default function Dashboard({ sseEvents, sseConnectionState }: DashboardProps) {
  const recentActivityLimit = 100

  // --- Independent data sections ---
  const fetchStatus = useCallback(() => statusApi.get(), [])
  const statusResult = useAsyncData(fetchStatus)

  const fetchPortfolio = useCallback(() => portfolioApi.current(), [])
  const portfolioResult = useAsyncData<PortfolioSnapshot | null>(fetchPortfolio)

  const fetchLatestRun = useCallback(async () => {
    const runs = await runsApi.list({ limit: 1 })
    return runs[0] || null
  }, [])
  const latestRunResult = useAsyncData<Run | null>(fetchLatestRun)

  const fetchPerformance = useCallback(() => performanceApi.getMetrics(), [])
  const perfResult = useAsyncData(fetchPerformance)

  const now = useMemo(() => new Date(), [])
  const currentYear = now.getUTCFullYear()
  const currentMonth = now.getUTCMonth() + 1
  const fetchMonthly = useCallback(() => dashboardApi.getMonthlySummary(currentYear, currentMonth), [currentYear, currentMonth])
  const monthlyResult = useAsyncData<MonthlySummary>(fetchMonthly)

  const fetchEvents = useCallback(() => eventsApi.list({ limit: 200 }), [])
  const historicalEventsResult = useAsyncData<Event[]>(fetchEvents)

  const fetchOrders = useCallback(() => ordersApi.list({ limit: 15 }), [])
  const ordersResult = useAsyncData<Order[]>(fetchOrders)

  const fetchRunFeed = useCallback(() => dashboardApi.getRunFeed({ limit: 15 }), [])
  const runFeedResult = useAsyncData<RunFeedEntry[]>(fetchRunFeed)

  const fetchMacroSummary = useCallback(() => macroApi.summary().catch(() => null), [])
  const macroResult = useAsyncData<MacroSummary | null>(fetchMacroSummary)

  const fetchDailyCosts = useCallback(async () => {
    const raw = await costsApi.getDaily({ days: 31 })
    return (raw || []).map((d: { date: string; llm_cost_gbp?: number; api_cost_gbp?: number; total_gbp?: number }) => {
      const llm = d.llm_cost_gbp ?? d.total_gbp ?? 0
      const apiCost = d.api_cost_gbp ?? 0
      return { date: d.date, llm_cost_gbp: llm, api_cost_gbp: apiCost, total_gbp: llm + apiCost }
    })
  }, [])
  const dailyCostsResult = useAsyncData(fetchDailyCosts)

  // --- Derived data ---
  const status = statusResult.data
  const systemState = status?.state ?? 'ACTIVE'
  const paused = status?.paused ?? false
  const nextRunUtc = status?.next_run_utc ?? null
  const portfolio = portfolioResult.data
  const latestRun = latestRunResult.data
  const latestRunReviewedCount = useMemo(() => {
    const summary = latestRun?.summary_json
    if (!summary) return null
    if (summary.stocks_reviewed != null) return summary.stocks_reviewed
    if (summary.decisions_made != null) return summary.decisions_made
    if (summary.num_trades != null || summary.num_rejected != null) {
      return (summary.num_trades ?? 0) + (summary.num_rejected ?? 0)
    }
    return null
  }, [latestRun?.summary_json])
  const latestRunScreenedCount = useMemo(() => {
    const summary = latestRun?.summary_json
    if (!summary) return null
    if (summary.stocks_screened != null) return summary.stocks_screened
    return null
  }, [latestRun?.summary_json])
  const monthlySummary = monthlyResult.data
  const latestOrders = ordersResult.data ?? []
  const runFeed = runFeedResult.data ?? []
  const dailyCosts = dailyCostsResult.data ?? []
  const perf = perfResult.data

  // Last run cost (depends on latestRun)
  const [lastRunCost, setLastRunCost] = useState<{ total_gbp: number } | null>(null)
  useEffect(() => {
    if (!latestRun?.cycle_id) { setLastRunCost(null); return }
    costsApi.getForCycle(latestRun.cycle_id).then(setLastRunCost).catch(() => setLastRunCost(null))
  }, [latestRun?.cycle_id])

  // Countdown (auto-update every 10s)
  const [countdownStr, setCountdownStr] = useState('—')
  useEffect(() => {
    const update = () => setCountdownStr(nextRunUtc ? formatCountdown(nextRunUtc) : '—')
    update()
    const interval = setInterval(update, 10_000)
    return () => clearInterval(interval)
  }, [nextRunUtc])

  // Merge SSE + historical events
  const events = useMemo(() => {
    const historical = historicalEventsResult.data ?? []
    const seen = new Set(sseEvents.map((e) => e.id))
    const fromHistory = historical.filter((e) => !seen.has(e.id))
    return [...sseEvents, ...fromHistory].slice(0, 200)
  }, [sseEvents, historicalEventsResult.data])

  // LLM detail for expanded trade row
  const [tickerForLLM, setTickerForLLM] = useState<string | null>(null)
  const [tickerDetail, setTickerDetail] = useState<InstrumentDetail | null>(null)
  useEffect(() => {
    if (!tickerForLLM) { setTickerDetail(null); return }
    universeApi.getByTicker(tickerForLLM).then(setTickerDetail).catch(() => setTickerDetail(null))
  }, [tickerForLLM])

  // UI state
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null)
  const [dailyCostExpanded, setDailyCostExpanded] = useState(false)
  const [latestTradesExpanded, setLatestTradesExpanded] = useState(false)
  const [runSummariesExpanded, setRunSummariesExpanded] = useState(false)
  const [latestTradesFilters, setLatestTradesFilters] = useState({ ticker: '', action: '', status: '' })
  const [triggerLoading, setTriggerLoading] = useState<'dry' | 'live' | null>(null)
  const [resetPeakLoading, setResetPeakLoading] = useState(false)
  const [showResetPeakConfirm, setShowResetPeakConfirm] = useState(false)
  const [showLiveConfirm, setShowLiveConfirm] = useState(false)
  const [showPauseConfirm, setShowPauseConfirm] = useState(false)
  const [pauseLoading, setPauseLoading] = useState(false)

  // Focus traps for modals
  const liveConfirmRef = useFocusTrap(showLiveConfirm, () => setShowLiveConfirm(false))
  const resetPeakRef = useFocusTrap(showResetPeakConfirm, () => setShowResetPeakConfirm(false))
  const pauseConfirmRef = useFocusTrap(showPauseConfirm, () => setShowPauseConfirm(false))

  const filteredLatestOrders = useMemo(() => {
    const { ticker, action, status } = latestTradesFilters
    return latestOrders.filter((o) => {
      if (ticker && !cleanTicker(o.ticker).toLowerCase().includes(ticker.toLowerCase())) return false
      if (action && o.action !== action) return false
      if (status && o.status !== status) return false
      return true
    })
  }, [latestOrders, latestTradesFilters])

  // Positions sorted by absolute P&L for home display
  const topPositions = useMemo(() => {
    const positions = portfolio?.positions ?? []
    return [...positions].sort((a, b) => Math.abs(b.pnl_gbp) - Math.abs(a.pnl_gbp)).slice(0, 5)
  }, [portfolio])

  // --- Action handlers ---
  const handleDryRun = async () => {
    setTriggerLoading('dry')
    try { await runsApi.triggerDryRun() } catch (e) { console.error('Dry run trigger failed:', e) }
    finally { setTriggerLoading(null) }
  }

  const handleLiveRun = async () => {
    setShowLiveConfirm(false)
    setTriggerLoading('live')
    try { await runsApi.triggerLiveRun() } catch (e) { console.error('Live run trigger failed:', e) }
    finally { setTriggerLoading(null) }
  }

  const handleResetPeak = async () => {
    setResetPeakLoading(true)
    try {
      await systemApi.resetPeak()
      setShowResetPeakConfirm(false)
      statusResult.refetch()
    } catch (e) { console.error('Reset peak failed:', e) }
    finally { setResetPeakLoading(false) }
  }

  const handlePauseResume = async () => {
    setShowPauseConfirm(false)
    setPauseLoading(true)
    try {
      if (paused) { await systemApi.resume() } else { await systemApi.pause() }
      statusResult.refetch()
    } catch (e) { console.error('Pause/resume failed:', e) }
    finally { setPauseLoading(false) }
  }

  // --- Event rendering helpers ---
  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case 'run_started': return '▶'
      case 'run_completed': return '✓'
      case 'decision_made': return '⚡'
      case 'order_placed': return '📝'
      case 'order_executed': return '✅'
      case 'universe_updated': return '🌐'
      case 'notification_sent': return '📧'
      default: return '•'
    }
  }

  const getEventColor = (eventType: string) => {
    switch (eventType) {
      case 'run_started': return 'text-neutral'
      case 'run_completed': return 'text-gain'
      case 'decision_made': return 'text-accent'
      case 'order_executed': return 'text-gain'
      case 'order_placed': return 'text-neutral'
      default: return 'text-terminal-text-dim'
    }
  }

  // Badge colours — PAUSED gets its own distinct colour (IA-5, VD-2)
  const stateBadgeColor = paused
    ? 'bg-accent'
    : systemState === 'HALTED' ? 'bg-loss' : systemState === 'CAUTIOUS' ? 'bg-warning' : 'bg-gain'
  const stateBadgeText = paused ? 'PAUSED' : systemState

  // Check if ALL critical sections are still loading
  const allLoading = statusResult.loading && portfolioResult.loading && latestRunResult.loading

  if (allLoading) {
    return <DashboardSkeleton />
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="Dashboard"
        title="ZenInvest Agent"
        description="System health, positions, and recent activity at a glance."
      />

      {/* System state badge + controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`inline-flex items-center px-3 py-1 rounded font-mono text-sm font-semibold text-terminal-bg ${stateBadgeColor}`}>
          {stateBadgeText}
        </span>
        {/* SSE indicator — small dot, not a full card */}
        <span
          className="flex items-center gap-1.5 text-xs text-terminal-text-dim"
          title={
            sseConnectionState === 'open'
              ? 'Event stream connected'
              : sseConnectionState === 'connecting'
                ? 'Event stream connecting…'
                : 'Event stream disconnected'
          }
        >
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              sseConnectionState === 'open' ? 'bg-gain' : sseConnectionState === 'connecting' ? 'bg-warning' : 'bg-loss'
            }`}
          />
          SSE
        </span>
        {/* Pause/Resume toggle */}
        <button
          type="button"
          onClick={paused ? handlePauseResume : () => setShowPauseConfirm(true)}
          disabled={pauseLoading}
          className="btn-secondary text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {pauseLoading ? '...' : paused ? 'Resume' : 'Pause'}
        </button>
        {systemState === 'CAUTIOUS' && (
          <button
            type="button"
            onClick={() => setShowResetPeakConfirm(true)}
            disabled={resetPeakLoading}
            className="btn-secondary text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {resetPeakLoading ? 'Resetting...' : 'Reset Peak'}
          </button>
        )}
        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={handleDryRun}
            disabled={triggerLoading != null}
            className="btn-secondary text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {triggerLoading === 'dry' ? 'Starting...' : 'Dry Run'}
          </button>
          <button
            type="button"
            onClick={() => setShowLiveConfirm(true)}
            disabled={triggerLoading != null || paused}
            className="btn-danger text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {triggerLoading === 'live' ? 'Starting...' : 'Live Run'}
          </button>
        </div>
      </div>

      {/* Confirmation modals */}
      {showLiveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowLiveConfirm(false)}>
          <div ref={liveConfirmRef} className="bg-terminal-surface border border-terminal-border rounded-lg p-4 max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-loss mb-2">Execute live cycle?</h3>
            <p className="text-sm text-terminal-text-dim mb-4">This will run a full cycle and execute real trades on the Trading 212 Practice account.</p>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowLiveConfirm(false)} className="btn-secondary text-sm py-1.5">Cancel</button>
              <button type="button" onClick={handleLiveRun} className="btn-danger-solid text-sm py-1.5">Run live</button>
            </div>
          </div>
        </div>
      )}
      {showResetPeakConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowResetPeakConfirm(false)}>
          <div ref={resetPeakRef} className="bg-terminal-surface border border-terminal-border rounded-lg p-4 max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-accent mb-2">Reset peak?</h3>
            <p className="text-sm text-terminal-text-dim mb-4">Sets peak portfolio value to current value and transitions to ACTIVE. Use when CAUTIOUS was triggered incorrectly.</p>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowResetPeakConfirm(false)} className="btn-secondary text-sm py-1.5">Cancel</button>
              <button type="button" onClick={handleResetPeak} disabled={resetPeakLoading} className="btn-secondary text-sm py-1.5 disabled:opacity-50">{resetPeakLoading ? 'Resetting...' : 'Reset'}</button>
            </div>
          </div>
        </div>
      )}
      {showPauseConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowPauseConfirm(false)}>
          <div ref={pauseConfirmRef} className="bg-terminal-surface border border-terminal-border rounded-lg p-4 max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-warning mb-2">Pause trading?</h3>
            <p className="text-sm text-terminal-text-dim mb-4">The agent will skip trading during scheduled cycles until resumed. Existing positions and stop-losses remain active.</p>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowPauseConfirm(false)} className="btn-secondary text-sm py-1.5">Cancel</button>
              <button type="button" onClick={handlePauseResume} className="btn-secondary text-sm py-1.5">Pause</button>
            </div>
          </div>
        </div>
      )}

      {/* Top bar — 4 cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Cycle timing (merged Next + Last + trades) */}
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Next Cycle</div>
          <div className="text-xl font-mono font-bold">{countdownStr}</div>
          {nextRunUtc && <div className="text-xs text-terminal-text-dim mt-0.5">{safeFormat(nextRunUtc, 'MMM dd, HH:mm', '')} UTC</div>}
          <div className="border-t border-terminal-border mt-2 pt-2">
            <div className="text-xs text-terminal-text-dim">Last run</div>
            <div className="text-sm font-mono">
              {latestRun ? safeFormat(latestRun.started_at, 'MMM dd, HH:mm', '—') : 'Never'}
              {latestRun && (
                <span className={`ml-2 ${latestRun.status === 'completed' ? 'text-gain' : latestRun.status === 'running' ? 'text-accent' : 'text-loss'}`}>
                  {latestRun.status}
                </span>
              )}
            </div>
            {lastRunCost != null && <div className="text-xs text-terminal-text-dim">Cost: £{lastRunCost.total_gbp.toFixed(4)}</div>}
          </div>
          {latestRunResult.error && <SectionError error="Failed to load" onRetry={latestRunResult.refetch} />}
        </div>

        {/* Card 2: Portfolio Value */}
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Portfolio Value</div>
          {portfolioResult.loading ? (
            <div className="text-lg font-mono text-terminal-text-dim">Loading...</div>
          ) : portfolio ? (
            <>
              <div className="text-xl font-mono font-bold">
                £{portfolio.total_value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-xs mt-1">
                <PnlCurrency value={portfolio.pnl_gbp} className="font-mono" /> <PnlValue value={portfolio.pnl_pct} suffix="%" className="font-mono" />
              </div>
              <div className="text-xs text-terminal-text-dim mt-0.5">{portfolio.num_positions} positions · £{portfolio.cash_gbp.toFixed(0)} cash</div>
            </>
          ) : (
            <div className="text-lg font-mono">N/A</div>
          )}
          {portfolioResult.error && <SectionError error="Failed to load" onRetry={portfolioResult.refetch} />}
          <FreshnessIndicator lastUpdatedAt={portfolioResult.lastUpdatedAt} isStale={portfolioResult.isStale} className="mt-1 block" />
        </div>

        {/* Card 3: Performance (replaces SSE card) */}
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Performance (30d)</div>
          {perfResult.loading ? (
            <div className="text-lg font-mono text-terminal-text-dim">Loading...</div>
          ) : perf ? (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-1">
                <div>
                  <div className="text-xs text-terminal-text-dim">Sharpe</div>
                  <div className="font-mono text-sm">{perf.sharpe_30d != null ? perf.sharpe_30d.toFixed(2) : '—'}</div>
                </div>
                <div>
                  <div className="text-xs text-terminal-text-dim">Win rate</div>
                  <div className="font-mono text-sm">{perf.win_rate_pct != null ? `${perf.win_rate_pct.toFixed(0)}%` : '—'}</div>
                </div>
                <div>
                  <div className="text-xs text-terminal-text-dim">Max DD</div>
                  <div className="font-mono text-sm text-loss">{perf.max_drawdown_pct != null ? `${perf.max_drawdown_pct.toFixed(1)}%` : '—'}</div>
                </div>
                <div>
                  <div className="text-xs text-terminal-text-dim">Trades</div>
                  <div className="font-mono text-sm">{perf.num_trades ?? '—'}</div>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-terminal-text-dim mt-1">No performance data yet</div>
          )}
          {perfResult.error && <SectionError error="Failed to load" onRetry={perfResult.refetch} />}
          <FreshnessIndicator lastUpdatedAt={perfResult.lastUpdatedAt} isStale={perfResult.isStale} className="mt-1 block" />
        </div>

        {/* Card 4: This month summary (compact) */}
        <div className="card">
          <div className="text-sm text-terminal-text-dim">This Month</div>
          {monthlyResult.loading ? (
            <div className="text-lg font-mono text-terminal-text-dim">Loading...</div>
          ) : monthlySummary ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-1">
              <div>
                <div className="text-xs text-terminal-text-dim">Runs</div>
                <div className="font-mono text-sm">{monthlySummary.runs_count}</div>
              </div>
              <div>
                <div className="text-xs text-terminal-text-dim">Cost</div>
                <div className="font-mono text-sm">£{monthlySummary.cost_gbp.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-xs text-terminal-text-dim">P&L</div>
                <div className="font-mono text-sm">
                  {monthlySummary.pnl_gbp != null ? <PnlCurrency value={monthlySummary.pnl_gbp} /> : '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-terminal-text-dim">Investigated</div>
                <div className="font-mono text-sm">{monthlySummary.new_investigated_this_month ?? '—'}</div>
              </div>
            </div>
          ) : (
            <div className="text-sm text-terminal-text-dim mt-1">No data</div>
          )}
          {monthlyResult.error && <SectionError error="Failed to load" onRetry={monthlyResult.refetch} />}
          <FreshnessIndicator lastUpdatedAt={monthlyResult.lastUpdatedAt} isStale={monthlyResult.isStale} className="mt-1 block" />
        </div>
      </div>

      {/* Macro conditions bar */}
      {macroResult.data && macroResult.data.regime && (
        <div className="card flex items-center gap-4 flex-wrap text-sm">
          <span className="text-xs uppercase tracking-wider text-terminal-text-dim">Macro</span>
          <span className={`pill ${macroResult.data.regime === 'RISK_ON' ? 'pill-emerald' : macroResult.data.regime === 'RISK_OFF' ? 'pill-loss' : 'pill-dim'}`}>
            {macroResult.data.regime === 'RISK_ON' ? 'Risk On' : macroResult.data.regime === 'RISK_OFF' ? 'Risk Off' : 'Neutral'}
          </span>
          {macroResult.data.confidence_score != null && (
            <span className="font-mono text-terminal-text">{Math.round(macroResult.data.confidence_score * 100)}% conf</span>
          )}
          {macroResult.data.top_signal && (
            <span className="text-terminal-text-dim truncate max-w-xs">{macroResult.data.top_signal}</span>
          )}
          {macroResult.data.headline_count_7d > 0 && (
            <span className="text-terminal-text-dim">{macroResult.data.headline_count_7d} headlines (7d)</span>
          )}
          <Link to="/world-news" className="text-xs text-accent hover:underline ml-auto">View World News &rarr;</Link>
        </div>
      )}

      {/* Last cycle summary — always visible (WF-3) */}
      {latestRun && (
        <div className="card bg-terminal-surface/60">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="font-mono text-accent">{latestRun.cycle_id}</span>
            <span className="text-terminal-text-dim">{safeFormat(latestRun.started_at, 'MMM dd, HH:mm', '')} UTC</span>
            <span className={latestRun.status === 'completed' ? 'text-gain' : latestRun.status === 'running' ? 'text-accent' : 'text-loss'}>
              {latestRun.status}
            </span>
            {latestRun.summary_json && (
              <>
                <span className="text-terminal-text-dim">·</span>
                {latestRunScreenedCount != null && (
                  <>
                    <span>{latestRunScreenedCount} screened</span>
                    <span className="text-terminal-text-dim">·</span>
                  </>
                )}
                <span>{latestRunReviewedCount ?? 0} reviewed</span>
                <span className="text-terminal-text-dim">·</span>
                <span>{latestRun.summary_json.num_trades ?? 0} trades</span>
                <span className="text-terminal-text-dim">·</span>
                <span>{latestRun.summary_json.num_rejected ?? 0} rejected</span>
                {latestRun.summary_json.duration_seconds != null && (
                  <>
                    <span className="text-terminal-text-dim">·</span>
                    <span>{Math.round(latestRun.summary_json.duration_seconds)}s</span>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Two-column layout: Positions + Activity on left, Stats on right */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Left column */}
        <div className="space-y-6">
          {/* Positions snapshot — always visible (IA-2) */}
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold tracking-wide">Positions</h2>
              <Link to="/portfolio" className="text-xs text-accent hover:underline">View all</Link>
            </div>
            {portfolioResult.loading ? (
              <div className="text-terminal-text-dim text-sm py-4">Loading positions...</div>
            ) : topPositions.length === 0 ? (
              <div className="text-terminal-text-dim text-sm py-4">No open positions</div>
            ) : (
              <div className="space-y-2">
                {topPositions.map((pos) => {
                  const maxAbsPnl = Math.max(...topPositions.map((p) => Math.abs(p.pnl_gbp)), 1)
                  const barWidth = Math.min(Math.abs(pos.pnl_gbp) / maxAbsPnl * 100, 100)
                  return (
                    <div key={pos.ticker} className="flex items-center gap-3">
                      <span className="font-mono font-semibold w-16 text-sm">{cleanTicker(pos.ticker)}</span>
                      <div className="flex-1 h-5 bg-terminal-bg rounded overflow-hidden relative">
                        <div
                          className={`h-full rounded ${pos.pnl_gbp >= 0 ? 'bg-gain/30' : 'bg-loss/30'}`}
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                      <PnlCurrency value={pos.pnl_gbp} className="font-mono text-sm w-24 text-right" />
                      <PnlValue value={pos.pnl_pct} suffix="%" className="font-mono text-xs w-16 text-right" />
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Recent activity — always visible (IA-1) */}
          <div className="card">
            <h2 className="text-lg font-semibold tracking-wide mb-3">Recent Activity</h2>
            <div className="space-y-1.5 max-h-[32rem] overflow-y-auto" aria-live="polite">
              {events.length === 0 ? (
                <div className="text-terminal-text-dim text-sm py-4">No events yet. Waiting for activity...</div>
              ) : (
                events.slice(0, recentActivityLimit).map((event) => (
                  <div key={event.id} className="flex items-start gap-2 py-1.5 border-b border-terminal-border/50 last:border-0">
                    <span className={`text-sm ${getEventColor(event.event_type)}`}>{getEventIcon(event.event_type)}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium">{event.event_type}</span>
                        <span className="text-xs text-terminal-text-dim">{safeFormat(event.timestamp, 'HH:mm:ss')}</span>
                      </div>
                      <div className="text-xs text-terminal-text-dim truncate">{event.message}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* Cumulative stats */}
          {monthlySummary && (monthlySummary.cumul_screened != null || monthlySummary.cumul_investigated != null) && (
            <div className="card">
              <h3 className="text-sm font-semibold mb-2">Cumulative</h3>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">Screened</span>
                  <span className="font-mono">{monthlySummary.cumul_screened ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">Investigated</span>
                  <span className="font-mono">{monthlySummary.cumul_investigated ?? '—'}</span>
                </div>
                {(monthlySummary.investigated_1_review != null) && (
                  <div className="text-xs text-terminal-text-dim pl-2">
                    1x: {monthlySummary.investigated_1_review ?? 0} · 2x: {monthlySummary.investigated_2_reviews ?? 0} · 3+: {monthlySummary.investigated_3plus_reviews ?? 0}
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">Uninvestigated</span>
                  <span className="font-mono">{monthlySummary.cumul_uninvestigated ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">Orders</span>
                  <span className="font-mono">{monthlySummary.cumul_orders ?? '—'}</span>
                </div>
              </div>
            </div>
          )}

          {/* Monthly cost detail */}
          {monthlySummary && (
            <div className="card">
              <h3 className="text-sm font-semibold mb-2">Cost Breakdown</h3>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">LLM</span>
                  <span className="font-mono">£{(monthlySummary.llm_cost_gbp ?? monthlySummary.cost_gbp).toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-terminal-text-dim">API</span>
                  <span className="font-mono">£{(monthlySummary.api_cost_gbp ?? 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between border-t border-terminal-border pt-1">
                  <span className="text-terminal-text-dim">Total</span>
                  <span className="font-mono">£{monthlySummary.cost_gbp.toFixed(2)}</span>
                </div>
                {monthlySummary.portfolio_start_gbp != null && monthlySummary.portfolio_end_gbp != null && (
                  <div className="flex justify-between mt-1">
                    <span className="text-terminal-text-dim">Portfolio</span>
                    <span className="font-mono text-xs">£{monthlySummary.portfolio_start_gbp.toFixed(0)} → £{monthlySummary.portfolio_end_gbp.toFixed(0)}</span>
                  </div>
                )}
              </div>
              {dailyCosts.length > 0 && (
                <div className="mt-3 pt-2 border-t border-terminal-border">
                  <button
                    type="button"
                    onClick={() => setDailyCostExpanded(!dailyCostExpanded)}
                    aria-expanded={dailyCostExpanded}
                    className="flex items-center gap-2 text-xs text-terminal-text-dim hover:text-terminal-text transition-colors w-full text-left"
                  >
                    <span className={dailyCostExpanded ? 'rotate-90' : ''}>▶</span>
                    Daily (last 7 days)
                  </button>
                  {dailyCostExpanded && (
                    <div className="overflow-x-auto mt-2">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-terminal-border text-left">
                            <th className="py-1 font-mono">Date</th>
                            <th className="py-1 font-mono">API</th>
                            <th className="py-1 font-mono">LLM</th>
                            <th className="py-1 font-mono">Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dailyCosts.slice(0, 7).map((d) => (
                            <tr key={d.date} className="border-b border-terminal-border/50">
                              <td className="py-1 font-mono">{d.date}</td>
                              <td className="py-1 font-mono">£{d.api_cost_gbp.toFixed(2)}</td>
                              <td className="py-1 font-mono">£{d.llm_cost_gbp.toFixed(2)}</td>
                              <td className="py-1 font-mono">£{d.total_gbp.toFixed(2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* --- Secondary sections (expandable) --- */}

      {/* Latest trades + LLM reasons */}
      <div className="card">
        <button
          type="button"
          onClick={() => setLatestTradesExpanded(!latestTradesExpanded)}
          aria-expanded={latestTradesExpanded}
          className="flex items-center gap-2 text-lg font-semibold mb-3 w-full text-left hover:opacity-90 transition-opacity"
        >
          <span className={latestTradesExpanded ? 'rotate-90' : ''}>▶</span>
          Latest trades & LLM reasons
        </button>
        {latestTradesExpanded && (
          latestOrders.length === 0 ? (
            <p className="text-terminal-text-dim text-sm">No orders yet.</p>
          ) : (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-3 mb-2 text-sm">
                <label className="flex items-center gap-1.5">
                  <span className="text-terminal-text-dim text-xs">Ticker</span>
                  <input
                    type="text"
                    placeholder="Filter..."
                    value={latestTradesFilters.ticker}
                    onChange={(e) => setLatestTradesFilters((f) => ({ ...f, ticker: e.target.value }))}
                    className="px-2 py-0.5 rounded bg-terminal-bg border border-terminal-border text-terminal-text font-mono text-xs w-24"
                  />
                </label>
                <label className="flex items-center gap-1.5">
                  <span className="text-terminal-text-dim text-xs">Action</span>
                  <select
                    value={latestTradesFilters.action}
                    onChange={(e) => setLatestTradesFilters((f) => ({ ...f, action: e.target.value }))}
                    className="px-2 py-0.5 rounded bg-terminal-bg border border-terminal-border text-terminal-text text-xs"
                  >
                    <option value="">All</option>
                    <option value="BUY">BUY</option>
                    <option value="SELL">SELL</option>
                    <option value="REDUCE">REDUCE</option>
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  <span className="text-terminal-text-dim text-xs">Status</span>
                  <select
                    value={latestTradesFilters.status}
                    onChange={(e) => setLatestTradesFilters((f) => ({ ...f, status: e.target.value }))}
                    className="px-2 py-0.5 rounded bg-terminal-bg border border-terminal-border text-terminal-text text-xs"
                  >
                    <option value="">All</option>
                    <option value="filled">filled</option>
                    <option value="pending">pending</option>
                    <option value="failed">failed</option>
                    <option value="dry_run">dry_run</option>
                  </select>
                </label>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-terminal-border text-left">
                      <th className="py-2 font-mono">Time</th>
                      <th className="py-2 font-mono">Ticker</th>
                      <th className="py-2 font-mono">Action</th>
                      <th className="py-2 font-mono">Qty</th>
                      <th className="py-2 font-mono">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLatestOrders.map((o) => (
                      <React.Fragment key={o.id}>
                        <tr
                          onClick={() => setTickerForLLM(tickerForLLM === o.ticker ? null : o.ticker)}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setTickerForLLM(tickerForLLM === o.ticker ? null : o.ticker) } }}
                          tabIndex={0}
                          role="button"
                          aria-expanded={tickerForLLM === o.ticker}
                          className="border-b border-terminal-border cursor-pointer hover:bg-terminal-surface/50"
                        >
                          <td className="py-1 font-mono text-xs">{safeFormat(o.timestamp, 'MMM dd HH:mm', '')}</td>
                          <td className="py-1 font-mono">{cleanTicker(o.ticker)}</td>
                          <td className="py-1">{o.action}</td>
                          <td className="py-1 font-mono">{o.quantity}</td>
                          <td className="py-1">{o.status}</td>
                        </tr>
                        {tickerForLLM === o.ticker && tickerDetail && (
                          <tr>
                            <td colSpan={5} className="py-3 bg-terminal-bg/80">
                              <LLMOutputPanel
                                key={tickerDetail.ticker}
                                ticker={tickerDetail.ticker}
                                lastDecision={tickerDetail.last_decision}
                                label={tickerDetail.label}
                              />
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); setTickerForLLM(null) }}
                                className="mt-2 text-xs text-terminal-text-dim hover:text-terminal-text"
                              >
                                Close
                              </button>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredLatestOrders.length === 0 && (
                <p className="text-terminal-text-dim text-xs">No orders match the filters.</p>
              )}
              <p className="text-terminal-text-dim text-xs">Click a row to see full LLM output (strategy, moderation, risk).</p>
            </div>
          )
        )}
      </div>

      {/* Run summaries */}
      <div className="card">
        <button
          type="button"
          onClick={() => setRunSummariesExpanded(!runSummariesExpanded)}
          aria-expanded={runSummariesExpanded}
          className="flex items-center gap-2 text-lg font-semibold w-full text-left hover:opacity-90 transition-opacity mb-3"
        >
          <span className={runSummariesExpanded ? 'rotate-90' : ''}>▶</span>
          Run summaries (notification-style)
        </button>
        {runSummariesExpanded && (
          <>
            <p className="text-terminal-text-dim text-xs mb-3">Full decisions and orders per run, organised by runtime.</p>
            {runFeed.length === 0 ? (
              <p className="text-terminal-text-dim text-sm">No runs yet.</p>
            ) : (
              <div className="space-y-3 max-h-[600px] overflow-y-auto">
                {runFeed.map(({ run, decisions, orders }) => {
                  const isExpanded = expandedRunId === run.id
                  return (
                    <div key={run.id} className="border border-terminal-border rounded p-3 bg-terminal-surface/30">
                      <button
                        type="button"
                        onClick={() => setExpandedRunId(isExpanded ? null : run.id)}
                        aria-expanded={isExpanded}
                        className="w-full text-left flex items-center justify-between"
                      >
                        <span className="font-mono text-sm">
                          {safeFormat(run.started_at, 'MMM dd, HH:mm', '')} — {run.cycle_id}
                        </span>
                        <span className="text-terminal-text-dim text-xs">
                          {run.status} · {decisions.length} decisions · {orders.length} orders
                        </span>
                      </button>
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-terminal-border space-y-3 text-sm">
                          <div>
                            <div className="text-terminal-text-dim text-xs font-medium mb-1">Decisions (full reasoning)</div>
                            <div className="space-y-2 max-h-64 overflow-y-auto">
                              {decisions.map((d) => (
                                <div key={d.id} className="p-2 rounded bg-terminal-bg/50 border border-terminal-border/50">
                                  <div className="font-mono text-terminal-text">
                                    {cleanTicker(d.ticker)} {d.action}
                                    {d.conviction != null && ` @ ${d.conviction}`}
                                    {d.primary_strategy && ` · ${d.primary_strategy}`}
                                  </div>
                                  {d.reasoning && (
                                    <div className="text-terminal-text-dim text-xs mt-1 whitespace-pre-wrap">{d.reasoning}</div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div className="text-terminal-text-dim text-xs font-medium mb-1">Orders</div>
                            <div className="space-y-1 text-xs">
                              {orders.length === 0 ? (
                                <span className="text-terminal-text-dim">None</span>
                              ) : (
                                orders.map((o) => (
                                  <div key={o.id} className="font-mono">
                                    {cleanTicker(o.ticker)} {o.action} {o.quantity} @ {o.status}
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
