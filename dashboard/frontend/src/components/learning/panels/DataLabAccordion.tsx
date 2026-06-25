import { useEffect, useState } from 'react'
import {
  learningApi,
  memoryApi,
  type LearningDatasetManifest,
  type LearningDatasetPreview,
  type LearningExportSummary,
} from '../../../api/client'
import { Panel } from '../../Panel'
import { SectionHeader } from '../../SectionHeader'
import { InfoCallout } from '../InfoCallout'
import { formatAge, formatBytes } from '../formatters'

const DATASET_ARTIFACTS: { id: string; label: string; download?: string; json?: boolean }[] = [
  { id: 'decisions', label: 'Decisions', download: 'decisions.parquet' },
  { id: 'features', label: 'Features', download: 'features.parquet' },
  { id: 'outcomes', label: 'Outcomes', download: 'outcomes.parquet' },
  { id: 'merged', label: 'Merged', download: 'merged.parquet' },
  { id: 'rejected', label: 'Rejected', download: 'rejected.parquet' },
  { id: 'text_corpus', label: 'Text corpus', download: 'text_corpus.parquet' },
  { id: 'memory_bundle', label: 'Memory JSONL', download: 'memory_bundle.jsonl' },
  { id: 'schema', label: 'Schema', json: true },
  { id: 'splits', label: 'Splits', json: true },
]

