import { useState } from 'react'

const MODERATOR_LABELS: Record<string, string> = {
  strategy: 'Strategy (proposer)',
  'gpt-4o': 'Skeptic (GPT-4o)',
  'gemini-2.5-flash': 'Risk assessor (Gemini)',
  'gemini-2.0-flash': 'Risk assessor (Gemini)',
}

const TOOL_ICONS: Record<string, string> = {
  web_search: '🌐',
  news_search: '📰',
  sector_search: '📊',
  sec_search: '📄',
  macro_search: '🏛️',
}

const MEMBER_LABELS: Record<string, string> = {
  strategy: 'Strategy (Claude)',
  skeptic: 'Skeptic (GPT-4o)',
  risk: 'Risk (Gemini)',
}

function consensusClass(consensus: string | null | undefined): string {
  const c = (consensus || '').toUpperCase()
  if (c === 'APPROVED') return 'text-profit'
  if (c === 'BLOCKED') return 'text-loss'
  if (c === 'CAUTION') return 'text-amber'
  return 'text-terminal-text-muted'
}

function pathClass(value: string | null | undefined): string {
  const v = (value || '').toUpperCase()
  if (v === 'APPROVED' || v === 'APPROVE') return 'text-profit'
  if (v === 'BLOCKED' || v === 'REJECT') return 'text-loss'
  if (v === 'CAUTION' || v === 'RESIZE' || v === 'MODIFY') return 'text-amber'
  return 'text-terminal-text'
}

export function CommitteeLegend() {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-panel border border-terminal-border/60 bg-terminal-surface/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-3 py-2 font-medium text-terminal-text hover:bg-white/5"
      >
        How to read committee verdicts {open ? '▾' : '▸'}
      </button>
      {open ? (
        <div className="px-3 pb-3 space-y-2 text-terminal-text-muted border-t border-terminal-border/40 pt-2">
          <p>
            <span className="text-terminal-text">strategy: AGREE</span> — strategy stands by its own BUY proposal.
          </p>
          <p>
            <span className="text-terminal-text">gpt-4o / gemini: AGREE · MODIFY · DISAGREE</span> — moderator verdict.
            MODIFY means proceed with reservations (often smaller size), not a hard block.
          </p>
          <p>
            <span className="text-terminal-text">conf</span> — confidence in the moderator&apos;s assessment (1–10).{' '}
            <span className="text-terminal-text">G</span> = growth potential, <span className="text-terminal-text">R</span>{' '}
            = risk level (Gemini, 1–10).
          </p>
          <p>
            <span className="text-terminal-text">Risk: APPROVE · RESIZE · REJECT</span> — deterministic portfolio rules
            (not Gemini). RESIZE = allowed at a smaller allocation.
          </p>
          <p>
            <span className="text-terminal-text">Path: mod … · risk …</span> — moderation consensus then risk verdict
            stored on the order.
          </p>
        </div>
      ) : null}
    </div>
  )
}

export function CommitteePathLine({
  moderationResult,
  riskResult,
  consensus,
}: {
  moderationResult?: string | null
  riskResult?: string | null
  consensus?: string | null
}) {
  const mod = consensus || moderationResult
  if (!mod && !riskResult) return null
  return (
    <p className="text-xs font-medium">
      <span className="text-terminal-text">Path:</span>{' '}
      <span className={pathClass(mod)}>mod {mod ?? '—'}</span>
      <span className="text-terminal-text-muted"> · </span>
      <span className={pathClass(riskResult)}>risk {riskResult ?? '—'}</span>
    </p>
  )
}

