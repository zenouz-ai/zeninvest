import { useEffect, useState, useMemo } from 'react'
import { useSSE } from '../hooks/useSSE'
import { runsApi, portfolioApi, eventsApi, statusApi } from '../api/client'
import type { Run, PortfolioSnapshot, Event } from '../types'
import { safeFormat } from '../utils/date'

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

export default function Dashboard() {
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [historicalEvents, setHistoricalEvents] = useState<Event[]>([])
  const [nextRunUtc, setNextRunUtc] = useState<string | null>(null)
  const [systemState, setSystemState] = useState<string>('ACTIVE')
  const [paused, setPaused] = useState<boolean>(false)
  const [loading, setLoading] = useState(true)
  const { events: sseEvents, isConnected } = useSSE({ enabled: true })

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [runs, portfolioData, eventsData, statusData] = await Promise.all([
          runsApi.list({ limit: 1 }),
          portfolioApi.current(),
          eventsApi.list({ limit: 50 }),
          statusApi.get(),
        ])
        setLatestRun(runs[0] || null)
        setPortfolio(portfolioData)
        setHistoricalEvents(eventsData)
        setNextRunUtc(statusData.next_run_utc)
        setSystemState(statusData.state ?? 'ACTIVE')
        setPaused(statusData.paused ?? false)
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

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
