import { useEffect, useState } from 'react'
import { stopLossApi } from '../api/client'
import { safeFormat } from '../utils/date'

export default function OrderManagement() {
  const [current, setCurrent] = useState<{ ticker: string; stop_price: number | null; source: string }[]>([])
  const [adjustments, setAdjustments] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [currentData, adjData] = await Promise.all([
          stopLossApi.getCurrent(),
          stopLossApi.getAdjustments({ limit: 50 }),
        ])
        setCurrent(currentData)
        setAdjustments(adjData)
      } catch (e) {
        console.error('Failed to fetch stop-loss data:', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Order Management</h1>
        <p className="text-terminal-text-dim text-sm mt-1 max-w-2xl">
          Stop-loss levels for current positions and history of adjustments (ATR reassessment, trailing stops, limit orders). Source indicates whether the stop came from an order, an adjustment, or if the position has no stop yet.
        </p>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Current Stop-Loss Levels ({current.length})</h2>
        {current.length === 0 ? (
          <p className="text-terminal-text-dim">No stop levels (no positions or no stop orders).</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
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
              <thead>
                <tr className="border-b border-terminal-border text-left sticky top-0 bg-terminal-surface">
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
