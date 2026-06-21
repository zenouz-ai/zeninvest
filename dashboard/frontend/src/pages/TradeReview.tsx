import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  outcomesApi,
  type NorthStarMetrics,
  type TradeOutcomeSummary,
  type TradeTimeline,
  type TradeTimelineClassificationRules,
  type TradeTimelineLeg,
} from '../api/client'
import {
  CommitteeDetailBlock,
  CommitteeLegend,
  CommitteePathLine,
  MarketContextDetailPanel,
  ResearchTrailBlock,
} from '../components/CommitteeBlocks'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { SkeletonCard } from '../components/Skeleton'

const LABEL_COLORS: Record<string, string> = {
  big_winner: '#22c55e',
  big_loser: '#ef4444',
  stall: '#f59e0b',
  neutral: '#64748b',
}

const RESULT_COLORS: Record<string, string> = {
  win: '#22c55e',
  loss: '#ef4444',
  flat: '#64748b',
}

const BUY_LINE_COLORS = ['#22c55e', '#4ade80', '#86efac', '#bbf7d0']

const DEFAULT_CLASSIFICATION_RULES: TradeTimelineClassificationRules = {
  flat_abs_pnl_pct: 0.5,
  success_min_profit_per_day_pct: 0.25,
  stall_min_gain_per_day_pct: -0.05,
  exit_reasons: [
    { code: 'hard_stop', label: 'Stop loss exit' },
    { code: 'trailing_stop_exit', label: 'Trailing stop (profit lock)' },
    { code: 'stagnation_exit', label: 'Stagnation / stale exit' },
    { code: 'manual_or_strategy', label: 'Market / strategy exit' },
  ],
}