function ModeratorRow({ row }: { row: Record<string, unknown> }) {
  const [showReasoning, setShowReasoning] = useState(false)
  const mods = row.modifications as Record<string, unknown> | null | undefined
  const moderator = String(row.moderator ?? '—')
  return (
    <div className="border border-terminal-border/40 rounded p-2 bg-terminal-bg/40">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-terminal-text">{MODERATOR_LABELS[moderator] ?? moderator}</span>
        <span className={pathClass(String(row.verdict))}>{String(row.verdict ?? '—')}</span>
        {row.confidence_score != null ? (
          <span className="text-terminal-text-dim">conf {String(row.confidence_score)}</span>
        ) : null}
        {row.growth_score != null ? (
          <span className="text-terminal-text-dim">G{String(row.growth_score)}</span>
        ) : null}
        {row.risk_score != null ? <span className="text-terminal-text-dim">R{String(row.risk_score)}</span> : null}
        {row.reasoning ? (
          <button
            type="button"
            onClick={() => setShowReasoning((v) => !v)}
            className="text-cyan hover:underline ml-auto"
          >
            {showReasoning ? 'Hide' : 'Reasoning'}
          </button>
        ) : null}
      </div>
      {mods ? (
        <p className="text-terminal-text-dim mt-1">
          Modifications:{' '}
          {mods.target_allocation_pct != null ? `size ${String(mods.target_allocation_pct)}%` : null}
          {mods.stop_loss_pct != null ? ` · stop ${String(mods.stop_loss_pct)}%` : null}
        </p>
      ) : null}
      {showReasoning && row.reasoning ? (
        <p className="text-terminal-text-dim mt-1 whitespace-pre-wrap">{String(row.reasoning)}</p>
      ) : null}
    </div>
  )
}

export function CommitteeDetailBlock({
  committee,
}: {
  committee: Record<string, unknown> | null | undefined
}) {
  if (!committee) return null
  const moderation = (committee.moderation as Array<Record<string, unknown>>) ?? []
  const consensus = (committee.consensus as string | null | undefined) ?? moderation[0]?.consensus as string | undefined
  const risk = committee.risk as Record<string, unknown> | null | undefined

  return (
    <div className="mt-3 pt-3 border-t border-terminal-border/60 space-y-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold text-terminal-text">Committee</p>
        {consensus ? (
          <span className={`px-2 py-0.5 rounded-full border border-terminal-border ${consensusClass(consensus)}`}>
            consensus {consensus}
          </span>
        ) : null}
      </div>
      <div className="space-y-1.5">
        {moderation.map((m) => (
          <ModeratorRow key={String(m.moderator)} row={m} />
        ))}
      </div>
      {risk ? <RiskDetailBlock risk={risk} /> : null}
    </div>
  )
}

