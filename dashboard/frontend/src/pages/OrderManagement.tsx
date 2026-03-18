import { useEffect, useState } from 'react'
import { ordersApi, stopLossApi } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'

function cleanTicker(t: string) {
  return t.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '')
}

export default function OrderManagement() {
  const [current, setCurrent] = useState<{ ticker: string; stop_price: number | null; source: string }[]>([])
  const [adjustments, setAdjustments] = useState<any[]>([])
  const [recentOrders, setRecentOrders] = useState<any[]>([])
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
      setCurrent(currentData)
      setAdjustments(adjData)
      setRecentOrders(ordersData)
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
    return <LoadingSpinner />
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
        description="Stop-loss levels for current positions and history of adjustments (ATR reassessment, trailing stops, limit orders). Recent market orders (BUY/SELL/REDUCE) are listed below."
      />

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Recent Orders ({recentOrders.length})</h2>
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
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((o) => (
                  <tr key={o.id} className="border-b border-terminal-border">
                    <td className="py-1 font-mono text-xs">{safeFormat(o.timestamp, 'MMM dd HH:mm', '')}</td>
                    <td className="py-1 font-mono">{cleanTicker(o.ticker)}</td>
                    <td className="py-1">{o.action}</td>
                    <td className="py-1 font-mono">{o.quantity}</td>
                    <td className="py-1 text-terminal-text-dim">{o.order_type}</td>
                    <td className="py-1">{o.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Current Stop-Loss Levels ({current.length})</h2>
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
        <h2 className="text-lg font-semibold mb-3">Adjustment History</h2>
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
