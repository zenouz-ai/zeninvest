import { useEffect, useState } from 'react'
import { runsApi } from '../api/client'
import type { Run } from '../types'
import { format } from 'date-fns'

export default function RunHistory() {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)

  useEffect(() => {
    const fetchRuns = async () => {
      try {
        const data = await runsApi.list({ limit: 50 })
        setRuns(data)
      } catch (error) {
        console.error('Failed to fetch runs:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchRuns()
    const interval = setInterval(fetchRuns, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

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
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading run history...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Run History</h1>

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
                        Started: {format(new Date(run.started_at), 'MMM dd, yyyy HH:mm:ss')}
                      </div>
                      {run.completed_at && (
                        <div className="text-sm text-terminal-text-dim">
                          Completed: {format(new Date(run.completed_at), 'MMM dd, yyyy HH:mm:ss')}
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
              <h3 className="text-lg font-semibold mb-4">Run Details</h3>
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
                  <div>{format(new Date(selectedRun.started_at), 'PPpp')}</div>
                </div>
                {selectedRun.completed_at && (
                  <div>
                    <div className="text-terminal-text-dim">Completed</div>
                    <div>{format(new Date(selectedRun.completed_at), 'PPpp')}</div>
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
