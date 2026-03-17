import { useState } from 'react'
import type { ModerationEntry, StrategyFull, RiskFull, ResearchCall } from '../types'
import { cleanTicker } from '../types'

export function LLMStrategyBlock({
  strategy,
  expanded,
  onToggle,
  rawExpanded,
  onRawToggle,
}: {
  strategy: StrategyFull
  expanded: boolean
  onToggle: () => void
  rawExpanded: boolean
  onRawToggle: () => void
}) {
  const hasExtra =
    strategy.exit_conditions ||
    strategy.news_sentiment_summary ||
    strategy.market_assessment ||
    strategy.portfolio_commentary ||
    strategy.primary_strategy ||
    strategy.growth_potential ||
    strategy.risk_level
  return (
    <div className="border border-terminal-border rounded p-3 bg-terminal-surface/30">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-terminal-text-dim text-xs font-medium">Strategy (Claude)</span>
        <div className="flex gap-2">
          {(hasExtra || strategy.raw_response_json != null) && (
            <button
              type="button"
              onClick={onToggle}
              className="text-xs text-accent hover:underline"
            >
              {expanded ? 'Hide full' : 'Full output'}
            </button>
          )}
          {strategy.raw_response_json != null && (
            <button
              type="button"
              onClick={onRawToggle}
              className="text-xs text-neutral hover:underline"
            >
              {rawExpanded ? 'Hide raw JSON' : 'Raw JSON'}
            </button>
          )}
        </div>
      </div>
      <div className="text-terminal-text">
        {strategy.action}
        {strategy.conviction != null && ` @ conviction ${strategy.conviction}`}
        {strategy.primary_strategy && ` · ${strategy.primary_strategy}`}
      </div>
      {strategy.reasoning && (
        <div className="text-terminal-text-dim text-xs mt-1 whitespace-pre-wrap">
          {strategy.reasoning}
        </div>
      )}
      {expanded && (
        <div className="mt-2 space-y-2 text-terminal-text-dim text-xs border-t border-terminal-border pt-2">
          {strategy.exit_conditions && (
            <div>
              <span className="font-medium text-terminal-text">Exit conditions:</span>{' '}
              {strategy.exit_conditions}
            </div>
          )}
          {strategy.news_sentiment_summary && (
            <div>
              <span className="font-medium text-terminal-text">News sentiment:</span>{' '}
              {strategy.news_sentiment_summary}
            </div>
          )}
          {strategy.market_assessment && (
            <div>
              <span className="font-medium text-terminal-text">Market assessment:</span>{' '}
              {strategy.market_assessment}
            </div>
          )}
          {strategy.portfolio_commentary && (
            <div>
              <span className="font-medium text-terminal-text">Portfolio commentary:</span>{' '}
              {strategy.portfolio_commentary}
            </div>
          )}
          {strategy.growth_potential != null && (
            <div>Growth potential: {strategy.growth_potential}</div>
          )}
          {strategy.risk_level != null && (
            <div>Risk level: {strategy.risk_level}</div>
          )}
          {strategy.stop_loss_pct != null && (
            <div>Stop loss: {strategy.stop_loss_pct}%</div>
          )}
          {strategy.expected_holding_period && (
            <div>Holding period: {strategy.expected_holding_period}</div>
          )}
          {strategy.upside_target_pct != null && (
            <div>Upside target: {strategy.upside_target_pct}%</div>
          )}
        </div>
      )}
      {rawExpanded && strategy.raw_response_json != null && (
        <pre className="mt-2 p-2 bg-terminal-bg rounded text-xs overflow-x-auto max-h-64 overflow-y-auto border border-terminal-border">
          {JSON.stringify(strategy.raw_response_json, null, 2)}
        </pre>
      )}
    </div>
  )
}

export function LLMModerationBlock({
  entries,
  expanded,
  onToggle,
}: {
  entries: ModerationEntry[]
  expanded: boolean
  onToggle: () => void
}) {
  const consensus = entries.find((e) => e.consensus)?.consensus ?? entries[entries.length - 1]?.verdict
  return (
    <div className="border border-terminal-border rounded p-3 bg-terminal-surface/30">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-terminal-text-dim text-xs font-medium">Moderation (GPT-4o + Gemini)</span>
        <button
          type="button"
          onClick={onToggle}
          className="text-xs text-accent hover:underline"
        >
          {expanded ? 'Hide full' : 'Full output'}
        </button>
      </div>
      <div className="text-terminal-text text-xs">
        Consensus: {consensus}
        {entries.length > 0 && ` · ${entries.length} moderator(s)`}
      </div>
      {expanded &&
        entries.map((m, i) => (
          <div key={i} className="mt-2 p-2 rounded bg-terminal-bg/50 border border-terminal-border/50">
            <div className="text-terminal-text font-medium text-xs">
              {m.moderator} — {m.verdict}
              {(m.growth_score != null || m.risk_score != null || m.confidence_score != null) && (
                <span className="text-terminal-text-dim ml-1">
                  (G: {m.growth_score ?? '—'}, R: {m.risk_score ?? '—'}, C: {m.confidence_score ?? '—'})
                </span>
              )}
            </div>
            {m.reasoning && (
              <div className="text-terminal-text-dim text-xs mt-1 whitespace-pre-wrap">
                {m.reasoning}
              </div>
            )}
          </div>
        ))}
    </div>
  )
}

