import { useEffect, useState } from 'react'
import { publicApi } from '../api/client'
import type { PublicRunSummary } from '../types'
import { EmptyState } from '../components/EmptyState'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

function auditVariant(run: PublicRunSummary) {
  if (run.audit_degraded) return 'warning' as const
  if (run.status === 'failed') return 'alert' as const
  if (run.status === 'completed') return 'active' as const
  return 'dim' as const
}

export default function PublicRuns() {
  const [rows, setRows] = useState<PublicRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchRows = async () => {
      setError(null)
      try {
        const data = await publicApi.getRuns({ limit: 5 })
        if (!cancelled) setRows(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public runs')
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
        title="Runs"
        description="A compact public ledger of recent analysis and refresh runs. The public surface exposes only timing, status, and coarse counts so visitors can understand the cadence without seeing cycle IDs or internal payloads."
      />

      <PublicPageBanner
        mode="live"
        message="Public run history is limited to the last five runs and shows high-level health only. Internal cycle IDs, diff tools, triggers, and detailed audit payloads remain private."
      />

      <Panel>
        {error ? (
          <EmptyState message="Public run history unavailable." hint={error} />
        ) : rows.length === 0 ? (
          <EmptyState message="No public runs yet." hint="Runs appear after the first dashboard-tracked cycle completes." />
        ) : (
          <div className="space-y-3">
            {rows.map((run, index) => (
              <div key={`${run.started_at}-${index}`} className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusPill label={run.status} variant={auditVariant(run)} />
                      <StatusPill label={run.run_type} variant="dim" />
                      <StatusPill label={run.audit_status === 'degraded' ? 'Audit degraded' : 'Audit healthy'} variant={run.audit_degraded ? 'warning' : 'active'} />
                    </div>
                    <p className="text-sm text-terminal-text-dim">
                      Started {safeFormat(run.started_at, 'MMM dd, yyyy HH:mm:ss', '—')}
                      {run.completed_at && ` · Completed ${safeFormat(run.completed_at, 'MMM dd, yyyy HH:mm:ss', '—')}`}
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="label-mono mb-1">Duration</div>
                    <div className="font-mono text-terminal-text">
                      {run.duration_seconds != null ? `${run.duration_seconds.toFixed(1)}s` : '—'}
                    </div>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div className="rounded-panel border border-terminal-border bg-terminal-bg/35 p-3 text-sm">
                    <div className="text-terminal-text-dim">Screened</div>
                    <div className="mt-1 font-heading text-2xl font-bold">{run.stocks_screened ?? '—'}</div>
                  </div>
                  <div className="rounded-panel border border-terminal-border bg-terminal-bg/35 p-3 text-sm">
                    <div className="text-terminal-text-dim">Decisions</div>
                    <div className="mt-1 font-heading text-2xl font-bold">{run.decisions_made ?? '—'}</div>
                  </div>
                  <div className="rounded-panel border border-terminal-border bg-terminal-bg/35 p-3 text-sm">
                    <div className="text-terminal-text-dim">Orders</div>
                    <div className="mt-1 font-heading text-2xl font-bold">{run.orders_placed ?? '—'}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
