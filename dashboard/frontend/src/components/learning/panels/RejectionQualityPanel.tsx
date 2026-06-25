import { useEffect, useState } from 'react'
import { learningApi, type RejectionAnalysisResponse } from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'

const RETUNE_FALSE_REJECT_THRESHOLD = 0.25

function formatRate(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return 'n/a'
  return `${(value * 100).toFixed(1)}%`
}

function formatGap(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return 'n/a'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatRet(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return 'n/a'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

interface StatCardProps {
  label: string
  value: string
  tone?: 'default' | 'loss'
}

function StatCard({ label, value, tone = 'default' }: StatCardProps) {
  return (
    <div className="px-3 py-2 border border-terminal-border rounded-panel">
      <p className="text-xs uppercase tracking-wide text-terminal-text-dim mb-1">{label}</p>
      <p className={`text-lg font-mono ${tone === 'loss' ? 'text-loss' : 'text-terminal-text'}`}>{value}</p>
    </div>
  )
}

export function RejectionQualityPanel() {
  const [data, setData] = useState<RejectionAnalysisResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const resp = await learningApi.getRejectionAnalysis().catch(() => null)
        if (cancelled) return
        setData(resp)
        setLoaded(true)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load rejection analysis')
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const caption = (
    <p className="text-xs text-terminal-text-dim mt-4">
      Mark-to-market counterfactual on declined tickers (v6 bands). Directional, not a P&amp;L claim.
    </p>
  )

  return (
    <Panel data-testid="learning-rejection-panel">
      <SectionHeader
        title="Rejection quality"
        subtitle="Did the gate decline tickers that would have lost?"
      />
      <InfoCallout
        why="Measures whether declined tickers underperformed (good misses) or would have been winners (false rejects), to validate or re-tune the gate."
        freshAsOf={data?.generated_at ?? data?.artifact_mtime ?? null}
        freshSource="rejected_analysis_*.json summary + data/learning/parquet/v6/rejected.parquet row dataset"
        action="poetry run python scripts/analyze_rejected_tickers.py"
        roadmapId="US-6.7"
      />
      {error ? <p className="text-sm text-loss">{error}</p> : null}

      {!loaded ? (
        <p className="text-sm text-terminal-text-muted">Loading rejection analysis…</p>
      ) : !data || data.available === false ? (
        <p className="text-sm text-terminal-text-muted">
          No rejection analysis artifact yet.{' '}
          {data?.hint ? <code className="text-terminal-text">{data.hint}</code> : null}
        </p>
      ) : (
        <>
          <p className="text-sm text-terminal-text-muted mb-3">
            Coverage {formatRate(data.coverage_pct)} · {data.rejected_total ?? 0} rejected decisions ·
            generated {data.generated_at ?? '—'}
          </p>
          <p className="text-xs text-terminal-text-muted mb-3">
            Row-level dataset:{' '}
            <code className="text-terminal-text">data/learning/parquet/v6/rejected.parquet</code>
            {' '}· included in weekly <code className="text-terminal-text">run-export</code> and available in Data lab → Rejected.
          </p>

          <div className="grid gap-2 grid-cols-2 sm:grid-cols-4 mb-4">
            <StatCard label="Good-miss rate" value={formatRate(data.good_miss_rate)} />
            <StatCard
              label="False-reject rate"
              value={formatRate(data.false_reject_rate)}
              tone={
                data.false_reject_rate != null && data.false_reject_rate > RETUNE_FALSE_REJECT_THRESHOLD
                  ? 'loss'
                  : 'default'
              }
            />
            <StatCard label="Stall rate" value={formatRate(data.stall_rate)} />
            <StatCard label="Selection gap" value={formatGap(data.selection_gap_pct)} />
          </div>

          {data.funnel_metrics ? (
            <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 mb-4">
              <StatCard
                label="Forward veto precision"
                value={formatRate(data.funnel_metrics.forward_precision_at_veto)}
              />
              <StatCard
                label="Missed-winner rate"
                value={formatRate(data.funnel_metrics.missed_winner_rate)}
              />
              <StatCard
                label="Accepted winner rate"
                value={formatRate(data.funnel_metrics.accepted_winner_rate)}
              />
            </div>
          ) : null}

          {(data.by_stage ?? []).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Stage</th>
                    <th className="px-2 py-1">n</th>
                    <th className="px-2 py-1">Resolved</th>
                    <th className="px-2 py-1">Good-miss</th>
                    <th className="px-2 py-1">False-reject</th>
                    <th className="px-2 py-1">Stall</th>
                    <th className="px-2 py-1">Mean fwd ret</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.by_stage ?? []).map((stage) => {
                    const retune =
                      stage.false_reject_rate != null &&
                      stage.false_reject_rate > RETUNE_FALSE_REJECT_THRESHOLD
                    return (
                      <tr
                        key={stage.stage}
                        className={`border-t border-terminal-border/60 ${retune ? 'bg-loss/5' : ''}`}
                      >
                        <td className="px-2 py-1 font-mono">
                          {stage.stage}
                          {retune ? (
                            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide bg-loss/15 text-loss">
                              re-tune
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-1">{stage.n}</td>
                        <td className="px-2 py-1">{stage.n_resolved}</td>
                        <td className="px-2 py-1">{formatRate(stage.good_miss_rate)}</td>
                        <td className={`px-2 py-1 ${retune ? 'text-loss font-semibold' : ''}`}>
                          {formatRate(stage.false_reject_rate)}
                        </td>
                        <td className="px-2 py-1">{formatRate(stage.stall_rate)}</td>
                        <td className="px-2 py-1">{formatRet(stage.mean_forward_ret_pct)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-terminal-text-muted">No per-stage breakdown in artifact.</p>
          )}

          {(data.history ?? []).length > 1 ? (
            <div className="mt-4 border-t border-terminal-border pt-3">
              <p className="text-xs uppercase tracking-wide text-terminal-text-dim mb-2">Trend (artifacts)</p>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="text-terminal-text-muted text-left">
                      <th className="px-2 py-1">Artifact</th>
                      <th className="px-2 py-1">Good-miss</th>
                      <th className="px-2 py-1">False-reject</th>
                      <th className="px-2 py-1">Gap</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.history ?? []).map((row) => (
                      <tr key={row.artifact_name} className="border-t border-terminal-border/60">
                        <td className="px-2 py-1 font-mono">{row.artifact_name}</td>
                        <td className="px-2 py-1">{formatRate(row.good_miss_rate)}</td>
                        <td className="px-2 py-1">{formatRate(row.false_reject_rate)}</td>
                        <td className="px-2 py-1">{formatGap(row.selection_gap_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </>
      )}

      {caption}
    </Panel>
  )
}
