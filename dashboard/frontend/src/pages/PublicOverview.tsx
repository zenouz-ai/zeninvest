import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { publicApi } from '../api/client'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { SkeletonCard } from '../components/Skeleton'

type PublicMetric = {
  snapshot_date?: string
  sharpe_30d?: number | null
  sharpe_60d?: number | null
  sharpe_90d?: number | null
  max_drawdown_pct?: number | null
  calmar_ratio?: number | null
  num_trades?: number | null
}

type PublicDailyCost = {
  date: string
  total_gbp: number
  llm_cost_gbp: number
  api_cost_gbp: number
  research_cost_gbp: number
}

type PublicMonthlyCost = {
  year_month: string
  total_gbp: number
  llm_cost_gbp: number
  api_cost_gbp: number
  research_cost_gbp: number
}

export default function PublicOverview() {
  const [metrics, setMetrics] = useState<PublicMetric | null>(null)
  const [dailyCosts, setDailyCosts] = useState<PublicDailyCost[]>([])
  const [monthlyCosts, setMonthlyCosts] = useState<PublicMonthlyCost[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [metricsData, dailyData, monthlyData] = await Promise.all([
        publicApi.getPerformanceMetrics(),
        publicApi.getDailyCosts({ days: 14 }),
        publicApi.getMonthlyCosts({ months: 6 }),
      ])
      setMetrics(metricsData)
      setDailyCosts(dailyData)
      setMonthlyCosts(monthlyData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load public dashboard')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchData()
  }, [])

  if (loading) {
    return <SkeletonCard lines={8} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { void fetchData() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  const latestDaily = dailyCosts[0] ?? null
  const latestMonth = monthlyCosts[0] ?? null

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Public Overview"
        description="Read-only dashboard view with aggregate performance and cost summaries. Operator controls and sensitive trading data require sign-in over HTTPS."
      />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Sharpe 30d</div>
          <div className="text-2xl font-heading text-terminal-text mt-2">
            {metrics?.sharpe_30d != null ? metrics.sharpe_30d.toFixed(2) : '—'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Max Drawdown</div>
          <div className="text-2xl font-heading text-terminal-text mt-2">
            {metrics?.max_drawdown_pct != null ? `${metrics.max_drawdown_pct.toFixed(2)}%` : '—'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Latest Daily Cost</div>
          <div className="text-2xl font-heading text-terminal-text mt-2">
            {latestDaily ? `£${latestDaily.total_gbp.toFixed(2)}` : '—'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Latest Monthly Cost</div>
          <div className="text-2xl font-heading text-terminal-text mt-2">
            {latestMonth ? `£${latestMonth.total_gbp.toFixed(2)}` : '—'}
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-2">Operator Access</h2>
        <p className="text-terminal-text-dim text-sm">
          Private tabs are available only after operator sign-in. Over public HTTP, operator login is intentionally blocked.
          Use HTTPS, or tunnel to localhost for maintenance until TLS is enabled.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link to="/login" className="btn-secondary">
            Operator sign in
          </Link>
          <Link to="/roadmap" className="btn-secondary">
            View roadmap
          </Link>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Aggregate Costs</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-left">
                <th className="py-2 font-mono">Period</th>
                <th className="py-2 font-mono">Total</th>
                <th className="py-2 font-mono">LLM</th>
                <th className="py-2 font-mono">API</th>
                <th className="py-2 font-mono">Research</th>
              </tr>
            </thead>
            <tbody>
              {monthlyCosts.map((row) => (
                <tr key={row.year_month} className="border-b border-terminal-border">
                  <td className="py-2 font-mono">{row.year_month}</td>
                  <td className="py-2 font-mono">£{row.total_gbp.toFixed(2)}</td>
                  <td className="py-2 font-mono">£{row.llm_cost_gbp.toFixed(2)}</td>
                  <td className="py-2 font-mono">£{row.api_cost_gbp.toFixed(2)}</td>
                  <td className="py-2 font-mono">£{row.research_cost_gbp.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
