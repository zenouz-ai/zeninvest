import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { publicApi } from '../api/client'
import { MetricCard } from '../components/MetricCard'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

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
  const snapshotDate = metrics?.snapshot_date ? safeFormat(metrics.snapshot_date, 'MMM dd, yyyy', 'Latest snapshot') : null

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Public Overview"
        description="Read-only dashboard view with aggregate performance and cost summaries. Operator controls and sensitive trading data require sign-in over HTTPS."
        titleMeta={snapshotDate ? <StatusPill label={snapshotDate} variant="draft" /> : undefined}
      />

      <Panel hero className="space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill label="Read Only" variant="live" dot />
              <StatusPill label="Aggregate Metrics" variant="draft" />
            </div>
            <p className="text-sm leading-6 text-terminal-text-muted">
              This public view mirrors the operator dashboard&apos;s visual language while intentionally exposing only rolled-up performance and cost data.
              It keeps the same premium control-room feel, without leaking private execution detail.
            </p>
          </div>
          <div className="rounded-panel border border-terminal-border bg-terminal-bg/40 px-4 py-3 text-sm text-terminal-text-dim">
            <div className="label-mono mb-1">Access Boundary</div>
            <div>Trading controls, positions, and order history stay behind operator sign-in.</div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Sharpe 30d"
            value={metrics?.sharpe_30d != null ? metrics.sharpe_30d.toFixed(2) : '—'}
            subtitle="Risk-adjusted return across the last 30 days."
          />
          <MetricCard
            label="Max Drawdown"
            value={metrics?.max_drawdown_pct != null ? `${metrics.max_drawdown_pct.toFixed(2)}%` : '—'}
            subtitle="Largest peak-to-trough decline in the public snapshot window."
            delta={metrics?.calmar_ratio != null ? `Calmar ${metrics.calmar_ratio.toFixed(2)}` : undefined}
            deltaColor="warning"
          />
          <MetricCard
            label="Latest Daily Cost"
            value={latestDaily ? `£${latestDaily.total_gbp.toFixed(2)}` : '—'}
            subtitle={latestDaily ? `${safeFormat(latestDaily.date, 'MMM dd, yyyy', latestDaily.date)} total spend.` : 'Most recent daily operating cost.'}
            delta={latestDaily ? `LLM £${latestDaily.llm_cost_gbp.toFixed(2)}` : undefined}
            deltaColor="cyan"
          />
          <MetricCard
            label="Latest Monthly Cost"
            value={latestMonth ? `£${latestMonth.total_gbp.toFixed(2)}` : '—'}
            subtitle={latestMonth ? `${latestMonth.year_month} aggregate spend.` : 'Most recent monthly operating cost.'}
            delta={metrics?.num_trades != null ? `${metrics.num_trades} trades` : undefined}
            deltaColor="emerald"
          />
        </div>
      </Panel>

      <Panel className="space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold tracking-[-0.02em]">Operator Access</h2>
            <p className="max-w-2xl text-sm leading-6 text-terminal-text-dim">
              Private tabs are available only after operator sign-in. Over public HTTP, operator login is intentionally blocked.
              Use HTTPS, or tunnel to localhost for maintenance until TLS is enabled.
            </p>
          </div>
          <StatusPill label="HTTPS Required" variant="warning" />
        </div>
        <div className="rounded-panel border border-terminal-border bg-terminal-bg/35 p-4">
          <p className="text-sm text-terminal-text-muted">
            Public users can inspect topline results and roadmap progress; operators get live system status, positions, runs, and execution tooling.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/login" className="btn-secondary">
            Operator sign in
          </Link>
          <Link to="/roadmap" className="btn-secondary">
            View roadmap
          </Link>
        </div>
      </Panel>

      <Panel className="space-y-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-[-0.02em]">Aggregate Costs</h2>
            <p className="mt-1 text-sm text-terminal-text-dim">
              Monthly operating totals across LLM, API, and research spend.
            </p>
          </div>
          <StatusPill label={`${monthlyCosts.length} months`} variant="dim" />
        </div>
        <div className="overflow-x-auto rounded-panel border border-terminal-border bg-terminal-bg/25">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border bg-white/[0.02] text-left">
                <th className="px-4 py-3 label-mono">Period</th>
                <th className="px-4 py-3 label-mono">Total</th>
                <th className="px-4 py-3 label-mono">LLM</th>
                <th className="px-4 py-3 label-mono">API</th>
                <th className="px-4 py-3 label-mono">Research</th>
              </tr>
            </thead>
            <tbody>
              {monthlyCosts.map((row) => (
                <tr key={row.year_month} className="border-b border-terminal-border/70 transition-colors hover:bg-white/[0.025] last:border-b-0">
                  <td className="px-4 py-3 font-mono">{row.year_month}</td>
                  <td className="px-4 py-3 font-mono">£{row.total_gbp.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono">£{row.llm_cost_gbp.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono">£{row.api_cost_gbp.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono">£{row.research_cost_gbp.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