export function RawDatasetsPanel() {
  const [versions, setVersions] = useState<string[]>([])
  const [version, setVersion] = useState<string>('')
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
      else if (res.versions.length > 0) setVersion(res.versions[res.versions.length - 1])
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
    <div data-testid="learning-raw-datasets">
      <SectionHeader
        title="Raw datasets"
        subtitle="On-disk parquet, JSONL, schema and splits. Preview is paginated; download for full files."
      />
      <InfoCallout
        why="Governance and reproducibility — audit rows without re-running the export pipeline."
        freshSource="data/learning/parquet/{version}/ · weekly run-export"
        action="poetry run python -m src.learning.cli run-export"
        roadmapId="US-2.5"
      />
      <div className="flex flex-wrap gap-2 items-center mb-3">
        <select
          className="bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          disabled={loading || versions.length === 0}
        >
          {(versions.length > 0 ? versions : version ? [version] : []).map((v) => (
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

      {previewError ? <p className="text-sm text-terminal-text-muted">{previewError}</p> : null}

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
    </div>
  )
}

function ExportHistoryTable({ exports }: { exports: LearningExportSummary[] }) {
  if (exports.length === 0) {
    return <p className="text-sm text-terminal-text-muted">No export runs recorded yet.</p>
  }
  return (
    <div className="overflow-x-auto border border-terminal-border rounded-panel">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="bg-terminal-surface text-terminal-text-muted text-left">
            <th className="px-2 py-1">Run ID</th>
            <th className="px-2 py-1">Version</th>
            <th className="px-2 py-1">Rows</th>
            <th className="px-2 py-1">Text docs</th>
            <th className="px-2 py-1">Status</th>
            <th className="px-2 py-1">When</th>
          </tr>
        </thead>
        <tbody>
          {exports.map((row) => (
            <tr key={row.run_id} className="border-t border-terminal-border/60">
              <td className="px-2 py-1 font-mono">{row.run_id}</td>
              <td className="px-2 py-1">{row.dataset_version}</td>
              <td className="px-2 py-1">{row.rows.toLocaleString()}</td>
              <td className="px-2 py-1">{row.text_corpus_rows.toLocaleString()}</td>
              <td className="px-2 py-1">{row.status}</td>
              <td className="px-2 py-1">{formatAge(row.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SectorRegimeGraphDeferred() {
  return (
    <div className="mt-6 border-t border-terminal-border pt-4">
      <SectionHeader
        title="Sector + regime graph (deferred)"
        subtitle="US-6.4 — Neo4j removed from ZenInvest VPS to save RAM; code remains in repo."
      />
      <InfoCallout
        why="Structured precedent by sector and macro regime was optional Track B research only — not used in live trading."
        action="Re-enable when shadow memory shows lift or operator adopts the graph weekly. See roadmap US-6.4."
        roadmapId="US-6.4"
      />
      <p className="text-sm text-terminal-text-muted mt-2">
        Similar-case search above uses vector embeddings and does not require Neo4j.
      </p>
    </div>
  )
}

function SimilarCasesSearch() {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Array<Record<string, unknown>>>([])
  const [searchError, setSearchError] = useState<string | null>(null)

  return (
    <div>
      <SectionHeader
        title="Similar past cases"
        subtitle="Vector search over memory_bundle (requires sync-embeddings)."
      />
      <InfoCallout
        why="Track B precedent retrieval for shadow challenger_memory — not live until gates pass."
        action="poetry run python -m src.learning.cli sync-embeddings"
        roadmapId="US-6.2"
      />
      <p className="text-xs text-amber/90 mb-2">Each search uses embedding API budget when enabled.</p>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="flex-1 min-w-[200px] bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm"
          placeholder="Describe thesis or pattern…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          type="button"
          className="px-3 py-2 text-sm border border-violet/40 text-violet rounded-panel hover:bg-violet/10"
          onClick={async () => {
            if (!query.trim()) return
            setSearchError(null)
            try {
              const res = await memoryApi.similar(query.trim(), { k: 5 })
              setHits(res.hits as Array<Record<string, unknown>>)
              if (res.hits.length === 0) setSearchError('No hits — run sync-embeddings or check embedding budget.')
            } catch (err) {
              setHits([])
              setSearchError(err instanceof Error ? err.message : 'Search failed')
            }
          }}
        >
          Search
        </button>
      </div>
      {searchError ? <p className="text-sm text-terminal-text-muted mt-2">{searchError}</p> : null}
      {hits.length > 0 ? (
        <ul className="mt-3 space-y-2 text-sm">
          {hits.map((hit) => (
            <li key={String(hit.doc_id)} className="border border-terminal-border rounded-panel p-2">
              <span className="font-mono text-cyan">{String(hit.ticker)}</span>
              {' · '}
              score {Number(hit.score).toFixed(3)}
              {' · '}
              {String((hit.metadata as Record<string, unknown>)?.label_3class ?? '—')}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function TemporalEpisodesPanel() {
  return (
    <div className="mt-6 border-t border-terminal-border pt-4">
      <SectionHeader
        title="Temporal episodes (Graphiti export)"
        subtitle="Ingest-ready JSON only — no Graphiti Docker service in Wave 1."
      />
      <InfoCallout
        why="Track B temporal memory export for future ingestion; upstream Graphiti CE is deprecated."
        action="poetry run python -m src.learning.cli sync-graphiti"
        roadmapId="US-6.5"
      />
      <p className="text-sm text-terminal-text-muted font-mono mt-2">
        Output: data/learning/graphiti/v6/episodes.json
      </p>
      <p className="text-xs text-terminal-text-muted mt-2">
        For temporal queries today, use Neo4j <code className="font-mono">decision_ts</code> on Decision nodes
        (see docs/MEMORY_AND_LEARNING.md).
      </p>
    </div>
  )
}

interface DataLabAccordionProps {
  exports: LearningExportSummary[]
}

export function DataLabAccordion({ exports }: DataLabAccordionProps) {
  const [open, setOpen] = useState(false)
  const [exportRows, setExportRows] = useState<LearningExportSummary[]>(exports)

  useEffect(() => {
    if (open && exportRows.length <= 1) {
      learningApi.listExports(10).then((r) => setExportRows(r.exports)).catch(() => {})
    }
  }, [open, exportRows.length])

  return (
    <Panel data-testid="learning-data-lab">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <SectionHeader
          title="Data lab (advanced)"
          subtitle="Export history, raw parquet preview, similar-case search — collapsed by default."
        />
        <span className="text-sm text-cyan ml-4 shrink-0">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open ? (
        <div className="mt-4 space-y-6 border-t border-terminal-border pt-4">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-terminal-text-muted mb-2">Export history</h4>
            <ExportHistoryTable exports={exportRows.length > 0 ? exportRows : exports} />
          </div>
          <RawDatasetsPanel />
          <SimilarCasesSearch />
          <SectorRegimeGraphDeferred />
          <TemporalEpisodesPanel />
        </div>
      ) : null}
    </Panel>
  )
}
