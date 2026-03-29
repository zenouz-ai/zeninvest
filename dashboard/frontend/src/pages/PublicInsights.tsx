import { useEffect, useState } from 'react'
import { publicApi } from '../api/client'
import type { PublicGuidanceSnapshot } from '../types'
import { EmptyState } from '../components/EmptyState'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { PublicPageBanner } from '../components/PublicPageBanner'
import { PublicPreviewSurface } from '../components/PublicPreviewSurface'
import { SectionHeader } from '../components/SectionHeader'
import { SkeletonCard } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { safeFormat } from '../utils/date'

export default function PublicInsights() {
  const [latest, setLatest] = useState<PublicGuidanceSnapshot | null>(null)
  const [history, setHistory] = useState<PublicGuidanceSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      setError(null)
      try {
        const [latestData, historyData] = await Promise.all([
          publicApi.getGuidanceLatest(),
          publicApi.getGuidanceHistory(14),
        ])
        if (!cancelled) {
          setLatest(latestData)
          setHistory(historyData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load public insights')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void fetchData()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <SkeletonCard lines={10} />

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="PUBLIC"
        title="Insights"
        description="A public-safe view of current market guidance. Repo-linked strategy attribution remains operator-only."
      />

      <PublicPageBanner
        mode="live"
        message="The public Insights surface exposes only sanitized market guidance. Cycle fingerprints, repo-linked change episodes, and attribution review controls remain private."
      />

      <Panel hero>
        <SectionHeader
          eyebrow="LATEST"
          title="Current Market Guidance"
          subtitle={latest ? safeFormat(latest.timestamp, 'MMM dd, HH:mm', '—') : 'No guidance snapshot yet'}
        />
        {error ? (
          <p className="mt-4 text-loss text-sm">{error}</p>
        ) : latest ? (
          <div className="mt-4 space-y-4">
            <div className="flex items-center gap-3 flex-wrap">
              <StatusPill label={latest.regime} variant={latest.regime === 'RISK_OFF' ? 'alert' : latest.regime === 'RISK_ON' ? 'active' : 'dim'} dot />
              <StatusPill label={latest.status} variant={latest.status === 'active' ? 'live' : latest.status === 'stale' ? 'warning' : 'alert'} />
              <StatusPill label={`${Math.round(latest.confidence_score * 100)}% confidence`} variant="dim" />
            </div>
            <p className="text-sm text-terminal-text">{latest.prompt_summary ?? latest.rationale}</p>
            <div className="grid gap-3 md:grid-cols-3">
              {latest.sector_scores.length > 0 ? latest.sector_scores.map((item) => (
                <div key={item.sector} className="rounded-panel border border-terminal-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-terminal-text">{item.sector}</span>
                    <StatusPill
                      label={item.label}
                      variant={item.label === 'favored' ? 'active' : item.label === 'avoid' ? 'alert' : 'dim'}
                    />
                  </div>
                  <p className="mt-2 text-sm text-terminal-text-dim">{item.rationale ?? 'No public rationale recorded.'}</p>
                </div>
              )) : (
                <EmptyState message="No sector tilts published yet." hint="Snapshots appear after the first macro-guided cycle completes." />
              )}
            </div>
          </div>
        ) : (
          <EmptyState message="No public guidance snapshot yet." hint="Run a cycle to publish the first market-guidance summary." />
        )}
      </Panel>

      <Panel>
        <SectionHeader eyebrow="HISTORY" title="Recent Guidance History" subtitle={`${history.length} snapshots in the public window`} />
        <div className="mt-4 space-y-3">
          {history.length === 0 ? (
            <EmptyState message="No public guidance history yet." hint="History appears after guidance snapshots are persisted." />
          ) : history.map((item) => (
            <div key={`${item.timestamp}-${item.regime}`} className="rounded-panel border border-terminal-border p-3">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <StatusPill label={item.regime} variant={item.regime === 'RISK_OFF' ? 'alert' : item.regime === 'RISK_ON' ? 'active' : 'dim'} dot />
                  <StatusPill label={item.status} variant={item.status === 'active' ? 'live' : item.status === 'stale' ? 'warning' : 'alert'} />
                </div>
                <span className="text-xs text-terminal-text-dim">{safeFormat(item.timestamp, 'MMM dd, HH:mm', '—')}</span>
              </div>
              <p className="mt-2 text-sm text-terminal-text-dim">{item.prompt_summary ?? item.rationale}</p>
            </div>
          ))}
        </div>
      </Panel>

      <PublicPreviewSurface
        title="Strategy Attribution"
        description="A preview of the private strategy-change review workflow."
        body="Repo-linked change episodes can reveal internal implementation details, commit history, and experimental fingerprints. The public surface keeps that workflow in preview-only mode."
      >
        <Panel className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill label="Guidance Live" variant="live" />
            <StatusPill label="Attribution Private" variant="warning" />
            <StatusPill label="Review Controls Locked" variant="alert" />
          </div>
          <div className="rounded-panel border border-terminal-border bg-white/[0.02] p-4">
            <p className="label-mono mb-2">Private Detail</p>
            <p className="text-sm text-terminal-text-dim">
              Operators can review proposed change episodes, confirm or reject them, and compare pre/post cycle windows. Anonymous visitors only see the existence of that workflow.
            </p>
          </div>
        </Panel>
      </PublicPreviewSurface>
    </div>
  )
}