function ClassificationRulesPanel({
  rules,
  activeLabel,
  rationale,
}: {
  rules: TradeTimelineClassificationRules
  activeLabel?: string
  rationale?: string
}) {
  const flat = rules.flat_abs_pnl_pct
  return (
    <Panel>
      <SectionHeader
        title="Classification rules"
        subtitle="WIN/LOSS uses realized GBP wallet P&L. The 3-class label is for learning analytics and can differ from WIN/LOSS."
      />
      {rationale ? (
        <div className="mb-4 rounded-panel border border-cyan/30 bg-cyan/5 px-3 py-2 text-sm text-terminal-text">
          <p className="text-xs uppercase tracking-wide text-cyan mb-1">Why this trade</p>
          <p>{rationale}</p>
        </div>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2 text-sm">
        <div>
          <p className="text-terminal-text font-medium mb-2">Result (WIN / LOSS / FLAT)</p>
          <ul className="space-y-1 text-terminal-text-muted list-disc pl-5">
            <li>
              <span className="text-terminal-text">WIN</span> — realized GBP P&amp;L &gt; +{flat}%
            </li>
            <li>
              <span className="text-terminal-text">LOSS</span> — realized GBP P&amp;L &lt; −{flat}%
            </li>
            <li>
              <span className="text-terminal-text">FLAT</span> — within ±{flat}%
            </li>
          </ul>
        </div>
        <div>
          <p className="text-terminal-text font-medium mb-2">3-class label (learning target)</p>
          <ul className="space-y-1 text-terminal-text-muted list-disc pl-5">
            <li>
              <span
                style={{
                  color: LABEL_COLORS.big_winner,
                  fontWeight: activeLabel === 'big_winner' ? 600 : undefined,
                }}
              >
                big_winner
              </span>{' '}
              — gain/day ≥{rules.success_min_profit_per_day_pct}% (any holding length)
            </li>
            <li>
              <span
                style={{
                  color: LABEL_COLORS.stall,
                  fontWeight: activeLabel === 'stall' ? 600 : undefined,
                }}
              >
                stall
              </span>{' '}
              — gain/day from {rules.stall_min_gain_per_day_pct}% to{' '}
              {rules.success_min_profit_per_day_pct}%
            </li>
            <li>
              <span
                style={{
                  color: LABEL_COLORS.big_loser,
                  fontWeight: activeLabel === 'big_loser' ? 600 : undefined,
                }}
              >
                big_loser
              </span>{' '}
              — gain/day &lt; {rules.stall_min_gain_per_day_pct}%
            </li>
          </ul>
        </div>
        <div className="md:col-span-2">
          <p className="text-terminal-text font-medium mb-2">Exit reason mapping</p>
          <ul className="space-y-1 text-terminal-text-muted list-disc pl-5">
            <li>Stop order or stop adjustment within 1h of sell → stop exit</li>
            <li>
              If realized P&amp;L &gt; +{flat}% on a stop exit →{' '}
              <span className="text-terminal-text">Trailing stop (profit lock)</span>
            </li>
            <li>
              Otherwise stop exit → <span className="text-terminal-text">Stop loss exit</span>
            </li>
            {rules.exit_reasons.map((item) => (
              <li key={item.code}>
                <span className="font-mono text-xs text-terminal-text-dim">{item.code}</span> —{' '}
                {item.label}
              </li>
            ))}
          </ul>
          <p className="text-xs text-terminal-text-dim mt-3">
            USD quote return is informational only. Once a trade closes, realized GBP wallet P&amp;L
            drives WIN/LOSS; the 3-class label uses unified gain/day bands (no neutral on closed
            trades).
          </p>
        </div>
      </div>
    </Panel>
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toISOString().slice(0, 10)
}

function formatPnlPct(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

function toChartDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  return formatDate(iso)
}

function legQuotePrice(leg: TradeTimelineLeg): number | null {
  if (leg.price != null) return leg.price
  if (leg.decision_price != null) return leg.decision_price
  return null
}

function tradeOptionLabel(trade: TradeOutcomeSummary): string {
  const buy = formatDate(trade.buy_timestamp)
  const sell = formatDate(trade.sell_timestamp)
  const pnl = formatPnlPct(trade.pnl_pct)
  const strategy = trade.strategy ?? '—'
  return `${trade.ticker} · ${buy} → ${sell} · ${pnl} · ${strategy}`
}

type ChartRow = {
  date: string
  close: number
  inPosition: boolean
}

type BuyMarkerRow = {
  date: string
  close: number
  legIndex: number
  label: string
}

function buildChartRows(timeline: TradeTimeline): {
  rows: ChartRow[]
  buyDates: Array<{ date: string; label: string; color: string }>
  sellDate: string | null
  buyMarkers: BuyMarkerRow[]
  sellMarker: BuyMarkerRow[]
  firstBuyDate: string | null
} {
  const buys = timeline.buys.length > 0 ? timeline.buys : [timeline.buy]
  const sellDate = toChartDate(timeline.sell.timestamp)
  const buyDates = buys
    .map((leg, idx) => {
      const date = toChartDate(leg.timestamp)
      if (!date) return null
      const legNum = leg.leg_index ?? idx + 1
      return {
        date,
        label: buys.length > 1 ? `Buy ${legNum}` : 'Buy',
        color: BUY_LINE_COLORS[idx % BUY_LINE_COLORS.length],
      }
    })
    .filter((item): item is { date: string; label: string; color: string } => item != null)

  const firstBuyDate = buyDates[0]?.date ?? null
  const lastBuyDate = buyDates[buyDates.length - 1]?.date ?? firstBuyDate

  const priceByDate = new Map(timeline.prices.map((point) => [point.date, point.close]))
  const eventBars: Array<{ date: string; close: number }> = []
  for (const leg of buys) {
    const date = toChartDate(leg.timestamp)
    const quote = legQuotePrice(leg)
    if (date && quote != null && !priceByDate.has(date)) {
      eventBars.push({ date, close: quote })
      priceByDate.set(date, quote)
    }
  }
  const sellQuote = legQuotePrice(timeline.sell)
  if (sellDate && sellQuote != null && !priceByDate.has(sellDate)) {
    eventBars.push({ date: sellDate, close: sellQuote })
    priceByDate.set(sellDate, sellQuote)
  }

  const chartPrices = [...timeline.prices, ...eventBars].sort((a, b) => a.date.localeCompare(b.date))

  const rows: ChartRow[] = chartPrices.map((point) => ({
    date: point.date,
    close: point.close,
    inPosition: Boolean(
      firstBuyDate &&
        sellDate &&
        point.date >= firstBuyDate &&
        point.date <= sellDate,
    ),
  }))

  const buyMarkers: BuyMarkerRow[] = buys.flatMap((leg, idx) => {
    const date = toChartDate(leg.timestamp)
    const quote = legQuotePrice(leg)
    if (!date || quote == null) return []
    const legNum = leg.leg_index ?? idx + 1
    return [{ date, close: quote, legIndex: legNum, label: `Buy ${legNum}` }]
  })

  const sellMarker: BuyMarkerRow[] =
    sellDate && sellQuote != null
      ? [{ date: sellDate, close: sellQuote, legIndex: 0, label: 'Sell' }]
      : []

  return {
    rows,
    buyDates,
    sellDate,
    buyMarkers,
    sellMarker,
    firstBuyDate: firstBuyDate ?? lastBuyDate,
  }
}

function TimelineTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ payload?: ChartRow }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div className="rounded-panel border border-cyan/30 bg-terminal-bg px-3 py-2 text-xs shadow-lg">
      <p className="font-mono text-cyan">{label ?? row.date}</p>
      <p className="text-terminal-text">Close: {row.close.toFixed(2)}</p>
      <p className="text-terminal-text-dim">{row.inPosition ? 'In position' : 'Flat'}</p>
    </div>
  )
}

