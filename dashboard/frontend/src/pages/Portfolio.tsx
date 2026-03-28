import { useEffect, useState, useMemo, useCallback } from 'react'
import { portfolioApi, publicApi, systemApi } from '../api/client'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { PnlCurrency, PnlValue } from '../components/PnlDisplay'
import { Sparkline } from '../components/Sparkline'
import { TableSkeleton } from '../components/Skeleton'
import { StatusPill, type PillVariant } from '../components/StatusPill'
import type { PortfolioSnapshot, Position } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Brush,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

type PositionSortKey = 'ticker' | 'sector' | 'quantity' | 'value_gbp' | 'pnl_gbp' | 'pnl_pct'
type PortfolioHistoryPoint = { timestamp: string; date: string; value: number }

const PORTFOLIO_HISTORY_FETCH_LIMIT = 1000
const PORTFOLIO_HISTORY_BASELINE_VALUE_GBP = 10000

function comparePositions(a: Position, b: Position, key: PositionSortKey, dir: 'asc' | 'desc'): number {
  const mul = dir === 'asc' ? 1 : -1
  if (key === 'ticker' || key === 'sector') {
    const sa = (a[key] ?? '').toString().toLowerCase()
    const sb = (b[key] ?? '').toString().toLowerCase()
    const c = sa.localeCompare(sb, undefined, { numeric: true, sensitivity: 'base' })
    if (c !== 0) return mul * c
    return a.ticker.localeCompare(b.ticker)
  }
  const va = Number(a[key])
  const vb = Number(b[key])
  if (va !== vb) return mul * (va < vb ? -1 : va > vb ? 1 : 0)
  return a.ticker.localeCompare(b.ticker)
}

function SortableTh({
  label,
  sortKey,
  active,
  dir,
  onSort,
  className = '',
}: {
  label: string
  sortKey: PositionSortKey
  active: boolean
  dir: 'asc' | 'desc' | null
  onSort: (k: PositionSortKey) => void
  className?: string
}) {
  const ariaSort = active && dir ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'
  return (
    <th scope="col" className={className} aria-sort={ariaSort}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 font-semibold text-terminal-text-dim hover:text-terminal-text transition-colors text-left max-w-full group"
      >
        <span>{label}</span>
        <span className="font-mono text-[10px] opacity-50 group-hover:opacity-90 tabular-nums" aria-hidden>
          {active && dir === 'asc' ? '▲' : active && dir === 'desc' ? '▼' : '·'}
        </span>
      </button>
    </th>
  )
}

/** Y-axis: pad slightly below min / above max so the line uses most of the chart height. */
function computeTightYDomain(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1]
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min
  if (range === 0) {
    const pad = Math.max(Math.abs(min) * 0.004, 40)
    return [min - pad, max + pad]
  }
  const pad = Math.max(range * 0.06, max * 0.0015, 30)
  const low = min - pad
  const high = max + pad
  const step = range < 400 ? 5 : range < 4000 ? 10 : 50
  return [Math.floor(low / step) * step, Math.ceil(high / step) * step]
}

/** Wider context (legacy): minimum vertical span so flat portfolios are not misleadingly zoomed in the other direction. */
function computeContextYDomain(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1]
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min
  const minVisibleSpan = 2000
  const paddedSpan = range > 0 ? range * 1.35 : 0
  const span = Math.max(minVisibleSpan, paddedSpan)
  const center = (min + max) / 2
  const rawLow = center - span / 2
  const rawHigh = center + span / 2
  return [Math.floor(rawLow / 100) * 100, Math.ceil(rawHigh / 100) * 100]
}

function formatMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `£${value.toFixed(2)}`
}

