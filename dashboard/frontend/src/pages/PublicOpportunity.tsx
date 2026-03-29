import { useEffect, useState } from 'react'
import { publicApi } from '../api/client'
import type { PublicOpportunityPreview } from '../types'
import { EmptyState } from '../components/EmptyState'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

function scoreVariant(label: string) {
  if (label === 'High Priority') return 'active' as const
  if (label === 'Promising') return 'live' as const
  return 'dim' as const
}

export default function PublicOpportunity() {
  const [rows, setRows] = useState<PublicOpportunityPreview[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchRows = async () => {
      setError(null)
      try {
        const data = await publicApi.getOpportunity({ limit: 5 })
        if (!cancelled) setRows(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public opportunity preview')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void fetchRows()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <SkeletonCard lines={8} />

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Opportunity"
        description="A safe preview of the opportunity pipeline. The public view shows a few sample names, stages, and broad score bands without exposing exact UOV values, capacity decisions, or model reasoning."
      />

      <PublicPageBanner
        mode="live"
        message="Only five public-safe opportunities are shown here. Exact queue thresholds, score values, and internal promotion logic remain operator-only."
      />

      <Panel>
        {error ? (
          <EmptyState message="Public opportunity preview unavailable." hint={error} />
        ) : rows.length === 0 ? (
          <EmptyState message="No public opportunity rows yet." hint="Rows appear after score or queue snapshots are written." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left">
                  <th className="px-4 py-3 label-mono">Ticker</th>
                  <th className="px-4 py-3 label-mono">Name</th>
                  <th className="px-4 py-3 label-mono">Sector</th>
                  <th className="px-4 py-3 label-mono">Stage</th>
                  <th className="px-4 py-3 label-mono">Action</th>
                  <th className="px-4 py-3 label-mono">Score Band</th>
                  <th className="px-4 py-3 label-mono">Last Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.ticker}-${row.last_updated}`} className="border-b border-terminal-border/70 last:border-b-0">
                    <td className="px-4 py-3 font-mono">{row.ticker}</td>
                    <td className="px-4 py-3">{row.name ?? '—'}</td>
                    <td className="px-4 py-3 text-terminal-text-dim">{row.sector ?? '—'}</td>
                    <td className="px-4 py-3">{row.stage}</td>
                    <td className="px-4 py-3">{row.action}</td>
                    <td className="px-4 py-3">
                      <StatusPill label={row.score_band} variant={scoreVariant(row.score_band)} />
                    </td>
                    <td className="px-4 py-3 text-terminal-text-dim">{safeFormat(row.last_updated, 'MMM dd, yyyy HH:mm', '—')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