export function RiskDetailBlock({ risk }: { risk: Record<string, unknown> }) {
  const [showReasoning, setShowReasoning] = useState(false)
  const rules = risk.triggered_rules as string[] | null | undefined
  return (
    <div className="border border-terminal-border/40 rounded p-2 bg-terminal-bg/40">
      <p>
        <span className="font-medium text-terminal-text">Deterministic risk:</span>{' '}
        <span className={pathClass(String(risk.verdict))}>{String(risk.verdict ?? '—')}</span>
      </p>
      {risk.proposed_allocation_pct != null ? (
        <p className="text-terminal-text-dim">Proposed: {String(risk.proposed_allocation_pct)}%</p>
      ) : null}
      {risk.adjusted_allocation_pct != null ? (
        <p className="text-terminal-text-dim">Adjusted: {String(risk.adjusted_allocation_pct)}%</p>
      ) : null}
      {rules && rules.length > 0 ? (
        <p className="text-terminal-text-dim">Triggered: {rules.join(', ')}</p>
      ) : null}
      {risk.reasoning ? (
        <>
          <button
            type="button"
            onClick={() => setShowReasoning((v) => !v)}
            className="text-cyan hover:underline mt-1"
          >
            {showReasoning ? 'Hide risk reasoning' : 'Risk reasoning'}
          </button>
          {showReasoning ? (
            <p className="text-terminal-text-dim mt-1 whitespace-pre-wrap">{String(risk.reasoning)}</p>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

export function MarketContextDetailPanel({
  ctx,
}: {
  ctx: Record<string, unknown> | null | undefined
}) {
  if (!ctx) return null
  const headlines = (ctx.macro_headlines as Array<Record<string, unknown>>) ?? []
  const shadow = (ctx.shadow_challengers as Array<Record<string, unknown>>) ?? []
  return (
    <div className="mt-3 pt-3 border-t border-terminal-border/60 space-y-1 text-xs">
      <p className="font-semibold text-terminal-text">Market context</p>
      <p>
        Macro: {String(ctx.macro_regime ?? '—')} ({String(ctx.macro_confidence ?? '—')})
      </p>
      <p>
        Guidance: {String(ctx.guidance_sector_label ?? '—')} · score {String(ctx.guidance_sector_score ?? '—')}
        {ctx.guidance_mode ? ` · mode ${String(ctx.guidance_mode)}` : ''}
      </p>
      {ctx.guidance_candidate_delta != null ? (
        <p>Universe delta after guidance: {String(ctx.guidance_candidate_delta)} candidates</p>
      ) : null}
      {ctx.news_sentiment_score != null ? (
        <p>News sentiment: {String(ctx.news_sentiment_score)}</p>
      ) : null}
      {headlines.length > 0 ? (
        <ul className="list-disc pl-4 text-terminal-text-dim space-y-0.5">
          {headlines.map((h, i) => (
            <li key={i}>
              {String(h.headline ?? '')}
              {h.source || h.category ? (
                <span className="text-terminal-text-muted">
                  {' '}
                  ({[h.category, h.source].filter(Boolean).map(String).join(' · ')})
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {shadow.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {shadow.map((s, i) => (
            <span
              key={i}
              className="px-1.5 py-0.5 rounded border border-violet/30 text-violet text-[10px]"
              title="Shadow ML — no execution influence"
            >
              {String(s.policy_id)}: {String(s.recommended_action)} (champion {String(s.champion_action)})
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export interface TradeResearchCall {
  member: string
  tool_name: string
  query?: string | null
  num_results?: number | null
  provider?: string | null
  cache_hit?: boolean
  latency_ms?: number | null
  cost_usd?: number | null
  results_preview?: string | null
  created_at?: string | null
}

export function ResearchTrailBlock({
  research,
}: {
  research: { summary?: Record<string, unknown>; calls?: TradeResearchCall[] } | null | undefined
}) {
  const [expanded, setExpanded] = useState(false)
  const calls = research?.calls ?? []
  if (!calls.length) return null

  const summary = research?.summary ?? {}
  const byMember = calls.reduce<Record<string, TradeResearchCall[]>>((acc, c) => {
    ;(acc[c.member] ??= []).push(c)
    return acc
  }, {})
  const totalCost = calls.reduce((s, c) => s + (c.cost_usd ?? 0), 0)
  const cacheHits = calls.filter((c) => c.cache_hit).length

  return (
    <div className="mt-3 pt-3 border-t border-terminal-border/60 text-xs">
      <div className="flex items-center justify-between gap-2 mb-1">
        <p className="font-semibold text-terminal-text">
          Agentic research
          <span className="ml-2 text-terminal-text-dim font-normal">
            {String(summary.total_calls ?? calls.length)} call{(summary.total_calls ?? calls.length) !== 1 ? 's' : ''}
          </span>
        </p>
        <button type="button" onClick={() => setExpanded((v) => !v)} className="text-cyan hover:underline">
          {expanded ? 'Hide' : 'Show'} queries
        </button>
      </div>
      <p className="text-terminal-text-dim">
        {calls.length - cacheHits} fresh · {cacheHits} cached
        {totalCost > 0 ? ` · $${totalCost.toFixed(3)}` : ''}
      </p>
      {expanded ? (
        <div className="mt-2 space-y-2">
          {Object.entries(byMember).map(([member, memberCalls]) => (
            <div key={member}>
              <p className="font-medium text-terminal-text mb-1">
                {MEMBER_LABELS[member] ?? member} ({memberCalls.length})
              </p>
              {memberCalls.map((call, idx) => (
                <ResearchCallDetail key={idx} call={call} />
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function ResearchCallDetail({ call }: { call: TradeResearchCall }) {
  const [showResult, setShowResult] = useState(false)
  return (
    <div className="p-2 mb-1 rounded border border-terminal-border/40 bg-terminal-bg/40">
      <div className="flex flex-wrap gap-1.5 items-center">
        <span>{TOOL_ICONS[call.tool_name] ?? '🔧'}</span>
        <span className="font-medium">{call.tool_name}</span>
        {call.cache_hit ? <span className="text-neutral text-[10px]">cached</span> : null}
        {call.provider ? <span className="text-terminal-text-dim">{call.provider}</span> : null}
        {call.latency_ms != null ? <span className="text-terminal-text-dim">{call.latency_ms}ms</span> : null}
      </div>
      {call.query ? <p className="text-terminal-text-dim mt-0.5">&quot;{call.query}&quot;</p> : null}
      {call.results_preview ? (
        <>
          <button type="button" onClick={() => setShowResult((v) => !v)} className="text-cyan hover:underline mt-1">
            {showResult ? 'Hide results' : 'Results preview'}
          </button>
          {showResult ? (
            <pre className="mt-1 text-[10px] text-terminal-text-dim whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
              {call.results_preview}
            </pre>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