function formatQuantity(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

function profitLockLabel(status: string | null | undefined): string {
  switch (status) {
    case 'protected':
      return 'Protected'
    case 'eligible':
      return 'Needs Lock'
    case 'exit_required':
      return 'Exit Required'
    default:
      return 'Inactive'
  }
}

function profitLockVariant(status: string | null | undefined): PillVariant {
  switch (status) {
    case 'protected':
      return 'active'
    case 'eligible':
      return 'warning'
    case 'exit_required':
      return 'alert'
    default:
      return 'dim'
  }
}

function hasProfitLockInfo(status: string | null | undefined): boolean {
  return Boolean(status && status !== 'inactive')
}

function ProfitLockSummary({
  status,
  requiredPriceGbp,
  stopPriceGbp,
  protectedQty,
  quantity,
}: {
  status: string | null | undefined
  requiredPriceGbp?: number | null
  stopPriceGbp?: number | null
  protectedQty?: number | null
  quantity?: number | null
}) {
  if (!hasProfitLockInfo(status)) {
    return <span className="text-terminal-text-dim text-xs">—</span>
  }

  return (
    <div className="flex flex-col gap-1">
      <StatusPill label={profitLockLabel(status)} variant={profitLockVariant(status)} className="w-fit" />
      <div className="font-mono text-[11px] leading-relaxed text-terminal-text-dim">
        <div>Lock {formatMoney(requiredPriceGbp)}</div>
        <div>Stop {formatMoney(stopPriceGbp)}</div>
        <div>Qty {formatQuantity(protectedQty)} / {formatQuantity(quantity)}</div>
      </div>
    </div>
  )
}

export default function Portfolio({ publicView = false }: { publicView?: boolean }) {
  const [currentPortfolio, setCurrentPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [history, setHistory] = useState<PortfolioSnapshot[]>([])
  const [historyStartTimestamp, setHistoryStartTimestamp] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [forceSellTicker, setForceSellTicker] = useState<string | null>(null)
  const [forceSellLoading, setForceSellLoading] = useState(false)
  const [forceSellResult, setForceSellResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const forceSellModalRef = useFocusTrap(forceSellTicker != null, () => setForceSellTicker(null))

  /** X-range for portfolio value chart (indices into `valueHistoryRows`). */
  const [valueHistoryBrush, setValueHistoryBrush] = useState<{ startIndex: number; endIndex: number } | null>(null)
  const [valueHistoryYMode, setValueHistoryYMode] = useState<'tight' | 'context' | 'custom'>('tight')
  const [valueHistoryYCustomMin, setValueHistoryYCustomMin] = useState('')
  const [valueHistoryYCustomMax, setValueHistoryYCustomMax] = useState('')
  const [valueHistoryYCustomApplied, setValueHistoryYCustomApplied] = useState<[number, number] | null>(null)

  const fetchPortfolio = async () => {
    setError(null)
    try {
      const [current, historyData, historyStart] = await Promise.all([
        publicView ? publicApi.getPortfolioCurrent() : portfolioApi.current(),
        publicView
          ? publicApi.getPortfolioHistory({ limit: PORTFOLIO_HISTORY_FETCH_LIMIT })
          : portfolioApi.history({ limit: PORTFOLIO_HISTORY_FETCH_LIMIT }),
        publicView ? publicApi.getPortfolioHistoryStart() : portfolioApi.historyStart(),
      ])
      setCurrentPortfolio(current)
      setHistory(historyData)
      setHistoryStartTimestamp(historyStart.timestamp)
    } catch (err) {
      console.error('Failed to fetch portfolio:', err)
      setError(err instanceof Error ? err.message : 'Failed to load portfolio')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPortfolio()
    const interval = setInterval(fetchPortfolio, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [publicView])

  const positions = currentPortfolio?.positions ?? []

  const [positionSort, setPositionSort] = useState<{ key: PositionSortKey; dir: 'asc' | 'desc' } | null>(null)

  const sortedPositions = useMemo(() => {
    const list = [...positions]
    if (!positionSort) return list
    const { key, dir } = positionSort
    list.sort((a, b) => comparePositions(a, b, key, dir))
    return list
  }, [positions, positionSort])

  const handlePositionSort = (key: PositionSortKey) => {
    setPositionSort((prev) => {
      if (!prev || prev.key !== key) {
        const defaultDir: 'asc' | 'desc' = key === 'ticker' || key === 'sector' ? 'asc' : 'desc'
        return { key, dir: defaultDir }
      }
      return { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
    })
  }

  // Build per-position sparkline data from history snapshots (3A bonus)
  const positionSparklines = useMemo(() => {
    const sparklines: Record<string, number[]> = {}
    // History is newest-first; reverse for chronological order
    const chronological = [...history].reverse()
    for (const snapshot of chronological) {
      for (const pos of snapshot.positions ?? []) {
        if (!sparklines[pos.ticker]) sparklines[pos.ticker] = []
        sparklines[pos.ticker].push(pos.pnl_pct)
      }
    }
    return sparklines
  }, [history])

  const sectorAllocation = positions.reduce((acc, pos) => {
    const sector = pos.sector ?? 'Unknown'
    acc[sector] = (acc[sector] || 0) + pos.value_gbp
    return acc
  }, {} as Record<string, number>)

  const pieData = Object.entries(sectorAllocation)
    .filter(([, value]) => value > 0)
    .map(([name, value]) => ({
      name,
      value: Number(value.toFixed(2)),
    }))

  const chartData = useMemo<PortfolioHistoryPoint[]>(() => {
    if (history.length === 0) return []

    const points = [...history]
      .reverse()
      .map((snapshot) => ({
        timestamp: snapshot.timestamp,
        date: safeFormat(snapshot.timestamp, 'MMM dd', ''),
        value: snapshot.total_value_gbp,
      }))
      .filter((point) => point.date)

    const historyStartMs = historyStartTimestamp ? Date.parse(historyStartTimestamp) : Number.NaN
    const filteredPoints = Number.isFinite(historyStartMs)
      ? points.filter((point) => {
          const timestampMs = Date.parse(point.timestamp)
          return Number.isFinite(timestampMs) && timestampMs >= historyStartMs
        })
      : points

    if (filteredPoints.length === 0) return []

    if (!Number.isFinite(historyStartMs) || !historyStartTimestamp) {
      return filteredPoints
    }

    const firstPointMs = Date.parse(filteredPoints[0].timestamp)
    // Anchor the chart to the first recorded order. When snapshots begin later, prepend
    // the intended inception value so the plotted series starts from the strategy baseline.
    const needsSyntheticBaseline =
      !Number.isFinite(firstPointMs) ||
      firstPointMs > historyStartMs ||
      Math.abs(filteredPoints[0].value - PORTFOLIO_HISTORY_BASELINE_VALUE_GBP) > 0.01

    if (!needsSyntheticBaseline) {
      return filteredPoints
    }

    const baselineDate = safeFormat(historyStartTimestamp, 'MMM dd', '')
    if (!baselineDate) return filteredPoints

    return [
      {
        timestamp: historyStartTimestamp,
        date: baselineDate,
        value: PORTFOLIO_HISTORY_BASELINE_VALUE_GBP,
      },
      ...filteredPoints,
    ]
  }, [history, historyStartTimestamp])

  useEffect(() => {
    const n = chartData.length
    if (n === 0) return
    const last = n - 1
    setValueHistoryBrush((b) => {
      if (b == null) return { startIndex: 0, endIndex: last }
      const s = Math.max(0, Math.min(b.startIndex, last))
      const e = Math.max(s, Math.min(b.endIndex, last))
      if (s === b.startIndex && e === b.endIndex) return b
      return { startIndex: s, endIndex: e }
    })
  }, [chartData])

  const displayedValueHistory = useMemo(() => {
    if (chartData.length === 0) return []
    const b = valueHistoryBrush ?? { startIndex: 0, endIndex: chartData.length - 1 }
    return chartData.slice(b.startIndex, b.endIndex + 1)
  }, [chartData, valueHistoryBrush])

  const valueHistoryYDomain = useMemo((): [number, number] => {
    if (valueHistoryYMode === 'custom' && valueHistoryYCustomApplied) {
      const [a, b] = valueHistoryYCustomApplied
      if (Number.isFinite(a) && Number.isFinite(b) && a < b) return [a, b]
    }
    const values = displayedValueHistory.map((d) => d.value)
    if (values.length === 0) return [0, 1]
    if (valueHistoryYMode === 'context') return computeContextYDomain(values)
    return computeTightYDomain(values)
  }, [displayedValueHistory, valueHistoryYMode, valueHistoryYCustomApplied])

  const onValueHistoryBrushChange = useCallback((e: { startIndex?: number; endIndex?: number }) => {
    if (e.startIndex == null || e.endIndex == null) return
    setValueHistoryBrush({ startIndex: e.startIndex, endIndex: e.endIndex })
  }, [])

  const resetValueHistoryRange = useCallback(() => {
    const last = chartData.length - 1
    if (last >= 0) setValueHistoryBrush({ startIndex: 0, endIndex: last })
  }, [chartData.length])

  const applyValueHistoryCustomY = useCallback(() => {
    const lo = parseFloat(valueHistoryYCustomMin.replace(/,/g, ''))
    const hi = parseFloat(valueHistoryYCustomMax.replace(/,/g, ''))
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo >= hi) return
    setValueHistoryYCustomApplied([lo, hi])
    setValueHistoryYMode('custom')
  }, [valueHistoryYCustomMin, valueHistoryYCustomMax])

  const COLORS = ['#00d4ff', '#00ffa3', '#6332ff', '#ff4466', '#f7c948']

  const handleForceSell = async () => {
    if (publicView || !forceSellTicker) return
    setForceSellLoading(true)
    setForceSellResult(null)
    try {
      const result = await systemApi.forceSell(forceSellTicker)
      if (result.status === 'sold' || result.status === 'dry_run') {
        setForceSellResult({ type: 'success', message: `${cleanTicker(forceSellTicker)} sold (${result.quantity} shares) — ${result.status}` })
        fetchPortfolio()
      } else if (result.status === 'no_position') {
        setForceSellResult({ type: 'error', message: `No open position for ${cleanTicker(forceSellTicker)}` })
      } else {
        setForceSellResult({ type: 'error', message: result.error || 'Unknown error' })
      }
    } catch (err) {
      setForceSellResult({ type: 'error', message: err instanceof Error ? err.message : 'Force sell failed' })
    } finally {
      setForceSellLoading(false)
      setForceSellTicker(null)
    }
  }

  useEffect(() => {
    if (!forceSellResult) return
    const t = setTimeout(() => setForceSellResult(null), 5000)
    return () => clearTimeout(t)
  }, [forceSellResult])

  if (loading) {
    return <TableSkeleton rows={6} cols={5} />
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-loss text-sm">{error}</p>
        <button type="button" onClick={() => { setLoading(true); fetchPortfolio() }} className="btn-secondary">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Portfolio"
        titleMeta={
          currentPortfolio ? (
            <div className="text-right">
              <div className="text-sm text-terminal-text-dim">Total Value</div>
              <div className="text-2xl font-mono font-bold">
                £{currentPortfolio.total_value_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </div>
            </div>
          ) : null
        }
        description={publicView
          ? 'Read-only portfolio view: current positions, cash, value history, and protection state from the latest snapshot. Charts show portfolio value over time and sector allocation; operator actions remain private.'
          : 'Current positions, cash, value history, and profit-lock protection state from the latest snapshot. Positions table lists ticker, quantity, value, P&L, and whether winners above the sell threshold are fully protected.'}
      />
      <div className="text-xs text-terminal-text-dim">
        {currentPortfolio?.timestamp
          ? `Snapshot captured ${safeFormat(currentPortfolio.timestamp, 'MMM dd, yyyy HH:mm:ss', '—')}. Intraday refresh runs keep this page aligned with the latest broker state between full cycles.`
          : 'Waiting for the first portfolio snapshot.'}
      </div>

      {/* Force Sell confirmation modal */}
      {!publicView && forceSellTicker && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setForceSellTicker(null)}>
          <div ref={forceSellModalRef} className="bg-terminal-surface border border-terminal-border rounded-lg p-4 max-w-sm shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-loss mb-2">Force sell {cleanTicker(forceSellTicker)}?</h3>
            <p className="text-sm text-terminal-text-dim mb-4">
              This will immediately sell the entire position at market price. This action cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setForceSellTicker(null)} className="btn-secondary text-sm py-1.5">Cancel</button>
              <button type="button" onClick={handleForceSell} disabled={forceSellLoading} className="btn-danger-solid text-sm py-1.5 disabled:opacity-50">
                {forceSellLoading ? 'Selling...' : 'Force Sell'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Result toast */}
      {!publicView && forceSellResult && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded shadow-lg text-sm font-mono ${forceSellResult.type === 'success' ? 'bg-gain/20 border border-gain/40 text-gain' : 'bg-loss/20 border border-loss/40 text-loss'}`}>
          {forceSellResult.message}
        </div>
      )}

      {publicView && (
        <div className="card border-cyan/20">
          <p className="text-sm text-terminal-text-dim">
            This page is public in read-only mode. Trading controls such as Force Sell remain operator-only behind sign-in.
          </p>
        </div>
      )}

      {/* Portfolio Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Cash Balance</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio
              ? `£${currentPortfolio.cash_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Investments</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio
              ? `£${currentPortfolio.invested_gbp.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : 'N/A'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Positions</div>
          <div className="text-xl font-mono mt-1">
            {currentPortfolio?.num_positions ?? positions.length}
          </div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Last Updated</div>
          <div className="text-sm font-mono mt-1">
            {currentPortfolio
              ? safeFormat(currentPortfolio.timestamp, 'MMM dd, yyyy HH:mm', 'N/A')
              : 'N/A'}
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Portfolio Value Chart */}
        <div className="card">
          <h3 className="text-lg font-semibold tracking-wide mb-2">Portfolio Value History</h3>
          <p className="text-xs text-terminal-text-dim mb-3">
            Y-axis defaults to a tight fit around the visible points. Use the scale control for a wider context or fixed £ bounds; drag the range bar under the navigator to pick a date window (like Plotly).
          </p>
          {chartData.length > 0 ? (
            <>
              <div className="flex flex-wrap gap-3 items-end mb-3">
                <label className="flex flex-col gap-0.5 text-xs min-w-0">
                  <span className="text-terminal-text-dim">Y-axis scale</span>
                  <select
                    value={valueHistoryYMode}
                    onChange={(e) => {
                      const m = e.target.value as 'tight' | 'context' | 'custom'
                      setValueHistoryYMode(m)
                      if (m !== 'custom') setValueHistoryYCustomApplied(null)
                    }}
                    className="rounded-md bg-terminal-bg border border-terminal-border px-2 py-1.5 text-sm font-mono text-terminal-text w-full max-w-[14rem]"
                  >
                    <option value="tight">Tight (min–max + pad)</option>
                    <option value="context">Wide context (~£2k min span)</option>
                    <option value="custom">Custom min / max £</option>
                  </select>
                </label>
                {valueHistoryYMode === 'custom' && (
                  <>
                    <label className="flex flex-col gap-0.5 text-xs">
                      <span className="text-terminal-text-dim">Min £</span>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={valueHistoryYCustomMin}
                        onChange={(e) => setValueHistoryYCustomMin(e.target.value)}
                        placeholder="e.g. 9900"
                        className="w-24 rounded-md bg-terminal-bg border border-terminal-border px-2 py-1.5 font-mono text-sm text-terminal-text"
                      />
                    </label>
                    <label className="flex flex-col gap-0.5 text-xs">
                      <span className="text-terminal-text-dim">Max £</span>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={valueHistoryYCustomMax}
                        onChange={(e) => setValueHistoryYCustomMax(e.target.value)}
                        placeholder="e.g. 10100"
                        className="w-24 rounded-md bg-terminal-bg border border-terminal-border px-2 py-1.5 font-mono text-sm text-terminal-text"
                      />
                    </label>
                    <button type="button" onClick={applyValueHistoryCustomY} className="text-xs rounded-md border border-accent/50 text-accent hover:bg-accent/10 px-2 py-1.5">
                      Apply Y
                    </button>
                  </>
                )}
                <button
                  type="button"
                  onClick={resetValueHistoryRange}
                  className="text-xs rounded-md border border-terminal-border text-terminal-text-dim hover:text-terminal-text hover:border-terminal-text/40 px-2 py-1.5 sm:ml-auto"
                >
                  Reset date range
                </button>
              </div>
              <ResponsiveContainer width="100%" height={268}>
                <LineChart data={displayedValueHistory} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis dataKey="date" stroke="#8b949e" interval="preserveStartEnd" minTickGap={24} />
                  <YAxis
                    type="number"
                    stroke="#8b949e"
                    domain={valueHistoryYDomain}
                    allowDataOverflow
                    tickCount={6}
                    tickFormatter={(v) => `£${Math.round(v).toLocaleString()}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#06060a',
                      border: '1px solid #00d4ff66',
                      borderRadius: '8px',
                      boxShadow: '0 6px 20px rgba(0, 0, 0, 0.45)',
                      color: '#e6edf3',
                    }}
                    itemStyle={{ color: '#e6edf3' }}
                    labelStyle={{ color: '#00d4ff', fontWeight: 600 }}
                    formatter={(value: number, name: string) => [
                      `£${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                      name,
                    ]}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    name="Portfolio value"
                    stroke="#00d4ff"
                    strokeWidth={2}
                    dot={{ fill: '#00d4ff', r: 4 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
              {chartData.length >= 2 ? (
                <div className="mt-1">
                  <ResponsiveContainer width="100%" height={76}>
                    <LineChart data={chartData} margin={{ top: 2, right: 12, left: 4, bottom: 2 }}>
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} stroke="#8b949e" interval="preserveStartEnd" minTickGap={32} />
                      <YAxis hide domain={['auto', 'auto']} />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke="#00d4ff66"
                        strokeWidth={1.25}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Brush
                        dataKey="date"
                        height={28}
                        stroke="#00d4ff"
                        fill="rgba(0, 212, 255, 0.12)"
                        travellerWidth={10}
                        startIndex={valueHistoryBrush?.startIndex ?? 0}
                        endIndex={valueHistoryBrush?.endIndex ?? chartData.length - 1}
                        onChange={onValueHistoryBrushChange}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-[11px] text-terminal-text-dim mt-1" id="portfolio-value-brush-hint">
                    Drag the handles or shaded band to change the date range in the chart above. Y-axis (tight mode) uses only points in that range.
                  </p>
                </div>
              ) : null}
            </>
          ) : (
            <div className="h-64 flex items-center justify-center text-terminal-text-dim">
              No history data available
            </div>
          )}
        </div>

        {/* Sector Allocation */}
        <div className="card">
          <h3 className="text-lg font-semibold tracking-wide mb-4">Sector Allocation</h3>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) =>
                    `${name}: ${(percent * 100).toFixed(0)}%`
                  }
                  outerRadius={80}
                  fill="#00d4ff"
                  dataKey="value"
                >
                  {pieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#06060a',
                    border: '1px solid #00d4ff66',
                    borderRadius: '8px',
                    boxShadow: '0 6px 20px rgba(0, 0, 0, 0.45)',
                    color: '#e6edf3',
                  }}
                  itemStyle={{ color: '#e6edf3' }}
                  labelStyle={{ color: '#00d4ff', fontWeight: 600 }}
                  formatter={(value: number, name: string) => [
                    `£${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                    name,
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-64 flex items-center justify-center text-terminal-text-dim">
              No positions
            </div>
          )}
        </div>
      </div>

      {/* Positions — mobile cards + desktop table */}
      <div className="card">
        <h3 className="text-lg font-semibold tracking-wide mb-4">Current Positions</h3>
        <p className="text-xs text-terminal-text-dim mb-4">
          Profit lock shows whether a winner above the sell threshold is fully protected by a live stop, still needs protection, or should be exited.
        </p>
        {positions.length === 0 ? (
          <div className="text-center py-8 text-terminal-text-dim">
            No positions
          </div>
        ) : (
          <>
            <label className="sm:hidden flex flex-col gap-1 mb-3 text-sm">
              <span className="text-terminal-text-dim text-xs">Sort by</span>
              <select
                value={positionSort ? `${positionSort.key}:${positionSort.dir}` : ''}
                onChange={(e) => {
                  const v = e.target.value
                  if (!v) setPositionSort(null)
                  else {
                    const [key, dir] = v.split(':') as [PositionSortKey, 'asc' | 'desc']
                    setPositionSort({ key, dir })
                  }
                }}
                className="w-full rounded-md bg-terminal-bg border border-terminal-border px-3 py-2 text-terminal-text font-mono text-sm"
              >
                <option value="">Default (API order)</option>
                <option value="ticker:asc">Ticker A–Z</option>
                <option value="ticker:desc">Ticker Z–A</option>
                <option value="sector:asc">Sector A–Z</option>
                <option value="sector:desc">Sector Z–A</option>
                <option value="quantity:desc">Quantity (high → low)</option>
                <option value="quantity:asc">Quantity (low → high)</option>
                <option value="value_gbp:desc">Value £ (high → low)</option>
                <option value="value_gbp:asc">Value £ (low → high)</option>
                <option value="pnl_gbp:desc">P&amp;L £ (high → low)</option>
                <option value="pnl_gbp:asc">P&amp;L £ (low → high)</option>
                <option value="pnl_pct:desc">P&amp;L % (high → low)</option>
                <option value="pnl_pct:asc">P&amp;L % (low → high)</option>
              </select>
            </label>
            {/* Mobile card layout */}
            <div className="sm:hidden space-y-3">
              {sortedPositions.map((pos) => (
                <div key={pos.ticker} className="border border-terminal-border rounded-lg p-3 bg-terminal-surface/30">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold">{cleanTicker(pos.ticker)}</span>
                      {positionSparklines[pos.ticker]?.length >= 2 && (
                        <Sparkline data={positionSparklines[pos.ticker]} directional width={48} height={16} />
                      )}
                    </div>
                    <PnlValue value={pos.pnl_pct} suffix="%" className="font-mono text-sm" />
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <span className="text-terminal-text-dim text-xs">Value</span>
                      <div className="font-mono">£{pos.value_gbp.toFixed(2)}</div>
                    </div>
                    <div>
                      <span className="text-terminal-text-dim text-xs">P&L</span>
                      <div className="font-mono"><PnlCurrency value={pos.pnl_gbp} /></div>
                    </div>
                    <div>
                      <span className="text-terminal-text-dim text-xs">Qty</span>
                      <div className="font-mono">{pos.quantity}</div>
                    </div>
                    {!publicView && (
                      <div className="flex items-end justify-end">
                        <button
                          type="button"
                          onClick={() => setForceSellTicker(pos.ticker)}
                          className="text-xs text-loss hover:text-loss/80 border border-loss/30 hover:border-loss/60 rounded px-2 py-0.5 transition-colors"
                        >
                          Force Sell
                        </button>
                      </div>
                    )}
                  </div>
                  {hasProfitLockInfo(pos.profit_lock_status) && (
                    <div className="mt-3 pt-3 border-t border-terminal-border">
                      <div className="text-terminal-text-dim text-xs mb-1">Profit Lock</div>
                      <ProfitLockSummary
                        status={pos.profit_lock_status}
                        requiredPriceGbp={pos.profit_lock_required_price_gbp}
                        stopPriceGbp={pos.profit_lock_stop_price_gbp}
                        protectedQty={pos.profit_lock_protected_qty}
                        quantity={pos.quantity}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-terminal-border">
                    <SortableTh
                      label="Ticker"
                      sortKey="ticker"
                      active={positionSort?.key === 'ticker'}
                      dir={positionSort?.key === 'ticker' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm"
                    />
                    <SortableTh
                      label="Sector"
                      sortKey="sector"
                      active={positionSort?.key === 'sector'}
                      dir={positionSort?.key === 'sector' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm hidden md:table-cell"
                    />
                    <SortableTh
                      label="Quantity"
                      sortKey="quantity"
                      active={positionSort?.key === 'quantity'}
                      dir={positionSort?.key === 'quantity' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm hidden lg:table-cell"
                    />
                    <SortableTh
                      label="Value"
                      sortKey="value_gbp"
                      active={positionSort?.key === 'value_gbp'}
                      dir={positionSort?.key === 'value_gbp' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm"
                    />
                    <SortableTh
                      label="P&L"
                      sortKey="pnl_gbp"
                      active={positionSort?.key === 'pnl_gbp'}
                      dir={positionSort?.key === 'pnl_gbp' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm"
                    />
                    <SortableTh
                      label="P&L %"
                      sortKey="pnl_pct"
                      active={positionSort?.key === 'pnl_pct'}
                      dir={positionSort?.key === 'pnl_pct' ? positionSort.dir : null}
                      onSort={handlePositionSort}
                      className="px-4 py-3 text-left text-sm"
                    />
                    <th scope="col" className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim">Protection</th>
                    <th scope="col" className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim hidden lg:table-cell">Trend</th>
                    {!publicView && <th scope="col" className="px-4 py-3 text-right text-sm font-semibold text-terminal-text-dim">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {sortedPositions.map((pos) => (
                    <tr key={pos.ticker} className="border-b border-terminal-border hover:bg-terminal-surface/50">
                      <td className="px-4 py-3 font-mono font-semibold">{cleanTicker(pos.ticker)}</td>
                      <td className="px-4 py-3 text-sm hidden md:table-cell">{pos.sector ?? '—'}</td>
                      <td className="px-4 py-3 font-mono hidden lg:table-cell">{pos.quantity}</td>
                      <td className="px-4 py-3 font-mono">
                        £{pos.value_gbp.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-4 py-3 font-mono"><PnlCurrency value={pos.pnl_gbp} /></td>
                      <td className="px-4 py-3 font-mono"><PnlValue value={pos.pnl_pct} suffix="%" /></td>
                      <td className="px-4 py-3 align-top">
                        <ProfitLockSummary
                          status={pos.profit_lock_status}
                          requiredPriceGbp={pos.profit_lock_required_price_gbp}
                          stopPriceGbp={pos.profit_lock_stop_price_gbp}
                          protectedQty={pos.profit_lock_protected_qty}
                          quantity={pos.quantity}
                        />
                      </td>
                      <td className="px-4 py-3 hidden lg:table-cell">
                        {positionSparklines[pos.ticker]?.length >= 2 ? (
                          <Sparkline data={positionSparklines[pos.ticker]} directional width={72} height={20} />
                        ) : (
                          <span className="text-terminal-text-dim text-xs">—</span>
                        )}
                      </td>
                      {!publicView && (
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => setForceSellTicker(pos.ticker)}
                            className="text-xs text-loss hover:text-loss/80 border border-loss/30 hover:border-loss/60 rounded px-2 py-0.5 transition-colors"
                          >
                            Force Sell
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
