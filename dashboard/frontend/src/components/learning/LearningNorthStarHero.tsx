import type { NorthStarMetrics } from '../../api/client'
import { Panel } from '../Panel'
import { SectionHeader } from '../SectionHeader'
import { pctRate } from './formatters'

interface LearningNorthStarHeroProps {
  metrics: NorthStarMetrics | null
}

export function LearningNorthStarHero({ metrics }: LearningNorthStarHeroProps) {
  if (!metrics) {
    return (
      <Panel data-testid="learning-north-star">
        <SectionHeader
          title="North-star KPIs"
          subtitle="Live closed-trade pace outcomes — same gain/day bands as learning labels (v6)."
        />
        <p className="text-sm text-terminal-text-muted">North-star metrics unavailable.</p>
      </Panel>
    )
  }

  const targets = metrics.targets ?? {}
  const stretch = targets.big_winner_hit_rate_stretch ?? 0.5
  const interim = targets.big_winner_hit_rate_interim ?? 0.35
  const bw = metrics.big_winner_hit_rate
  const bwClass =
    bw == null
      ? 'text-terminal-text'
      : bw >= stretch
        ? 'text-cyan'
        : bw >= interim
          ? 'text-emerald'
          : 'text-amber'

  return (
    <Panel data-testid="learning-north-star">
      <SectionHeader
        title="North-star KPIs"
        subtitle={`Rolling ${metrics.window_days}d closed trades · pace-aligned v6 labels (≥${metrics.thresholds?.success_min_profit_per_day_pct ?? 0.25}%/day winner).`}
      />
      <p className="text-xs text-terminal-text-dim mb-3" title="Primary operating targets; learning labels use identical bands.">
        Why: measure live trading pace before promoting shadow ML. Compare with Trade Review timelines.
      </p>
      {!metrics.sufficient_data ? (
        <p className="text-sm text-terminal-text-muted mb-3">
          {metrics.total_trades} closed trades in window — need ≥{targets.min_trades_for_display ?? 30} for stable rates.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">big_winner rate</p>
          <p className={`text-lg font-mono ${bwClass}`}>{pctRate(bw)}</p>
          <p className="text-xs text-terminal-text-dim">Target interim {pctRate(interim)} · stretch {pctRate(stretch)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">stall rate</p>
          <p className="text-lg font-mono text-amber">{pctRate(metrics.stall_rate)}</p>
          <p className="text-xs text-terminal-text-dim">Max {pctRate(targets.stall_rate_max ?? 0.3)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">big_loser rate</p>
          <p className="text-lg font-mono text-red-400">{pctRate(metrics.big_loser_rate)}</p>
          <p className="text-xs text-terminal-text-dim">Max {pctRate(targets.big_loser_rate_max ?? 0.2)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">Expectancy</p>
          <p className="text-lg font-mono text-terminal-text">
            {metrics.expectancy_gbp != null ? `£${metrics.expectancy_gbp.toFixed(2)}` : '—'}
          </p>
          <p className="text-xs text-terminal-text-dim">Avg gain/day {metrics.avg_gain_per_day_pct?.toFixed(3) ?? '—'}%</p>
        </div>
      </div>
    </Panel>
  )
}
