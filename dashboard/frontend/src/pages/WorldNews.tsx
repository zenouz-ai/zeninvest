import { useEffect, useState, useCallback, useMemo } from 'react'
import { macroApi, publicApi } from '../api/client'
import type { MacroState, MacroHeadline } from '../types'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { StatusPill } from '../components/StatusPill'
import { FreshnessIndicator } from '../components/FreshnessIndicator'
import { SkeletonCard } from '../components/Skeleton'
import { safeFormat } from '../utils/date'

type PillVariant = 'live' | 'active' | 'draft' | 'alert' | 'warning' | 'dim'

const REGIME_VARIANT: Record<string, PillVariant> = {
  RISK_ON: 'active',
  RISK_OFF: 'alert',
  NEUTRAL: 'dim',
}

const REGIME_LABEL: Record<string, string> = {
  RISK_ON: 'Risk On',
  RISK_OFF: 'Risk Off',
  NEUTRAL: 'Neutral',
}

const CATEGORY_VARIANT: Record<string, PillVariant> = {
  fed: 'draft',
  rates: 'draft',
  trade: 'warning',
  earnings: 'active',
  inflation: 'alert',
  jobs: 'live',
  gdp: 'live',
  market: 'dim',
  general: 'dim',
}

const CATEGORY_LABELS: Record<string, string> = {
  fed: 'Fed',
  rates: 'Rates',
  trade: 'Trade',
  earnings: 'Earnings',
  inflation: 'Inflation',
  jobs: 'Jobs',
  gdp: 'GDP',
  market: 'Market',
  general: 'General',
}

const ALL_CATEGORIES = ['all', 'fed', 'rates', 'trade', 'earnings', 'inflation', 'jobs', 'gdp', 'market', 'general']

function groupHeadlinesByDate(headlines: MacroHeadline[]): Record<string, MacroHeadline[]> {
  const groups: Record<string, MacroHeadline[]> = {}
  for (const h of headlines) {
    const date = h.published_at.slice(0, 10) // YYYY-MM-DD
    if (!groups[date]) groups[date] = []
    groups[date].push(h)
  }
  return groups
}

