import { useEffect, useState } from 'react'
import { opportunityApi, universeApi } from '../api/client'
import { TableSkeleton } from '../components/Skeleton'
import type { InstrumentDetail } from '../types'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'

type QueueConfig = { queue_ttl_cycles: number; immediate_threshold_z: number }
type QueueMeta = { blocked_by_capacity?: boolean; final_allocation_pct?: number }

function parseMetadata(metadataJson: string | null | undefined): QueueMeta {
  if (!metadataJson) return {}
  try {
    return JSON.parse(metadataJson) as QueueMeta
  } catch {
    return {}
  }
}

function getWhyReason(q: { queued_cycles: number; reason?: string | null; metadata_json?: string | null }): string {
  const meta = parseMetadata(q.metadata_json)
  if (meta.blocked_by_capacity) return 'Capacity gated (no slot or cash)'
  if ((q.queued_cycles ?? 1) < 2) return 'Awaiting 2nd cycle for promotion'
  return 'Below immediate threshold'
}

function getWhenAction(
  q: { queued_cycles: number; metadata_json?: string | null },
  config: QueueConfig
): string {
  const meta = parseMetadata(q.metadata_json)
  const cycles = q.queued_cycles ?? 1
  const ttl = config?.queue_ttl_cycles ?? 4
  const expiresIn = Math.max(0, ttl - cycles)

  const parts: string[] = []
  if (cycles < 2) {
    parts.push('Promotes next cycle if above threshold')
  } else if (meta.blocked_by_capacity) {
    parts.push('When slot/cash frees')
  } else {
    parts.push('Eligible for promotion next cycle')
  }
  if (expiresIn > 0) {
    parts.push(`Expires in ${expiresIn} cycle${expiresIn !== 1 ? 's' : ''}`)
  }
  return parts.join(' · ')
}

