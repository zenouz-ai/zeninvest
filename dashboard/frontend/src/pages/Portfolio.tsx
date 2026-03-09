import { useEffect, useState } from 'react'
import { portfolioApi } from '../api/client'
import type { PortfolioSnapshot } from '../types'
import { cleanTicker } from '../types'
import { format } from 'date-fns'
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
  Legend,
} from 'recharts'

export default function Portfolio() {
  const [currentPortfolio, setCurrentPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [history, setHistory] = useState<PortfolioSnapshot[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const [current, historyData] = await Promise.all([
          portfolioApi.current(),
          portfolioApi.history({ limit: 30 }),
        ])
        setCurrentPortfolio(current)
        setHistory(historyData)
      } catch (error) {
        console.error('Failed to fetch portfolio:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchPortfolio()
    const interval = setInterval(fetchPortfolio, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const positions = currentPortfolio
    ? Object.values(currentPortfolio.positions_json || {})
    : []

  const sectorAllocation = positions.reduce((acc, pos) => {
    // Simplified - in real app, you'd fetch sector from instrument data
    const sector = 'Unknown' // Would need to join with instruments table
    acc[sector] = (acc[sector] || 0) + pos.value
    return acc
  }, {} as Record<string, number>)

  const pieData = Object.entries(sectorAllocation).map(([name, value]) => ({
    name,
    value: Number(value.toFixed(2)),
  }))

  const chartData = history.map((snapshot) => ({
    date: format(new Date(snapshot.snapshot_date), 'MMM dd'),
    value: snapshot.total_value,
  }))

  const COLORS = ['#4a9eff', '#00ff88', '#ffd700', '#ff4444', '#ffaa00']

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading portfolio...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        {currentPortfolio && (
          <div className="text-right">
            <div className="text-sm text-terminal-text-dim">Total Value</div>
            <div className="text-2xl font-mono font-bold">
              ${currentPortfolio.total_value.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
          </div>
        )}
      </div>

      {/* Portfolio Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Cash Balance</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio
              ? `$${currentPortfolio.cash_balance.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Positions</div>
          <div className="text-xl font-mono mt-1">{positions.length}</div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Last Updated</div>
          <div className="text-sm font-mono mt-1">
            {currentPortfolio
              ? format(new Date(currentPortfolio.snapshot_date), 'MMM dd, yyyy HH:mm')
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
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                <XAxis dataKey="date" stroke="#888888" />
                <YAxis stroke="#888888" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#141414',
                    border: '1px solid #2a2a2a',
                    color: '#e0e0e0',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#4a9eff"
                  strokeWidth={2}
                  dot={{ fill: '#4a9eff', r: 4 }}
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
                  fill="#8884d8"
                  dataKey="value"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#141414',
                    border: '1px solid #2a2a2a',
                    color: '#e0e0e0',
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
                    Quantity
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Avg Price
                  </th>
                  <th className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">
                    Current Price
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
                    <td className="px-4 py-3 font-mono">{pos.quantity}</td>
                    <td className="px-4 py-3 font-mono">
                      ${pos.avg_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 font-mono">
                      ${pos.current_price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 font-mono">
                      ${pos.value.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td
                      className={`px-4 py-3 font-mono ${
                        pos.pnl >= 0 ? 'text-gain' : 'text-loss'
                      }`}
                    >
                      {pos.pnl >= 0 ? '+' : ''}
                      ${pos.pnl.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </td>
                    <td
                      className={`px-4 py-3 font-mono ${
                        pos.pnl_pct >= 0 ? 'text-gain' : 'text-loss'
                      }`}
                    >
                      {pos.pnl_pct >= 0 ? '+' : ''}
                      {pos.pnl_pct.toFixed(2)}%
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
