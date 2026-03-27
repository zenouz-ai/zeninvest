import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { StatusPill } from '../components/StatusPill'
import type { PillVariant } from '../components/StatusPill'
import { SectionHeader } from '../components/SectionHeader'
import { TableSkeleton } from '../components/Skeleton'
import { chatApi, commandsApi } from '../api/client'
import { useSSE } from '../hooks/useSSE'
import type {
  ChatAction,
  ChatResearchLog,
  ChatSessionDetail,
  ChatSessionSummary,
  ChatTurn,
  CommandStats,
  Event,
  SlackCommand,
} from '../types'
import { cleanTicker } from '../types'

const STATUS_VARIANT: Record<string, PillVariant> = {
  executed: 'active',
  rejected: 'alert',
  error: 'alert',
  failed: 'alert',
  executing: 'warning',
  awaiting_confirmation: 'warning',
  confirmed: 'live',
  expired: 'warning',
  cancelled: 'dim',
  partial: 'warning',
  received: 'dim',
  review_only: 'live',
  active: 'live',
  closed: 'dim',
}

const ACTION_COLOUR: Record<string, string> = {
  BUY: 'text-gain',
  SELL: 'text-loss',
  REVIEW: 'text-cyan',
  CANCEL: 'text-warning',
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

function relativeSessionLabel(session: ChatSessionSummary): string {
  const started = session.channel_type === 'slack' ? 'Started in Slack' : 'Started in dashboard'
  const last = session.last_channel_type && session.last_channel_type !== session.channel_type
    ? `, last active in ${session.last_channel_type}`
    : ''
  return `${started}${last}`
}

function latestAssistantTurn(detail: ChatSessionDetail | null): ChatTurn | null {
  if (!detail) return null
  for (let idx = detail.turns.length - 1; idx >= 0; idx -= 1) {
    const turn = detail.turns[idx]
    if (turn.role === 'assistant') return turn
  }
  return null
}

function renderActionStatus(action: ChatAction) {
  return (
    <StatusPill
      variant={STATUS_VARIANT[action.status] || 'dim'}
      label={action.status.replace(/_/g, ' ')}
    />
  )
}

function renderHistoryStatus(status: string) {
  return (
    <StatusPill
      variant={STATUS_VARIANT[status] || 'dim'}
      label={status}
    />
  )
}

function SessionList({
  sessions,
  selectedSessionId,
  loading,
  onSelect,
  onCreate,
}: {
  sessions: ChatSessionSummary[]
  selectedSessionId: number | null
  loading: boolean
  onSelect: (sessionId: number) => void
  onCreate: () => void
}) {
  return (
    <Panel className="space-y-4 p-0">
      <div className="flex items-center justify-between px-5 pt-5">
        <SectionHeader
          eyebrow="Operator Sessions"
          title="Conversations"
          subtitle="Slack threads and dashboard chat share the same backend session ledger."
        />
        <button
          onClick={onCreate}
          className="rounded border border-cyan/40 px-3 py-1.5 text-xs uppercase tracking-wide text-cyan transition-colors hover:border-cyan hover:bg-cyan/10"
        >
          New Session
        </button>
      </div>

      {loading ? (
        <div className="px-5 pb-5">
          <TableSkeleton rows={5} cols={2} />
        </div>
      ) : sessions.length === 0 ? (
        <div className="px-5 pb-5 text-sm text-terminal-text-dim">
          No conversation sessions yet. Start in Slack or open a new dashboard session here.
        </div>
      ) : (
        <div className="max-h-[720px] space-y-2 overflow-y-auto px-3 pb-4">
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => onSelect(session.id)}
              className={`w-full rounded-xl border px-4 py-3 text-left transition-colors ${
                selectedSessionId === session.id
                  ? 'border-cyan bg-cyan/10'
                  : 'border-terminal-border bg-terminal-surface/40 hover:border-terminal-border-strong hover:bg-white/[0.03]'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-terminal-text">
                    {session.title || `Session ${session.id}`}
                  </p>
                  <p className="mt-1 text-xs text-terminal-text-dim">
                    {relativeSessionLabel(session)}
                  </p>
                </div>
                {session.pending_actions_count > 0 && (
                  <span className="rounded-full bg-warning/10 px-2 py-1 text-[10px] uppercase tracking-wide text-warning">
                    {session.pending_actions_count} pending
                  </span>
                )}
              </div>
              <p className="mt-3 line-clamp-2 text-xs text-terminal-text-muted">
                {session.last_message_text || 'No turns yet.'}
              </p>
              <div className="mt-3 flex items-center justify-between text-[11px] text-terminal-text-dim">
                <span>{safeFormat(session.last_activity_at)}</span>
                <StatusPill
                  variant={STATUS_VARIANT[session.status] || 'dim'}
                  label={session.status}
                />
              </div>
            </button>
          ))}
        </div>
      )}
    </Panel>
  )
}

function ChatThread({
  sessionDetail,
  loading,
  submitting,
  composer,
  onComposerChange,
  onSubmit,
  onClose,
}: {
  sessionDetail: ChatSessionDetail | null
  loading: boolean
  submitting: boolean
  composer: string
  onComposerChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onClose: () => void
}) {
  const latestAssistant = latestAssistantTurn(sessionDetail)

  return (
    <Panel hero className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeader
          eyebrow="Live Thread"
          title={sessionDetail?.title || 'Conversational Trading'}
          subtitle="Natural language is allowed, but execution still routes through explicit proposals and confirmations."
        />
        <div className="flex items-center gap-2">
          {sessionDetail && renderHistoryStatus(sessionDetail.status)}
          {sessionDetail?.last_channel_type && (
            <span className="rounded-full border border-terminal-border px-2 py-1 text-[10px] uppercase tracking-wide text-terminal-text-dim">
              Last active: {sessionDetail.last_channel_type}
            </span>
          )}
          {sessionDetail?.status === 'active' && (
            <button
              onClick={onClose}
              className="rounded border border-terminal-border px-3 py-1.5 text-xs uppercase tracking-wide text-terminal-text-dim transition-colors hover:border-terminal-border-strong hover:text-terminal-text"
            >
              End Session
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <TableSkeleton rows={8} cols={1} />
      ) : !sessionDetail ? (
        <div className="rounded-2xl border border-dashed border-terminal-border p-8 text-center text-sm text-terminal-text-dim">
          Open a dashboard session or continue an active Slack thread from the session rail.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 text-[11px] text-terminal-text-dim">
            <span>Started: {safeFormat(sessionDetail.started_at)}</span>
            <span>Operator: {sessionDetail.user_id || 'dashboard'}</span>
            <span>{relativeSessionLabel(sessionDetail)}</span>
            {sessionDetail.linked_cycle_id && <span>Cycle: {sessionDetail.linked_cycle_id}</span>}
          </div>

          <div className="max-h-[540px] space-y-3 overflow-y-auto rounded-2xl border border-terminal-border/70 bg-terminal-surface/40 p-4">
            {sessionDetail.turns.length === 0 ? (
              <p className="text-sm text-terminal-text-dim">
                No turns yet. Ask for research, compare tickers, preview a trade, update a stop, or run a bounded portfolio rule.
              </p>
            ) : (
              sessionDetail.turns.map((turn) => (
                <div
                  key={turn.id}
                  className={`max-w-[92%] rounded-2xl border px-4 py-3 ${
                    turn.role === 'user'
                      ? 'ml-auto border-cyan/30 bg-cyan/10 text-terminal-text'
                      : turn.role === 'assistant'
                        ? 'border-terminal-border bg-terminal-surface text-terminal-text'
                        : 'border-terminal-border/50 bg-white/[0.03] text-terminal-text-dim'
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-terminal-text-dim">
                    <span>{turn.role}</span>
                    <span>{safeFormat(turn.created_at)}</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6">
                    {turn.message_text}
                  </pre>
                </div>
              ))
            )}
          </div>

          {latestAssistant?.message_text && (
            <div className="rounded-xl border border-terminal-border/80 bg-terminal-surface/50 p-3 text-xs text-terminal-text-dim">
              <span className="mr-2 uppercase tracking-wide text-terminal-text">Latest system reply</span>
              {latestAssistant.message_text.slice(0, 220)}
              {latestAssistant.message_text.length > 220 ? '…' : ''}
            </div>
          )}

          <form className="space-y-3" onSubmit={onSubmit}>
            <textarea
              value={composer}
              onChange={(event) => onComposerChange(event.target.value)}
              placeholder="Try: review AMD and compare it with NVDA, or liquidate holdings below £100, or set the stop for TSLA to 240"
              rows={4}
              className="w-full rounded-2xl border border-terminal-border bg-terminal-surface/70 px-4 py-3 text-sm text-terminal-text outline-none transition-colors placeholder:text-terminal-text-dim focus:border-cyan"
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-terminal-text-dim">
                Dashboard replies continue the same session even when the thread started in Slack.
              </p>
              <button
                type="submit"
                disabled={submitting || !composer.trim()}
                className="rounded border border-cyan/50 bg-cyan/10 px-4 py-2 text-xs uppercase tracking-wide text-cyan transition-colors hover:border-cyan hover:bg-cyan/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? 'Sending…' : 'Send'}
              </button>
            </div>
          </form>
        </>
      )}
    </Panel>
  )
}

