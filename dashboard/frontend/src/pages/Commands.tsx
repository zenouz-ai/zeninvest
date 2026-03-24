import { useState, useEffect } from 'react'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { StatusPill } from '../components/StatusPill'
import type { PillVariant } from '../components/StatusPill'
import { SectionHeader } from '../components/SectionHeader'
import { TableSkeleton } from '../components/Skeleton'
import { commandsApi } from '../api/client'
import type { SlackCommand, CommandStats } from '../types'
import { cleanTicker } from '../types'

const STATUS_VARIANT: Record<string, PillVariant> = {
  executed: 'active',
  rejected: 'alert',
  error: 'alert',
  executing: 'warning',
  awaiting_confirmation: 'warning',
  expired: 'warning',
  cancelled: 'dim',
  received: 'dim',
  review_only: 'live',
}

const ACTION_COLOUR: Record<string, string> = {
  BUY: 'text-terminal-positive',
  SELL: 'text-terminal-negative',
  REVIEW: 'text-cyan',
}

function safeFormat(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function Commands() {
  const [commands, setCommands] = useState<SlackCommand[]>([])
  const [stats, setStats] = useState<CommandStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [filterAction, setFilterAction] = useState<string>('')
  const [filterStatus, setFilterStatus] = useState<string>('')

  const fetchData = async () => {
    try {
      setLoading(true)
      setError(null)
      const params: Record<string, string | number> = { limit: 100 }
      if (filterAction) params.action = filterAction
      if (filterStatus) params.status = filterStatus
      const [cmds, st] = await Promise.all([
        commandsApi.list(params),
        commandsApi.stats(),
      ])
      setCommands(cmds)
      setStats(st)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load commands')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [filterAction, filterStatus])

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="Trade Commands"
        title="Commands"
        description="Slack-triggered trade commands with full pipeline audit trail. Every BUY, SELL, and REVIEW command is logged here."
      />

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-terminal-text-dim">Total</p>
            <p className="text-2xl font-heading font-bold mt-1">{stats.total}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-terminal-positive">Executed</p>
            <p className="text-2xl font-heading font-bold mt-1 text-terminal-positive">{stats.by_status?.executed || 0}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-terminal-negative">Rejected</p>
            <p className="text-2xl font-heading font-bold mt-1 text-terminal-negative">{stats.by_status?.rejected || 0}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-cyan">Review</p>
            <p className="text-2xl font-heading font-bold mt-1 text-cyan">{stats.by_status?.review_only || 0}</p>
          </Panel>
        </div>
      )}

      {/* Filters */}
      <Panel className="p-4">
        <div className="flex flex-wrap gap-3 items-center">
          <label className="text-xs text-terminal-text-dim uppercase tracking-wide">Action</label>
          <select
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
            className="bg-terminal-surface border border-terminal-border rounded px-2 py-1 text-sm text-terminal-text focus:outline-none focus:ring-1 focus:ring-cyan/40"
          >
            <option value="">All</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
            <option value="REVIEW">REVIEW</option>
          </select>
          <label className="text-xs text-terminal-text-dim uppercase tracking-wide ml-4">Status</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-terminal-surface border border-terminal-border rounded px-2 py-1 text-sm text-terminal-text focus:outline-none focus:ring-1 focus:ring-cyan/40"
          >
            <option value="">All</option>
            <option value="executed">Executed</option>
            <option value="rejected">Rejected</option>
            <option value="review_only">Review</option>
            <option value="error">Error</option>
            <option value="received">Received</option>
          </select>
          <button
            onClick={fetchData}
            className="ml-auto text-xs text-cyan hover:text-cyan/80 transition-colors"
          >
            Refresh
          </button>
        </div>
      </Panel>

      {/* Commands table */}
      <Panel className="p-0 overflow-hidden">
        <SectionHeader title="Command History" />
        {loading ? (
          <div className="p-4"><TableSkeleton rows={6} cols={6} /></div>
        ) : error ? (
          <div className="p-6 text-center">
            <p className="text-terminal-negative text-sm">{error}</p>
            <button onClick={fetchData} className="mt-2 text-xs text-cyan hover:text-cyan/80">Retry</button>
          </div>
        ) : commands.length === 0 ? (
          <div className="p-8 text-center text-terminal-text-dim text-sm">
            No commands yet. Send a trade command in Slack to get started.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-terminal-text-dim border-b border-terminal-border">
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">Time</th>
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">User</th>
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">Action</th>
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">Ticker</th>
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">Message</th>
                  <th className="px-4 py-3 sticky top-0 bg-terminal-surface z-10">Status</th>
                </tr>
              </thead>
              <tbody>
                {commands.map((cmd) => (
                  <>
                    <tr
                      key={cmd.id}
                      className="border-b border-terminal-border/50 hover:bg-white/[0.02] cursor-pointer transition-colors"
                      onClick={() => setExpandedId(expandedId === cmd.id ? null : cmd.id)}
                      aria-expanded={expandedId === cmd.id}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-terminal-text-dim whitespace-nowrap">
                        {safeFormat(cmd.timestamp)}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{cmd.user_id || '—'}</td>
                      <td className="px-4 py-3">
                        <span className={`font-bold text-xs ${ACTION_COLOUR[cmd.action || ''] || 'text-terminal-text'}`}>
                          {cmd.action || '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs font-medium">
                        {cmd.ticker ? cleanTicker(cmd.ticker) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs text-terminal-text-muted max-w-[200px] truncate">
                        {cmd.raw_message}
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill
                          variant={STATUS_VARIANT[cmd.status] || 'dim'}
                          label={cmd.status}
                        />
                      </td>
                    </tr>
                    {expandedId === cmd.id && (
                      <tr key={`${cmd.id}-detail`} className="bg-white/[0.01]">
                        <td colSpan={6} className="px-6 py-4">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                            <div>
                              <p className="text-terminal-text-dim uppercase tracking-wide mb-1">Cycle ID</p>
                              <p className="font-mono">{cmd.cycle_id || '—'}</p>
                            </div>
                            <div>
                              <p className="text-terminal-text-dim uppercase tracking-wide mb-1">Order ID</p>
                              <p className="font-mono">{cmd.order_id ?? '—'}</p>
                            </div>
                            {cmd.rejection_reason && (
                              <div className="sm:col-span-2">
                                <p className="text-terminal-text-dim uppercase tracking-wide mb-1">Rejection Reason</p>
                                <p className="text-terminal-negative">{cmd.rejection_reason}</p>
                              </div>
                            )}
                            {cmd.response_message && (
                              <div className="sm:col-span-2">
                                <p className="text-terminal-text-dim uppercase tracking-wide mb-1">Response</p>
                                <p className="text-terminal-text-muted whitespace-pre-wrap">{cmd.response_message}</p>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
