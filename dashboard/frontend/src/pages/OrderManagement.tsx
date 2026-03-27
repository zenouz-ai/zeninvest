import { Fragment, useEffect, useState } from 'react'
import { ordersApi, stopLossApi } from '../api/client'
import { TableSkeleton } from '../components/Skeleton'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'

function cleanTicker(t: string) {
  return t.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '')
}

export default function OrderManagement() {
  const [current, setCurrent] = useState<{ ticker: string; stop_price: number | null; source: string }[]>([])
  const [adjustments, setAdjustments] = useState<any[]>([])
  const [recentOrders, setRecentOrders] = useState<any[]>([])
  const [expandedErrorOrderId, setExpandedErrorOrderId] = useState<number | null>(null)
  const [health, setHealth] = useState<{
    failed_open_count: number
    pending_local_count: number
    pending_live_count: number
    stale_pending_count: number
    reconciled_pending_count: number
    unresolved_window_days: number
    last_reconciled_at: string
    live_fetch_error?: string | null
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = async () => {
    setError(null)
    try {
      const [currentData, adjData, ordersData] = await Promise.all([
        stopLossApi.getCurrent(),
        stopLossApi.getAdjustments({ limit: 50 }),
        ordersApi.list({ limit: 30 }),
      ])
      const healthData = await ordersApi.health({ unresolved_window_days: 7, reconcile_pending: true })
      setCurrent(currentData)
      setAdjustments(adjData)
      setRecentOrders(ordersData)
      setHealth(healthData)
    } catch (e) {
      console.error('Failed to fetch stop-loss data:', e)
      setError(e instanceof Error ? e.message : 'Failed to load stop-loss data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  if (loading) {
    return <TableSkeleton rows={5} cols={5} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); fetchData() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Order Management"
        description="Stop-loss levels for current positions and history of adjustments (ATR reassessment, trailing stops, limit orders). Recent broker orders include failure details and any off-hours placement notes."
      />

      {health && (
        <div className="card">
          <h2 className="text-lg font-semibold tracking-wide mb-3">Order Health</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div className="border border-terminal-border rounded-md p-3">
              <div className="text-terminal-text-dim">Unresolved failed</div>
              <div className={`font-mono text-lg ${health.failed_open_count > 0 ? 'text-loss' : 'text-profit'}`}>
                {health.failed_open_count}
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
              <div className="text-terminal-text-dim">Last reconciled</div>
              <div className="font-mono text-xs">{safeFormat(health.last_reconciled_at, 'MMM dd HH:mm:ss', '—')}</div>
            </div>
          </div>
          {health.live_fetch_error && (
            <p className="text-warning text-xs mt-2">
              Live pending fetch warning: {health.live_fetch_error}
            </p>
          )}
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
                      <td className="py-1 font-mono">{o.quantity}</td>
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
                        <td className="py-2 text-xs text-terminal-text-dim" colSpan={8}>
                          <div><span className="font-semibold">Order ID:</span> {o.id}</div>
                          <div><span className="font-semibold">Broker ID:</span> {o.t212_order_id ?? '—'}</div>
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
                        <td className="py-2 text-xs text-terminal-text-dim" colSpan={8}>
                          <div><span className="font-semibold">Order ID:</span> {o.id}</div>
                          <div><span className="font-semibold">Broker ID:</span> {o.t212_order_id ?? '—'}</div>
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
        {current.length === 0 ? (
          <p className="text-terminal-text-dim">No stop levels (no positions or no stop orders).</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Stop price</th>
                  <th className="py-2 font-mono">Source</th>
                </tr>
              </thead>
              <tbody>
                {current.map((c) => (
                  <tr key={c.ticker} className="border-b border-terminal-border">
                    <td className="py-2 font-mono">{c.ticker}</td>
                    <td className="py-2 font-mono">{c.stop_price != null ? c.stop_price.toFixed(2) : '—'}</td>
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
