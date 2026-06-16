import type { LearningPageStatus } from '../../api/client'
import { formatAge } from './formatters'

interface ArtifactFreshnessBannerProps {
  status: LearningPageStatus | null
}

export function ArtifactFreshnessBanner({ status }: ArtifactFreshnessBannerProps) {
  if (!status) return null

  const warnings = status.staleness_warnings ?? []
  const exportRow = status.latest_export
  const evalRow = status.latest_evaluation
  const trainRow = status.latest_train_run
  const shadow = status.shadow_summary
  const version = status.dataset_version ?? 'v6'

  return (
    <div
      data-testid="learning-freshness"
      className={`rounded-panel border px-4 py-3 text-sm ${
        warnings.length > 0
          ? 'border-amber/40 bg-amber/5'
          : 'border-terminal-border bg-terminal-surface/40'
      }`}
    >
      <p className="text-xs uppercase tracking-wide text-terminal-text-muted mb-2">
        Artifact freshness · dataset {version}
      </p>
      <p className="text-xs text-terminal-text-dim mb-2">
        Why: stale parquet or missing evaluation invalidates offline conclusions.
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs text-terminal-text-muted">
        <div>
          <span className="text-terminal-text-dim">Weekly export:</span>{' '}
          {exportRow
            ? `${exportRow.rows.toLocaleString()} rows · ${formatAge(exportRow.created_at)}`
            : 'none — run run-export'}
        </div>
        <div>
          <span className="text-terminal-text-dim">Evaluation:</span>{' '}
          {evalRow
            ? `${evalRow.run_id} · ${formatAge(evalRow.created_at)}`
            : 'none — run evaluate'}
        </div>
        <div>
          <span className="text-terminal-text-dim">Train run:</span>{' '}
          {trainRow
            ? `${trainRow.run_id} · ${formatAge(trainRow.created_at)}`
            : 'none — manual cli train'}
        </div>
        <div>
          <span className="text-terminal-text-dim">Shadow scores:</span>{' '}
          {shadow && shadow.total_scores > 0
            ? `${shadow.total_scores} over ${shadow.span_days ?? shadow.days}d`
            : 'none — enable shadow_scoring'}
        </div>
      </div>
      {warnings.length > 0 ? (
        <ul className="mt-3 space-y-1 text-xs text-amber">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
