import { useEffect, useState, useCallback } from 'react'
import { SkeletonCard } from '../components/Skeleton'
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
import { costsApi, researchApi, type ResearchSummary } from '../api/client'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { usePollingInterval } from '../hooks/usePollingInterval'

const COSTS_POLL_MS = 120_000

export default function Costs() {
  const [daily, setDaily] = useState<any[]>([])
  const [monthly, setMonthly] = useState<any[]>([])
  const [degradation, setDegradation] = useState<{ level: string; message?: string } | null>(null)
  const [researchSummary, setResearchSummary] = useState<ResearchSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setError(null)
    try {
      const [dailyData, monthlyData, degData, resSummary] = await Promise.all([
        costsApi.getDaily({ days: 30 }),
        costsApi.getMonthly({ months: 12 }),
        costsApi.getDegradation(),
        researchApi.getSummary().catch(() => null),
      ])
      setDaily(dailyData)
      setMonthly(monthlyData)
      setDegradation(degData)
      setResearchSummary(resSummary)
    } catch (e) {
      console.error('Failed to fetch costs:', e)
      setError(e instanceof Error ? e.message : 'Failed to load costs')
    } finally {
      setLoading(false)
    }
  }, [])

  const pollingActive = usePollingInterval(true, fetchData)

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  useEffect(() => {
    if (!pollingActive) return
    const interval = setInterval(() => { void fetchData() }, COSTS_POLL_MS)
    return () => clearInterval(interval)
  }, [fetchData, pollingActive])

  if (loading) {
    return <SkeletonCard lines={6} />
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

  const dailyChartData = daily
    .map((d) => {
      const llm = (d.llm_cost_gbp ?? d.total_gbp) || 0
      const api = d.api_cost_gbp ?? 0
      const research = d.research_cost_gbp ?? 0
      return {
        date: d.date,
        anthropic: d.anthropic_gbp,
        openai: d.openai_gbp,
        google: d.google_gbp,
        llm,
        api,
        research,
        total: llm + api + research,
      }
    })
    .sort((a, b) => a.date.localeCompare(b.date))

  const degradationHelp: Record<string, string> = {
    full: 'All LLMs active. Strategy (Claude), moderation (GPT-4o + Gemini) running normally.',
    no_gemini: 'Google daily budget exceeded. Gemini skipped; GPT-4o and Claude still active.',
    no_gpt4o: 'OpenAI daily budget exceeded. GPT-4o skipped; Claude strategy still runs.',
    no_strategy: 'Anthropic daily budget exceeded. No new trades proposed this cycle.',
    halted: 'Monthly cap exceeded. All LLM calls halted until next month.',
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Costs"
        description="LLM spend tracking and budget enforcement. Daily budgets (Anthropic £1, OpenAI £0.75, Google £0.50) plus a monthly cap (£50) control costs. If a budget is exceeded, the system degrades gracefully instead of failing. Use the charts and table to monitor spend by provider."
      />

      {degradation && (
        <div className="card">
          <div className="flex items-center gap-4 flex-wrap">
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
          <p className="text-terminal-text-dim text-xs mt-2">
            {degradationHelp[degradation.level] ?? 'Budget status determines which LLMs are available.'}
          </p>
          <details className="mt-2">
            <summary className="text-xs text-terminal-text-dim cursor-pointer hover:text-terminal-text">
              All degradation levels
            </summary>
            <ul className="mt-1 text-xs text-terminal-text-dim space-y-1 list-disc list-inside">
              <li><strong className="text-gain">full</strong> — All providers within budget</li>
              <li><strong className="text-warning">no_gemini</strong> — Skip Gemini (Google over daily)</li>
              <li><strong className="text-warning">no_gpt4o</strong> — Skip GPT-4o (OpenAI over daily)</li>
              <li><strong className="text-warning">no_strategy</strong> — Skip strategy cycle (Anthropic over daily)</li>
              <li><strong className="text-loss">halted</strong> — Monthly cap hit; all LLMs disabled</li>
            </ul>
          </details>
        </div>
      )}

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-1">Daily cost: API vs LLM (last 30 days)</h2>
        <p className="text-terminal-text-dim text-xs mb-3">
          Stacked: each line = cumulative sum up to that provider. Height of each band = that provider&apos;s cost.
        </p>
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
                  content={({ active, payload, label }) =>
                    active && payload?.length ? (
                      <div className="rounded border border-terminal-border bg-terminal-surface px-3 py-2 text-sm">
                        <div className="font-mono text-terminal-text-dim mb-1">{label}</div>
                        {payload.map((p) => (
                          <div key={p.dataKey} className="flex justify-between gap-4">
                            <span style={{ color: p.color }}>{p.name}</span>
                            <span className="font-mono">£{Number(p.value).toFixed(4)}</span>
                          </div>
                        ))}
                        <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-terminal-border text-terminal-text-dim text-xs">
                          <span>Total (stacked)</span>
                          <span className="font-mono">
                            £{payload.reduce((s, p) => s + (Number(p.value) || 0), 0).toFixed(4)}
                          </span>
                        </div>
                      </div>
                    ) : null
                  }
                />
                <Legend />
                <Area type="monotone" dataKey="api" stackId="1" stroke="#ff4466" fill="#ff446633" name="API (Brave/Tavily)" />
                <Area type="monotone" dataKey="research" stackId="1" stroke="#c084fc" fill="#c084fc33" name="Agentic Research" />
                <Area type="monotone" dataKey="anthropic" stackId="1" stroke="#00ffa3" fill="#00ffa333" name="Anthropic" />
                <Area type="monotone" dataKey="openai" stackId="1" stroke="#00d4ff" fill="#00d4ff33" name="OpenAI" />
                <Area type="monotone" dataKey="google" stackId="1" stroke="#6332ff" fill="#6332ff33" name="Google" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Monthly cumulative (£): API vs LLM</h2>
        {monthly.length === 0 ? (
          <p className="text-terminal-text-dim">No monthly data.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Month</th>
                  <th className="py-2 font-mono">Total</th>
                  <th className="py-2 font-mono">API</th>
                  <th className="py-2 font-mono">Research</th>
                  <th className="py-2 font-mono">LLM</th>
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
                    <td className="py-2 font-mono">£{(m.api_cost_gbp ?? 0).toFixed(2)}</td>
                    <td className="py-2 font-mono" style={{ color: '#c084fc' }}>£{(m.research_cost_gbp ?? 0).toFixed(2)}</td>
                    <td className="py-2 font-mono">£{(m.llm_cost_gbp ?? 0).toFixed(2)}</td>
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

      {researchSummary && researchSummary.total_calls > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold tracking-wide mb-1">Agentic Research Cost Breakdown</h2>
          <p className="text-terminal-text-dim text-xs mb-3">
            Research tool calls made by Strategy, Skeptic, and Risk during pipeline cycles.
            Cost derived from research_logs ($0.005 per paid Brave/Tavily call; SEC EDGAR is free).
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            <div className="bg-terminal-surface/30 rounded p-3 border border-terminal-border">
              <div className="text-terminal-text-dim text-xs">Total calls</div>
              <div className="text-xl font-mono font-semibold">{researchSummary.total_calls}</div>
            </div>
            <div className="bg-terminal-surface/30 rounded p-3 border border-terminal-border">
              <div className="text-terminal-text-dim text-xs">Total cost (USD)</div>
              <div className="text-xl font-mono font-semibold" style={{ color: '#c084fc' }}>
                ${researchSummary.total_cost_usd.toFixed(3)}
              </div>
            </div>
            <div className="bg-terminal-surface/30 rounded p-3 border border-terminal-border">
              <div className="text-terminal-text-dim text-xs">Cache hit rate</div>
              <div className="text-xl font-mono font-semibold text-gain">
                {(researchSummary.cache_hit_rate * 100).toFixed(1)}%
              </div>
            </div>
            <div className="bg-terminal-surface/30 rounded p-3 border border-terminal-border">
              <div className="text-terminal-text-dim text-xs">Avg latency</div>
              <div className="text-xl font-mono font-semibold">
                {researchSummary.avg_latency_ms != null ? `${researchSummary.avg_latency_ms.toFixed(0)}ms` : '—'}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <h3 className="text-sm font-semibold mb-2 text-terminal-text-dim">By Member</h3>
              <div className="space-y-1">
                {Object.entries(researchSummary.by_member).map(([member, data]) => (
                  <div key={member} className="flex justify-between text-xs">
                    <span className="text-terminal-text">
                      {member === 'strategy' ? 'Strategy (Claude)' : member === 'skeptic' ? 'Skeptic (GPT-4o)' : member === 'risk' ? 'Risk (Gemini)' : member}
                    </span>
                    <span className="font-mono text-terminal-text-dim">
                      {data.calls} calls · ${data.cost_usd.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold mb-2 text-terminal-text-dim">By Tool</h3>
              <div className="space-y-1">
                {Object.entries(researchSummary.by_tool).map(([tool, data]) => (
                  <div key={tool} className="flex justify-between text-xs">
                    <span className="text-terminal-text">{tool}</span>
                    <span className="font-mono text-terminal-text-dim">
                      {data.calls} calls · ${data.cost_usd.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold mb-2 text-terminal-text-dim">By Provider</h3>
              <div className="space-y-1">
                {Object.entries(researchSummary.by_provider).map(([provider, data]) => (
                  <div key={provider} className="flex justify-between text-xs">
                    <span className="text-terminal-text">{provider}</span>
                    <span className="font-mono text-terminal-text-dim">
                      {data.calls} calls · ${data.cost_usd.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
