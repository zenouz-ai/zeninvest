import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { learningApi, type LearningRunDetail, type LearningRunSummary } from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'
import { formatNumber, formatPct } from '../formatters'

const LABEL_COLORS: Record<string, string> = {
  big_winner: '#22c55e',
  big_loser: '#ef4444',
  stall: '#f59e0b',
  neutral: '#64748b',
}

interface ModelLabPanelProps {
  runs: LearningRunSummary[]
  datasetVersion?: string | null
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-terminal-text-muted">{label}</div>
      <div className="text-base font-medium text-terminal-text">{value}</div>
    </div>
  )
}

export function ModelLabPanel({ runs, datasetVersion }: ModelLabPanelProps) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(runs[0]?.run_id ?? null)
  const [detail, setDetail] = useState<LearningRunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (runs.length === 0) {
      setSelectedRunId(null)
      setDetail(null)
      return
    }
    if (!selectedRunId || !runs.some((run) => run.run_id === selectedRunId)) {
      setSelectedRunId(runs[0].run_id)
    }
  }, [runs, selectedRunId])

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null)
      setError(null)
      return
    }
    let cancelled = false
    setError(null)
    learningApi.getRun(selectedRunId)
      .then((data) => { if (!cancelled) setDetail(data) })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load run')
      })
    return () => { cancelled = true }
  }, [selectedRunId])

  const labelData = useMemo(() => {
    if (!detail?.run) return []
    const dist = detail.run.label_distribution || {}
    return Object.entries(dist).map(([label, count]) => ({ label, count: Number(count) }))
  }, [detail])

  const calibrationData = useMemo(() => {
    const curve = detail?.metrics?.calibrator
    if (!curve) return []
    const labels: string[] = curve.bin_labels || []
    const rates: number[] = curve.bin_win_rates || []
    const counts: number[] = curve.bin_counts || []
    return labels.map((label, idx) => ({
      bin: label,
      win_rate: rates[idx] || 0,
      count: counts[idx] || 0,
    }))
  }, [detail])

  const featureImportance = useMemo(() => {
    const map = detail?.metrics?.gbm?.feature_importance || {}
    return Object.entries(map as Record<string, number>)
      .map(([feature, gain]) => ({ feature, gain: Number(gain) }))
      .sort((a, b) => b.gain - a.gain)
      .slice(0, 15)
  }, [detail])

  const decileLift = useMemo(() => {
    const rows = detail?.metrics?.gbm?.decile_lift || []
    return rows.map((r: { decile: number; mean_ret_30d_pct: number; count: number }) => ({
      decile: `D${r.decile}`,
      mean_ret_30d_pct: Number(r.mean_ret_30d_pct),
      count: Number(r.count),
    }))
  }, [detail])

  const foldTrend = useMemo(() => {
    const folds = detail?.metrics?.gbm?.fold_metrics || []
    return folds.map((f: { fold: number; accuracy?: number; macro_f1?: number }, idx: number) => ({
      fold: `F${f.fold ?? idx + 1}`,
      accuracy: f.accuracy != null ? Number(f.accuracy) * 100 : null,
      macro_f1: f.macro_f1 != null ? Number(f.macro_f1) * 100 : null,
    }))
  }, [detail])

  if (runs.length === 0) {
    return (
      <Panel data-testid="learning-model-lab">
        <SectionHeader title="Model lab" subtitle="Offline train diagnostics (calibrator + GBM + stall)." />
        <InfoCallout
          why="Validates model fit (calibration, decile lift) before promotion evidence — separate from weekly export."
          action="poetry run python -m src.learning.cli train"
          roadmapId="US-2.1"
        />
        <p className="text-sm text-terminal-text-muted">
          No {datasetVersion ?? 'current'} train run yet — shadow evaluation still works from weekly export.
          Run train when sample size warrants refresh.
        </p>
      </Panel>
    )
  }

  const gbm = detail?.metrics?.gbm ?? null
  const stall = detail?.metrics?.stall ?? null
  const calibrator = detail?.metrics?.calibrator ?? null
  const meta = detail?.run

  return (
    <div className="space-y-4" data-testid="learning-model-lab">
      <Panel>
        <SectionHeader title="Model lab" subtitle="Interactive diagnostics from latest train run — shadow-only." />
        <InfoCallout
          why="Decile lift and calibration curves are promotion evidence; same gain/day labels as north-star KPIs."
          freshAsOf={meta?.created_at ?? null}
          freshSource="learning_runs · manual cli train"
          action="poetry run python -m src.learning.cli train"
          roadmapId="US-6.1"
        />
        {error ? <p className="text-sm text-loss mb-2">{error}</p> : null}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <select
            className="bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm"
            value={selectedRunId ?? ''}
            onChange={(e) => setSelectedRunId(e.target.value)}
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id} · {run.dataset_version} · {run.rows.toLocaleString()} rows
              </option>
            ))}
          </select>
          {detail?.report_available && meta ? (
            <a
              className="px-3 py-2 text-sm border border-cyan/40 text-cyan rounded-panel hover:bg-cyan/10"
              href={learningApi.reportUrl(meta.run_id)}
              target="_blank"
              rel="noreferrer"
            >
              Open full HTML report (all PNGs)
            </a>
          ) : null}
        </div>
        {meta ? (
          <div className="grid gap-3 grid-cols-2 md:grid-cols-4 text-sm">
            <Metric label="Rows" value={meta.rows.toLocaleString()} />
            <Metric label="Dataset" value={meta.dataset_version} />
            <Metric label="Calibrator Brier" value={formatNumber(calibrator?.brier_score)} />
            <Metric label="Calibrator log-loss" value={formatNumber(calibrator?.log_loss)} />
            <Metric label="GBM accuracy" value={formatPct(gbm?.aggregate_metrics?.accuracy, 1)} />
            <Metric label="GBM big_winner AUC" value={formatNumber(gbm?.aggregate_metrics?.auc?.big_winner)} />
            <Metric label="GBM big_winner recall" value={formatPct(gbm?.aggregate_metrics?.per_class_recall?.big_winner, 1)} />
            <Metric label="Stall AUC" value={formatNumber(stall?.aggregate_metrics?.auc)} />
          </div>
        ) : null}
      </Panel>

      {detail ? (
        <>
          {foldTrend.length > 0 ? (
            <Panel>
              <SectionHeader title="Per-fold metric trend" subtitle="Walk-forward out-of-fold stability." />
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={foldTrend}>
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <XAxis dataKey="fold" stroke="#8b949e" fontSize={12} />
                    <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${v}%`} />
                    <Tooltip contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="accuracy" name="Accuracy %" stroke="#22d3ee" dot />
                    <Line type="monotone" dataKey="macro_f1" name="Macro F1 %" stroke="#a78bfa" dot />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          ) : null}

          <div className="grid gap-6 md:grid-cols-2">
            <Panel>
              <SectionHeader title="Label distribution" subtitle="Hybrid label across BUY-eligible rows." />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={labelData}>
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <XAxis dataKey="label" stroke="#8b949e" fontSize={12} />
                    <YAxis stroke="#8b949e" fontSize={12} />
                    <Tooltip contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }} />
                    <Bar dataKey="count">
                      {labelData.map((entry) => (
                        <Cell key={entry.label} fill={LABEL_COLORS[entry.label] || '#94a3b8'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel>
              <SectionHeader title="Conviction calibration" subtitle="Empirical big_winner rate per conviction bin." />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={calibrationData}>
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <XAxis dataKey="bin" stroke="#8b949e" fontSize={11} />
                    <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                    <Tooltip
                      formatter={(value: number, name) => (name === 'win_rate' ? formatPct(value, 1) : value)}
                      contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="win_rate" name="Empirical win rate" fill="#22d3ee" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel>
              <SectionHeader title="Top features (gain)" subtitle="Walk-forward mean relative gain." />
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={featureImportance} layout="vertical" margin={{ left: 80 }}>
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <XAxis type="number" stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} />
                    <YAxis type="category" dataKey="feature" stroke="#8b949e" fontSize={11} width={150} />
                    <Tooltip
                      formatter={(value: number) => `${(value * 100).toFixed(2)}%`}
                      contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }}
                    />
                    <Bar dataKey="gain" fill="#a78bfa" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel>
              <SectionHeader title="Decile lift" subtitle="Out-of-fold mean ret_30d by probability decile." />
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={decileLift}>
                    <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                    <XAxis dataKey="decile" stroke="#8b949e" fontSize={12} />
                    <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip
                      formatter={(value: number, name) => (name === 'mean_ret_30d_pct' ? `${value.toFixed(2)}%` : value)}
                      contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }}
                    />
                    <Bar dataKey="mean_ret_30d_pct" fill="#34d399">
                      {decileLift.map((entry: { decile: string; mean_ret_30d_pct: number; count: number }) => (
                        <Cell
                          key={entry.decile}
                          fill={entry.mean_ret_30d_pct >= 0 ? '#22c55e' : '#ef4444'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>
        </>
      ) : (
        <p className="text-sm text-terminal-text-muted">Loading run metrics…</p>
      )}
    </div>
  )
}
