import { useEffect, useState } from 'react'
import { learningApi } from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'
import { formatMoney, formatPct } from '../formatters'

interface AttributionPanelProps {
  closedTrades: number
  evaluationCreatedAt?: string | null
}

export function AttributionPanel({ closedTrades, evaluationCreatedAt }: AttributionPanelProps) {
  const [committeeData, setCommitteeData] = useState<Record<string, unknown> | null>(null)
  const [researchData, setResearchData] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const influenceGate = 200
  const belowGate = closedTrades < influenceGate

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [committee, research] = await Promise.all([
          learningApi.getCommitteeEvaluation().catch(() => null),
          learningApi.getResearchEvaluation().catch(() => null),
        ])
        if (cancelled) return
        setCommitteeData(committee as unknown as Record<string, unknown> | null)
        setResearchData(research as unknown as Record<string, unknown> | null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load attribution')
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (belowGate) {
    return (
      <Panel data-testid="learning-attribution-panel">
        <SectionHeader title="Pipeline attribution" subtitle="Committee, context, and research influence." />
        <InfoCallout
          why="Explains which pipeline stages correlate with bad pace outcomes — required before influence review."
          freshAsOf={evaluationCreatedAt ?? null}
          freshSource="learning_evaluation_runs"
          roadmapId="US-2.3"
        />
        <p className="text-sm text-terminal-text-muted">
          Detailed attribution unlocks at {influenceGate} closed trades (currently {closedTrades}). Shadow and offline
          evaluation tabs remain available.
        </p>
      </Panel>
    )
  }

  const committee = (committeeData?.committee ?? {}) as Record<string, unknown>
  const contextInfluence = (committeeData?.context_influence ?? {}) as Record<string, unknown>
  const committeePolicies = (committeeData?.policies ?? {}) as Record<string, Record<string, unknown>>
  const funnel = (committee.stage_funnel ?? {}) as Record<string, number>
  const stratified = (committee.stratified ?? {}) as Record<string, Array<Record<string, unknown>>>
  const macro = (contextInfluence?.macro_regime as Record<string, unknown> | undefined)?.rows as Array<Record<string, unknown>> | undefined
  const guidance = (contextInfluence?.guidance_sector as Record<string, unknown> | undefined)?.rows as Array<Record<string, unknown>> | undefined

  const influence = (researchData?.research_influence ?? {}) as Record<string, unknown>
  const descriptive = (influence.descriptive ?? {}) as Record<string, unknown>
  const researchStratified = (influence.stratified ?? {}) as Record<string, Array<Record<string, unknown>>>
  const citation = (influence.citation ?? {}) as Record<string, unknown>
  const researchPolicies = (researchData?.policies ?? {}) as Record<string, Record<string, unknown>>

  return (
    <Panel data-testid="learning-attribution-panel">
      <SectionHeader title="Pipeline attribution" subtitle="Committee, context, and research influence." />
      <InfoCallout
        why="Identifies which moderation stage, macro regime, or research intensity correlates with stall/big_loser outcomes."
        freshAsOf={evaluationCreatedAt ?? null}
        freshSource="learning_evaluation_runs · weekly evaluate"
        action="poetry run python -m src.learning.cli evaluate"
        roadmapId="US-2.3"
      />
      {error ? <p className="text-sm text-loss">{error}</p> : null}

      <h4 className="text-xs font-semibold uppercase tracking-wide text-terminal-text-muted mt-4 mb-2">Committee funnel</h4>
      {!committeeData ? (
        <p className="text-sm text-terminal-text-muted mb-4">Run evaluate after export to populate committee metrics.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-3 text-xs text-terminal-text-muted mb-3">
            {Object.entries(funnel).map(([k, v]) => (
              <span key={k} className="px-2 py-1 border border-terminal-border rounded-panel">
                {k.replace(/_/g, ' ')}: {v}
              </span>
            ))}
          </div>
          {(stratified.by_consensus ?? []).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel mb-4">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Consensus</th>
                    <th className="px-2 py-1">n</th>
                    <th className="px-2 py-1">Bad rate</th>
                  </tr>
                </thead>
                <tbody>
                  {(stratified.by_consensus ?? []).map((row) => (
                    <tr key={String(row.moderation_consensus)} className="border-t border-terminal-border/60">
                      <td className="px-2 py-1">{String(row.moderation_consensus)}</td>
                      <td className="px-2 py-1">{String(row.n)}</td>
                      <td className="px-2 py-1">{formatPct(row.bad_rate as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {Object.keys(committeePolicies).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel mb-6">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Committee policy</th>
                    <th className="px-2 py-1">Fwd veto precision</th>
                    <th className="px-2 py-1">Missed winner</th>
                    <th className="px-2 py-1">Net £ (realized)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(committeePolicies).map(([pid, m]) => (
                    <tr key={pid} className="border-t border-terminal-border/60">
                      <td className="px-2 py-1 font-mono">{pid}</td>
                      <td className="px-2 py-1">{formatPct(m.forward_precision_at_veto as number | null)}</td>
                      <td className="px-2 py-1">{formatPct(m.missed_winner_rate as number | null)}</td>
                      <td className="px-2 py-1">{formatMoney(m.net_counterfactual_gbp as number | null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}

      <h4 className="text-xs font-semibold uppercase tracking-wide text-terminal-text-muted mb-2">Context influence</h4>
      {!contextInfluence || Object.keys(contextInfluence).length === 0 ? (
        <p className="text-sm text-terminal-text-muted mb-4">No context influence report yet.</p>
      ) : (
        <div className="grid md:grid-cols-2 gap-4 mb-6">
          <div>
            <p className="text-xs font-semibold mb-2">Macro regime</p>
            <ul className="text-xs space-y-1 text-terminal-text-muted">
              {(macro ?? []).map((row) => (
                <li key={String(row.regime)}>
                  {String(row.regime)}: win {formatPct(row.win_rate as number)} · loss {formatPct(row.loss_rate as number)} (n={String(row.n)})
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold mb-2">Guidance sector</p>
            <ul className="text-xs space-y-1 text-terminal-text-muted">
              {(guidance ?? []).map((row) => (
                <li key={String(row.guidance_label)}>
                  {String(row.guidance_label)}: win {formatPct(row.win_rate as number)} (n={String(row.n)})
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <h4 className="text-xs font-semibold uppercase tracking-wide text-terminal-text-muted mb-2">Research influence</h4>
      {!researchData ? (
        <p className="text-sm text-terminal-text-muted">Run evaluate after export to populate research metrics.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-3 text-xs text-terminal-text-muted mb-4">
            <span className="px-2 py-1 border border-terminal-border rounded-panel">
              decisions w/ research: {String(descriptive.total_decisions_with_research ?? '—')}
            </span>
            <span className="px-2 py-1 border border-terminal-border rounded-panel">
              cache hit rate: {formatPct(descriptive.cache_hit_rate as number)}
            </span>
            <span className="px-2 py-1 border border-terminal-border rounded-panel">
              query overlap: {formatPct(descriptive.query_overlap_pct as number)}
            </span>
            <span className="px-2 py-1 border border-terminal-border rounded-panel">
              citation rate: {formatPct(citation.citation_rate as number)}
            </span>
          </div>
          {(researchStratified.by_intensity ?? []).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel mb-4">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Research calls</th>
                    <th className="px-2 py-1">n</th>
                    <th className="px-2 py-1">Bad rate</th>
                  </tr>
                </thead>
                <tbody>
                  {(researchStratified.by_intensity ?? []).map((row) => (
                    <tr key={String(row.bucket)} className="border-t border-terminal-border/60">
                      <td className="px-2 py-1">{String(row.bucket)}</td>
                      <td className="px-2 py-1">{String(row.n)}</td>
                      <td className="px-2 py-1">{formatPct(row.bad_rate as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {Object.keys(researchPolicies).length > 0 ? (
            <div className="overflow-x-auto border border-terminal-border rounded-panel">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                    <th className="px-2 py-1">Research policy</th>
                    <th className="px-2 py-1">Fwd veto precision</th>
                    <th className="px-2 py-1">Missed winner</th>
                    <th className="px-2 py-1">Net £ (realized)</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(researchPolicies).map(([pid, m]) => (
                    <tr key={pid} className="border-t border-terminal-border/60">
                      <td className="px-2 py-1 font-mono">{pid}</td>
                      <td className="px-2 py-1">{formatPct(m.forward_precision_at_veto as number | null)}</td>
                      <td className="px-2 py-1">{formatPct(m.missed_winner_rate as number | null)}</td>
                      <td className="px-2 py-1">{formatMoney(m.net_counterfactual_gbp as number | null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </Panel>
  )
}
