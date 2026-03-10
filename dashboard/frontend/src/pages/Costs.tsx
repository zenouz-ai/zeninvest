import { useEffect, useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { costsApi } from '../api/client'

export default function Costs() {
  const [daily, setDaily] = useState<any[]>([])
  const [monthly, setMonthly] = useState<any[]>([])
  const [degradation, setDegradation] = useState<{ level: string; message?: string } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [dailyData, monthlyData, degData] = await Promise.all([
          costsApi.getDaily({ days: 30 }),
          costsApi.getMonthly({ months: 12 }),
          costsApi.getDegradation(),
        ])
        setDaily(dailyData)
        setMonthly(monthlyData)
        setDegradation(degData)
      } catch (e) {
        console.error('Failed to fetch costs:', e)
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

  const dailyChartData = daily.map((d) => ({
    date: d.date,
    anthropic: d.anthropic_gbp,
    openai: d.openai_gbp,
    google: d.google_gbp,
    total: d.total_gbp,
  }))

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Costs</h1>

      {degradation && (
        <div className="card flex items-center gap-4">
          <span className="text-terminal-text-dim">Degradation level:</span>
          <span
            className={`font-mono font-semibold px-2 py-1 rounded ${
              degradation.level === 'full' ? 'text-gain' : degradation.level === 'halted' ? 'text-loss' : 'text-warning'
            }`}
          >
            {degradation.level}
          </span>
          {degradation.message && (
            <span className="text-terminal-text-dim text-sm">{degradation.message}</span>
          )}
        </div>
      )}

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Daily cost by provider (last 30 days)</h2>
        {dailyChartData.length === 0 ? (
          <p className="text-terminal-text-dim">No cost data.</p>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dailyChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                <XAxis dataKey="date" stroke="#8b949e" fontSize={12} />
                <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `£${v.toFixed(2)}`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d' }}
                  labelStyle={{ color: '#e6edf3' }}
                  formatter={(value: number) => [`£${value.toFixed(4)}`, '']}
                />
                <Legend />
                <Area type="monotone" dataKey="anthropic" stackId="1" stroke="#00ff88" fill="#00ff8833" name="Anthropic" />
                <Area type="monotone" dataKey="openai" stackId="1" stroke="#58a6ff" fill="#58a6ff33" name="OpenAI" />
                <Area type="monotone" dataKey="google" stackId="1" stroke="#d4a017" fill="#d4a01733" name="Google" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-3">Monthly cumulative (£)</h2>
        {monthly.length === 0 ? (
          <p className="text-terminal-text-dim">No monthly data.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Month</th>
                  <th className="py-2 font-mono">Total</th>
                  <th className="py-2 font-mono">Anthropic</th>
                  <th className="py-2 font-mono">OpenAI</th>
                  <th className="py-2 font-mono">Google</th>
                </tr>
              </thead>
              <tbody>
                {monthly.map((m) => (
                  <tr key={m.year_month} className="border-b border-terminal-border">
                    <td className="py-2 font-mono">{m.year_month}</td>
                    <td className="py-2 font-mono">{m.total_gbp?.toFixed(2)}</td>
                    <td className="py-2 font-mono">{m.by_provider?.anthropic?.toFixed(2) ?? '—'}</td>
                    <td className="py-2 font-mono">{m.by_provider?.openai?.toFixed(2) ?? '—'}</td>
                    <td className="py-2 font-mono">{m.by_provider?.google?.toFixed(2) ?? '—'}</td>
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
