import { useEffect, useState } from 'react'
import { portfolioApi, systemApi } from '../api/client'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { PnlCurrency, PnlValue } from '../components/PnlDisplay'
import { LoadingSpinner } from '../components/LoadingSpinner'
import type { PortfolioSnapshot } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

export default function Portfolio() {
  const [currentPortfolio, setCurrentPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [history, setHistory] = useState<PortfolioSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [forceSellTicker, setForceSellTicker] = useState<string | null>(null)
  const [forceSellLoading, setForceSellLoading] = useState(false)
  const [forceSellResult, setForceSellResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const forceSellModalRef = useFocusTrap(forceSellTicker != null, () => setForceSellTicker(null))

  const fetchPortfolio = async () => {
    setError(null)
    try {
      const [current, historyData] = await Promise.all([
        portfolioApi.current(),
        portfolioApi.history({ limit: 30 }),
      ])
      setCurrentPortfolio(current)
      setHistory(historyData)
    } catch (err) {
      console.error('Failed to fetch portfolio:', err)
      setError(err instanceof Error ? err.message : 'Failed to load portfolio')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPortfolio()
    const interval = setInterval(fetchPortfolio, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const positions = currentPortfolio?.positions ?? []

  const sectorAllocation = positions.reduce((acc, pos) => {
    const sector = pos.sector ?? 'Unknown'
    acc[sector] = (acc[sector] || 0) + pos.value_gbp
    return acc
  }, {} as Record<string, number>)

  const pieData = Object.entries(sectorAllocation)
    .filter(([, value]) => value > 0)
    .map(([name, value]) => ({
      name,
      value: Number(value.toFixed(2)),
    }))

  const chartData = [...history]
    .reverse()
    .map((snapshot) => ({
      date: safeFormat(snapshot.timestamp, 'MMM dd', ''),
      value: snapshot.total_value_gbp,
    }))
    .filter((d) => d.date)

  const COLORS = ['#00d4ff', '#00ffa3', '#6332ff', '#ff4466', '#f7c948']

  const handleForceSell = async () => {
    if (!forceSellTicker) return
    setForceSellLoading(true)
    setForceSellResult(null)
    try {
      const result = await systemApi.forceSell(forceSellTicker)
      if (result.status === 'sold' || result.status === 'dry_run') {
        setForceSellResult({ type: 'success', message: `${cleanTicker(forceSellTicker)} sold (${result.quantity} shares) — ${result.status}` })
        fetchPortfolio()
      } else if (result.status === 'no_position') {
        setForceSellResult({ type: 'error', message: `No open position for ${cleanTicker(forceSellTicker)}` })
      } else {
        setForceSellResult({ type: 'error', message: result.error || 'Unknown error' })
      }
    } catch (err) {
      setForceSellResult({ type: 'error', message: err instanceof Error ? err.message : 'Force sell failed' })
    } finally {
      setForceSellLoading(false)
      setForceSellTicker(null)
    }
  }

  // Auto-dismiss result toast after 5s
  if (forceSellResult) {
    setTimeout(() => setForceSellResult(null), 5000)
  }

  if (loading) {
    return <LoadingSpinner />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); fetchPortfolio() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Portfolio"
        titleMeta={
          currentPortfolio ? (
            <div className="text-right">
              <div className="text-sm text-terminal-text-dim">Total Value</div>
              <div className="text-2xl font-mono font-bold">
                £{currentPortfolio.total_value_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </div>
            </div>
          ) : null
        }
        description="Current positions, cash, and value history from the latest snapshot (updated each run). Charts show portfolio value over time and sector allocation. Positions table lists ticker, quantity, value, and P&L per position."
      />

      {/* Force Sell confirmation modal */}
      {forceSellTicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setForceSellTicker(null)}>
          <div ref={forceSellModalRef} className="bg-terminal-surface border border-terminal-border rounded-lg p-4 max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-semibold text-loss mb-2">Force sell {cleanTicker(forceSellTicker)}?</h3>
            <p className="text-sm text-terminal-text-dim mb-4">
              This will immediately sell the entire position at market price. This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setForceSellTicker(null)} className="btn-secondary text-sm py-1.5">Cancel</button>
              <button type="button" onClick={handleForceSell} disabled={forceSellLoading} className="btn-danger-solid text-sm py-1.5 disabled:opacity-50">
                {forceSellLoading ? 'Selling...' : 'Force Sell'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Result toast */}
      {forceSellResult && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded shadow-lg text-sm font-mono ${forceSellResult.type === 'success' ? 'bg-gain/20 border border-gain/40 text-gain' : 'bg-loss/20 border border-loss/40 text-loss'}`}>
          {forceSellResult.message}
        </div>
      )}

      {/* Portfolio Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Cash Balance</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio
              ? `£${currentPortfolio.cash_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Investments</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio
              ? `£${currentPortfolio.invested_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Positions</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio?.num_positions ?? positions.length}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Last Updated</div>
          <div className="text-sm font-mono mt-1">
            {currentPortfolio
              ? safeFormat(currentPortfolio.timestamp, 'MMM dd, yyyy HH:mm', 'N/A')
              : 'N/A'}
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Portfolio Value Chart */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Portfolio Value History</h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                <XAxis dataKey="date" stroke="#8b949e" />
                <YAxis stroke="#8b949e" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0d1117',
                    border: '1px solid #30363d',
                    color: '#e6edf3',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#00d4ff"
                  strokeWidth={2}
                  dot={{ fill: '#00d4ff', r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-terminal-text-dim">
              No history data available
            </div>
          )}
        </div>

        {/* Sector Allocation */}
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Sector Allocation</h3>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) =>
                    `${name}: ${(percent * 100).toFixed(0)}%`
                  }
                  outerRadius={80}
                  fill="#00d4ff"
                  dataKey="value"
                >
                  {pieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0d1117',
                    border: '1px solid #30363d',
                    color: '#e6edf3',
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-terminal-text-dim">
              No positions
            </div>
          )}
        </div>
      </div>

      {/* Positions Table */}
      <div className="card">
        <h3 className="text-lg font-semibold mb-4">Current Positions</h3>
        {positions.length === 0 ? (
          <div className="text-center py-8 text-terminal-text-dim">
            No positions
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-terminal-border">
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Ticker
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Sector
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Quantity
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Value
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    P&L
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    P&L %
                  </th>
                  <th className="px-4 py-3 text-right text-sm font-semibold text-terminal-text-dim">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr
                    key={pos.ticker}
                    className="border-b border-terminal-border hover:bg-terminal-surface/50"
                  >
                    <td className="px-4 py-3 font-mono font-semibold">
                      {cleanTicker(pos.ticker)}
                    </td>
                    <td className="px-4 py-3 text-sm">{pos.sector ?? '—'}</td>
                    <td className="px-4 py-3 font-mono">{pos.quantity}</td>
                    <td className="px-4 py-3 font-mono">
                      £{pos.value_gbp.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <PnlCurrency value={pos.pnl_gbp} />
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <PnlValue value={pos.pnl_pct} suffix="%" />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => setForceSellTicker(pos.ticker)}
                        className="text-xs text-loss hover:text-loss/80 border border-loss/30 hover:border-loss/60 rounded px-2 py-0.5 transition-colors"
                      >
                        Force Sell
                      </button>
                    </td>
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