export function LLMRiskBlock({
  risk,
  expanded,
  onToggle,
}: {
  risk: RiskFull
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="border border-terminal-border rounded p-3 bg-terminal-surface/30">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-terminal-text-dim text-xs font-medium">Risk (rules + reasoning)</span>
        <button
          type="button"
          onClick={onToggle}
          className="text-xs text-accent hover:underline"
        >
          {expanded ? 'Hide full' : 'Full output'}
        </button>
      </div>
      <div className="text-terminal-text text-xs">
        Verdict: {risk.verdict}
        {risk.adjusted_allocation_pct != null && ` · Adjusted allocation: ${risk.adjusted_allocation_pct}%`}
        {Array.isArray(risk.triggered_rules) && risk.triggered_rules.length > 0 && (
          <span> · Triggered: {risk.triggered_rules.join(', ')}</span>
        )}
      </div>
      {expanded && (
        <div className="mt-2 space-y-2 text-terminal-text-dim text-xs border-t border-terminal-border pt-2">
          {risk.reasoning && (
            <div className="whitespace-pre-wrap">{risk.reasoning}</div>
          )}
          {risk.triggered_rules_json && (
            <div>
              <span className="font-medium text-terminal-text">Triggered rules (raw):</span>
              <pre className="mt-1 p-2 bg-terminal-bg rounded overflow-x-auto text-xs">
                {risk.triggered_rules_json}
              </pre>
            </div>
          )}
          {risk.rules_checked_json && (
            <div>
              <span className="font-medium text-terminal-text">Rules checked (raw):</span>
              <pre className="mt-1 p-2 bg-terminal-bg rounded overflow-x-auto text-xs max-h-32 overflow-y-auto">
                {risk.rules_checked_json}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const MEMBER_LABELS: Record<string, string> = {
  strategy: 'Strategy (Claude)',
  skeptic: 'Skeptic (GPT-4o)',
  risk: 'Risk (Gemini)',
}

const TOOL_ICONS: Record<string, string> = {
  web_search: '🌐',
  news_search: '📰',
  sector_search: '📊',
  sec_search: '📄',
  macro_search: '🏛️',
}

export function LLMResearchBlock({
  calls,
  expanded,
  onToggle,
}: {
  calls: ResearchCall[]
  expanded: boolean
  onToggle: () => void
}) {
  const totalCost = calls.reduce((s, c) => s + (c.cost_usd ?? 0), 0)
  const cacheHits = calls.filter((c) => c.cache_hit).length
  const freshCalls = calls.length - cacheHits
  const byMember = calls.reduce<Record<string, ResearchCall[]>>((acc, c) => {
    ;(acc[c.member] ??= []).push(c)
    return acc
  }, {})

  return (
    <div className="border border-terminal-border rounded p-3 bg-terminal-surface/30">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-terminal-text-dim text-xs font-medium">
          Agentic Research
          <span className="ml-2 px-1.5 py-0.5 rounded bg-accent/20 text-accent text-[10px]">
            {calls.length} call{calls.length !== 1 ? 's' : ''}
          </span>
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="text-xs text-accent hover:underline"
        >
          {expanded ? 'Hide details' : 'Show details'}
        </button>
      </div>

      <div className="text-terminal-text text-xs flex flex-wrap gap-3">
        <span>{freshCalls} fresh · {cacheHits} cached</span>
        {totalCost > 0 && <span>Cost: ${totalCost.toFixed(3)}</span>}
        <span>
          Tools:{' '}
          {[...new Set(calls.map((c) => c.tool_name))].map((t) => (
            <span key={t} className="inline-block mr-1.5">
              {TOOL_ICONS[t] ?? '🔧'} {t}
            </span>
          ))}
        </span>
      </div>

      {expanded && (
        <div className="mt-2 space-y-3 border-t border-terminal-border pt-2">
          {Object.entries(byMember).map(([member, memberCalls]) => (
            <div key={member}>
              <div className="text-terminal-text font-medium text-xs mb-1">
                {MEMBER_LABELS[member] ?? member}
                <span className="text-terminal-text-dim ml-1">
                  ({memberCalls.length} call{memberCalls.length !== 1 ? 's' : ''})
                </span>
              </div>
              <div className="space-y-1.5">
                {memberCalls.map((call, idx) => (
                  <ResearchCallRow key={idx} call={call} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ResearchCallRow({ call }: { call: ResearchCall }) {
  const [showResult, setShowResult] = useState(false)

  return (
    <div className="p-2 rounded bg-terminal-bg/50 border border-terminal-border/50 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span>{TOOL_ICONS[call.tool_name] ?? '🔧'}</span>
            <span className="font-medium text-terminal-text">{call.tool_name}</span>
            {call.cache_hit && (
              <span className="px-1 py-0.5 rounded bg-neutral/20 text-neutral text-[10px]">
                cached
              </span>
            )}
            {call.provider && (
              <span className="text-terminal-text-dim">{call.provider}</span>
            )}
            {call.latency_ms != null && (
              <span className="text-terminal-text-dim">{call.latency_ms}ms</span>
            )}
            {call.cost_usd != null && call.cost_usd > 0 && (
              <span className="text-terminal-text-dim">${call.cost_usd.toFixed(3)}</span>
            )}
          </div>
          {call.query && (
            <div className="text-terminal-text-dim mt-0.5 truncate" title={call.query}>
              "{call.query}"
            </div>
          )}
        </div>
        {call.results_summary && (
          <button
            type="button"
            onClick={() => setShowResult((v) => !v)}
            className="text-[10px] text-accent hover:underline whitespace-nowrap"
          >
            {showResult ? 'hide' : `${call.num_results ?? '?'} results`}
          </button>
        )}
      </div>
      {showResult && call.results_summary && (
        <pre className="mt-1.5 p-1.5 bg-terminal-bg rounded text-[10px] overflow-x-auto max-h-32 overflow-y-auto border border-terminal-border whitespace-pre-wrap">
          {call.results_summary}
        </pre>
      )}
    </div>
  )
}


export type LastDecision = {
  cycle_id?: string
  strategy?: StrategyFull
  moderation?: ModerationEntry[] | null
  risk?: RiskFull
  research?: ResearchCall[] | null
  execution_summary?: {
    last_buy?: {
      timestamp: string
      status: string
      quantity: number
    }
    last_sell?: {
      timestamp: string
      status: string
      quantity: number
    }
  }
} | null

export function LLMOutputPanel({
  ticker,
  lastDecision,
  label,
}: {
  ticker: string
  lastDecision: LastDecision
  label?: string | null
}) {
  const [showStrategyFull, setShowStrategyFull] = useState(false)
  const [showModerationFull, setShowModerationFull] = useState(false)
  const [showRiskFull, setShowRiskFull] = useState(false)
  const [showRawJson, setShowRawJson] = useState(false)
  const [showResearchFull, setShowResearchFull] = useState(false)

  if (!lastDecision) {
    return <div className="text-terminal-text-dim text-sm">No decision data for this ticker.</div>
  }

  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold text-accent">Committee reasoning — {cleanTicker(ticker)}</span>
        {label != null && label !== '' && (
          <span className="text-xs px-2 py-0.5 rounded bg-terminal-surface">{label}</span>
        )}
        {lastDecision.cycle_id && (
          <span className="text-terminal-text-dim text-xs">{lastDecision.cycle_id}</span>
        )}
      </div>

      {lastDecision.execution_summary && (
        <div className="text-xs text-terminal-text-dim">
          {lastDecision.execution_summary.last_buy ? (
            <span>
              Last BUY: {lastDecision.execution_summary.last_buy.quantity.toFixed(2)}&nbsp;sh ·{' '}
              {lastDecision.execution_summary.last_buy.status} ·{' '}
              {new Date(lastDecision.execution_summary.last_buy.timestamp).toUTCString()}
            </span>
          ) : (
            <span>No recorded BUY orders for this ticker.</span>
          )}
          {lastDecision.execution_summary.last_sell && (
            <span>
              {' '}
              · Last SELL: {lastDecision.execution_summary.last_sell.quantity.toFixed(2)}&nbsp;sh ·{' '}
              {lastDecision.execution_summary.last_sell.status} ·{' '}
              {new Date(lastDecision.execution_summary.last_sell.timestamp).toUTCString()}
            </span>
          )}
        </div>
      )}

      {lastDecision.strategy && (
        <LLMStrategyBlock
          strategy={lastDecision.strategy}
          expanded={showStrategyFull}
          onToggle={() => setShowStrategyFull((v) => !v)}
          rawExpanded={showRawJson}
          onRawToggle={() => setShowRawJson((v) => !v)}
        />
      )}

      {lastDecision.moderation && lastDecision.moderation.length > 0 && (
        <LLMModerationBlock
          entries={lastDecision.moderation}
          expanded={showModerationFull}
          onToggle={() => setShowModerationFull((v) => !v)}
        />
      )}

      {lastDecision.risk && (
        <LLMRiskBlock
          risk={lastDecision.risk}
          expanded={showRiskFull}
          onToggle={() => setShowRiskFull((v) => !v)}
        />
      )}

      {lastDecision.research && lastDecision.research.length > 0 && (
        <LLMResearchBlock
          calls={lastDecision.research}
          expanded={showResearchFull}
          onToggle={() => setShowResearchFull((v) => !v)}
        />
      )}
    </div>
  )
}
