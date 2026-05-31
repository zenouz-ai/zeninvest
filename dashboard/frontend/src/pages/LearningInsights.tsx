import { useEffect, useMemo, useState } from 'react'
import {
  BarChart,
  Bar,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { learningApi, memoryApi, type LearningDatasetManifest, type LearningDatasetPreview, type LearningEvaluationSummary, type LearningExportSummary, type LearningRunDetail, type LearningRunSummary, type LearningShadowDisagreement, type LearningShadowSummary } from '../api/client'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { SkeletonCard } from '../components/Skeleton'

const LABEL_COLORS: Record<string, string> = {
  big_winner: '#22c55e',
  big_loser: '#ef4444',
  stall: '#f59e0b',
  neutral: '#64748b',
}

const CHART_FILES: { name: string; caption: string }[] = [
  { name: '01_label_distribution.png', caption: '3-class label distribution — justifies focusing on big_winner / big_loser recall over plain accuracy.' },
  { name: '02_conviction_calibration.png', caption: 'Empirical conviction vs realized win rate. A non-monotonic curve is what justifies the isotonic calibrator.' },
  { name: '03_realized_pnl_distribution.png', caption: 'Realized P&L distribution on closed trades — the hybrid label uses this as the final reward.' },
  { name: '04_horizon_vs_label.png', caption: 'Holding-day distribution per label justifies the 14-day stall qualifier.' },
  { name: '05_macro_regime_outcomes.png', caption: 'Outcome split by macro regime supports keeping regime features in the model.' },
  { name: '06_gbm_feature_importance.png', caption: 'LightGBM top-20 features by gain (walk-forward mean).' },
  { name: '07_decile_lift.png', caption: 'Out-of-fold decile lift on the (winner − loser) probability spread.' },
  { name: '08_conviction_vs_pnl.png', caption: 'Conviction vs realized P&L scatter — a near-zero Pearson r is why we cannot just trust conviction.' },
  { name: '09_baseline_vs_gbm.png', caption: 'Baseline (majority + conviction-only) vs LightGBM out-of-fold metrics.' },
]

const DATASET_ARTIFACTS: { id: string; label: string; download?: string; json?: boolean }[] = [
  { id: 'decisions', label: 'Decisions', download: 'decisions.parquet' },
  { id: 'features', label: 'Features', download: 'features.parquet' },
  { id: 'outcomes', label: 'Outcomes', download: 'outcomes.parquet' },
  { id: 'merged', label: 'Merged', download: 'merged.parquet' },
  { id: 'text_corpus', label: 'Text corpus', download: 'text_corpus.parquet' },
  { id: 'memory_bundle', label: 'Memory JSONL', download: 'memory_bundle.jsonl' },
  { id: 'schema', label: 'Schema', json: true },
  { id: 'splits', label: 'Splits', json: true },
]

function formatBytes(bytes: number | undefined): string {
  if (bytes === undefined || Number.isNaN(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function formatPercent(value: number | undefined | null, digits = 1): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function formatNumber(value: number | undefined | null, digits = 3): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

export default function LearningInsights() {
  const [exports, setExports] = useState<LearningExportSummary[]>([])
  const [similarQuery, setSimilarQuery] = useState('')
  const [similarHits, setSimilarHits] = useState<Array<Record<string, unknown>>>([])
  const [runs, setRuns] = useState<LearningRunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<LearningRunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const list = await learningApi.listRuns(25)
        if (cancelled) return
        setRuns(list.runs)
        if (list.runs.length > 0 && !selectedRunId) {
          setSelectedRunId(list.runs[0].run_id)
        }
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load runs')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    learningApi.listExports(10).then((r) => { if (!cancelled) setExports(r.exports) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selectedRunId) return
    let cancelled = false
    async function load(runId: string) {
      try {
        const data = await learningApi.getRun(runId)
        if (cancelled) return
        setDetail(data)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load run detail')
      }
    }
    load(selectedRunId)
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
    return rows.map((r: any) => ({
      decile: `D${r.decile}`,
      mean_ret_30d_pct: Number(r.mean_ret_30d_pct),
      count: Number(r.count),
    }))
  }, [detail])

  if (loading) return <SkeletonCard lines={12} />

  if (error) {
    return (
      <Panel>
        <p className="text-loss text-sm">{error}</p>
      </Panel>
    )
  }

  if (runs.length === 0 || !detail) {
    return (
      <div className="space-y-4">
        <PageBrandHeader
          eyebrow="LEARNING"
          title="Trade-outcome learning insights"
          description="Read-only diagnostics for the calibrator / LightGBM / stall pipeline. Models are shadow-only and never influence live trading."
        />
        <RawDatasetsPanel />
        <ChampionVsChallengersPanel />
        <Panel>
          <p className="text-sm text-terminal-text-muted">
            No learning runs persisted yet. Run <code>poetry run python -m src.learning.cli train</code> to seed the first row.
          </p>
        </Panel>
      </div>
    )
  }

  const gbm = detail.metrics?.gbm ?? null
  const stall = detail.metrics?.stall ?? null
  const baselines = detail.metrics?.baselines ?? null
  const meta = detail.run

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="LEARNING"
        title="Trade-outcome learning insights"
        description="Track A: shadow ML diagnostics. Track B: weekly v2 export + similar-case search (memory). Neither influences live trading."
      />

      {exports.length > 0 ? (
        <Panel>
          <SectionHeader title="Weekly exports" subtitle="Scheduled audit + build + memory JSONL (learning_export_runs)." />
          <p className="text-sm text-terminal-text-muted">
            Latest: {exports[0].run_id} · {exports[0].rows} rows · {exports[0].text_corpus_rows} text docs · {exports[0].status}
          </p>
        </Panel>
      ) : null}

      <RawDatasetsPanel />

      <ChampionVsChallengersPanel />

      <Panel>
        <SectionHeader title="Similar past cases" subtitle="Vector search over memory_bundle (requires sync-embeddings on host)." />
        <div className="flex flex-wrap gap-2 items-center">
          <input
            className="flex-1 min-w-[200px] bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm"
            placeholder="Describe thesis or pattern…"
            value={similarQuery}
            onChange={(e) => setSimilarQuery(e.target.value)}
          />
          <button
            type="button"
            className="px-3 py-2 text-sm border border-violet/40 text-violet rounded-panel hover:bg-violet/10"
            onClick={async () => {
              if (!similarQuery.trim()) return
              try {
                const res = await memoryApi.similar(similarQuery.trim(), { k: 5 })
                setSimilarHits(res.hits as Array<Record<string, unknown>>)
              } catch {
                setSimilarHits([])
              }
            }}
          >
            Search
          </button>
        </div>
        {similarHits.length > 0 ? (
          <ul className="mt-3 space-y-2 text-sm">
            {similarHits.map((hit) => (
              <li key={String(hit.doc_id)} className="border border-terminal-border rounded-panel p-2">
                <span className="font-mono text-cyan">{String(hit.ticker)}</span>
                {' · '}
                score {formatNumber(Number(hit.score), 3)}
                {' · '}
                {String((hit.metadata as Record<string, unknown>)?.label_3class ?? '—')}
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      <Panel>
        <SectionHeader title="Run selector" subtitle="One row per `python -m src.learning.cli train` invocation." />
        <div className="flex flex-wrap items-center gap-2">
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
          {detail.report_available ? (
            <a
              className="px-3 py-2 text-sm border border-cyan/40 text-cyan rounded-panel hover:bg-cyan/10"
              href={learningApi.reportUrl(meta.run_id)}
              target="_blank"
              rel="noreferrer"
            >
              Open full HTML report
            </a>
          ) : null}
        </div>
      </Panel>

      <Panel>
        <SectionHeader title="Summary" subtitle="Dataset and headline model metrics" />
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 text-sm">
          <Metric label="Rows" value={meta.rows.toLocaleString()} />
          <Metric label="Dataset" value={meta.dataset_version} />
          <Metric
            label="GBM accuracy"
            value={formatPercent(gbm?.aggregate_metrics?.accuracy, 1)}
          />
          <Metric
            label="GBM big_winner AUC"
            value={formatNumber(gbm?.aggregate_metrics?.auc?.big_winner)}
          />
          <Metric
            label="GBM big_winner recall"
            value={formatPercent(gbm?.aggregate_metrics?.per_class_recall?.big_winner)}
          />
          <Metric
            label="GBM big_loser recall"
            value={formatPercent(gbm?.aggregate_metrics?.per_class_recall?.big_loser)}
          />
          <Metric label="Stall AUC" value={formatNumber(stall?.aggregate_metrics?.auc)} />
          <Metric label="Folds" value={String(gbm?.aggregate_metrics?.n_folds ?? '—')} />
        </div>
      </Panel>

      <div className="grid gap-6 md:grid-cols-2">
        <Panel>
          <SectionHeader
            title="Label distribution"
            subtitle="Hybrid label across all BUY-eligible decision rows."
          />
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={labelData}>
                <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                <XAxis dataKey="label" stroke="#8b949e" fontSize={12} />
                <YAxis stroke="#8b949e" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    background: 'rgba(14, 16, 28, 0.95)',
                    border: '1px solid #1f2937',
                  }}
                />
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
          <SectionHeader
            title="Conviction calibration"
            subtitle="Empirical big_winner rate per conviction bin. Non-monotonic = isotonic justified."
          />
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={calibrationData}>
                <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                <XAxis dataKey="bin" stroke="#8b949e" fontSize={11} />
                <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <Tooltip
                  formatter={(value: number, name) => {
                    if (name === 'win_rate') return formatPercent(value, 1)
                    return value
                  }}
                  contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="win_rate" name="Empirical win rate" fill="#22d3ee" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel>
          <SectionHeader
            title="Top features (gain)"
            subtitle="Walk-forward mean relative gain across LightGBM folds."
          />
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
          <SectionHeader
            title="Decile lift"
            subtitle="Out-of-fold mean ret_30d by (winner − loser) probability decile."
          />
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={decileLift}>
                <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
                <XAxis dataKey="decile" stroke="#8b949e" fontSize={12} />
                <YAxis stroke="#8b949e" fontSize={12} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                <Tooltip
                  formatter={(value: number, name) => {
                    if (name === 'mean_ret_30d_pct') return `${value.toFixed(2)}%`
                    return value
                  }}
                  contentStyle={{ background: 'rgba(14, 16, 28, 0.95)', border: '1px solid #1f2937' }}
                />
                <Bar dataKey="mean_ret_30d_pct" fill="#34d399">
                  {decileLift.map((entry: any) => (
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

      <Panel>
        <SectionHeader title="Static insight figures" subtitle="Same PNGs embedded in the HTML report and docs/LEARNING_INSIGHTS.md" />
        <div className="grid gap-6 md:grid-cols-2">
          {CHART_FILES.filter((c) => detail.insight_files.includes(c.name)).map((chart) => (
            <figure key={chart.name} className="space-y-2">
              <img
                src={learningApi.insightUrl(meta.run_id, chart.name)}
                alt={chart.caption}
                loading="lazy"
                className="rounded-panel border border-terminal-border bg-terminal-surface w-full"
              />
              <figcaption className="text-xs text-terminal-text-muted">{chart.caption}</figcaption>
            </figure>
          ))}
        </div>
      </Panel>

      {baselines ? (
        <Panel>
          <SectionHeader title="Conviction-only baseline" subtitle="Per-bin big_winner share — direct evidence for needing a calibrator." />
          <pre className="text-xs text-terminal-text-muted overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(baselines, null, 2)}
          </pre>
        </Panel>
      ) : null}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-terminal-text-muted">{label}</div>
      <div className="text-base font-medium text-terminal-text">{value}</div>
    </div>
  )
}

function RawDatasetsPanel() {
  const [versions, setVersions] = useState<string[]>([])
  const [version, setVersion] = useState<string>('v2')
  const [artifact, setArtifact] = useState('decisions')
  const [manifest, setManifest] = useState<LearningDatasetManifest | null>(null)
  const [preview, setPreview] = useState<LearningDatasetPreview | null>(null)
  const [jsonPayload, setJsonPayload] = useState<Record<string, unknown> | null>(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const pageSize = 25

  useEffect(() => {
    let cancelled = false
    learningApi.listDatasetVersions().then((res) => {
      if (cancelled) return
      setVersions(res.versions)
      if (res.default) setVersion(res.default)
    }).catch(() => {}).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!version) return
    let cancelled = false
    setManifest(null)
    learningApi.getDatasetManifest(version).then((m) => {
      if (!cancelled) setManifest(m)
    }).catch(() => { if (!cancelled) setManifest(null) })
    return () => { cancelled = true }
  }, [version])

  useEffect(() => {
    setOffset(0)
  }, [artifact, version])

  useEffect(() => {
    if (!version || !artifact) return
    const tab = DATASET_ARTIFACTS.find((a) => a.id === artifact)
    let cancelled = false
    setPreviewError(null)
    setPreview(null)
    setJsonPayload(null)

    if (tab?.json) {
      learningApi.getDatasetJson(version, artifact as 'schema' | 'splits').then((data) => {
        if (!cancelled) setJsonPayload(data)
      }).catch((err) => {
        if (!cancelled) setPreviewError(err instanceof Error ? err.message : 'Failed to load JSON')
      })
      return () => { cancelled = true }
    }

    learningApi.previewDataset(version, artifact, { offset, limit: pageSize }).then((data) => {
      if (!cancelled) setPreview(data)
    }).catch((err) => {
      if (!cancelled) setPreviewError(err instanceof Error ? err.message : 'Artifact not found — run build or weekly export first')
    })
    return () => { cancelled = true }
  }, [version, artifact, offset])

  const activeTab = DATASET_ARTIFACTS.find((a) => a.id === artifact)
  const fileInfo =
    artifact === 'memory_bundle'
      ? manifest?.extras?.memory_bundle
      : manifest?.artifacts?.[artifact]

  return (
    <Panel>
      <SectionHeader
        title="Raw datasets"
        subtitle="On-disk v2 parquet, JSONL, schema and splits under data/learning/. Preview is paginated; download for full files."
      />
      <div className="flex flex-wrap gap-2 items-center mb-3">
        <select
          className="bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          disabled={loading || versions.length === 0}
        >
          {(versions.length > 0 ? versions : [version]).map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        {activeTab?.download && fileInfo?.exists ? (
          <a
            className="px-3 py-2 text-sm border border-cyan/40 text-cyan rounded-panel hover:bg-cyan/10"
            href={learningApi.datasetDownloadUrl(version, activeTab.download)}
            target="_blank"
            rel="noreferrer"
          >
            Download {activeTab.download}
          </a>
        ) : null}
        {fileInfo?.exists ? (
          <span className="text-xs text-terminal-text-muted">
            {formatBytes(fileInfo.size_bytes)} · modified {fileInfo.modified_at?.slice(0, 19) ?? '—'}
          </span>
        ) : (
          <span className="text-xs text-terminal-text-muted">File not on disk yet</span>
        )}
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {DATASET_ARTIFACTS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`px-2 py-1 text-xs rounded-panel border ${
              artifact === tab.id
                ? 'border-cyan/50 text-cyan bg-cyan/10'
                : 'border-terminal-border text-terminal-text-muted hover:bg-terminal-surface'
            }`}
            onClick={() => setArtifact(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {previewError ? (
        <p className="text-sm text-terminal-text-muted">{previewError}</p>
      ) : null}

      {jsonPayload ? (
        <pre className="text-xs text-terminal-text-muted overflow-x-auto whitespace-pre-wrap max-h-96">
          {JSON.stringify(jsonPayload, null, 2)}
        </pre>
      ) : null}

      {preview && preview.rows.length > 0 ? (
        <>
          <p className="text-xs text-terminal-text-muted mb-2">
            Rows {preview.offset + 1}–{preview.offset + preview.rows.length} of {preview.total_rows.toLocaleString()}
          </p>
          <div className="overflow-x-auto border border-terminal-border rounded-panel">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                  {(preview.columns ?? Object.keys(preview.rows[0] ?? {})).slice(0, 12).map((col) => (
                    <th key={col} className="px-2 py-1 font-medium whitespace-nowrap">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, idx) => (
                  <tr key={idx} className="border-t border-terminal-border/60">
                    {(preview.columns ?? Object.keys(row)).slice(0, 12).map((col) => (
                      <td key={col} className="px-2 py-1 align-top max-w-[240px] truncate" title={String(row[col] ?? '')}>
                        {typeof row[col] === 'object' ? JSON.stringify(row[col]) : String(row[col] ?? '—')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              className="px-2 py-1 text-xs border border-terminal-border rounded-panel disabled:opacity-40"
              disabled={offset <= 0}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
            >
              Previous
            </button>
            <button
              type="button"
              className="px-2 py-1 text-xs border border-terminal-border rounded-panel disabled:opacity-40"
              disabled={!preview || offset + pageSize >= preview.total_rows}
              onClick={() => setOffset(offset + pageSize)}
            >
              Next
            </button>
          </div>
        </>
      ) : null}

      {!previewError && !jsonPayload && preview && preview.rows.length === 0 ? (
        <p className="text-sm text-terminal-text-muted">No rows in this artifact.</p>
      ) : null}
    </Panel>
  )
}

function ChampionVsChallengersPanel() {
  const [evaluation, setEvaluation] = useState<LearningEvaluationSummary | null>(null)
  const [shadow, setShadow] = useState<LearningShadowSummary | null>(null)
  const [disagreements, setDisagreements] = useState<LearningShadowDisagreement[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [ev, sh, dis] = await Promise.all([
          learningApi.getLatestEvaluation().catch(() => null),
          learningApi.getShadowSummary(30).catch(() => null),
          learningApi.getShadowDisagreements(20, 30).catch(() => ({ disagreements: [], count: 0 })),
        ])
        if (cancelled) return
        setEvaluation(ev)
        setShadow(sh)
        setDisagreements(dis.disagreements)
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Failed to load evaluation')
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const policies = (evaluation?.metrics as Record<string, unknown>)?.policies as Record<string, Record<string, unknown>>
    ?? evaluation?.policies
    ?? {}
  const gates = (evaluation?.gates ?? {}) as Record<string, unknown>
  const tiers = (gates.tiers as Array<Record<string, unknown>>) ?? []
  const summary = String(gates.summary ?? '')

  return (
    <Panel>
      <SectionHeader
        title="Champion vs challengers"
        subtitle="Offline counterfactual + live shadow scoring. Shadow policies never influence execution."
      />
      {loadError ? <p className="text-sm text-loss">{loadError}</p> : null}
      {!evaluation ? (
        <p className="text-sm text-terminal-text-muted">
          No evaluation yet. Run <code>poetry run python -m src.learning.cli evaluate</code> after export.
        </p>
      ) : (
        <>
          {summary ? <p className="text-sm text-terminal-text-muted mb-3">{summary}</p> : null}
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
          <div className="overflow-x-auto border border-terminal-border rounded-panel mb-4">
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
                {Object.entries(policies).map(([pid, m]) => (
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
          {tiers.length > 0 ? (
            <div className="flex flex-wrap gap-2 mb-4">
              {tiers.map((tier) => (
                <span
                  key={String(tier.tier_id)}
                  className={`text-xs px-2 py-1 rounded-panel border ${
                    tier.passed
                      ? 'border-emerald/40 text-emerald bg-emerald/10'
                      : 'border-terminal-border text-terminal-text-muted'
                  }`}
                >
                  {String(tier.label)}: {tier.passed ? 'PASS' : 'FAIL'}
                </span>
              ))}
            </div>
          ) : null}
        </>
      )}
      {shadow && shadow.total_scores > 0 ? (
        <p className="text-xs text-terminal-text-muted mb-2">
          Live shadow: {shadow.total_scores} scores over {shadow.span_days ?? shadow.days}d
        </p>
      ) : null}
      {disagreements.length > 0 ? (
        <div className="overflow-x-auto border border-terminal-border rounded-panel">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="bg-terminal-surface text-terminal-text-muted text-left">
                <th className="px-2 py-1">Ticker</th>
                <th className="px-2 py-1">Policy</th>
                <th className="px-2 py-1">Champion</th>
                <th className="px-2 py-1">Challenger</th>
              </tr>
            </thead>
            <tbody>
              {disagreements.map((d, idx) => (
                <tr key={`${d.cycle_id}-${d.ticker}-${idx}`} className="border-t border-terminal-border/60">
                  <td className="px-2 py-1 font-mono">{d.ticker}</td>
                  <td className="px-2 py-1">{d.policy_id}</td>
                  <td className="px-2 py-1">{d.champion_action}</td>
                  <td className="px-2 py-1">{d.recommended_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Panel>
  )
}

function formatPct(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function formatMoney(value: number | null | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—'
  return `£${value.toFixed(2)}`
}
