import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { runsApi, portfolioApi, eventsApi, statusApi, costsApi, dashboardApi, ordersApi, universeApi, systemApi, performanceApi, macroApi, insightsApi } from '../api/client'
import type { Run, PortfolioSnapshot, Event, Order, InstrumentDetail, MacroSummary, GuidanceSnapshot, StrategyChangeEpisode } from '../types'
import { safeFormat } from '../utils/date'
import { cleanTicker } from '../types'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'
import { MetricCard, type DeltaColor } from '../components/MetricCard'
import { DashboardSkeleton } from '../components/Skeleton'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { StatusPill, type PillVariant } from '../components/StatusPill'
import { useAsyncData } from '../hooks/useAsyncData'
import { FreshnessIndicator } from '../components/FreshnessIndicator'
import type { SseConnectionState } from '../hooks/useSSE'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { PnlCurrency, PnlValue } from '../components/PnlDisplay'
import { EpisodeCard } from '../components/EpisodeCard'

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

function getSystemStateVariant(systemState: string, paused: boolean): PillVariant {
  if (paused) return 'warning'
  if (systemState === 'HALTED') return 'alert'
  if (systemState === 'CAUTIOUS') return 'warning'
  return 'active'
}

function getStreamVariant(connectionState: SseConnectionState): PillVariant {
  if (connectionState === 'open') return 'live'
  if (connectionState === 'connecting') return 'warning'
  return 'alert'
}

function getRunStatusVariant(status: string): PillVariant {
  if (status === 'completed') return 'active'
  if (status === 'running') return 'live'
  return 'alert'
}

