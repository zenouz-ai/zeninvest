import { useEffect, useState } from 'react'
import { learningApi, type LearningEvaluationSummary } from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'
import { formatMoney, formatPct } from '../formatters'

interface EvaluationPanelProps {
  evaluation: LearningEvaluationSummary | null
}

export function EvaluationPanel({ evaluation: initialEvaluation }: EvaluationPanelProps) {
  const [evaluation, setEvaluation] = useState<LearningEvaluationSummary | null>(initialEvaluation)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (initialEvaluation) {
      setEvaluation(initialEvaluation)
      return
    }
    let cancelled = false
    learningApi.getLatestEvaluation()
      .then((ev) => { if (!cancelled) setEvaluation(ev) })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Failed to load evaluation')
      })
    return () => { cancelled = true }
  }, [initialEvaluation])

  const policies = (evaluation?.metrics as Record<string, unknown>)?.policies as Record<string, Record<string, unknown>>
    ?? evaluation?.policies
    ?? {}
  const policyEntries = Object.entries(policies)
  const champion = policies.champion_as_is

  return (
    <Panel data-testid="learning-evaluation-panel">
      <SectionHeader
        title="Champion vs challengers"
        subtitle="Offline counterfactual on historical decisions."
      />
      <InfoCallout
        why="Quantifies whether shadow ML would have improved net GBP and big_loser recall before live influence."
        freshAsOf={evaluation?.created_at ?? null}
        freshSource="learning_evaluation_runs · weekly Sun 14:00 UTC"
        action="poetry run python -m src.learning.cli evaluate"
        roadmapId="US-6.6"
      />
      {loadError ? <p className="text-sm text-loss">{loadError}</p> : null}
      {!evaluation ? (
        <p className="text-sm text-terminal-text-muted">
          No evaluation yet. Run evaluate after weekly export.
        </p>
      ) : (
        <>
          {champion?.fast_winner_hit_rate != null ? (
            <p className="text-xs text-terminal-text-muted mb-2">
              Gain/day winner hit rate (realized): {formatPct(champion.fast_winner_hit_rate as number)}
              {' · '}
              Stall win rate: {formatPct(champion.slow_win_rate as number | null)}
            </p>
          ) : null}
          {evaluation.report_available && evaluation.run_id ? (
            <a
              className="inline-block mb-3 px-3 py-2 text-sm border border-cyan/40 text-cyan rounded-panel hover:bg-cyan/10"
              href={learningApi.evaluationReportUrl(evaluation.run_id)}
              target="_blank"
              rel="noreferrer"
            >
              Open evaluation report
            </a>
          ) : null}
          <div className="overflow-x-auto border border-terminal-border rounded-panel">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                  <th className="px-2 py-1">Policy</th>
                  <th className="px-2 py-1">Bad rate (realized)</th>
                  <th className="px-2 py-1">n</th>
                  <th className="px-2 py-1">Net counterfactual £</th>
                  <th className="px-2 py-1">Big-loser recall</th>
                  <th className="px-2 py-1">Veto precision</th>
                </tr>
              </thead>
              <tbody>
                {policyEntries.map(([pid, m]) => (
                  <tr key={pid} className="border-t border-terminal-border/60">
                    <td className="px-2 py-1 font-mono">{pid}</td>
                    <td className="px-2 py-1">{formatPct(m.bad_decision_rate_realized as number | null)}</td>
                    <td className="px-2 py-1">{String(m.realized_n ?? '—')}</td>
                    <td className="px-2 py-1">{formatMoney(m.net_counterfactual_gbp as number | null)}</td>
                    <td className="px-2 py-1">{formatPct(m.big_loser_recall as number | null)}</td>
                    <td className="px-2 py-1">{formatPct(m.precision_at_veto as number | null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  )
}