function ActionRail({
  sessionDetail,
  onConfirm,
  onReject,
}: {
  sessionDetail: ChatSessionDetail | null
  onConfirm: (actionId: number) => void
  onReject: (actionId: number) => void
}) {
  const pendingActions = useMemo(
    () => (sessionDetail?.actions || []).filter((action) =>
      ['awaiting_confirmation', 'confirmed', 'executing'].includes(action.status)
    ),
    [sessionDetail]
  )

  const recentActions = useMemo(
    () => (sessionDetail?.actions || []).slice(0, 6),
    [sessionDetail]
  )

  const researchLogs = useMemo(
    () => (sessionDetail?.research_logs || []).slice(0, 8),
    [sessionDetail]
  )

  return (
    <div className="space-y-4">
      <Panel className="space-y-4">
        <SectionHeader
          eyebrow="Execution"
          title="Pending Proposals"
          subtitle="Every action stays bounded, auditable, and explicit before execution."
        />
        {pendingActions.length === 0 ? (
          <p className="text-sm text-terminal-text-dim">No pending proposals in this session.</p>
        ) : (
          pendingActions.map((action) => (
            <div key={action.id} className="rounded-2xl border border-terminal-border bg-terminal-surface/40 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-terminal-text">{action.title || action.action_type}</p>
                  <p className="mt-1 text-xs text-terminal-text-dim">
                    {action.ticker ? cleanTicker(action.ticker) : 'Multi-item action'}
                  </p>
                </div>
                {renderActionStatus(action)}
              </div>
              {action.preview_text && (
                <pre className="mt-3 whitespace-pre-wrap break-words text-xs leading-6 text-terminal-text-muted">
                  {action.preview_text}
                </pre>
              )}
              {action.status === 'awaiting_confirmation' && (
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={() => onConfirm(action.id)}
                    className="rounded border border-gain/50 bg-gain/10 px-3 py-1.5 text-xs uppercase tracking-wide text-gain transition-colors hover:border-gain"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => onReject(action.id)}
                    className="rounded border border-loss/50 bg-loss/10 px-3 py-1.5 text-xs uppercase tracking-wide text-loss transition-colors hover:border-loss"
                  >
                    Reject
                  </button>
                </div>
              )}
              {action.expires_at && (
                <p className="mt-3 text-[11px] text-terminal-text-dim">
                  Expires: {safeFormat(action.expires_at)}
                </p>
              )}
            </div>
          ))
        )}
      </Panel>

      <Panel className="space-y-4">
        <SectionHeader
          eyebrow="Audit Trail"
          title="Recent Actions"
          subtitle="Executed, rejected, and expired actions stay attached to the session."
        />
        {recentActions.length === 0 ? (
          <p className="text-sm text-terminal-text-dim">No action history yet.</p>
        ) : (
          <div className="space-y-3">
            {recentActions.map((action) => (
              <div key={action.id} className="rounded-xl border border-terminal-border bg-terminal-surface/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-terminal-text">
                    {action.title || action.action_type}
                  </p>
                  {renderActionStatus(action)}
                </div>
                {action.rejection_reason && (
                  <p className="mt-2 text-xs text-loss">{action.rejection_reason}</p>
                )}
                {action.result_json && (
                  <pre className="mt-2 whitespace-pre-wrap break-words text-[11px] leading-5 text-terminal-text-dim">
                    {JSON.stringify(action.result_json, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel className="space-y-4">
        <SectionHeader
          eyebrow="Research"
          title="Trace"
          subtitle="Conversational research logs are separate from the legacy one-shot Slack command audit."
        />
        {researchLogs.length === 0 ? (
          <p className="text-sm text-terminal-text-dim">No research trace for this session yet.</p>
        ) : (
          <div className="space-y-3">
            {researchLogs.map((log: ChatResearchLog) => (
              <div key={log.id} className="rounded-xl border border-terminal-border bg-terminal-surface/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-terminal-text">
                    {log.tool_name}
                  </p>
                  <span className="text-[11px] text-terminal-text-dim">{safeFormat(log.created_at)}</span>
                </div>
                <p className="mt-2 text-xs text-terminal-text-dim">
                  {(log.provider || 'unknown provider')} {log.query ? `• ${log.query}` : ''}
                </p>
                {log.result_summary && (
                  <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-terminal-text-muted">
                    {log.result_summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}

function CommandHistory({
  commands,
  stats,
  loading,
  error,
  expandedId,
  filterAction,
  filterStatus,
  onExpandedChange,
  onFilterActionChange,
  onFilterStatusChange,
  onRefresh,
}: {
  commands: SlackCommand[]
  stats: CommandStats | null
  loading: boolean
  error: string | null
  expandedId: number | null
  filterAction: string
  filterStatus: string
  onExpandedChange: (value: number | null) => void
  onFilterActionChange: (value: string) => void
  onFilterStatusChange: (value: string) => void
  onRefresh: () => void
}) {
  return (
    <div className="space-y-6">
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-terminal-text-dim">Total</p>
            <p className="mt-1 text-2xl font-heading font-bold">{stats.total}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-gain">Executed</p>
            <p className="mt-1 text-2xl font-heading font-bold text-gain">{stats.by_status?.executed || 0}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-loss">Rejected</p>
            <p className="mt-1 text-2xl font-heading font-bold text-loss">{stats.by_status?.rejected || 0}</p>
          </Panel>
          <Panel className="p-4 text-center">
            <p className="text-xs uppercase tracking-widest text-cyan">Review</p>
            <p className="mt-1 text-2xl font-heading font-bold text-cyan">{stats.by_status?.review_only || 0}</p>
          </Panel>
        </div>
      )}

      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs uppercase tracking-wide text-terminal-text-dim">Action</label>
          <select
            value={filterAction}
            onChange={(event) => onFilterActionChange(event.target.value)}
            className="rounded border border-terminal-border bg-terminal-surface px-2 py-1 text-sm text-terminal-text focus:outline-none focus:ring-1 focus:ring-cyan/40"
          >
            <option value="">All</option>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
            <option value="REVIEW">REVIEW</option>
            <option value="CANCEL">CANCEL</option>
          </select>
          <label className="ml-4 text-xs uppercase tracking-wide text-terminal-text-dim">Status</label>
          <select
            value={filterStatus}
            onChange={(event) => onFilterStatusChange(event.target.value)}
            className="rounded border border-terminal-border bg-terminal-surface px-2 py-1 text-sm text-terminal-text focus:outline-none focus:ring-1 focus:ring-cyan/40"
          >
            <option value="">All</option>
            <option value="executed">Executed</option>
            <option value="rejected">Rejected</option>
            <option value="review_only">Review</option>
            <option value="partial">Partial</option>
            <option value="error">Error</option>
            <option value="received">Received</option>
            <option value="awaiting_confirmation">Awaiting confirmation</option>
          </select>
          <button
            onClick={onRefresh}
            className="ml-auto text-xs text-cyan transition-colors hover:text-cyan/80"
          >
            Refresh
          </button>
        </div>
      </Panel>

      <Panel className="overflow-hidden p-0">
        <div className="border-b border-terminal-border px-5 py-4">
          <SectionHeader
            eyebrow="Legacy Audit"
            title="Command History"
            subtitle="The original Slack one-shot command log is still preserved as a secondary surface."
          />
        </div>
        {loading ? (
          <div className="p-4">
            <TableSkeleton rows={6} cols={6} />
          </div>
        ) : error ? (
          <div className="p-6 text-center">
            <p className="text-sm text-loss">{error}</p>
            <button onClick={onRefresh} className="mt-2 text-xs text-cyan hover:text-cyan/80">Retry</button>
          </div>
        ) : commands.length === 0 ? (
          <div className="p-8 text-center text-sm text-terminal-text-dim">
            No legacy commands yet. Slack one-shot trades and cancels will continue to appear here.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-terminal-border text-left text-xs uppercase tracking-wider text-terminal-text-dim">
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">Time</th>
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">User</th>
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">Action</th>
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">Ticker</th>
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">Message</th>
                  <th className="sticky top-0 z-10 bg-terminal-surface px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {commands.flatMap((cmd) => {
                  const rows = [
                    (
                      <tr
                        key={cmd.id}
                        className="cursor-pointer border-b border-terminal-border/50 transition-colors hover:bg-white/[0.02]"
                        onClick={() => onExpandedChange(expandedId === cmd.id ? null : cmd.id)}
                        aria-expanded={expandedId === cmd.id}
                      >
                        <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-terminal-text-dim">
                          {safeFormat(cmd.timestamp)}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">{cmd.user_id || '—'}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-bold ${ACTION_COLOUR[cmd.action || ''] || 'text-terminal-text'}`}>
                            {cmd.action || '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs font-medium">
                          {cmd.ticker ? cleanTicker(cmd.ticker) : '—'}
                        </td>
                        <td className="max-w-[240px] truncate px-4 py-3 text-xs text-terminal-text-muted">
                          {cmd.raw_message}
                        </td>
                        <td className="px-4 py-3">{renderHistoryStatus(cmd.status)}</td>
                      </tr>
                    ),
                  ]

                  if (expandedId === cmd.id) {
                    rows.push(
                      <tr key={`${cmd.id}-detail`} className="bg-white/[0.01]">
                        <td colSpan={6} className="px-6 py-4">
                          <div className="grid grid-cols-1 gap-4 text-xs sm:grid-cols-2">
                            <div>
                              <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Cycle ID</p>
                              <p className="font-mono">{cmd.cycle_id || '—'}</p>
                            </div>
                            <div>
                              <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Order ID</p>
                              <p className="font-mono">{cmd.order_id ?? '—'}</p>
                            </div>
                            <div>
                              <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Execution Mode</p>
                              <p className="font-mono">{cmd.execution_mode || '—'}</p>
                            </div>
                            <div>
                              <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Command Kind</p>
                              <p className="font-mono">{cmd.command_kind || '—'}</p>
                            </div>
                            <div>
                              <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Target Order Class</p>
                              <p className="font-mono">{cmd.target_order_class || '—'}</p>
                            </div>
                            {cmd.target_tickers_json && (
                              <div className="sm:col-span-2">
                                <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Target Tickers</p>
                                <p className="break-words font-mono whitespace-pre-wrap">{cmd.target_tickers_json}</p>
                              </div>
                            )}
                            {cmd.rejection_reason && (
                              <div className="sm:col-span-2">
                                <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Rejection Reason</p>
                                <p className="text-loss">{cmd.rejection_reason}</p>
                              </div>
                            )}
                            {cmd.response_message && (
                              <div className="sm:col-span-2">
                                <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Response</p>
                                <p className="whitespace-pre-wrap text-terminal-text-muted">{cmd.response_message}</p>
                              </div>
                            )}
                            {cmd.result_json && (
                              <div className="sm:col-span-2">
                                <p className="mb-1 uppercase tracking-wide text-terminal-text-dim">Result JSON</p>
                                <p className="break-words whitespace-pre-wrap text-terminal-text-muted">{cmd.result_json}</p>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  }

                  return rows
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

export default function Commands() {
  const [activeTab, setActiveTab] = useState<'console' | 'history'>('console')
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [sessionDetail, setSessionDetail] = useState<ChatSessionDetail | null>(null)
  const [chatLoading, setChatLoading] = useState(true)
  const [chatError, setChatError] = useState<string | null>(null)
  const [composer, setComposer] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const [commands, setCommands] = useState<SlackCommand[]>([])
  const [stats, setStats] = useState<CommandStats | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [filterAction, setFilterAction] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  const fetchSessions = useCallback(async (nextSelectedId?: number | null) => {
    setChatLoading(true)
    setChatError(null)
    try {
      const nextSessions = await chatApi.listSessions({ limit: 50 })
      setSessions(nextSessions)
      const preferredId = nextSelectedId ?? selectedSessionId
      if (preferredId && nextSessions.some((session) => session.id === preferredId)) {
        setSelectedSessionId(preferredId)
      } else if (nextSessions.length > 0) {
        setSelectedSessionId(nextSessions[0].id)
      } else {
        setSelectedSessionId(null)
        setSessionDetail(null)
      }
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to load conversation sessions')
    } finally {
      setChatLoading(false)
    }
  }, [selectedSessionId])

  const fetchSessionDetail = useCallback(async (sessionId: number) => {
    try {
      const detail = await chatApi.getSession(sessionId)
      setSessionDetail(detail)
      return detail
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to load conversation detail')
      return null
    }
  }, [])

  const fetchCommandHistory = useCallback(async () => {
    try {
      setHistoryLoading(true)
      setHistoryError(null)
      const params: Record<string, string | number> = { limit: 100 }
      if (filterAction) params.action = filterAction
      if (filterStatus) params.status = filterStatus
      const [cmds, summary] = await Promise.all([
        commandsApi.list(params),
        commandsApi.stats(),
      ])
      setCommands(cmds)
      setStats(summary)
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Failed to load command history')
    } finally {
      setHistoryLoading(false)
    }
  }, [filterAction, filterStatus])

  useEffect(() => {
    void fetchSessions()
  }, [fetchSessions])

  useEffect(() => {
    if (selectedSessionId == null) return
    void fetchSessionDetail(selectedSessionId)
  }, [selectedSessionId, fetchSessionDetail])

  useEffect(() => {
    void fetchCommandHistory()
  }, [fetchCommandHistory])

  const handleSseEvent = useCallback((event: Event) => {
    if (!event.event_type.startsWith('chat_')) return
    const sessionId = Number(event.metadata_json?.session_id)
    if (Number.isFinite(sessionId) && sessionId > 0) {
      void fetchSessions(sessionId)
      if (selectedSessionId === sessionId) {
        void fetchSessionDetail(sessionId)
      }
      return
    }
    void fetchSessions()
  }, [fetchSessionDetail, fetchSessions, selectedSessionId])

  useSSE({ enabled: true, onEvent: handleSseEvent })

  const handleCreateSession = useCallback(async () => {
    setSubmitting(true)
    setChatError(null)
    try {
      const detail = await chatApi.createSession({ channel_type: 'dashboard' })
      setSelectedSessionId(detail.id)
      setSessionDetail(detail)
      await fetchSessions(detail.id)
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to create chat session')
    } finally {
      setSubmitting(false)
    }
  }, [fetchSessions])

  const handleSendTurn = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const message = composer.trim()
    if (!message) return

    setSubmitting(true)
    setChatError(null)
    try {
      let activeSessionId = selectedSessionId
      if (!activeSessionId) {
        const created = await chatApi.createSession({ channel_type: 'dashboard', title: message.slice(0, 120) })
        activeSessionId = created.id
        setSelectedSessionId(created.id)
      }
      const detail = await chatApi.submitTurn(activeSessionId, {
        message_text: message,
        channel_type: 'dashboard',
      })
      setSessionDetail(detail)
      setComposer('')
      await fetchSessions(detail.id)
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to send chat turn')
    } finally {
      setSubmitting(false)
    }
  }, [composer, fetchSessions, selectedSessionId])

  const handleConfirmAction = useCallback(async (actionId: number) => {
    if (!sessionDetail) return
    setSubmitting(true)
    try {
      const detail = await chatApi.confirmAction(sessionDetail.id, actionId, { channel_type: 'dashboard' })
      setSessionDetail(detail)
      await fetchSessions(detail.id)
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to confirm action')
    } finally {
      setSubmitting(false)
    }
  }, [fetchSessions, sessionDetail])

  const handleRejectAction = useCallback(async (actionId: number) => {
    if (!sessionDetail) return
    setSubmitting(true)
    try {
      const detail = await chatApi.rejectAction(sessionDetail.id, actionId, { channel_type: 'dashboard' })
      setSessionDetail(detail)
      await fetchSessions(detail.id)
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to reject action')
    } finally {
      setSubmitting(false)
    }
  }, [fetchSessions, sessionDetail])

  const handleCloseSession = useCallback(async () => {
    if (!sessionDetail) return
    setSubmitting(true)
    try {
      await chatApi.endSession(sessionDetail.id)
      await fetchSessions()
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'Failed to close session')
    } finally {
      setSubmitting(false)
    }
  }, [fetchSessions, sessionDetail])

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="Trade Console"
        title="Commands"
        description="Slack remains the primary live surface, but this dashboard now continues the same conversational trading sessions with proposal review, execution state, research trace, and legacy command history."
      />

      <Panel className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          <button
            onClick={() => setActiveTab('console')}
            className={`rounded-full px-4 py-2 text-xs uppercase tracking-wide transition-colors ${
              activeTab === 'console'
                ? 'bg-cyan text-terminal-bg'
                : 'border border-terminal-border text-terminal-text-dim hover:border-cyan/40 hover:text-terminal-text'
            }`}
          >
            Conversation Console
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`rounded-full px-4 py-2 text-xs uppercase tracking-wide transition-colors ${
              activeTab === 'history'
                ? 'bg-cyan text-terminal-bg'
                : 'border border-terminal-border text-terminal-text-dim hover:border-cyan/40 hover:text-terminal-text'
            }`}
          >
            Command History
          </button>
        </div>
        {chatError && (
          <p className="text-sm text-loss">{chatError}</p>
        )}
      </Panel>

      {activeTab === 'console' ? (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[300px_minmax(0,1fr)_360px]">
          <SessionList
            sessions={sessions}
            selectedSessionId={selectedSessionId}
            loading={chatLoading}
            onSelect={setSelectedSessionId}
            onCreate={() => void handleCreateSession()}
          />
          <ChatThread
            sessionDetail={sessionDetail}
            loading={chatLoading && !sessionDetail}
            submitting={submitting}
            composer={composer}
            onComposerChange={setComposer}
            onSubmit={(event) => void handleSendTurn(event)}
            onClose={() => void handleCloseSession()}
          />
          <ActionRail
            sessionDetail={sessionDetail}
            onConfirm={(actionId) => void handleConfirmAction(actionId)}
            onReject={(actionId) => void handleRejectAction(actionId)}
          />
        </div>
      ) : (
        <CommandHistory
          commands={commands}
          stats={stats}
          loading={historyLoading}
          error={historyError}
          expandedId={expandedId}
          filterAction={filterAction}
          filterStatus={filterStatus}
          onExpandedChange={setExpandedId}
          onFilterActionChange={setFilterAction}
          onFilterStatusChange={setFilterStatus}
          onRefresh={() => void fetchCommandHistory()}
        />
      )}
    </div>
  )
}