export default function Opportunity() {
  const [scores, setScores] = useState<any[]>([])
  const [queue, setQueue] = useState<any[]>([])
  const [config, setConfig] = useState<QueueConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [detail, setDetail] = useState<InstrumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const fetchData = async () => {
    setError(null)
    try {
      const [scoresData, queueData, configData] = await Promise.all([
        opportunityApi.listScores({ limit: 50 }),
        opportunityApi.getQueue(),
        opportunityApi.getConfig().catch(() => null),
      ])
      setConfig(configData ?? null)
      setScores(scoresData)
      const queueByTicker = new Map<string, (typeof queueData)[0]>()
      for (const q of queueData) {
        queueByTicker.set(q.ticker, q)
      }
      const seenTickers = new Set(queueByTicker.keys())
      for (const s of scoresData) {
        const isQueued = s.action === 'QUEUED' || s.stage === 'opportunity_queue'
        if (isQueued && !seenTickers.has(s.ticker)) {
          seenTickers.add(s.ticker)
          queueByTicker.set(s.ticker, {
            ticker: s.ticker,
            last_uov_z: s.uov_z ?? 0,
            last_uov_ewma: s.uov_ewma ?? 0,
            queued_cycles: 1,
          } as typeof queueData[0])
        }
      }
      setQueue(Array.from(queueByTicker.values()).sort((a, b) => (b.last_uov_ewma ?? 0) - (a.last_uov_ewma ?? 0)))
    } catch (e) {
      console.error('Failed to fetch opportunity data:', e)
      setError(e instanceof Error ? e.message : 'Failed to load opportunity data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  useEffect(() => {
    if (!expandedTicker) {
      setDetail(null)
      return
    }
    setDetailLoading(true)
    universeApi
      .getByTicker(expandedTicker)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }, [expandedTicker])

  if (loading) {
    return <TableSkeleton rows={5} cols={4} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); fetchData() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  const toggleTicker = (ticker: string) => {
    setExpandedTicker((prev) => (prev === ticker ? null : ticker))
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Opportunity Pipeline"
        description="UOV-ranked queue of tickers awaiting execution, and latest score snapshots. Tickers above the queue threshold but below immediate threshold sit in the queue. Click a row to see full LLM output (strategy, moderation, risk)."
      />

      {expandedTicker && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold tracking-wide text-accent">
              LLM output — {cleanTicker(expandedTicker)}
            </h2>
            <button
              type="button"
              onClick={() => setExpandedTicker(null)}
              className="text-sm text-terminal-text-dim hover:text-terminal-text"
            >
              Close
            </button>
          </div>
          {detailLoading ? (
            <div className="text-terminal-text-dim text-sm">Loading...</div>
          ) : detail ? (
            <LLMOutputPanel
              key={detail.ticker}
              ticker={detail.ticker}
              lastDecision={detail.last_decision}
              label={detail.label}
            />
          ) : (
            <div className="text-terminal-text-dim text-sm">No decision data for this ticker.</div>
          )}
        </div>
      )}

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Opportunity Queue ({queue.length})</h2>
        <p className="text-terminal-text-dim text-sm mb-3">
          Tickers above the queue threshold but deferred. Action: BUY. Promotes when queued ≥2 cycles and capacity available.
          {config && ` Queue TTL: ${config.queue_ttl_cycles} cycles.`}
        </p>
        {queue.length === 0 ? (
          <p className="text-terminal-text-dim">No queued opportunities.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">UOV (z)</th>
                  <th className="py-2 font-mono">UOV (EWMA)</th>
                  <th className="py-2 font-mono">Queued cycles</th>
                  <th className="py-2">When queued</th>
                  <th className="py-2">Why queued</th>
                  <th className="py-2">Action</th>
                  <th className="py-2">When action taken</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((q) => (
                  <tr
                    key={q.ticker}
                    onClick={() => toggleTicker(q.ticker)}
                    className={`border-b border-terminal-border cursor-pointer hover:bg-terminal-surface/50 transition-colors ${
                      expandedTicker === q.ticker ? 'bg-terminal-surface/70' : ''
                    }`}
                  >
                    <td className="py-2 font-mono">{cleanTicker(q.ticker)}</td>
                    <td className="py-2 font-mono">{q.last_uov_z?.toFixed(3)}</td>
                    <td className="py-2 font-mono">{q.last_uov_ewma?.toFixed(3)}</td>
                    <td className="py-2 font-mono">{q.queued_cycles}</td>
                    <td className="py-2 text-terminal-text-dim text-xs">
                      {q.created_at ? safeFormat(q.created_at, 'MMM d, HH:mm', '—') : '—'}
                    </td>
                    <td className="py-2 text-terminal-text-dim text-xs max-w-[140px] truncate" title={getWhyReason(q)}>
                      {getWhyReason(q)}
                    </td>
                    <td className="py-2 font-mono text-gain">{q.action ?? 'BUY'}</td>
                    <td className="py-2 text-terminal-text-dim text-xs max-w-[180px]" title={config ? getWhenAction(q, config) : ''}>
                      {config ? getWhenAction(q, config) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-terminal-text-dim text-xs mt-2">
          Click a row to see full LLM output (strategy, moderation, risk) for that ticker.
        </p>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold tracking-wide mb-3">Latest UOV Scores ({scores.length})</h2>
        {scores.length === 0 ? (
          <p className="text-terminal-text-dim">No score snapshots.</p>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-terminal-surface z-10">
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Cycle</th>
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">Action</th>
                  <th className="py-2 font-mono">uov_raw</th>
                  <th className="py-2 font-mono">uov_z</th>
                  <th className="py-2 font-mono">uov_ewma</th>
                </tr>
              </thead>
              <tbody>
                {scores.slice(0, 100).map((s) => (
                  <tr
                    key={`${s.cycle_id}-${s.ticker}`}
                    onClick={() => toggleTicker(s.ticker)}
                    className={`border-b border-terminal-border cursor-pointer hover:bg-terminal-surface/50 transition-colors ${
                      expandedTicker === s.ticker ? 'bg-terminal-surface/70' : ''
                    }`}
                  >
                    <td className="py-1 font-mono text-xs">{s.cycle_id}</td>
                    <td className="py-1 font-mono">{cleanTicker(s.ticker)}</td>
                    <td className="py-1">{s.action ?? '—'}</td>
                    <td className="py-1 font-mono">{s.uov_raw?.toFixed(3)}</td>
                    <td className="py-1 font-mono">{s.uov_z?.toFixed(3)}</td>
                    <td className="py-1 font-mono">{s.uov_ewma?.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-terminal-text-dim text-xs mt-2">
          Click a row to see full LLM output (strategy, moderation, risk) for that ticker.
        </p>
      </div>
    </div>
  )
}
