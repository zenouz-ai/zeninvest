import { useEffect, useState } from 'react'
import { publicApi } from '../api/client'
import type { PublicUniverseItem } from '../types'
import { EmptyState } from '../components/EmptyState'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

export default function PublicUniverse() {
  const [rows, setRows] = useState<PublicUniverseItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchRows = async () => {
      setError(null)
      try {
        const data = await publicApi.getUniverse({ limit: 10 })
        if (!cancelled) setRows(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public universe')
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
        title="Universe"
        description="A limited read-only sample of the instrument universe. The public view shows a safe slice of the screening universe without internal scores, research traces, or decision reasoning."
      />

      <PublicPageBanner
        mode="live"
        message="This public sample is capped at 10 instruments and exposes only descriptive screening metadata. Full universe filters, UOV scores, holdings, and reasoning remain operator-only."
      />

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-[-0.02em]">Universe Sample</h2>
            <p className="mt-1 text-sm text-terminal-text-dim">First 10 public-safe rows from the screening universe.</p>
          </div>
          <StatusPill label={`${rows.length} rows`} variant="dim" />
        </div>
      </Panel>

      <Panel>
        {error ? (
          <EmptyState message="Public universe unavailable." hint={error} />
        ) : rows.length === 0 ? (
          <EmptyState message="No public universe rows yet." hint="Rows appear after screening snapshots have been written." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left">
                  <th className="px-4 py-3 label-mono">Ticker</th>
                  <th className="px-4 py-3 label-mono">Name</th>
                  <th className="px-4 py-3 label-mono">Sector</th>
                  <th className="px-4 py-3 label-mono">Industry</th>
                  <th className="px-4 py-3 label-mono">Market Cap</th>
                  <th className="px-4 py-3 label-mono">Status</th>
                  <th className="px-4 py-3 label-mono">Last Screened</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.ticker} className="border-b border-terminal-border/70 last:border-b-0">
                    <td className="px-4 py-3 font-mono text-terminal-text">{row.ticker}</td>
                    <td className="px-4 py-3">{row.name ?? '—'}</td>
                    <td className="px-4 py-3 text-terminal-text-dim">{row.sector ?? '—'}</td>
                    <td className="px-4 py-3 text-terminal-text-dim">{row.industry ?? '—'}</td>
                    <td className="px-4 py-3">{row.market_cap_bucket}</td>
                    <td className="px-4 py-3">
                      <StatusPill label={row.status} variant={row.status === 'Available' ? 'active' : 'warning'} />
                    </td>
                    <td className="px-4 py-3 text-terminal-text-dim">
                      {row.last_screened_at ? safeFormat(row.last_screened_at, 'MMM dd, yyyy HH:mm', '—') : 'Never'}
                    </td>
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