export default function WorldNews({ publicView = false }: { publicView?: boolean }) {
  const [state, setState] = useState<MacroState | null>(null)
  const [stateHistory, setStateHistory] = useState<MacroState[]>([])
  const [headlines, setHeadlines] = useState<MacroHeadline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState('all')
  const [days, setDays] = useState(7)
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set())

  const fetchData = useCallback(async () => {
    setError(null)
    try {
      const [stateData, historyData, headlineData] = await Promise.all([
        (publicView ? publicApi.getMacroState() : macroApi.state()).catch(() => null),
        (publicView ? publicApi.getMacroStateHistory(days) : macroApi.stateHistory(days)).catch(() => []),
        (publicView ? publicApi.getMacroHeadlines(days, selectedCategory) : macroApi.headlines(days, selectedCategory)).catch(() => []),
      ])
      setState(stateData)
      setStateHistory(historyData)
      setHeadlines(headlineData)
      // Auto-expand the first date group
      if (headlineData.length > 0) {
        const firstDate = headlineData[0]?.published_at?.slice(0, 10)
        if (firstDate) setExpandedDates(new Set([firstDate]))
      }
    } catch (e) {
      console.error('Failed to fetch macro data:', e)
      setError(e instanceof Error ? e.message : 'Failed to load macro data')
    } finally {
      setLoading(false)
    }
  }, [days, publicView, selectedCategory])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const grouped = useMemo(() => groupHeadlinesByDate(headlines), [headlines])
  const dateKeys = useMemo(() => Object.keys(grouped).sort().reverse(), [grouped])

  const toggleDate = (date: string) => {
    setExpandedDates((prev) => {
      const next = new Set(prev)
      if (next.has(date)) next.delete(date)
      else next.add(date)
      return next
    })
  }

  if (loading) return <SkeletonCard lines={8} />

  if (error) {
    return (
      <div className="space-y-6">
        <PageBrandHeader title="World News" description="Macro-economic intelligence and headlines" eyebrow="MACRO" />
        <Panel><p className="text-loss">{error}</p></Panel>
      </div>
    )
  }

  const actionPlan = state?.action_plan
  const biasLabel = actionPlan?.portfolio_bias
    ? actionPlan.portfolio_bias.charAt(0).toUpperCase() + actionPlan.portfolio_bias.slice(1)
    : null

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="World News"
        description={publicView
          ? 'Public read-only macro headlines, regime classification, and portfolio implications.'
          : 'Macro-economic headlines, regime classification, and portfolio implications'}
        eyebrow="MACRO INTELLIGENCE"
      />

      {publicView && (
        <Panel>
          <p className="text-sm text-terminal-text-dim">
            This page is public in read-only mode. It exposes the macro archive and regime context without any operator controls.
          </p>
        </Panel>
      )}

      {/* --- Current Macro Regime --- */}
      <Panel hero>
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <SectionHeader eyebrow="CURRENT REGIME" title={state ? REGIME_LABEL[state.regime] || state.regime : 'No Data'} />
              {state && (
                <StatusPill label={REGIME_LABEL[state.regime] || state.regime} variant={REGIME_VARIANT[state.regime] || 'dim'} dot />
              )}
            </div>

            {state && (
              <>
                {/* Confidence */}
                <div className="flex items-center gap-3">
                  <span className="text-xs uppercase tracking-wider text-terminal-text-dim">Confidence</span>
                  <div className="flex-1 max-w-xs h-2 rounded-full bg-terminal-bg overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.round(state.confidence_score * 100)}%`,
                        background: 'linear-gradient(90deg, var(--color-violet), var(--color-cyan), var(--color-emerald))',
                      }}
                    />
                  </div>
                  <span className="text-sm font-mono text-terminal-text">{Math.round(state.confidence_score * 100)}%</span>
                </div>

                {/* Portfolio bias */}
                {biasLabel && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs uppercase tracking-wider text-terminal-text-dim">Portfolio Bias</span>
                    <StatusPill
                      label={biasLabel}
                      variant={biasLabel === 'Defensive' ? 'alert' : biasLabel === 'Constructive' ? 'active' : 'dim'}
                    />
                  </div>
                )}

                {/* Top signals */}
                {state.top_signals.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-xs uppercase tracking-wider text-terminal-text-dim">Top Signals</span>
                    <ul className="space-y-1 ml-1">
                      {state.top_signals.map((sig, i) => (
                        <li key={i} className="text-sm text-terminal-text flex items-start gap-2">
                          <span className="text-cyan mt-0.5">&#9656;</span>
                          <span>{sig.signal_text}</span>
                          <span className="text-terminal-text-dim text-xs">({sig.source})</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}

            {!state && (
              <p className="text-sm text-terminal-text-dim">
                No macro state data yet. Enable <code className="text-cyan">macro.proactive_scan_enabled</code> in settings to start collecting regime snapshots.
              </p>
            )}
          </div>

          {state && (
            <div className="text-right">
              <FreshnessIndicator lastUpdatedAt={state.timestamp ? new Date(state.timestamp) : null} isStale={state.timestamp ? (Date.now() - new Date(state.timestamp).getTime()) > 48 * 60 * 60 * 1000 : false} />
            </div>
          )}
        </div>
      </Panel>

      {/* --- Regime Timeline --- */}
      {stateHistory.length > 1 && (
        <Panel>
          <SectionHeader eyebrow="TIMELINE" title="Regime History" subtitle={`Past ${days} days`} />
          <div className="flex items-center gap-1 mt-4 overflow-x-auto pb-2">
            {stateHistory.slice().reverse().map((s, i) => {
              const color = s.regime === 'RISK_ON'
                ? 'var(--color-emerald)'
                : s.regime === 'RISK_OFF'
                  ? 'var(--color-loss)'
                  : 'var(--color-terminal-text-dim)'
              const dateStr = s.timestamp ? new Date(s.timestamp).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : ''
              return (
                <div key={i} className="flex flex-col items-center gap-1 min-w-[40px]" title={`${dateStr}: ${s.regime}`}>
                  <div
                    className="w-6 h-6 rounded-full border"
                    style={{ backgroundColor: color, borderColor: color, opacity: 0.85 }}
                  />
                  <span className="text-[10px] text-terminal-text-dim font-mono">{dateStr}</span>
                </div>
              )
            })}
          </div>
        </Panel>
      )}

      {/* --- Headlines Feed --- */}
      <Panel>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <SectionHeader eyebrow="HEADLINES" title="Economic News" subtitle={`${headlines.length} headlines in the past ${days} days`} />
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs text-terminal-text"
            >
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
            </select>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs text-terminal-text"
            >
              {ALL_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {cat === 'all' ? 'All Categories' : CATEGORY_LABELS[cat] || cat}
                </option>
              ))}
            </select>
          </div>
        </div>

        {headlines.length === 0 ? (
          <p className="text-sm text-terminal-text-dim py-4">
            No headlines archived yet. Headlines are collected automatically each analysis cycle when <code className="text-cyan">macro.persist_headlines</code> is enabled.
          </p>
        ) : (
          <div className="space-y-2">
            {dateKeys.map((date) => {
              const items = grouped[date]
              const isExpanded = expandedDates.has(date)
              const displayDate = new Date(date + 'T00:00:00Z').toLocaleDateString('en-GB', {
                weekday: 'short',
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })
              return (
                <div key={date} className="border border-terminal-border rounded-lg overflow-hidden">
                  <button
                    type="button"
                    onClick={() => toggleDate(date)}
                    aria-expanded={isExpanded}
                    className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-white/5 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-terminal-text">{displayDate}</span>
                      <span className="text-xs text-terminal-text-dim font-mono">{items.length} headline{items.length !== 1 ? 's' : ''}</span>
                    </div>
                    <span className="text-terminal-text-dim text-xs">{isExpanded ? '▲' : '▼'}</span>
                  </button>
                  {isExpanded && (
                    <div className="border-t border-terminal-border divide-y divide-terminal-border">
                      {items.map((h) => (
                        <div key={h.id} className="px-4 py-2.5 flex items-start gap-3">
                          <StatusPill
                            label={CATEGORY_LABELS[h.category || 'general'] || h.category || 'General'}
                            variant={CATEGORY_VARIANT[h.category || 'general'] || 'dim'}
                          />
                          <div className="flex-1 min-w-0">
                            {h.url ? (
                              <a
                                href={h.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-sm text-terminal-text hover:text-cyan transition-colors"
                              >
                                {h.headline}
                              </a>
                            ) : (
                              <span className="text-sm text-terminal-text">{h.headline}</span>
                            )}
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className="text-xs text-terminal-text-dim">{h.source}</span>
                              <span className="text-xs text-terminal-text-dim">{safeFormat(h.published_at, 'HH:mm')}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Panel>

      {/* --- Action Plan: What This Means --- */}
      {actionPlan && (actionPlan.sector_implications?.length || actionPlan.risks?.length || actionPlan.opportunities?.length) && (
        <Panel>
          <SectionHeader eyebrow="PORTFOLIO IMPLICATIONS" title="What This Means" subtitle="Deterministic action plan derived from macro regime" />

          {/* Sector implications */}
          {actionPlan.sector_implications && actionPlan.sector_implications.length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs uppercase tracking-wider text-terminal-text-dim mb-2">Sector Implications</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-terminal-text-dim uppercase tracking-wider">
                      <th className="pb-2 pr-4">Sector</th>
                      <th className="pb-2 pr-4">Bias</th>
                      <th className="pb-2 pr-4">Confidence</th>
                      <th className="pb-2">Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {actionPlan.sector_implications.map((si, i) => (
                      <tr key={i} className="border-t border-terminal-border">
                        <td className="py-2 pr-4 text-terminal-text whitespace-nowrap">{si.sector}</td>
                        <td className="py-2 pr-4">
                          <StatusPill
                            label={si.bias}
                            variant={si.bias === 'tailwind' ? 'active' : si.bias === 'headwind' ? 'alert' : 'dim'}
                          />
                        </td>
                        <td className="py-2 pr-4 font-mono text-terminal-text">{Math.round(si.confidence * 100)}%</td>
                        <td className="py-2 text-terminal-text-dim">{si.rationale}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Risks and opportunities side by side */}
          <div className="grid md:grid-cols-2 gap-4 mt-4">
            {actionPlan.risks && actionPlan.risks.length > 0 && (
              <div>
                <h3 className="text-xs uppercase tracking-wider text-loss mb-2">Risks</h3>
                <ul className="space-y-1">
                  {actionPlan.risks.map((r, i) => (
                    <li key={i} className="text-sm text-terminal-text flex items-start gap-2">
                      <span className="text-loss mt-0.5">&#9679;</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {actionPlan.opportunities && actionPlan.opportunities.length > 0 && (
              <div>
                <h3 className="text-xs uppercase tracking-wider text-emerald mb-2">Opportunities</h3>
                <ul className="space-y-1">
                  {actionPlan.opportunities.map((o, i) => (
                    <li key={i} className="text-sm text-terminal-text flex items-start gap-2">
                      <span className="text-emerald mt-0.5">&#9679;</span>
                      <span>{o}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Summary */}
          {actionPlan.summary && (
            <p className="text-sm text-terminal-text-dim mt-4 italic">{actionPlan.summary}</p>
          )}
        </Panel>
      )}

      {/* --- Sector Snapshot --- */}
      {state?.sector_summary && (
        <Panel>
          <SectionHeader eyebrow="SECTORS" title="Sector Performance Snapshot" />
          <pre className="mt-3 text-sm text-terminal-text font-mono whitespace-pre-wrap leading-relaxed">
            {state.sector_summary}
          </pre>
        </Panel>
      )}
    </div>
  )
}
