import type { LearningEvaluationSummary, NorthStarMetrics } from '../../api/client'
import { Panel } from '../Panel'
import { SectionHeader } from '../SectionHeader'

interface PromotionGateStripProps {
  evaluation: LearningEvaluationSummary | null
  northStar: NorthStarMetrics | null
}

export function PromotionGateStrip({ evaluation, northStar }: PromotionGateStripProps) {
  const gates = (evaluation?.gates ?? {}) as Record<string, unknown>
  const tiers = (gates.tiers as Array<Record<string, unknown>>) ?? []
  const summary = String(gates.summary ?? '')
  const closedTrades = northStar?.total_trades ?? evaluation?.closed_trades ?? 0
  const influenceGate = 200
  const liveGate = 500

  return (
    <Panel data-testid="learning-gates">
      <SectionHeader
        title="Promotion gates"
        subtitle="Safety ladder before any ML/memory influence on live trading."
      />
      <p className="text-xs text-terminal-text-dim mb-3">
        Why: legal/safety ladder — shadow-only until tier 3 ({influenceGate} closed trades) and tier 4 ({liveGate} + sign-off).
      </p>
      <p className="text-sm text-terminal-text-muted mb-2">
        Closed trades (90d window): <span className="font-mono text-terminal-text">{closedTrades}</span>
        {' · '}
        Influence review at <span className="font-mono">{influenceGate}</span>
        {' · '}
        Live influence at <span className="font-mono">{liveGate}</span> + sign-off
      </p>
      {summary ? <p className="text-sm text-terminal-text-muted mb-3">{summary}</p> : null}
      {tiers.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {tiers.map((tier) => (
            <span
              key={String(tier.tier_id)}
              className={`text-xs px-2 py-1 rounded-panel border ${
                tier.passed
                  ? 'border-emerald/40 text-emerald bg-emerald/10'
                  : 'border-terminal-border text-terminal-text-muted'
              }`}
              title={String(tier.description ?? tier.label ?? '')}
            >
              {String(tier.label)}: {tier.passed ? 'PASS' : 'FAIL'}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-sm text-terminal-text-muted">
          No gate evaluation yet. Run weekly export + evaluate, or{' '}
          <code>poetry run python -m src.learning.cli evaluate</code>.
        </p>
      )}
    </Panel>
  )
}