function AnnotationCard({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="rounded-panel border border-terminal-border bg-terminal-surface/40 p-4 space-y-2">
      <h3 className="text-sm font-semibold text-terminal-text">{title}</h3>
      <div className="text-sm text-terminal-text-muted leading-relaxed">{children}</div>
    </div>
  )
}

function BuyLegCard({ leg, ticker }: { leg: TradeTimelineLeg; ticker: string }) {
  const legNum = leg.leg_index ?? 1
  const quote = legQuotePrice(leg)
  const consensus =
    (leg.committee as Record<string, unknown> | null | undefined)?.consensus as string | undefined
  return (
    <AnnotationCard title={`Why we bought (entry ${legNum})`}>
      <CommitteePathLine
        moderationResult={leg.moderation_result}
        riskResult={leg.risk_result}
        consensus={consensus}
      />
      <p>
        <span className="text-terminal-text">Strategy:</span> {leg.strategy ?? '—'}
      </p>
      {leg.conviction != null ? (
        <p>
          <span className="text-terminal-text">Conviction:</span> {leg.conviction}/100
        </p>
      ) : null}
      {leg.quantity != null ? (
        <p>
          <span className="text-terminal-text">Shares:</span> {leg.quantity}
        </p>
      ) : null}
      {quote != null ? (
        <p>
          <span className="text-terminal-text">Quote fill:</span> {quote.toFixed(2)} on{' '}
          {formatDate(leg.timestamp)}
        </p>
      ) : null}
      {leg.value_gbp != null ? (
        <p>
          <span className="text-terminal-text">Wallet debit:</span> £{leg.value_gbp.toFixed(2)}
          {leg.value_gbp_per_share != null ? ` (£${leg.value_gbp_per_share.toFixed(2)}/share)` : ''}
        </p>
      ) : null}
      <p className="whitespace-pre-wrap">
        {leg.reasoning ?? 'No strategy reasoning matched for this entry.'}
      </p>
      <CommitteeDetailBlock committee={leg.committee} />
      <MarketContextDetailPanel ctx={leg.market_context} />
      <ResearchTrailBlock research={leg.research} />
      {leg.cycle_id ? (
        <Link
          to={`/dashboard?cycle=${encodeURIComponent(leg.cycle_id)}&ticker=${encodeURIComponent(ticker)}`}
          className="inline-block text-cyan hover:underline text-xs mt-1"
        >
          View buy cycle context
        </Link>
      ) : null}
    </AnnotationCard>
  )
}

