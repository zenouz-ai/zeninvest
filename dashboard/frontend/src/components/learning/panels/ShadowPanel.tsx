import { useEffect, useState } from 'react'
import {
  learningApi,
  type LearningEntryAdvisory,
  type LearningShadowDisagreement,
  type LearningShadowSummary,
} from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'

export function ShadowPanel() {
  const [shadow, setShadow] = useState<LearningShadowSummary | null>(null)
  const [entryAdvisory, setEntryAdvisory] = useState<LearningEntryAdvisory | null>(null)
  const [disagreements, setDisagreements] = useState<LearningShadowDisagreement[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [sh, dis, advisory] = await Promise.all([
          learningApi.getShadowSummary(30).catch(() => null),
          learningApi.getShadowDisagreements(10, 30).catch(() => ({ disagreements: [], count: 0 })),
          learningApi.getEntryAdvisory(30).catch(() => null),
        ])
        if (cancelled) return
        setShadow(sh)
        setDisagreements(dis.disagreements)
        setEntryAdvisory(advisory)
        setLoaded(true)
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Failed to load shadow data')
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  return (
    <Panel data-testid="learning-shadow-panel">
      <SectionHeader title="Live shadow scoring" subtitle="Per-cycle challenger recommendations — zero execution influence." />
      <InfoCallout
        why="Validates whether shadow challengers agree with the champion on recent BUYs before any promotion."
        freshSource="decision_shadow_scores · daily outcome join 22:30 UTC"
        action="Enable shadow_scoring_enabled in settings"
        roadmapId="US-6.6"
      />
      {loadError ? <p className="text-sm text-loss">{loadError}</p> : null}
      {!loaded ? (
        <p className="text-sm text-terminal-text-muted">Loading shadow data…</p>
      ) : !shadow || shadow.total_scores === 0 ? (
        <p className="text-sm text-terminal-text-muted">No shadow scores in the last 30 days.</p>
      ) : (
        <>
          <p className="text-sm text-terminal-text-muted mb-3">
            {shadow.total_scores} scores over {shadow.span_days ?? shadow.days}d
          </p>
          {shadow.by_policy && Object.keys(shadow.by_policy).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel mb-4">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Policy</th>
                    <th className="px-2 py-1">Matured</th>
                    <th className="px-2 py-1">Veto correct</th>
                    <th className="px-2 py-1">Missed winner</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(shadow.by_policy).map(([pid, row]) => (
                    <tr key={pid} className="border-t border-terminal-border/60">
                      <td className="px-2 py-1 font-mono">{pid}</td>
                      <td className="px-2 py-1">{String(row.matured ?? '—')}</td>
                      <td className="px-2 py-1">{String(row.veto_correct ?? '—')}</td>
                      <td className="px-2 py-1">{String(row.veto_missed_winner ?? '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}

      {entryAdvisory && entryAdvisory.total_buy_scores > 0 ? (
        <div className="mb-4 rounded-panel border border-amber/30 bg-amber/5 px-3 py-2 text-sm">
          <p className="text-xs uppercase tracking-wide text-amber mb-1">Entry advisory (shadow only)</p>
          <p className="text-terminal-text-muted text-xs mb-2">{entryAdvisory.message}</p>
          <div className="grid gap-2 sm:grid-cols-3 text-xs font-mono">
            <span>High stall p≥35%: {entryAdvisory.high_stall_probability ?? 0}</span>
            <span>High loser p≥35%: {entryAdvisory.high_loser_probability ?? 0}</span>
            <span>Would skip: {entryAdvisory.challenger_would_skip ?? 0}</span>
          </div>
        </div>
      ) : null}

      {disagreements.length > 0 ? (
        <>
          <p className="text-xs font-semibold mb-2">Recent disagreements (top 10)</p>
          <div className="overflow-x-auto border border-terminal-border rounded-panel">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                  <th className="px-2 py-1">Ticker</th>
                  <th className="px-2 py-1">Policy</th>
                  <th className="px-2 py-1">Champion</th>
                  <th className="px-2 py-1">Challenger</th>
                  <th className="px-2 py-1">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {disagreements.map((d, idx) => (
                  <tr key={`${d.cycle_id}-${d.ticker}-${idx}`} className="border-t border-terminal-border/60">
                    <td className="px-2 py-1 font-mono">{d.ticker}</td>
                    <td className="px-2 py-1">{d.policy_id}</td>
                    <td className="px-2 py-1">{d.champion_action}</td>
                    <td className="px-2 py-1">{d.recommended_action}</td>
                    <td className="px-2 py-1">
                      {d.outcome && typeof d.outcome === 'object'
                        ? String((d.outcome as Record<string, unknown>).label_3class ?? '—')
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : loaded && disagreements.length === 0 ? (
        <p className="text-sm text-terminal-text-muted mt-2">No champion/challenger disagreements in window.</p>
      ) : null}
    </Panel>
  )
}
