import { useEffect, useState } from 'react'
import { publicApi } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { MetricCard } from '../components/MetricCard'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'

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

export default function PublicCosts() {
  const [daily, setDaily] = useState<PublicDailyCost[]>([])
  const [monthly, setMonthly] = useState<PublicMonthlyCost[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      setError(null)
      try {
        const [dailyData, monthlyData] = await Promise.all([
          publicApi.getDailyCosts({ days: 14 }),
          publicApi.getMonthlyCosts({ months: 6 }),
        ])
        if (!cancelled) {
          setDaily(dailyData)
          setMonthly(monthlyData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public costs')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void fetchData()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <SkeletonCard lines={8} />

  const latestDaily = daily[0]
  const latestMonthly = monthly[0]

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Costs"
        description="A public aggregate view of operating costs. The anonymous surface shows daily and monthly totals only, without provider-specific degradation controls or internal cost diagnostics."
      />

      <PublicPageBanner
        mode="live"
        message="Public cost reporting is aggregated and read-only. Provider-level controls, degradation status, and per-cycle operational telemetry remain private."
      />

      {error ? (
        <Panel>
          <EmptyState message="Public costs unavailable." hint={error} />
        </Panel>
      ) : (
        <>
          <Panel hero>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Latest Daily Total"
                value={latestDaily ? `£${latestDaily.total_gbp.toFixed(2)}` : '—'}
                subtitle="Combined public-safe daily operating total."
              />
              <MetricCard
                label="Latest Monthly Total"
                value={latestMonthly ? `£${latestMonthly.total_gbp.toFixed(2)}` : '—'}
                subtitle="Combined public-safe monthly operating total."
              />
              <MetricCard
                label="Daily LLM"
                value={latestDaily ? `£${latestDaily.llm_cost_gbp.toFixed(2)}` : '—'}
                subtitle="Latest daily model usage total."
              />
              <MetricCard
                label="Daily API + Research"
                value={latestDaily ? `£${(latestDaily.api_cost_gbp + latestDaily.research_cost_gbp).toFixed(2)}` : '—'}
                subtitle="Latest daily non-LLM spend."
              />
            </div>
          </Panel>

          <Panel>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold tracking-[-0.02em]">Monthly Totals</h2>
                <p className="mt-1 text-sm text-terminal-text-dim">Six months of aggregate public cost reporting.</p>
              </div>
              <StatusPill label={`${monthly.length} months`} variant="dim" />
            </div>
            {monthly.length === 0 ? (
              <EmptyState message="No public monthly totals yet." />
            ) : (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-terminal-border text-left">
                      <th className="px-4 py-3 label-mono">Period</th>
                      <th className="px-4 py-3 label-mono">Total</th>
                      <th className="px-4 py-3 label-mono">LLM</th>
                      <th className="px-4 py-3 label-mono">API</th>
                      <th className="px-4 py-3 label-mono">Research</th>
                    </tr>
                  </thead>
                  <tbody>
                    {monthly.map((row) => (
                      <tr key={row.year_month} className="border-b border-terminal-border/70 last:border-b-0">
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
            )}
          </Panel>
        </>
      )}
    </div>
  )
}
