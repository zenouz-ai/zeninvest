import { useEffect, useState } from 'react'
import { opportunityApi, universeApi } from '../api/client'
import type { InstrumentDetail } from '../types'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'
import { cleanTicker } from '../types'

export default function Opportunity() {
  const [scores, setScores] = useState<any[]>([])
  const [queue, setQueue] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [detail, setDetail] = useState<InstrumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [scoresData, queueData] = await Promise.all([
          opportunityApi.listScores({ limit: 50 }),
          opportunityApi.getQueue(),
        ])
        setScores(scoresData)
        setQueue(queueData)
      } catch (e) {
        console.error('Failed to fetch opportunity data:', e)
      } finally {
        setLoading(false)
      }
    }
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
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading...</div>
      </div>
    )
  }

  const toggleTicker = (ticker: string) => {
    setExpandedTicker((prev) => (prev === ticker ? null : ticker))
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Opportunity Pipeline</h1>

      {expandedTicker && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-accent">
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
        <h2 className="text-lg font-semibold mb-3">Opportunity Queue ({queue.length})</h2>
        {queue.length === 0 ? (
          <p className="text-terminal-text-dim">No queued opportunities.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left">
                  <th className="py-2 font-mono">Ticker</th>
                  <th className="py-2 font-mono">UOV (z)</th>
                  <th className="py-2 font-mono">UOV (EWMA)</th>
                  <th className="py-2 font-mono">Queued cycles</th>
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
        <h2 className="text-lg font-semibold mb-3">Latest UOV Scores ({scores.length})</h2>
        {scores.length === 0 ? (
          <p className="text-terminal-text-dim">No score snapshots.</p>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left sticky top-0 bg-terminal-surface">
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
