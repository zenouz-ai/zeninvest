import { useCallback, useEffect, useState } from 'react'
import { latencyApi, type LatencySchedule, type LatencySummary, type LatencySlowCall } from '../api/client'

const PHASE_ORDER = ['screening', 'strategy', 'moderation', 'risk', 'execution']

export function CostsLatencyTab() {
  const [schedule, setSchedule] = useState<LatencySchedule | null>(null)
  const [summary, setSummary] = useState<LatencySummary | null>(null)
  const [slowCalls, setSlowCalls] = useState<LatencySlowCall[]>([])
  const [baselineMsg, setBaselineMsg] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [baselineLoading, setBaselineLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setError(null)
    try {
      const [sched, sum, slow] = await Promise.all([
        latencyApi.getSchedule(),
        latencyApi.getSummary({ days: 30 }),
        latencyApi.getSlowCalls({ days: 7 }),
      ])
      setSchedule(sched)
      setSummary(sum)
      setSlowCalls(slow)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load latency data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  const runBaseline = async (dryRun: boolean) => {
    setBaselineLoading(true)
    setBaselineMsg(null)
    try {
      const res = await latencyApi.triggerBaseline({ dry_run: dryRun })
      setBaselineMsg(res.message)
      setTimeout(() => { void fetchData() }, 5000)
    } catch (e) {
      setBaselineMsg(e instanceof Error ? e.message : 'Baseline failed to start')
    } finally {
      setBaselineLoading(false)
    }
  }

  if (loading) {
    return <p className="text-terminal-text-dim text-sm">Loading latency observability…</p>
  }

  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" className="btn-secondary" onClick={() => { setLoading(true); void fetchData() }}>
          Retry
        </button>
      </div>
    )
  }

  const lockJobs = schedule?.jobs.filter((j) => j.shares_cycle_lock) ?? []
  const offHoursJobs = schedule?.jobs.filter((j) => !j.shares_cycle_lock) ?? []
  const scheduledStats = summary?.run_types.scheduled

  return (
    <div className="space-y-6">
      <div className="card flex flex-wrap items-center gap-3 justify-between">
        <div>
          <h2 className="text-lg font-semibold">Pipeline timing</h2>
          <p className="text-terminal-text-dim text-xs mt-1">
            End-to-end durations from <code className="font-mono">runs.summary_json</code>, step spans, and slow API calls (&gt;1s).
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={baselineLoading}
            onClick={() => void runBaseline(true)}
          >
            {baselineLoading ? 'Starting…' : 'Run baseline (dry)'}
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={baselineLoading}
            onClick={() => void runBaseline(false)}
          >
            Run baseline (live refresh)
          </button>
        </div>
        {baselineMsg && <p className="text-xs text-terminal-text-dim w-full">{baselineMsg}</p>}
      </div>

      {summary && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {summary.frozen_baseline && (
            <div className="card lg:col-span-2">
              <h3 className="text-sm font-semibold mb-2">Scheduled-cycle scorecard vs Jun 2026 baseline (US-9.12)</h3>
              <p className="text-xs text-terminal-text-dim mb-3">
                Frozen baseline: p50 {summary.frozen_baseline.p50_seconds}s · p95 {summary.frozen_baseline.p95_seconds}s ·
                truncation {(summary.frozen_baseline.truncation_rate ?? 0) * 100}%. Refresh with{' '}
                <code className="font-mono">poetry run python -m src.observability.scorecard</code>.
              </p>
              <div className="flex flex-wrap gap-4 text-xs font-mono">
                {!scheduledStats && (
                  <span className="text-terminal-text-dim">
                    No scheduled cycles found in the selected 30d window.
                  </span>
                )}
                {summary.truncation_rate != null && (
                  <span>
                    Truncation (30d scheduled): {(summary.truncation_rate * 100).toFixed(1)}%
                    {summary.baseline_delta?.truncation_rate != null && (
                      <span className={summary.baseline_delta.truncation_rate <= 0 ? ' text-profit' : ' text-loss'}>
                        {' '}
                        ({summary.baseline_delta.truncation_rate >= 0 ? '+' : ''}
                        {(summary.baseline_delta.truncation_rate * 100).toFixed(1)}pp vs baseline)
                      </span>
                    )}
                  </span>
                )}
                {summary.baseline_delta?.p95_seconds != null && (
                  <span>
                    p95 delta: {summary.baseline_delta.p95_seconds >= 0 ? '+' : ''}
                    {summary.baseline_delta.p95_seconds}s
                  </span>
                )}
              </div>
            </div>
          )}
          <div className="card">
            <h3 className="text-sm font-semibold mb-3">Run duration by type (30d)</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-terminal-text-dim text-left">
                  <th className="pb-2">Type</th>
                  <th className="pb-2">n</th>
                  <th className="pb-2">p50</th>
                  <th className="pb-2">p95</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.run_types).map(([type, stats]) => (
                  <tr key={type} className="border-t border-terminal-border">
                    <td className="py-1 font-mono">{type}</td>
                    <td className="py-1">{stats.count}</td>
                    <td className="py-1">{stats.p50_seconds}s</td>
                    <td className="py-1">{stats.p95_seconds}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3 className="text-sm font-semibold mb-3">Cycle phase p50 / p95 (seconds)</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-terminal-text-dim text-left">
                  <th className="pb-2">Phase</th>
                  <th className="pb-2">n</th>
                  <th className="pb-2">p50</th>
                  <th className="pb-2">p95</th>
                </tr>
              </thead>
              <tbody>
                {PHASE_ORDER.filter((p) => summary.phases[p]).map((phase) => {
                  const stats = summary.phases[phase]
                  return (
                    <tr key={phase} className="border-t border-terminal-border">
                      <td className="py-1">{phase}</td>
                      <td className="py-1">{stats.count}</td>
                      <td className="py-1">{stats.p50_seconds}s</td>
                      <td className="py-1">{stats.p95_seconds}s</td>
                    </tr>
                  )
                })}
                {Object.keys(summary.phases).length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-2 text-terminal-text-dim">No phase_timing in recent runs yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {summary && Object.keys(summary.steps).length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold mb-3">Refresh / pre-cycle steps</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            {Object.entries(summary.steps).map(([step, stats]) => (
              <div key={step} className="bg-terminal-surface/30 rounded p-2 border border-terminal-border">
                <div className="text-terminal-text-dim">{step}</div>
                <div className="font-mono">p50 {stats.p50_seconds}s · p95 {stats.p95_seconds}s</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {schedule && (
        <div className="card">
          <h3 className="text-sm font-semibold mb-1">Schedule map ({schedule.timezone})</h3>
          <p className="text-xs text-terminal-text-dim mb-3">{schedule.cycle_lock_note}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div>
              <h4 className="font-semibold text-terminal-text-dim mb-2">Market session (shared lock)</h4>
              <ul className="space-y-1 max-h-48 overflow-y-auto">
                {lockJobs.map((j) => (
                  <li key={j.job_id} className="flex justify-between gap-2 font-mono">
                    <span>{j.job_id}</span>
                    <span className="text-terminal-text-dim">{j.cron}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="font-semibold text-terminal-text-dim mb-2">Off-hours / weekly</h4>
              <ul className="space-y-1 max-h-48 overflow-y-auto">
                {offHoursJobs.map((j) => (
                  <li key={j.job_id} className="flex justify-between gap-2 font-mono">
                    <span>{j.job_id}</span>
                    <span className="text-terminal-text-dim">{j.cron}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {summary && summary.off_hours_jobs.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold mb-3">Recent off-hours job runs</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-terminal-text-dim text-left">
                <th className="pb-2">Type</th>
                <th className="pb-2">Duration</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Started</th>
              </tr>
            </thead>
            <tbody>
              {summary.off_hours_jobs.map((job) => (
                <tr key={job.cycle_id} className="border-t border-terminal-border">
                  <td className="py-1 font-mono">{job.run_type}</td>
                  <td className="py-1">{job.duration_seconds}s</td>
                  <td className="py-1">{job.status}</td>
                  <td className="py-1 text-terminal-text-dim">{job.started_at?.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h3 className="text-sm font-semibold mb-3">Slow API calls (&gt;1s, 7d)</h3>
        {slowCalls.length === 0 ? (
          <p className="text-terminal-text-dim text-xs">No slow calls recorded in the window.</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-terminal-text-dim text-left">
                <th className="pb-2">Service</th>
                <th className="pb-2">Endpoint</th>
                <th className="pb-2">Count</th>
                <th className="pb-2">p95</th>
                <th className="pb-2">Max</th>
              </tr>
            </thead>
            <tbody>
              {slowCalls.map((row) => (
                <tr key={`${row.service}-${row.endpoint}`} className="border-t border-terminal-border">
                  <td className="py-1">{row.service}</td>
                  <td className="py-1 font-mono truncate max-w-[200px]">{row.endpoint}</td>
                  <td className="py-1">{row.count}</td>
                  <td className="py-1">{row.p95_duration_ms}ms</td>
                  <td className="py-1">{row.max_duration_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
