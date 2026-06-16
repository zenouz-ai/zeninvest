import { Fragment, useEffect, useState, useCallback } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ordersApi, stopLossApi } from '../api/client'
import { TableSkeleton } from '../components/Skeleton'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { StatusPill, type PillVariant } from '../components/StatusPill'
import { usePollingInterval } from '../hooks/usePollingInterval'
import { cleanTicker, type ExecutionQuality, type StopLossCurrent } from '../types'

const ORDER_POLL_MS = 120_000

function formatMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `£${value.toFixed(2)}`
}

function formatQuantity(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

function formatBps(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)} bps`
}

function profitLockLabel(status: string | null | undefined): string {
  switch (status) {
    case 'protected':
      return 'Protected'
    case 'eligible':
      return 'Needs Lock'
    case 'exit_required':
      return 'Exit Required'
    default:
      return 'Inactive'
  }
}

function profitLockVariant(status: string | null | undefined): PillVariant {
  switch (status) {
    case 'protected':
      return 'active'
    case 'eligible':
      return 'warning'
    case 'exit_required':
      return 'alert'
    default:
      return 'dim'
  }
}

export default function OrderManagement() {
  const [current, setCurrent] = useState<StopLossCurrent[]>([])
  const [adjustments, setAdjustments] = useState<any[]>([])
  const [recentOrders, setRecentOrders] = useState<any[]>([])
  const [executionQuality, setExecutionQuality] = useState<ExecutionQuality | null>(null)
  const [expandedErrorOrderId, setExpandedErrorOrderId] = useState<number | null>(null)
  const [health, setHealth] = useState<{
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
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [brokerSyncLoading, setBrokerSyncLoading] = useState(false)

  const fetchData = useCallback(async (reconcilePending = false) => {
    setError(null)
    try {
      const healthData = await ordersApi.health({
        unresolved_window_days: 7,
        reconcile_pending: reconcilePending,
      })
      const [currentData, adjData, ordersData, executionQualityData] = await Promise.all([
        stopLossApi.getCurrent(),
        stopLossApi.getAdjustments({ limit: 50 }),
        ordersApi.list({ limit: 30 }),
        ordersApi.executionQuality({ days: 30 }),
      ])
      setCurrent(currentData)
      setAdjustments(adjData)
      setRecentOrders(ordersData)
      setExecutionQuality(executionQualityData)
      setHealth(healthData)
    } catch (e) {
      console.error('Failed to fetch stop-loss data:', e)
      setError(e instanceof Error ? e.message : 'Failed to load stop-loss data')
    } finally {
      setLoading(false)
    }
  }, [])

  const syncWithBroker = async () => {
    setBrokerSyncLoading(true)
    setError(null)
    try {
      await fetchData(true)
    } finally {
      setBrokerSyncLoading(false)
    }
  }

  const pollingActive = usePollingInterval(true, () => { void fetchData(false) })

  useEffect(() => {
    void fetchData(false)
  }, [fetchData])

  useEffect(() => {
    if (!pollingActive) return
    const interval = setInterval(() => { void fetchData(false) }, ORDER_POLL_MS)
    return () => clearInterval(interval)
  }, [fetchData, pollingActive])

  if (loading) {
    return <TableSkeleton rows={5} cols={5} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); void fetchData(false) }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Order Management"
        description="Execution quality, partial-fill recovery visibility, stop-loss levels for current positions, and history of adjustments. Recent broker orders include fill telemetry, failure details, and any off-hours placement notes."
      />

      {health && (
        <div className="card">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="text-lg font-semibold tracking-wide">Order Health</h2>
            <button
              type="button"
              onClick={() => { void syncWithBroker() }}
              disabled={brokerSyncLoading}
              className="btn-secondary text-xs"
            >
              {brokerSyncLoading ? 'Syncing with broker…' : 'Sync with broker'}
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 text-sm">
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Active unresolved</div>
              <div className={`font-mono text-lg ${health.active_failed_count > 0 ? 'text-loss' : 'text-profit'}`}>
                {health.active_failed_count}
              </div>
              <div className="text-xs text-terminal-text-dim mt-1">
                alerts window {health.unresolved_window_days}d
              </div>
            </div>
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Archived unresolved</div>
              <div className={`font-mono text-lg ${health.archived_failed_count > 0 ? 'text-warning' : 'text-terminal-text-dim'}`}>
                {health.archived_failed_count}
              </div>
              <div className="text-xs text-terminal-text-dim mt-1">
                retained in history, removed from banner
              </div>
            </div>
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Pending (local vs live)</div>
              <div className="font-mono text-lg">
                {health.pending_local_count} / {health.pending_live_count}
              </div>
              <div className="text-xs text-terminal-text-dim mt-1">
                stale={health.stale_pending_count}, reconciled={health.reconciled_pending_count}
              </div>
            </div>
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Broker sync health</div>
              <div className="font-mono text-xs">{safeFormat(health.last_reconciled_at, 'MMM dd HH:mm:ss', '—')}</div>
              <div className="text-xs text-terminal-text-dim mt-1">
                history {safeFormat(health.last_history_sync_at, 'MMM dd HH:mm:ss', '—')}
              </div>
              <div className="text-xs text-terminal-text-dim">
                live pending {safeFormat(health.last_live_pending_sync_at, 'MMM dd HH:mm:ss', '—')}
              </div>
            </div>
          </div>
          {health.last_refresh_completed_at && (
            <div className="mt-3 text-xs text-terminal-text-dim">
              Last scheduled refresh: {safeFormat(health.last_refresh_completed_at, 'MMM dd HH:mm:ss', '—')}
              {health.last_refresh_status ? ` (${health.last_refresh_status})` : ''}
              {health.last_refresh_summary && (
                <>
                  {` · fills ${health.last_refresh_summary.orders_updated_total ?? 0}`}
                  {` · stop actions ${health.last_refresh_summary.stop_adjustments ?? 0}`}
                  {` · exits ${health.last_refresh_summary.deterministic_exits ?? 0}`}
                  {health.last_refresh_summary.audit_summary && (
                    ` · audit ${health.last_refresh_summary.audit_summary.succeeded ?? 0}/${health.last_refresh_summary.audit_summary.datasets_total ?? 0}`
                  )}
                </>
              )}
            </div>
          )}
          {health.last_broker_sync_at && (
            <p className="text-xs text-terminal-text-dim mt-2">
              Last successful broker sync: {safeFormat(health.last_broker_sync_at, 'MMM dd HH:mm:ss', '—')}
            </p>
          )}
          {health.live_fetch_error && (
            <p className="text-warning text-xs mt-2">
              Live pending fetch warning{health.live_fetch_error_at ? ` (${safeFormat(health.live_fetch_error_at, 'MMM dd HH:mm:ss', '—')})` : ''}: {health.live_fetch_error}
            </p>
          )}
          {health.history_fetch_error && (
            <p className="text-warning text-xs mt-2">
              Broker history sync warning{health.history_fetch_error_at ? ` (${safeFormat(health.history_fetch_error_at, 'MMM dd HH:mm:ss', '—')})` : ''}: {health.history_fetch_error}
            </p>
          )}
          {health.failed_recent.length > 0 && (
            <div className="mt-4 border border-terminal-border rounded-md p-3">
              <div className="text-sm font-semibold">Active failed orders</div>
              <div className="mt-2 space-y-1 text-xs text-terminal-text-dim">
                {health.failed_recent.map((order) => (
                  <div key={order.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-mono text-terminal-text">{cleanTicker(order.ticker)}</span>
                    <span>{order.action}</span>
                    <span>{order.order_type}</span>
                    <span>{safeFormat(order.timestamp, 'MMM dd HH:mm', '—')}</span>
                    {order.error_message && <span className="truncate">{order.error_message}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          {health.archived_failed_recent.length > 0 && (
            <div className="mt-4 border border-terminal-border rounded-md p-3">
              <div className="text-sm font-semibold">Archived failed orders</div>
              <div className="mt-2 space-y-1 text-xs text-terminal-text-dim">
                {health.archived_failed_recent.map((order) => (
                  <div key={order.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-mono text-terminal-text">{cleanTicker(order.ticker)}</span>
                    <span>{order.action}</span>
                    <span>{order.order_type}</span>
                    <span>{safeFormat(order.timestamp, 'MMM dd HH:mm', '—')}</span>
                    {order.error_message && <span className="truncate">{order.error_message}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {executionQuality && (
        <div className="card">
          <h2 className="text-lg font-semibold tracking-wide mb-3">Execution Quality</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Overall ({executionQuality.window_days}d)</div>
              <div className="font-mono text-lg">{formatBps(executionQuality.overall.mean_bps)}</div>
              <div className="text-xs text-terminal-text-dim mt-1">
                fills={executionQuality.overall.count} · p50={formatBps(executionQuality.overall.p50_bps)} · p95={formatBps(executionQuality.overall.p95_bps)}
              </div>
            </div>
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">BUY</div>
              <div className="font-mono text-lg">{formatBps(executionQuality.buy.mean_bps)}</div>
              <div className="text-xs text-terminal-text-dim mt-1">
                fills={executionQuality.buy.count} · best={formatBps(executionQuality.buy.best_bps)} · worst={formatBps(executionQuality.buy.worst_bps)}
              </div>
            </div>
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">EXIT</div>
              <div className="font-mono text-lg">{formatBps(executionQuality.exit.mean_bps)}</div>
              <div className="text-xs text-terminal-text-dim mt-1">
                fills={executionQuality.exit.count} · best={formatBps(executionQuality.exit.best_bps)} · worst={formatBps(executionQuality.exit.worst_bps)}
              </div>
            </div>
          </div>
          {executionQuality.warning_breached && executionQuality.warning_message && (
            <p className="text-warning text-xs mt-3">{executionQuality.warning_message}</p>
          )}
          {(executionQuality.buy.count > 0 || executionQuality.exit.count > 0) && (
            <div className="h-72 mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={[
                    {
                      bucket: 'BUY',
                      mean: executionQuality.buy.mean_bps,
                      p50: executionQuality.buy.p50_bps,
                      p95: executionQuality.buy.p95_bps,
                    },
                    {
                      bucket: 'EXIT',
                      mean: executionQuality.exit.mean_bps,
                      p50: executionQuality.exit.p50_bps,
                      p95: executionQuality.exit.p95_bps,
                    },
                  ]}
                  margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="bucket" stroke="rgba(255,255,255,0.45)" />
                  <YAxis stroke="rgba(255,255,255,0.45)" tickFormatter={(value) => `${value}bps`} />
                  <Tooltip formatter={(value: number) => formatBps(value)} />
                  <Legend />
                  <Bar dataKey="mean" fill="#00d4ff" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="p50" fill="#6332ff" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="p95" fill="#00ffa3" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {executionQuality && executionQuality.recent_partial_fills.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold tracking-wide mb-3">Open Partial Fills</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Time</th>
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Requested</th>
                  <th className="py-2 font-mono">Filled</th>
                  <th className="py-2 font-mono">Remaining</th>
                  <th className="py-2 font-mono">Status</th>
                  <th className="py-2 font-mono">Eligible</th>
                </tr>
              </thead>
              <tbody>
                {executionQuality.recent_partial_fills.map((order) => (
                  <tr key={order.id} className="border-b border-terminal-border">
                    <td className="py-1 font-mono text-xs">{safeFormat(order.timestamp, 'MMM dd HH:mm', '')}</td>
                    <td className="py-1 font-mono">{cleanTicker(order.ticker)}</td>
                    <td className="py-1 font-mono">{formatQuantity(order.requested_quantity)}</td>
                    <td className="py-1 font-mono">{formatQuantity(order.filled_quantity)}</td>
                    <td className="py-1 font-mono">{formatQuantity(order.remaining_quantity)}</td>
                    <td className="py-1">{order.status}</td>
                    <td className="py-1">
                      <StatusPill
                        label={order.resubmission_eligible ? 'Can Retry' : 'Observe'}
                        variant={order.resubmission_eligible ? 'warning' : 'dim'}
                        className="w-fit"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Recent Orders ({recentOrders.length})</h2>
        {recentOrders.length === 0 ? (
          <p className="text-terminal-text-dim">No orders yet.</p>
        ) : (
          <div className="overflow-x-auto max-h-64 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Time</th>
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Action</th>
                  <th className="py-2 font-mono">Qty</th>
                  <th className="py-2 font-mono">Decision</th>
                  <th className="py-2 font-mono">Fill</th>
                  <th className="py-2 font-mono">Slip bps</th>
                  <th className="py-2 font-mono">Remaining</th>
                  <th className="py-2 font-mono">Type</th>
                  <th className="py-2 font-mono">Status</th>
                  <th className="py-2 font-mono">Notes</th>
                  <th className="py-2 font-mono">Error</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((o) => (
                  <Fragment key={o.id}>
                    <tr className="border-b border-terminal-border">
                      <td className="py-1 font-mono text-xs">{safeFormat(o.timestamp, 'MMM dd HH:mm', '')}</td>
                      <td className="py-1 font-mono">{cleanTicker(o.ticker)}</td>
                      <td className="py-1">{o.action}</td>
                      <td className="py-1 font-mono">{formatQuantity(o.quantity)}</td>
                      <td className="py-1 font-mono">{o.decision_price != null ? o.decision_price.toFixed(2) : '—'}</td>
                      <td className="py-1 font-mono">{o.price != null ? o.price.toFixed(2) : '—'}</td>
                      <td className={`py-1 font-mono ${o.slippage_bps != null && o.slippage_bps > 0 ? 'text-warning' : ''}`}>
                        {formatBps(o.slippage_bps)}
                      </td>
                      <td className="py-1 font-mono">{formatQuantity(o.remaining_quantity)}</td>
                      <td className="py-1 text-terminal-text-dim">{o.order_type}</td>
                      <td className={`py-1 ${o.status === 'failed' ? 'text-loss' : ''}`}>{o.status}</td>
                      <td className="py-1 text-xs text-terminal-text-dim">
                        {o.warning_note ? 'note' : '—'}
                      </td>
                      <td className="py-1 text-xs text-terminal-text-dim">
                        {o.error_message || o.warning_note ? (
                          <button
                            type="button"
                            className="underline hover:text-terminal-text"
                            onClick={() => setExpandedErrorOrderId(expandedErrorOrderId === o.id ? null : o.id)}
                          >
                            {expandedErrorOrderId === o.id ? 'hide' : 'details'}
                          </button>
                        ) : '—'}
                      </td>
                    </tr>
                    {expandedErrorOrderId === o.id && o.error_message && (
                      <tr className="border-b border-terminal-border bg-terminal-surface/30">
                        <td className="py-2 text-xs text-terminal-text-dim" colSpan={12}>
                          <div><span className="font-semibold">Order ID:</span> {o.id}</div>
                          <div><span className="font-semibold">Broker ID:</span> {o.t212_order_id ?? '—'}</div>
                          <div><span className="font-semibold">Filled / Remaining:</span> {formatQuantity(o.filled_quantity)} / {formatQuantity(o.remaining_quantity)}</div>
                          <div><span className="font-semibold">Slippage:</span> {formatBps(o.slippage_bps)}</div>
                          {o.warning_note && (
                            <div className="mt-1 whitespace-pre-wrap break-words text-warning">
                              <span className="font-semibold">Note:</span> {o.warning_note}
                            </div>
                          )}
                          <div className="mt-1 whitespace-pre-wrap break-words">
                            <span className="font-semibold">Error:</span> {o.error_message}
                          </div>
                        </td>
                      </tr>
                    )}
                    {expandedErrorOrderId === o.id && !o.error_message && o.warning_note && (
                      <tr className="border-b border-terminal-border bg-terminal-surface/30">
                        <td className="py-2 text-xs text-terminal-text-dim" colSpan={12}>
                          <div><span className="font-semibold">Order ID:</span> {o.id}</div>
                          <div><span className="font-semibold">Broker ID:</span> {o.t212_order_id ?? '—'}</div>
                          <div><span className="font-semibold">Filled / Remaining:</span> {formatQuantity(o.filled_quantity)} / {formatQuantity(o.remaining_quantity)}</div>
                          <div><span className="font-semibold">Slippage:</span> {formatBps(o.slippage_bps)}</div>
                          <div className="mt-1 whitespace-pre-wrap break-words text-warning">
                            <span className="font-semibold">Note:</span> {o.warning_note}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Current Stop-Loss Levels ({current.length})</h2>
        <p className="text-xs text-terminal-text-dim mb-3">
          Live stop price is the broker/native stop. Profit-lock fields are shown in GBP so you can verify whether a winning position is fully protected above the policy threshold.
        </p>
        {current.length === 0 ? (
          <p className="text-terminal-text-dim">No stop levels (no positions or no stop orders).</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Live stop</th>
                  <th className="py-2 font-mono">Profit lock</th>
                  <th className="py-2 font-mono">Lock line GBP</th>
                  <th className="py-2 font-mono">Active stop GBP</th>
                  <th className="py-2 font-mono">Protected qty</th>
                  <th className="py-2 font-mono">Source</th>
                </tr>
              </thead>
              <tbody>
                {current.map((c) => (
                  <tr key={c.ticker} className="border-b border-terminal-border">
                    <td className="py-2 font-mono">{cleanTicker(c.ticker)}</td>
                    <td className="py-2 font-mono">{c.stop_price != null ? c.stop_price.toFixed(2) : '—'}</td>
                    <td className="py-2">
                      <StatusPill label={profitLockLabel(c.profit_lock_status)} variant={profitLockVariant(c.profit_lock_status)} className="w-fit" />
                    </td>
                    <td className="py-2 font-mono">{formatMoney(c.profit_lock_required_price_gbp)}</td>
                    <td className="py-2 font-mono">{formatMoney(c.profit_lock_stop_price_gbp)}</td>
                    <td className="py-2 font-mono">{formatQuantity(c.profit_lock_protected_qty)}</td>
                    <td className="py-2 text-terminal-text-dim">{c.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Adjustment History</h2>
        {adjustments.length === 0 ? (
          <p className="text-terminal-text-dim">No adjustments yet.</p>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Time</th>
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Type</th>
                  <th className="py-2 font-mono">Old → New</th>
                  <th className="py-2 font-mono">Reason</th>
                  <th className="py-2 font-mono">Status</th>
                </tr>
              </thead>
              <tbody>
                {adjustments.map((a) => (
                  <tr key={a.id} className="border-b border-terminal-border">
                    <td className="py-1 font-mono text-xs">{safeFormat(a.timestamp, 'MMM dd HH:mm', '')}</td>
                    <td className="py-1 font-mono">{a.ticker}</td>
                    <td className="py-1">{a.adjustment_type}</td>
                    <td className="py-1 font-mono">
                      {a.old_stop_price != null ? a.old_stop_price.toFixed(2) : '—'} →{' '}
                      {a.new_stop_price != null ? a.new_stop_price.toFixed(2) : '—'}
                    </td>
                    <td className="py-1 text-terminal-text-dim">{a.trigger_reason ?? '—'}</td>
                    <td className="py-1">{a.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
