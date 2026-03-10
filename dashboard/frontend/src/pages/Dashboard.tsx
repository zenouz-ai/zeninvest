import { useEffect, useState } from 'react'
import { useSSE } from '../hooks/useSSE'
import { runsApi, portfolioApi } from '../api/client'
import type { Run, PortfolioSnapshot, Event } from '../types'
import { format } from 'date-fns'

export default function Dashboard() {
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const { events, isConnected } = useSSE({ enabled: true })

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [runs, portfolioData] = await Promise.all([
          runsApi.list({ limit: 1 }),
          portfolioApi.current(),
        ])
        setLatestRun(runs[0] || null)
        setPortfolio(portfolioData)
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

  return (
    <div className="space-y-6">
      {/* Top Bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Last Run</div>
          <div className="text-lg font-mono">
            {latestRun
              ? format(new Date(latestRun.started_at), 'MMM dd, HH:mm')
              : 'Never'}
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
              ? `$${portfolio.total_value.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
          {portfolio && (
            <div className="text-xs text-terminal-text-dim mt-1">
              Cash: ${portfolio.cash_balance.toLocaleString()}
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
                      {format(new Date(event.timestamp), 'HH:mm:ss')}
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
