import React, { useEffect, useState, useMemo } from 'react'
import { useSSE } from '../hooks/useSSE'
import { runsApi, portfolioApi, eventsApi, statusApi, costsApi, dashboardApi, ordersApi, universeApi } from '../api/client'
import type { Run, PortfolioSnapshot, Event, Order, InstrumentDetail } from '../types'
import { safeFormat } from '../utils/date'
import { cleanTicker } from '../types'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'

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

export default function Dashboard() {
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [lastRunCost, setLastRunCost] = useState<{ total_gbp: number } | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [historicalEvents, setHistoricalEvents] = useState<Event[]>([])
  const [nextRunUtc, setNextRunUtc] = useState<string | null>(null)
  const [systemState, setSystemState] = useState<string>('ACTIVE')
  const [paused, setPaused] = useState<boolean>(false)
  const [loading, setLoading] = useState(true)
  const [monthlySummary, setMonthlySummary] = useState<{
    runs_count: number
    cost_gbp: number
    llm_cost_gbp: number
    api_cost_gbp: number
    portfolio_start_gbp: number | null
    portfolio_end_gbp: number | null
    pnl_gbp: number | null
  } | null>(null)
  const [dailyCosts, setDailyCosts] = useState<Array<{
    date: string
    llm_cost_gbp: number
    api_cost_gbp: number
    total_gbp: number
  }>>([])
  const [latestOrders, setLatestOrders] = useState<Order[]>([])
  const [runFeed, setRunFeed] = useState<RunFeedEntry[]>([])
  const [tickerForLLM, setTickerForLLM] = useState<string | null>(null)
  const [tickerDetail, setTickerDetail] = useState<InstrumentDetail | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null)
  const { events: sseEvents, isConnected } = useSSE({ enabled: true })

  const now = useMemo(() => new Date(), [])
  const currentYear = now.getUTCFullYear()
  const currentMonth = now.getUTCMonth() + 1

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [runs, portfolioData, eventsData, statusData, monthly, orders, feed, dailyCostData] = await Promise.all([
          runsApi.list({ limit: 1 }),
          portfolioApi.current(),
          eventsApi.list({ limit: 50 }),
          statusApi.get(),
          dashboardApi.getMonthlySummary(currentYear, currentMonth),
          ordersApi.list({ limit: 15 }),
          dashboardApi.getRunFeed({ limit: 15 }),
          costsApi.getDaily({ days: 31 }),
        ])
        setLatestRun(runs[0] || null)
        setPortfolio(portfolioData)
        setHistoricalEvents(eventsData)
        setNextRunUtc(statusData.next_run_utc)
        setSystemState(statusData.state ?? 'ACTIVE')
        setPaused(statusData.paused ?? false)
        setMonthlySummary(monthly)
        setLatestOrders(orders)
        setRunFeed(feed)
        setDailyCosts(
          (dailyCostData || []).map((d: { date: string; llm_cost_gbp?: number; api_cost_gbp?: number; total_gbp?: number }) => {
            const llm = d.llm_cost_gbp ?? d.total_gbp ?? 0
            const api = d.api_cost_gbp ?? 0
            return {
              date: d.date,
              llm_cost_gbp: llm,
              api_cost_gbp: api,
              total_gbp: llm + api,
            }
          })
        )
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [currentYear, currentMonth])

  useEffect(() => {
    if (!latestRun?.cycle_id) {
      setLastRunCost(null)
      return
    }
    costsApi.getForCycle(latestRun.cycle_id).then((c) => setLastRunCost(c)).catch(() => setLastRunCost(null))
  }, [latestRun?.cycle_id])

  useEffect(() => {
    if (!tickerForLLM) {
      setTickerDetail(null)
      return
    }
    universeApi.getByTicker(tickerForLLM).then(setTickerDetail).catch(() => setTickerDetail(null))
  }, [tickerForLLM])

  const nextRunCountdown = useMemo(
    () => (nextRunUtc ? formatCountdown(nextRunUtc) : '—'),
    [nextRunUtc]
  )

  // Merge SSE (new) + historical; dedupe by id, newest first
  const events = useMemo(() => {
    const seen = new Set(sseEvents.map((e) => e.id))
    const fromHistory = historicalEvents.filter((e) => !seen.has(e.id))
    return [...sseEvents, ...fromHistory].slice(0, 100)
  }, [sseEvents, historicalEvents])

  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case 'run_started':
        return '▶'
      case 'run_completed':
        return '✓'
      case 'decision_made':
        return '⚡'
      case 'order_placed':
        return '📝'
      case 'order_executed':
        return '✅'
      case 'universe_updated':
        return '🌐'
      case 'notification_sent':
        return '📧'
      default:
        return '•'
    }
  }

  const getEventColor = (eventType: string) => {
    switch (eventType) {
      case 'run_started':
        return 'text-neutral'
      case 'run_completed':
        return 'text-gain'
      case 'decision_made':
        return 'text-accent'
      case 'order_executed':
        return 'text-gain'
      case 'order_placed':
        return 'text-neutral'
      default:
        return 'text-terminal-text-dim'
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading...</div>
      </div>
    )
  }

  const stateBadgeColor =
    systemState === 'HALTED' ? 'bg-loss' : systemState === 'CAUTIOUS' ? 'bg-warning' : 'bg-gain'
  const stateBadgeText = paused ? 'PAUSED' : systemState

  return (
    <div className="space-y-6">
      {/* System state badge */}
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex items-center px-3 py-1 rounded font-mono text-sm font-semibold text-terminal-bg ${stateBadgeColor}`}
        >
          {stateBadgeText}
        </span>
        {paused && (
          <span className="text-terminal-text-dim text-sm">Trading paused</span>
        )}
      </div>

      {/* Top Bar */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Next Run</div>
          <div className="text-lg font-mono">{nextRunCountdown}</div>
          {nextRunUtc && (
            <div className="text-xs text-terminal-text-dim mt-1">
              {safeFormat(nextRunUtc, 'MMM dd, HH:mm', '')} UTC
            </div>
          )}
        </div>

        <div className="card">
          <div className="text-sm text-terminal-text-dim">Last Run</div>
          <div className="text-lg font-mono">
            {latestRun ? safeFormat(latestRun.started_at, 'MMM dd, HH:mm', '—') : 'Never'}
          </div>
          {latestRun && (
            <div className="text-xs text-terminal-text-dim mt-1">
              {latestRun.status === 'completed' ? (
                <span className="text-gain">Completed</span>
              ) : latestRun.status === 'running' ? (
                <span className="text-neutral">Running...</span>
              ) : (
                <span className="text-loss">Failed</span>
              )}
            </div>
          )}
          {lastRunCost != null && (
            <div className="text-xs text-terminal-text-dim mt-1">
              Cost: £{lastRunCost.total_gbp.toFixed(4)}
            </div>
          )}
        </div>

        <div className="card">
          <div className="text-sm text-terminal-text-dim">Portfolio Value</div>
          <div className="text-lg font-mono">
            {portfolio
              ? `£${portfolio.total_value_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
          {portfolio && (
            <div className="text-xs mt-1">
              <span className={portfolio.pnl_gbp >= 0 ? 'text-gain' : 'text-loss'}>
                P&L: £{portfolio.pnl_gbp.toFixed(2)} ({portfolio.pnl_pct >= 0 ? '+' : ''}
                {portfolio.pnl_pct.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>

        <div className="card">
          <div className="text-sm text-terminal-text-dim">SSE Status</div>
          <div className="text-lg font-mono">
            {isConnected ? (
              <span className="text-gain">Connected</span>
            ) : (
              <span className="text-loss">Disconnected</span>
            )}
          </div>
          <div className="text-xs text-terminal-text-dim mt-1">
            {events.length} events received
          </div>
        </div>

        <div className="card">
          <div className="text-sm text-terminal-text-dim">Latest Run</div>
          <div className="text-lg font-mono">
            {latestRun?.summary_json?.num_trades ?? 0} trades
          </div>
          {latestRun?.summary_json && (
            <div className="text-xs text-terminal-text-dim mt-1">
              {latestRun.summary_json.num_rejected ?? 0} rejected
            </div>
          )}
        </div>
      </div>

      {/* This month */}
      {monthlySummary && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-3">This month</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-terminal-text-dim">Runs</div>
              <div className="font-mono">{monthlySummary.runs_count}</div>
            </div>
            <div>
              <div className="text-xs text-terminal-text-dim">Cost (monthly)</div>
              <div className="font-mono">£{monthlySummary.cost_gbp.toFixed(2)}</div>
              <div className="text-xs text-terminal-text-dim mt-0.5">
                API: £{(monthlySummary.api_cost_gbp ?? 0).toFixed(2)} · LLM: £{(monthlySummary.llm_cost_gbp ?? monthlySummary.cost_gbp).toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-xs text-terminal-text-dim">Portfolio (start → end)</div>
              <div className="font-mono text-sm">
                {monthlySummary.portfolio_start_gbp != null
                  ? `£${monthlySummary.portfolio_start_gbp.toFixed(0)}`
                  : '—'}
                {' → '}
                {monthlySummary.portfolio_end_gbp != null
                  ? `£${monthlySummary.portfolio_end_gbp.toFixed(0)}`
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs text-terminal-text-dim">P&L (month)</div>
              <div className={`font-mono ${monthlySummary.pnl_gbp != null && monthlySummary.pnl_gbp >= 0 ? 'text-gain' : monthlySummary.pnl_gbp != null ? 'text-loss' : ''}`}>
                {monthlySummary.pnl_gbp != null ? `£${monthlySummary.pnl_gbp.toFixed(2)}` : '—'}
              </div>
            </div>
          </div>
          {dailyCosts.length > 0 && (
            <div className="mt-4 pt-3 border-t border-terminal-border">
              <div className="text-xs text-terminal-text-dim mb-2">Daily cost (API vs LLM, last 7 days)</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-terminal-border text-left">
                      <th className="py-1 font-mono text-xs">Date</th>
                      <th className="py-1 font-mono text-xs">API</th>
                      <th className="py-1 font-mono text-xs">LLM</th>
                      <th className="py-1 font-mono text-xs">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dailyCosts.slice(0, 7).map((d) => (
                      <tr key={d.date} className="border-b border-terminal-border/50">
                        <td className="py-1 font-mono text-xs">{d.date}</td>
                        <td className="py-1 font-mono">£{d.api_cost_gbp.toFixed(2)}</td>
                        <td className="py-1 font-mono">£{d.llm_cost_gbp.toFixed(2)}</td>
                        <td className="py-1 font-mono">£{d.total_gbp.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Latest trades + LLM reasons */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Latest trades & LLM reasons</h2>
        {latestOrders.length === 0 ? (
          <p className="text-terminal-text-dim text-sm">No orders yet.</p>
        ) : (
          <div className="space-y-2">
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
                  {latestOrders.map((o) => (
                    <React.Fragment key={o.id}>
                      <tr
                        onClick={() => setTickerForLLM(tickerForLLM === o.ticker ? null : o.ticker)}
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
            <p className="text-terminal-text-dim text-xs">Click a row to see full LLM output (strategy, moderation, risk).</p>
          </div>
        )}
      </div>

      {/* Run summaries (notification-style, untruncated, by runtime) */}
      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Run summaries (notification-style)</h2>
        <p className="text-terminal-text-dim text-xs mb-3">Full decisions and orders per run, organised by runtime. Same style as Slack/Email, untruncated.</p>
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
      </div>

      {/* Activity Feed */}
      <div className="card">
        <h2 className="text-xl font-semibold mb-4">Activity Feed</h2>
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {events.length === 0 ? (
            <div className="text-terminal-text-dim text-center py-8">
              No events yet. Waiting for activity...
            </div>
          ) : (
            events.map((event) => (
              <div
                key={event.id}
                className="flex items-start gap-3 py-2 border-b border-terminal-border last:border-0"
              >
                <div className={`text-lg ${getEventColor(event.event_type)}`}>
                  {getEventIcon(event.event_type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{event.event_type}</span>
                    <span className="text-xs text-terminal-text-dim">
                      {safeFormat(event.timestamp, 'HH:mm:ss')}
                    </span>
                    <span className="text-xs text-terminal-text-dim">
                      [{event.source}]
                    </span>
                  </div>
                  <div className="text-sm text-terminal-text mt-1">
                    {event.message}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