function getRunDeltaColor(status: string): DeltaColor {
  if (status === 'completed') return 'emerald'
  if (status === 'running') return 'cyan'
  return 'loss'
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
  const followUpRefreshTimersRef = useRef<number[]>([])

  // --- Independent data sections ---
  const fetchStatus = useCallback(() => statusApi.get(), [])
  const statusResult = useAsyncData(fetchStatus)

  const fetchPortfolio = useCallback(() => portfolioApi.current(), [])
  const portfolioResult = useAsyncData<PortfolioSnapshot | null>(fetchPortfolio)

  const fetchLatestRun = useCallback(async () => {
    const runs = await runsApi.list({ limit: 10 })
    return runs.find((run) => run.run_type !== 'refresh') || null
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
  const fetchGuidanceSummary = useCallback(() => insightsApi.getLatestGuidance().catch(() => null), [])
  const guidanceResult = useAsyncData<GuidanceSnapshot | null>(fetchGuidanceSummary)
  const fetchEpisodes = useCallback(() => insightsApi.listEpisodes().catch(() => []), [])
  const episodeResult = useAsyncData<StrategyChangeEpisode[]>(fetchEpisodes)

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
  const latestRunCounts = latestRun?.summary_json?.counts
  const monthlySummary = monthlyResult.data
  const latestOrders = ordersResult.data ?? []
  const runFeed = runFeedResult.data ?? []
  const dailyCosts = dailyCostsResult.data ?? []
  const perf = perfResult.data
  const latestGuidance = guidanceResult.data
  const activeEpisodes = useMemo(
    () => (episodeResult.data ?? []).filter((item) => item.status === 'confirmed').slice(0, 3),
    [episodeResult.data]
  )

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
  const [triggerLoading, setTriggerLoading] = useState<'dry' | 'live' | 'refresh' | null>(null)
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

  const refetchDashboardSections = useCallback(() => {
    statusResult.refetch()
    portfolioResult.refetch()
    latestRunResult.refetch()
    perfResult.refetch()
    monthlyResult.refetch()
    historicalEventsResult.refetch()
    ordersResult.refetch()
    runFeedResult.refetch()
    macroResult.refetch()
    guidanceResult.refetch()
    episodeResult.refetch()
    dailyCostsResult.refetch()
  }, [
    dailyCostsResult,
    episodeResult,
    guidanceResult,
    historicalEventsResult,
    latestRunResult,
    macroResult,
    monthlyResult,
    ordersResult,
    perfResult,
    portfolioResult,
    runFeedResult,
    statusResult,
  ])

  const scheduleFollowUpRefreshes = useCallback(() => {
    followUpRefreshTimersRef.current.forEach((timerId) => window.clearTimeout(timerId))
    followUpRefreshTimersRef.current = []
    refetchDashboardSections()
    ;[5000, 15000].forEach((delayMs) => {
      const timerId = window.setTimeout(refetchDashboardSections, delayMs)
      followUpRefreshTimersRef.current.push(timerId)
    })
  }, [refetchDashboardSections])

  useEffect(() => {
    return () => {
      followUpRefreshTimersRef.current.forEach((timerId) => window.clearTimeout(timerId))
      followUpRefreshTimersRef.current = []
    }
  }, [])

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

  const handleRefresh = async () => {
    setTriggerLoading('refresh')
    try {
      await systemApi.triggerRefresh()
      scheduleFollowUpRefreshes()
    } catch (e) {
      console.error('Refresh trigger failed:', e)
    } finally {
      setTriggerLoading(null)
    }
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

  const stateBadgeText = paused ? 'PAUSED' : systemState
  const stateBadgeVariant = getSystemStateVariant(systemState, paused)
  const streamVariant = getStreamVariant(sseConnectionState)
  const streamLabel = sseConnectionState === 'open'
    ? 'Stream Live'
    : sseConnectionState === 'connecting'
      ? 'Stream Reconnecting'
      : 'Stream Offline'
  const scheduleLabel = status?.schedule_mode === 'market_session'
    ? `${(status.cycle_times_local ?? []).join(' / ')} NY`
    : `${(status?.cycle_times_utc ?? []).join(' / ')} UTC`
  const compactScheduleLabel = status?.schedule_mode === 'market_session'
    ? `Cycles ${(status.cycle_times_local ?? []).join(' / ')}`
    : `Cycles ${(status?.cycle_times_utc ?? []).join(' / ')} UTC`
  const refreshScheduleLabel = (status?.refresh_times_local ?? []).length > 0
    ? `${(status?.refresh_times_local ?? []).join(' / ')} NY`
    : null
  const nextCycleMetricSubtitle = (
    <>
      <div>{nextRunUtc ? `${safeFormat(nextRunUtc, 'MMM dd, HH:mm', '—')} UTC` : 'Scheduler has not published the next cycle yet.'}</div>
      {scheduleLabel && <div>{compactScheduleLabel}</div>}
    </>
  )
  const nextRefreshMetricSubtitle = (
    <>
      <div>{status?.next_refresh_utc ? `${safeFormat(status.next_refresh_utc, 'MMM dd, HH:mm', '—')} UTC` : 'Refresh lane is not scheduled.'}</div>
      {refreshScheduleLabel && <div>{`Refresh ${refreshScheduleLabel}`}</div>}
    </>
  )
  const lastRefreshMetricSubtitle = status?.last_refresh_completed_at
    ? `Last ${safeFormat(status.last_refresh_completed_at, 'MMM dd, HH:mm', '—')} UTC`
    : 'No refresh has completed yet.'
  const latestRunMetricSubtitle = latestRun
    ? `Last ${safeFormat(latestRun.started_at, 'MMM dd, HH:mm', '—')} UTC${lastRunCost != null ? ` · £${lastRunCost.total_gbp.toFixed(2)}` : ''}`
    : 'Awaiting first completed cycle.'
  const portfolioValueMetric = portfolio
    ? `£${Math.round(portfolio.total_value_gbp).toLocaleString()}`
    : 'N/A'
  const portfolioDelta = portfolio?.pnl_pct != null
    ? `${portfolio.pnl_pct >= 0 ? '+' : ''}${portfolio.pnl_pct.toFixed(2)}%`
    : undefined
  const portfolioDeltaColor: DeltaColor = portfolio?.pnl_pct == null
    ? 'dim'
    : portfolio.pnl_pct >= 0
      ? 'emerald'
      : 'loss'
  const performanceValue = perf?.sharpe_30d != null ? perf.sharpe_30d.toFixed(2) : '—'
  const performanceDelta = perf?.win_rate_pct != null ? `Win ${perf.win_rate_pct.toFixed(0)}%` : undefined
  const performanceDeltaColor: DeltaColor = perf?.win_rate_pct != null ? 'cyan' : 'dim'
  const performanceSubtitle = perf
    ? `Max DD ${perf.max_drawdown_pct != null ? `${perf.max_drawdown_pct.toFixed(1)}%` : '—'} · ${perf.num_trades ?? 0} trades`
    : 'No 30-day performance snapshot yet.'
  const monthlyValue = monthlySummary ? `£${monthlySummary.cost_gbp.toFixed(2)}` : '—'
  const monthlyDelta = monthlySummary ? `${monthlySummary.runs_count} runs` : undefined
  const monthlyDeltaColor: DeltaColor = monthlySummary ? 'violet' : 'dim'
  const monthlySubtitle = monthlySummary
    ? `P&L ${monthlySummary.pnl_gbp != null ? `£${monthlySummary.pnl_gbp.toFixed(2)}` : '—'} · Investigated ${monthlySummary.new_investigated_this_month ?? 0}`
    : 'Monthly summary not available yet.'
  const latestCycleAuditSummary = latestRun?.summary_json?.audit_summary
  const latestRefreshAuditSummary = status?.last_refresh_summary?.audit_summary
  const auditStatusLine = [
    latestCycleAuditSummary
      ? `Cycle audit ${latestCycleAuditSummary.succeeded ?? 0}/${latestCycleAuditSummary.datasets_total ?? 0}${latestCycleAuditSummary.degraded ? ' degraded' : ' healthy'}`
      : null,
    latestRefreshAuditSummary
      ? `Refresh audit ${latestRefreshAuditSummary.succeeded ?? 0}/${latestRefreshAuditSummary.datasets_total ?? 0}${latestRefreshAuditSummary.degraded ? ' degraded' : ' healthy'}`
      : null,
  ].filter(Boolean).join(' · ')

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
        titleMeta={<StatusPill label={stateBadgeText} variant={stateBadgeVariant} dot />}
      />

      <Panel hero className="space-y-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill label={stateBadgeText} variant={stateBadgeVariant} dot />
              <StatusPill label={streamLabel} variant={streamVariant} dot />
              {scheduleLabel && (
                <StatusPill label={compactScheduleLabel} variant="dim" />
              )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-terminal-text-dim">
              {status?.next_run_utc && (
                <span>{`Next cycle ${safeFormat(status.next_run_utc, 'MMM dd, HH:mm', '—')} UTC`}</span>
              )}
              {status?.next_refresh_utc && (
                <span>{`Next refresh ${safeFormat(status.next_refresh_utc, 'MMM dd, HH:mm', '—')} UTC`}</span>
              )}
              {refreshScheduleLabel && (
                <span>{`Refresh lane ${refreshScheduleLabel}`}</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
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
            <button
              type="button"
              onClick={handleRefresh}
              disabled={triggerLoading != null}
              className="btn-secondary text-sm py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {triggerLoading === 'refresh' ? 'Starting...' : 'Refresh'}
            </button>
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
          <MetricCard
            label="Next Cycle"
            value={countdownStr}
            subtitle={nextCycleMetricSubtitle}
            delta={latestRun ? latestRun.status : undefined}
            deltaColor={latestRun ? getRunDeltaColor(latestRun.status) : 'dim'}
          />
          <MetricCard
            label="Next Refresh"
            value={status?.next_refresh_utc ? formatCountdown(status.next_refresh_utc) : '—'}
            subtitle={
              <>
                {nextRefreshMetricSubtitle}
                <div>{lastRefreshMetricSubtitle}</div>
              </>
            }
            delta={status?.last_refresh_status ?? undefined}
            deltaColor={status?.last_refresh_status === 'failed' ? 'loss' : status?.last_refresh_status ? 'cyan' : 'dim'}
          />
          <MetricCard
            label="Portfolio Value"
            value={portfolioValueMetric}
            subtitle={portfolio ? `${portfolio.num_positions} positions · £${portfolio.cash_gbp.toFixed(0)} cash` : 'No portfolio snapshot available.'}
            delta={portfolioDelta}
            deltaColor={portfolioDeltaColor}
          />
          <MetricCard
            label="Performance (30d)"
            value={performanceValue}
            subtitle={performanceSubtitle}
            delta={performanceDelta}
            deltaColor={performanceDeltaColor}
          />
          <MetricCard
            label="This Month"
            value={monthlyValue}
            subtitle={monthlySubtitle}
            delta={monthlyDelta}
            deltaColor={monthlyDeltaColor}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-panel border border-terminal-border p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Market Guidance</div>
                <div className="mt-1 text-base font-semibold text-terminal-text">Current Screening Tilt</div>
              </div>
              <Link to="/insights" className="text-xs text-cyan hover:underline">Open Insights</Link>
            </div>
            {latestGuidance ? (
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <StatusPill label={latestGuidance.regime} variant={latestGuidance.regime === 'RISK_OFF' ? 'alert' : latestGuidance.regime === 'RISK_ON' ? 'active' : 'dim'} dot />
                  <StatusPill label={latestGuidance.status} variant={latestGuidance.status === 'active' ? 'live' : latestGuidance.status === 'stale' ? 'warning' : 'alert'} />
                </div>
                <p className="text-sm text-terminal-text-dim">{latestGuidance.prompt_summary ?? latestGuidance.rationale}</p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-terminal-text-dim">No guidance snapshot has been recorded yet.</p>
            )}
          </div>
          <div className="rounded-panel border border-terminal-border p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Strategy Attribution</div>
                <div className="mt-1 text-base font-semibold text-terminal-text">Active Confirmed Episodes</div>
              </div>
              <Link to="/insights" className="text-xs text-cyan hover:underline">Open Insights</Link>
            </div>
            {activeEpisodes.length > 0 ? (
              <div className="mt-3 space-y-2">
                {activeEpisodes.map((episode) => (
                  <Link to="/insights" key={episode.id} className="block no-underline">
                    <EpisodeCard episode={episode} />
                  </Link>
                ))}
                <Link to="/insights" className="text-xs text-cyan-400 hover:text-cyan-300 inline-block mt-2">
                  View all episodes →
                </Link>
              </div>
            ) : (
              <p className="mt-3 text-sm text-terminal-text-dim">No strategy changes deployed this week</p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 border-t border-terminal-border/70 pt-3 md:flex-row md:items-center md:justify-between">
          <div className="text-sm text-terminal-text-dim">
            {latestRunMetricSubtitle}
          </div>
          {auditStatusLine && (
            <div className="text-xs text-terminal-text-dim">
              {auditStatusLine}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs text-terminal-text-dim">
            {portfolioResult.error && <SectionError error="Portfolio unavailable" onRetry={portfolioResult.refetch} />}
            {perfResult.error && <SectionError error="Performance unavailable" onRetry={perfResult.refetch} />}
            {monthlyResult.error && <SectionError error="Monthly summary unavailable" onRetry={monthlyResult.refetch} />}
          </div>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-terminal-text-dim">
          {portfolio?.timestamp && (
            <span className="block">Snapshot {safeFormat(portfolio.timestamp, 'MMM dd HH:mm:ss', '—')}</span>
          )}
          {status?.last_refresh_completed_at && (
            <span className="block">Refresh {safeFormat(status.last_refresh_completed_at, 'MMM dd HH:mm:ss', '—')}</span>
          )}
          <span className="block">Portfolio <FreshnessIndicator lastUpdatedAt={portfolioResult.lastUpdatedAt} isStale={portfolioResult.isStale} className="inline" /></span>
          <span className="block">Performance <FreshnessIndicator lastUpdatedAt={perfResult.lastUpdatedAt} isStale={perfResult.isStale} className="inline" /></span>
          <span className="block">Monthly <FreshnessIndicator lastUpdatedAt={monthlyResult.lastUpdatedAt} isStale={monthlyResult.isStale} className="inline" /></span>
        </div>
      </Panel>

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

      {/* Macro conditions bar */}
      {macroResult.data && macroResult.data.regime && (
        <Panel className="flex items-center gap-4 flex-wrap text-sm">
          <span className="label-mono">Macro</span>
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
        </Panel>
      )}

      {/* Last cycle summary — always visible (WF-3) */}
      {latestRun && (
        <Panel className="bg-terminal-surface/60">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <StatusPill label={latestRun.status} variant={getRunStatusVariant(latestRun.status)} dot />
            <span className="font-mono text-accent">{latestRun.cycle_id}</span>
            <span className="text-terminal-text-dim">{safeFormat(latestRun.started_at, 'MMM dd, HH:mm', '')} UTC</span>
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
                {latestRunCounts?.broker_orders_submitted != null && (
                  <>
                    <span className="text-terminal-text-dim">·</span>
                    <span>{latestRunCounts.broker_orders_submitted} broker orders</span>
                  </>
                )}
                {latestRunCounts?.queued != null && latestRunCounts.queued > 0 && (
                  <>
                    <span className="text-terminal-text-dim">·</span>
                    <span>{latestRunCounts.queued} queued</span>
                  </>
                )}
                {latestRunCounts?.skipped != null && latestRunCounts.skipped > 0 && (
                  <>
                    <span className="text-terminal-text-dim">·</span>
                    <span>{latestRunCounts.skipped} skipped</span>
                  </>
                )}
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
        </Panel>
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