function pctRate(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function NorthStarPanel({ metrics }: { metrics: NorthStarMetrics | null }) {
  if (!metrics) return null
  const targets = metrics.targets ?? {}
  const stretch = targets.big_winner_hit_rate_stretch ?? 0.5
  const interim = targets.big_winner_hit_rate_interim ?? 0.35
  const bw = metrics.big_winner_hit_rate
  const bwClass =
    bw == null
      ? 'text-terminal-text'
      : bw >= stretch
        ? 'text-cyan'
        : bw >= interim
          ? 'text-emerald'
          : 'text-amber'

  return (
    <Panel>
      <SectionHeader
        title="North-star KPIs"
        subtitle={`Rolling ${metrics.window_days}d closed trades · pace-aligned v6 labels (≥${metrics.thresholds?.success_min_profit_per_day_pct ?? 0.25}%/day winner).`}
      />
      {!metrics.sufficient_data ? (
        <p className="text-sm text-terminal-text-muted mb-3">
          {metrics.total_trades} closed trades in window — need ≥{targets.min_trades_for_display ?? 30} for stable rates.
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">big_winner rate</p>
          <p className={`text-lg font-mono ${bwClass}`}>
            {pctRate(bw)}
          </p>
          <p className="text-xs text-terminal-text-dim">Target interim {pctRate(interim)} · stretch {pctRate(stretch)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">stall rate</p>
          <p className="text-lg font-mono text-amber">{pctRate(metrics.stall_rate)}</p>
          <p className="text-xs text-terminal-text-dim">Max {pctRate(targets.stall_rate_max ?? 0.3)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">big_loser rate</p>
          <p className="text-lg font-mono text-red-400">{pctRate(metrics.big_loser_rate)}</p>
          <p className="text-xs text-terminal-text-dim">Max {pctRate(targets.big_loser_rate_max ?? 0.2)}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-terminal-text-muted">Expectancy</p>
          <p className="text-lg font-mono text-terminal-text">
            {metrics.expectancy_gbp != null ? `£${metrics.expectancy_gbp.toFixed(2)}` : '—'}
          </p>
          <p className="text-xs text-terminal-text-dim">Avg gain/day {metrics.avg_gain_per_day_pct?.toFixed(3) ?? '—'}%</p>
        </div>
      </div>
    </Panel>
  )
}

export default function TradeReview() {
  const [trades, setTrades] = useState<TradeOutcomeSummary[]>([])
  const [northStar, setNorthStar] = useState<NorthStarMetrics | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [timeline, setTimeline] = useState<TradeTimeline | null>(null)
  const [loadingTrades, setLoadingTrades] = useState(true)
  const [loadingTimeline, setLoadingTimeline] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadTrades() {
      setLoadingTrades(true)
      setError(null)
      try {
        const [list, kpi] = await Promise.all([
          outcomesApi.list({ limit: 500 }),
          outcomesApi.getNorthStar(90).catch(() => null),
        ])
        if (cancelled) return
        setTrades(list)
        setNorthStar(kpi)
        if (list.length > 0) {
          setSelectedId((prev) => prev ?? list[0].id)
        }
      } catch {
        if (!cancelled) setError('Failed to load completed trades.')
      } finally {
        if (!cancelled) setLoadingTrades(false)
      }
    }
    loadTrades()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedId == null) {
      setTimeline(null)
      return
    }
    let cancelled = false
    async function loadTimeline() {
      setLoadingTimeline(true)
      setError(null)
      const outcomeId = selectedId
      if (outcomeId == null) return
      try {
        const data = await outcomesApi.getTimeline(outcomeId)
        if (!cancelled) setTimeline(data)
      } catch {
        if (!cancelled) {
          setTimeline(null)
          setError('Failed to load price timeline for this trade.')
        }
      } finally {
        if (!cancelled) setLoadingTimeline(false)
      }
    }
    loadTimeline()
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const chart = useMemo(
    () => (timeline ? buildChartRows(timeline) : null),
    [timeline],
  )

  const buyLegs = timeline ? (timeline.buys.length > 0 ? timeline.buys : [timeline.buy]) : []

  if (loadingTrades) {
    return (
      <div className="space-y-4">
        <PageBrandHeader
          eyebrow="TRADES"
          title="Trade review"
          description="Interactive price timeline for completed trades with buy/sell annotations."
        />
        <SkeletonCard />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="TRADES"
        title="Trade review"
        description="Daily price series (USD quote) with every FIFO buy lot, GBP wallet P&L, and pipeline reasoning."
      />
      <CommitteeLegend />

      <NorthStarPanel metrics={northStar} />

      <Panel>
        <SectionHeader
          title="Completed trade"
          subtitle="Select a closed trade to inspect entry, exit, and post-exit price action."
        />
        {trades.length === 0 ? (
          <p className="text-sm text-terminal-text-muted">No completed trades recorded yet.</p>
        ) : (
          <select
            className="w-full max-w-3xl bg-terminal-surface border border-terminal-border rounded-panel px-3 py-2 text-sm font-mono"
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {trades.map((trade) => (
              <option key={trade.id} value={trade.id}>
                {tradeOptionLabel(trade)}
              </option>
            ))}
          </select>
        )}
      </Panel>

      {error ? (
        <Panel>
          <p className="text-sm text-red-400">{error}</p>
        </Panel>
      ) : null}

      {loadingTimeline ? <SkeletonCard /> : null}

      {!loadingTimeline && timeline && chart ? (
        <>
          <Panel>
            <div className="flex flex-wrap gap-3 items-center text-sm mb-2">
              <span className="font-mono text-cyan text-base">{timeline.ticker}</span>
              <span
                className="px-2 py-0.5 rounded-full text-xs font-medium uppercase"
                style={{
                  color: RESULT_COLORS[timeline.outcome.result] ?? '#64748b',
                  border: `1px solid ${RESULT_COLORS[timeline.outcome.result] ?? '#64748b'}66`,
                }}
              >
                {timeline.outcome.result}
              </span>
              <span
                className="px-2 py-0.5 rounded-full text-xs font-medium"
                style={{
                  color: LABEL_COLORS[timeline.outcome.label_3class] ?? '#64748b',
                  border: `1px solid ${LABEL_COLORS[timeline.outcome.label_3class] ?? '#64748b'}66`,
                }}
              >
                {timeline.outcome.label_3class}
              </span>
              {timeline.moderation_result ? (
                <span className="text-xs text-terminal-text-muted">Mod: {timeline.moderation_result}</span>
              ) : null}
              {timeline.risk_result ? (
                <span className="text-xs text-terminal-text-muted">Risk: {timeline.risk_result}</span>
              ) : null}
              <span className="text-terminal-text-muted">
                P&amp;L {formatPnlPct(timeline.outcome.pnl_pct)} (£{timeline.outcome.pnl_gbp.toFixed(2)})
              </span>
              {timeline.outcome.holding_days != null ? (
                <span className="text-terminal-text-muted">
                  Held {timeline.outcome.holding_days.toFixed(1)} days
                </span>
              ) : null}
              <span className="text-terminal-text-muted">{timeline.outcome.exit_label}</span>
            </div>
            <p className="text-xs text-terminal-text-dim mb-4">
              Chart: {timeline.price_series_currency} daily close · Outcome: {timeline.pnl_currency} wallet (
              cost £{timeline.outcome.cost_basis_gbp.toFixed(2)} → proceeds £
              {timeline.outcome.sell_proceeds_gbp.toFixed(2)}
              {buyLegs.length > 1 ? ` · ${buyLegs.length} buy entries` : ''})
            </p>

            <ResponsiveContainer width="100%" height={380}>
              <ComposedChart data={chart.rows} margin={{ top: 16, right: 16, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                <XAxis
                  dataKey="date"
                  stroke="#8b949e"
                  interval="preserveStartEnd"
                  minTickGap={28}
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  stroke="#8b949e"
                  domain={['auto', 'auto']}
                  tickFormatter={(v) => v.toFixed(2)}
                  width={56}
                />
                <Tooltip content={<TimelineTooltip />} />
                {chart.firstBuyDate && chart.sellDate ? (
                  <ReferenceArea
                    x1={chart.firstBuyDate}
                    x2={chart.sellDate}
                    fill="#22c55e"
                    fillOpacity={0.08}
                    strokeOpacity={0}
                  />
                ) : null}
                {chart.buyDates.map((buy) => (
                  <ReferenceLine
                    key={`${buy.date}-${buy.label}`}
                    x={buy.date}
                    stroke={buy.color}
                    strokeDasharray="4 4"
                    label={{ value: buy.label, fill: buy.color, fontSize: 11, position: 'insideTopLeft' }}
                  />
                ))}
                {chart.sellDate ? (
                  <ReferenceLine
                    x={chart.sellDate}
                    stroke="#ef4444"
                    strokeDasharray="4 4"
                    label={{ value: 'Sell', fill: '#ef4444', fontSize: 11, position: 'insideTopRight' }}
                  />
                ) : null}
                <Line
                  type="monotone"
                  dataKey="close"
                  name="Daily close"
                  stroke="#00d4ff"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                {chart.buyMarkers.map((marker) => (
                  <ReferenceDot
                    key={`buy-${marker.legIndex}-${marker.date}`}
                    x={marker.date}
                    y={marker.close}
                    r={7}
                    fill={BUY_LINE_COLORS[(marker.legIndex - 1) % BUY_LINE_COLORS.length]}
                    stroke="#0a0a0f"
                    strokeWidth={1.5}
                  />
                ))}
                {chart.sellMarker.map((marker) => (
                  <ReferenceDot
                    key={`sell-${marker.date}`}
                    x={marker.date}
                    y={marker.close}
                    r={7}
                    fill="#ef4444"
                    stroke="#0a0a0f"
                    strokeWidth={1.5}
                  />
                ))}
                <Brush dataKey="date" height={28} stroke="#00d4ff" fill="rgba(0, 212, 255, 0.12)" />
              </ComposedChart>
            </ResponsiveContainer>
            <p className="mt-2 text-xs text-terminal-text-dim">
              Window: {formatDate(timeline.window.start)} → {formatDate(timeline.window.end)}
            </p>
          </Panel>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {buyLegs.map((leg) => (
              <BuyLegCard
                key={leg.order_id ?? leg.leg_index ?? leg.timestamp}
                leg={leg}
                ticker={timeline.ticker}
              />
            ))}

            <AnnotationCard title="Why we sold">
              <p>
                <span className="text-terminal-text">Exit:</span> {timeline.outcome.exit_label}
              </p>
              {timeline.sell.order_type ? (
                <p>
                  <span className="text-terminal-text">Order type:</span> {timeline.sell.order_type}
                </p>
              ) : null}
              {timeline.sell.quantity != null ? (
                <p>
                  <span className="text-terminal-text">Shares:</span> {timeline.sell.quantity}
                </p>
              ) : null}
              {legQuotePrice(timeline.sell) != null ? (
                <p>
                  <span className="text-terminal-text">Quote fill:</span>{' '}
                  {legQuotePrice(timeline.sell)!.toFixed(2)} on {formatDate(timeline.sell.timestamp)}
                </p>
              ) : null}
              {timeline.sell.value_gbp != null ? (
                <p>
                  <span className="text-terminal-text">Wallet credit:</span> £
                  {timeline.sell.value_gbp.toFixed(2)}
                  {timeline.sell.value_gbp_per_share != null
                    ? ` (£${timeline.sell.value_gbp_per_share.toFixed(2)}/share)`
                    : ''}
                </p>
              ) : null}
              <p className="whitespace-pre-wrap">
                {timeline.sell.reasoning ?? 'No strategy reasoning matched for this exit.'}
              </p>
              {timeline.sell.cycle_id ? (
                <Link
                  to={`/dashboard?cycle=${encodeURIComponent(timeline.sell.cycle_id)}&ticker=${encodeURIComponent(timeline.ticker)}`}
                  className="inline-block text-cyan hover:underline text-xs mt-1"
                >
                  View sell cycle context
                </Link>
              ) : null}
            </AnnotationCard>

            <AnnotationCard title="Outcome (GBP wallet)">
              <p>
                <span className="text-terminal-text">Result:</span>{' '}
                <span style={{ color: RESULT_COLORS[timeline.outcome.result] }}>
                  {timeline.outcome.result.toUpperCase()}
                </span>
              </p>
              <p>
                <span className="text-terminal-text">Classification:</span>{' '}
                <span style={{ color: LABEL_COLORS[timeline.outcome.label_3class] }}>
                  {timeline.outcome.label_3class}
                </span>
              </p>
              <p className="text-xs text-terminal-text-dim">
                {timeline.outcome.classification_rationale}
              </p>
              {timeline.outcome.quote_return_pct != null ? (
                <p>
                  <span className="text-terminal-text">USD quote return:</span>{' '}
                  {formatPnlPct(timeline.outcome.quote_return_pct)}
                </p>
              ) : null}
              <p>
                <span className="text-terminal-text">Cost basis:</span> £
                {timeline.outcome.cost_basis_gbp.toFixed(2)}
              </p>
              <p>
                <span className="text-terminal-text">Sell proceeds:</span> £
                {timeline.outcome.sell_proceeds_gbp.toFixed(2)}
              </p>
              <p>
                <span className="text-terminal-text">Realized P&amp;L:</span> £
                {timeline.outcome.pnl_gbp.toFixed(2)} ({formatPnlPct(timeline.outcome.pnl_pct)})
              </p>
              <p className="text-xs text-terminal-text-dim pt-1">
                Shares and quote fill are native instrument prices. GBP wallet debits/credits come from
                Trading 212 fill history and drive win/loss.
              </p>
              <p>
                <span className="text-terminal-text">Exit reason code:</span> {timeline.outcome.exit_reason}
              </p>
              <Link to="/learning" className="inline-block text-violet hover:underline text-xs mt-1">
                Open learning insights →
              </Link>
            </AnnotationCard>
          </div>
        </>
      ) : null}

      <ClassificationRulesPanel
        rules={timeline?.classification_rules ?? DEFAULT_CLASSIFICATION_RULES}
        activeLabel={timeline?.outcome.label_3class}
        rationale={timeline?.outcome.classification_rationale}
      />
    </div>
  )
}
