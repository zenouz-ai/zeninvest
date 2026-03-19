import { useEffect, useState } from 'react'
import { runsApi } from '../api/client'
import { TableSkeleton } from '../components/Skeleton'
import type { Run } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'

type RunDiff = {
  from_cycle_id: string
  to_cycle_id: string
  new_positions: string[]
  closed_positions: string[]
  size_changes: { ticker: string; from_qty: number; to_qty: number }[]
}

export default function RunHistory() {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [diffFrom, setDiffFrom] = useState<Run | null>(null)
  const [diffTo, setDiffTo] = useState<Run | null>(null)
  const [diff, setDiff] = useState<RunDiff | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)

  const fetchRuns = async () => {
    setError(null)
    try {
      const data = await runsApi.list({ limit: 50 })
      setRuns(data)
    } catch (err) {
      console.error('Failed to fetch runs:', err)
      setError(err instanceof Error ? err.message : 'Failed to load runs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRuns()
    const interval = setInterval(fetchRuns, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (!diffFrom || !diffTo || diffFrom.cycle_id === diffTo.cycle_id) {
      setDiff(null)
      return
    }
    setDiffLoading(true)
    runsApi
      .getDiff(diffFrom.cycle_id, diffTo.cycle_id)
      .then(setDiff)
      .catch(() => setDiff(null))
      .finally(() => setDiffLoading(false))
  }, [diffFrom, diffTo])

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-gain'
      case 'failed':
        return 'text-loss'
      case 'running':
        return 'text-neutral'
      default:
        return 'text-terminal-text-dim'
    }
  }

  const getRunTypeColor = (runType: string) => {
    switch (runType) {
      case 'scheduled':
        return 'text-neutral'
      case 'manual':
        return 'text-accent'
      case 'dry_run':
        return 'text-terminal-text-dim'
      default:
        return 'text-terminal-text'
    }
  }

  if (loading) {
    return <TableSkeleton rows={5} cols={4} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); fetchRuns() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Run History"
        description="Timeline of past analysis cycles (scheduled, manual, or dry-run). Use Compare Runs to diff two cycles and see position changes. Expand a run to view full decisions and orders. Data refreshes every 30s."
      />

      {/* Run diff */}
      <div className="card">
        <h3 className="text-lg font-semibold tracking-wide mb-4">Compare Runs</h3>
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-xs text-terminal-text-dim mb-1">From (earlier)</label>
            <select
              value={diffFrom?.cycle_id ?? ''}
              onChange={(e) =>
                setDiffFrom(runs.find((r) => r.cycle_id === e.target.value) ?? null)
              }
              className="bg-terminal-bg border border-terminal-border rounded px-3 py-2 text-terminal-text focus:outline-none focus:ring-2 focus:ring-neutral min-w-[200px]"
            >
              <option value="">Select run</option>
              {runs.map((r) => (
                <option key={r.id} value={r.cycle_id}>
                  {safeFormat(r.started_at, 'MMM dd HH:mm')} — {r.cycle_id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-terminal-text-dim mb-1">To (later)</label>
            <select
              value={diffTo?.cycle_id ?? ''}
              onChange={(e) =>
                setDiffTo(runs.find((r) => r.cycle_id === e.target.value) ?? null)
              }
              className="bg-terminal-bg border border-terminal-border rounded px-3 py-2 text-terminal-text focus:outline-none focus:ring-2 focus:ring-neutral min-w-[200px]"
            >
              <option value="">Select run</option>
              {runs.map((r) => (
                <option key={r.id} value={r.cycle_id}>
                  {safeFormat(r.started_at, 'MMM dd HH:mm')} — {r.cycle_id}
                </option>
              ))}
            </select>
          </div>
        </div>
        {diffLoading && (
          <div className="mt-4 text-terminal-text-dim text-sm">Loading diff...</div>
        )}
        {diff && !diffLoading && (
          <div className="mt-4 space-y-3 text-sm">
            {diff.new_positions.length > 0 && (
              <div>
                <span className="text-terminal-text-dim">New positions: </span>
                <span className="text-gain">
                  {diff.new_positions.map(cleanTicker).join(', ') || '—'}
                </span>
              </div>
            )}
            {diff.closed_positions.length > 0 && (
              <div>
                <span className="text-terminal-text-dim">Closed: </span>
                <span className="text-loss">
                  {diff.closed_positions.map(cleanTicker).join(', ') || '—'}
                </span>
              </div>
            )}
            {diff.size_changes.length > 0 && (
              <div>
                <span className="text-terminal-text-dim">Size changes: </span>
                {diff.size_changes.map((c) => (
                  <span key={c.ticker} className="mr-2">
                    {cleanTicker(c.ticker)} {c.from_qty.toFixed(2)} → {c.to_qty.toFixed(2)}
                  </span>
                ))}
              </div>
            )}
            {diff.new_positions.length === 0 &&
              diff.closed_positions.length === 0 &&
              diff.size_changes.length === 0 && (
                <div className="text-terminal-text-dim">No position changes</div>
              )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="lg:col-span-2">
          <div className="card space-y-4">
            {runs.length === 0 ? (
              <div className="text-center py-8 text-terminal-text-dim">
                No runs found
              </div>
            ) : (
              runs.map((run) => (
                <div
                  key={run.id}
                  className={`border-l-2 pl-4 ${
                    run.status === 'completed'
                      ? 'border-gain'
                      : run.status === 'failed'
                      ? 'border-loss'
                      : 'border-neutral'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`font-semibold ${getStatusColor(run.status)}`}>
                          {run.status.toUpperCase()}
                        </span>
                        <span className={`text-sm ${getRunTypeColor(run.run_type)}`}>
                          {run.run_type}
                        </span>
                        <span className="text-xs text-terminal-text-dim font-mono">
                          {run.cycle_id}
                        </span>
                      </div>
                      <div className="text-sm text-terminal-text-dim">
                        Started: {safeFormat(run.started_at, 'MMM dd, yyyy HH:mm:ss')}
                      </div>
                      {run.completed_at && (
                        <div className="text-sm text-terminal-text-dim">
                          Completed: {safeFormat(run.completed_at, 'MMM dd, yyyy HH:mm:ss')}
                        </div>
                      )}
                      {run.summary_json && (
                        <div className="mt-2 text-sm">
                          <span className="text-terminal-text-dim">
                            {run.summary_json.num_trades ?? 0} trades
                          </span>
                          {run.summary_json.num_rejected !== undefined && (
                            <>
                              {' • '}
                              <span className="text-terminal-text-dim">
                                {run.summary_json.num_rejected} rejected
                              </span>
                            </>
                          )}
                          {run.summary_json.duration_seconds && (
                            <>
                              {' • '}
                              <span className="text-terminal-text-dim font-mono">
                                {run.summary_json.duration_seconds.toFixed(1)}s
                              </span>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => setSelectedRun(run)}
                      className="btn-secondary text-sm"
                    >
                      Details
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Details Panel */}
        <div className="lg:col-span-1">
          {selectedRun ? (
            <div className="card sticky top-4">
              <h3 className="text-lg font-semibold tracking-wide mb-4">Run Details</h3>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-terminal-text-dim">Cycle ID</div>
                  <div className="font-mono text-xs break-all">{selectedRun.cycle_id}</div>
                </div>
                <div>
                  <div className="text-terminal-text-dim">Type</div>
                  <div>{selectedRun.run_type}</div>
                </div>
                <div>
                  <div className="text-terminal-text-dim">Status</div>
                  <div className={getStatusColor(selectedRun.status)}>
                    {selectedRun.status}
                  </div>
                </div>
                <div>
                  <div className="text-terminal-text-dim">Started</div>
                  <div>{safeFormat(selectedRun.started_at, 'PPpp')}</div>
                </div>
                {selectedRun.completed_at && (
                  <div>
                    <div className="text-terminal-text-dim">Completed</div>
                    <div>{safeFormat(selectedRun.completed_at, 'PPpp')}</div>
                  </div>
                )}
                {selectedRun.summary_json && (
                  <div className="pt-3 border-t border-terminal-border">
                    <div className="text-terminal-text-dim mb-2">Summary</div>
                    <pre className="text-xs bg-terminal-bg p-2 rounded overflow-auto">
                      {JSON.stringify(selectedRun.summary_json, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card">
              <div className="text-terminal-text-dim text-center py-8">
                Select a run to view details
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
