import { useEffect, useState, useCallback } from 'react'
import { statusApi, costsApi, portfolioApi, ordersApi } from '../api/client'
import { cleanTicker } from '../types'
import { runWhenIdle, usePollingInterval } from '../hooks/usePollingInterval'

interface Alert {
  id: string
  severity: 'critical' | 'warning'
  message: string
}

const ALERT_POLL_MS = 120_000

export function AlertBanner({ sseDisconnectedAlert }: { sseDisconnectedAlert: boolean }) {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState(false)

  const fetchAlerts = useCallback(async () => {
    const newAlerts: Alert[] = []

    try {
      const status = await statusApi.get()
      if (status.state === 'HALTED') {
        newAlerts.push({ id: 'state-halted', severity: 'critical', message: 'System HALTED — manual recovery required' })
      } else if (status.state === 'CAUTIOUS') {
        newAlerts.push({ id: 'state-cautious', severity: 'warning', message: 'System CAUTIOUS — new BUYs blocked by risk' })
      }
      if (status.paused) {
        newAlerts.push({ id: 'state-paused', severity: 'warning', message: 'Trading is paused' })
      }
      if (status.state === 'HALTED' && (status.halted_recovery_streak ?? 0) > 0) {
        newAlerts.push({
          id: 'state-halted-recovery',
          severity: 'warning',
          message: `HALTED auto-recovery progress: ${status.halted_recovery_streak}/${status.halted_auto_recovery_target ?? '—'} clean cycles`,
        })
      }
      if (status.peak_inflation_warning_note) {
        newAlerts.push({
          id: 'peak-inflation-warning',
          severity: 'warning',
          message: status.peak_inflation_warning_note,
        })
      }
    } catch { /* silent */ }

    if (sseDisconnectedAlert) {
      newAlerts.push({ id: 'sse-disconnected', severity: 'warning', message: 'Real-time event stream disconnected' })
    }

    try {
      const deg = await costsApi.getDegradation()
      if (deg.level === 'halted' || deg.level === 'no_strategy') {
        newAlerts.push({ id: `deg-${deg.level}`, severity: 'critical', message: `Cost degradation: ${deg.level.toUpperCase().replace(/_/g, ' ')}` })
      } else if (deg.level !== 'full') {
        newAlerts.push({ id: `deg-${deg.level}`, severity: 'warning', message: `Cost degradation: ${deg.level.toUpperCase().replace(/_/g, ' ')}` })
      }
    } catch { /* silent */ }

    try {
      const portfolio = await portfolioApi.current()
      if (portfolio?.positions) {
        const losers = portfolio.positions.filter((p) => p.pnl_pct < -5)
        if (losers.length > 0) {
          const worst = losers.sort((a, b) => a.pnl_pct - b.pnl_pct)[0]
          const msg = losers.length === 1
            ? `${cleanTicker(worst.ticker)} down ${worst.pnl_pct.toFixed(1)}%`
            : `${losers.length} positions losing >5% (worst: ${cleanTicker(worst.ticker)} ${worst.pnl_pct.toFixed(1)}%)`
          newAlerts.push({ id: 'losing-positions', severity: 'warning', message: msg })
        }
      }
    } catch { /* silent */ }

    try {
      const health = await ordersApi.health({ unresolved_window_days: 7, reconcile_pending: false })
      if (health.active_failed_count > 0) {
        newAlerts.push({
          id: 'failed-orders',
          severity: 'critical',
          message: `${health.active_failed_count} unresolved failed order${health.active_failed_count > 1 ? 's' : ''} — check Order Management`,
        })
      }
    } catch { /* silent */ }

    try {
      const executionQuality = await ordersApi.executionQuality({ days: 7 })
      if (executionQuality.warning_breached && executionQuality.warning_message) {
        newAlerts.push({
          id: 'execution-quality',
          severity: 'warning',
          message: executionQuality.warning_message,
        })
      }
    } catch { /* silent */ }

    setAlerts(newAlerts)
  }, [sseDisconnectedAlert])

  const pollingActive = usePollingInterval(true, fetchAlerts)

  useEffect(() => {
    const cancelIdle = runWhenIdle(() => {
      void fetchAlerts()
    })
    return cancelIdle
  }, [fetchAlerts])

  useEffect(() => {
    if (!pollingActive) return
    const interval = setInterval(fetchAlerts, ALERT_POLL_MS)
    return () => clearInterval(interval)
  }, [fetchAlerts, pollingActive])

  const visible = alerts.filter((a) => !dismissed.has(a.id))
  if (visible.length === 0) return null

  const hasCritical = visible.some((a) => a.severity === 'critical')
  const borderColor = hasCritical ? 'border-loss/40' : 'border-warning/40'
  const bgColor = hasCritical ? 'bg-loss/10' : 'bg-warning/10'
  const iconColor = hasCritical ? 'text-loss' : 'text-warning'

  const shown = expanded ? visible : visible.slice(0, 1)

  return (
    <div className={`${bgColor} ${borderColor} border-b px-4 py-2`}>
      <div className="max-w-7xl mx-auto">
        {shown.map((alert) => (
          <div key={alert.id} className="flex items-center gap-2 py-0.5">
            <span className={`text-sm ${alert.severity === 'critical' ? 'text-loss' : 'text-warning'}`}>
              {alert.severity === 'critical' ? '!' : '!'}
            </span>
            <span className="text-sm text-terminal-text flex-1">{alert.message}</span>
            <button
              type="button"
              onClick={() => setDismissed((prev) => new Set(prev).add(alert.id))}
              className="text-terminal-text-dim hover:text-terminal-text text-xs px-1"
              aria-label={`Dismiss alert: ${alert.message}`}
            >
              x
            </button>
          </div>
        ))}
        {visible.length > 1 && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className={`text-xs ${iconColor} hover:underline mt-0.5`}
          >
            +{visible.length - 1} more alert{visible.length - 1 > 1 ? 's' : ''}
          </button>
        )}
        {expanded && visible.length > 1 && (
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className={`text-xs ${iconColor} hover:underline mt-0.5`}
          >
            Show less
          </button>
        )}
      </div>
    </div>
  )
}
