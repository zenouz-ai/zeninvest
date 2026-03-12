import { useState } from 'react'
import type { ModerationEntry, StrategyFull, RiskFull } from '../types'
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

export type LastDecision = {
  cycle_id?: string
  strategy?: StrategyFull
  moderation?: ModerationEntry[] | null
  risk?: RiskFull
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
    </div>
  )
}
