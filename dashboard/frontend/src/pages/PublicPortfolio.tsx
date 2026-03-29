import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { publicApi } from '../api/client'
import type { PublicPortfolioHistoryPoint, PublicPortfolioSnapshot } from '../types'
import { EmptyState } from '../components/EmptyState'
import { MetricCard } from '../components/MetricCard'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

export function PublicPortfolioPage({
  initialSnapshot,
  initialHistory,
}: {
  initialSnapshot?: PublicPortfolioSnapshot | null
  initialHistory?: PublicPortfolioHistoryPoint[]
}) {
  const [snapshot, setSnapshot] = useState<PublicPortfolioSnapshot | null>(initialSnapshot ?? null)
  const [history, setHistory] = useState<PublicPortfolioHistoryPoint[]>(initialHistory ?? [])
  const [loading, setLoading] = useState(initialSnapshot === undefined || initialHistory === undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialSnapshot !== undefined && initialHistory !== undefined) return
    let cancelled = false
    const fetchData = async () => {
      setError(null)
      try {
        const [snapshotData, historyData] = await Promise.all([
          publicApi.getPortfolioCurrent(),
          publicApi.getPortfolioHistory({ limit: 180 }),
        ])
        if (!cancelled) {
          setSnapshot(snapshotData)
          setHistory(historyData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public portfolio')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void fetchData()
    return () => {
      cancelled = true
    }
  }, [initialHistory, initialSnapshot])

  const chartData = useMemo(
    () =>
      history.map((point) => ({
        ...point,
        label: safeFormat(point.timestamp, 'MMM dd', ''),
      })),
    [history]
  )

  if (loading) return <SkeletonCard lines={8} />

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Portfolio"
        description="A normalized, read-only portfolio view. Public users can inspect allocation mix, protection posture, and a normalized performance index without seeing exact account values, trade controls, or broker-level detail."
      />

      <PublicPageBanner
        mode="live"
        message="This portfolio view is sanitized for public demo use. It shows percentages, counts, and normalized index history only. Exact account size, quantities, stops, and operator actions stay private."
      />

      {error ? (
        <Panel>
          <EmptyState message="Public portfolio unavailable." hint={error} />
        </Panel>
      ) : snapshot == null ? (
        <Panel>
          <EmptyState message="No public portfolio snapshot yet." hint="A snapshot appears after portfolio refresh data is available." />
        </Panel>
      ) : (
        <>
          <Panel hero>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <StatusPill label={snapshot.pnl_band} variant={snapshot.pnl_band === 'Outperforming' ? 'active' : snapshot.pnl_band === 'Underwater' ? 'alert' : 'dim'} />
                  <StatusPill label={`Top ${snapshot.positions_visible} visible`} variant="draft" />
                </div>
                <p className="text-sm text-terminal-text-dim">
                  Snapshot captured {safeFormat(snapshot.timestamp, 'MMM dd, yyyy HH:mm:ss', '—')}. The value line below is normalized to an index rather than exposing exact account balances.
                </p>
              </div>
              <div className="text-right">
                <div className="label-mono mb-1">Normalized Index</div>
                <div className="text-3xl font-heading font-bold text-terminal-text">{snapshot.value_index.toFixed(1)}</div>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Positions" value={snapshot.num_positions} subtitle="Total open holdings in the latest safe snapshot." />
              <MetricCard label="Cash Mix" value={`${snapshot.cash_pct.toFixed(1)}%`} subtitle="Cash share of the portfolio." />
              <MetricCard label="Invested Mix" value={`${snapshot.invested_pct.toFixed(1)}%`} subtitle="Invested share of the portfolio." />
              <MetricCard label="Protection" value={snapshot.protection_summary.protected_count} subtitle="Holdings currently marked as protected." />
            </div>
          </Panel>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
            <Panel>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold tracking-[-0.02em]">Normalized Value History</h2>
                  <p className="mt-1 text-sm text-terminal-text-dim">Index series rebased to 100 for safe public comparison.</p>
                </div>
              </div>
              {chartData.length === 0 ? (
                <EmptyState message="No normalized history yet." />
              ) : (
                <div className="mt-4 h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                      <XAxis dataKey="label" stroke="rgba(255,255,255,0.45)" />
                      <YAxis stroke="rgba(255,255,255,0.45)" tickFormatter={(value) => value.toFixed(0)} />
                      <Tooltip
                        formatter={(value: number) => [value.toFixed(2), 'Index']}
                        labelFormatter={(label) => `Date ${label}`}
                        contentStyle={{ backgroundColor: '#06060a', border: '1px solid rgba(0, 212, 255, 0.35)' }}
                      />
                      <Line type="monotone" dataKey="value_index" stroke="#00d4ff" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>

            <Panel className="space-y-4">
              <div>
                <h2 className="text-xl font-semibold tracking-[-0.02em]">Protection Posture</h2>
                <p className="mt-1 text-sm text-terminal-text-dim">Counts only. No stop prices or quantities are exposed publicly.</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <div className="text-terminal-text-dim">Protected</div>
                  <div className="mt-1 text-2xl font-heading font-bold">{snapshot.protection_summary.protected_count}</div>
                </div>
                <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <div className="text-terminal-text-dim">Needs Lock</div>
                  <div className="mt-1 text-2xl font-heading font-bold">{snapshot.protection_summary.needs_lock_count}</div>
                </div>
                <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <div className="text-terminal-text-dim">Exit Required</div>
                  <div className="mt-1 text-2xl font-heading font-bold">{snapshot.protection_summary.exit_required_count}</div>
                </div>
                <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-3">
                  <div className="text-terminal-text-dim">Inactive</div>
                  <div className="mt-1 text-2xl font-heading font-bold">{snapshot.protection_summary.inactive_count}</div>
                </div>
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <Panel>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold tracking-[-0.02em]">Visible Holdings</h2>
                  <p className="mt-1 text-sm text-terminal-text-dim">Top holdings by allocation, capped to the first five public rows.</p>
                </div>
                <StatusPill label={`Top ${snapshot.positions_visible}`} variant="dim" />
              </div>
              {snapshot.positions.length === 0 ? (
                <EmptyState message="No visible public holdings." />
              ) : (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-terminal-border text-left">
                        <th className="px-4 py-3 label-mono">Ticker</th>
                        <th className="px-4 py-3 label-mono">Sector</th>
                        <th className="px-4 py-3 label-mono">Allocation</th>
                        <th className="px-4 py-3 label-mono">P&amp;L Band</th>
                        <th className="px-4 py-3 label-mono">Protection</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.positions.map((position) => (
                        <tr key={position.ticker} className="border-b border-terminal-border/70 last:border-b-0">
                          <td className="px-4 py-3 font-mono">{position.ticker}</td>
                          <td className="px-4 py-3 text-terminal-text-dim">{position.sector ?? '—'}</td>
                          <td className="px-4 py-3 font-mono">{position.allocation_pct.toFixed(2)}%</td>
                          <td className="px-4 py-3">{position.pnl_band}</td>
                          <td className="px-4 py-3">{position.protection_status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            <Panel>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold tracking-[-0.02em]">Sector Allocation</h2>
                  <p className="mt-1 text-sm text-terminal-text-dim">Percent allocation only. Exact GBP exposure is withheld.</p>
                </div>
              </div>
              {snapshot.sector_allocations.length === 0 ? (
                <EmptyState message="No sector allocations available." />
              ) : (
                <div className="mt-4 space-y-3">
                  {snapshot.sector_allocations.map((sector) => (
                    <div key={sector.sector}>
                      <div className="mb-1 flex items-center justify-between gap-3 text-sm">
                        <span>{sector.sector}</span>
                        <span className="font-mono text-terminal-text-dim">{sector.allocation_pct.toFixed(2)}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-terminal-bg">
                        <div
                          className="h-2 rounded-full brand-gradient"
                          style={{ width: `${Math.min(100, Math.max(0, sector.allocation_pct))}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}

export default function PublicPortfolio() {
  return <PublicPortfolioPage />
}
