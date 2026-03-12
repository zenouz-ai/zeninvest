import React, { useEffect, useState, useMemo } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table'
import { universeApi } from '../api/client'
import type { Instrument, InstrumentDetail, UniverseBubbleItem } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'

const columnHelper = createColumnHelper<Instrument>()

export default function Universe() {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [investigatedMap, setInvestigatedMap] = useState<Record<string, boolean>>({})
  const [decisionStatsMap, setDecisionStatsMap] = useState<
    Record<string, { count: number; buy: number; sell: number; reduce: number; hold: number }>
  >({})
  const [holdingsMap, setHoldingsMap] = useState<Record<string, number>>({})
  const [soldMap, setSoldMap] = useState<Record<string, number>>({})
  const [uovMap, setUovMap] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sectorFilter, setSectorFilter] = useState<string>('')
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [detail, setDetail] = useState<InstrumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    const fetchUniverse = async () => {
      try {
        // Fetch base universe plus bubble metadata (for investigated flag)
        const [listData, bubble]: [Instrument[], UniverseBubbleItem[]] = await Promise.all([
          universeApi.list({ limit: 1000 }),
          universeApi.getBubble({ limit: 1000 }),
        ])
        setInstruments(listData)
        const investigated: Record<string, boolean> = {}
        const stats: Record<string, { count: number; buy: number; sell: number; reduce: number; hold: number }> = {}
        const holds: Record<string, number> = {}
        const sold: Record<string, number> = {}
        const uov: Record<string, number | null> = {}
        bubble.forEach((b) => {
          if (b.investigated) {
            investigated[b.ticker] = true
          }
          stats[b.ticker] = {
            count: b.decision_count ?? 0,
            buy: b.buy_count ?? 0,
            sell: b.sell_count ?? 0,
            reduce: b.reduce_count ?? 0,
            hold: b.hold_count ?? 0,
          }
          holds[b.ticker] = b.hold_qty ?? 0
          sold[b.ticker] = b.sold_qty ?? 0
          uov[b.ticker] = b.uov_ewma ?? null
        })
        setInvestigatedMap(investigated)
        setDecisionStatsMap(stats)
        setHoldingsMap(holds)
        setSoldMap(sold)
        setUovMap(uov)
      } catch (error) {
        console.error('Failed to fetch universe:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchUniverse()
  }, [])

  useEffect(() => {
    if (!expandedTicker) {
      setDetail(null)
      return
    }
    setDetailLoading(true)
    universeApi
      .getByTicker(expandedTicker)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }, [expandedTicker])

  const sectors = useMemo(() => {
    const unique = new Set(instruments.map((i) => i.sector).filter(Boolean))
    return Array.from(unique).sort()
  }, [instruments])

  const columns = useMemo(
    () => [
      columnHelper.accessor('ticker', {
        header: 'Ticker',
        cell: (info) => (
          <span className="font-mono font-semibold">
            {cleanTicker(info.getValue())}
          </span>
        ),
      }),
      columnHelper.accessor('name', {
        header: 'Name',
        cell: (info) => (
          <span className="truncate max-w-[160px] inline-block align-middle">
            {info.getValue()}
          </span>
        ),
      }),
      columnHelper.accessor('sector', {
        header: 'Sector',
        cell: (info) => (
          <span className="text-terminal-text-dim">{info.getValue() || 'N/A'}</span>
        ),
      }),
      columnHelper.accessor('industry', {
        header: 'Industry',
        cell: (info) => (
          <span className="text-terminal-text-dim text-sm">
            {info.getValue() || 'N/A'}
          </span>
        ),
      }),
      columnHelper.accessor('market_cap', {
        header: 'Market Cap',
        cell: (info) => {
          const value = info.getValue()
          if (!value) return 'N/A'
          if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
          if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
          if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`
          return `$${value.toLocaleString()}`
        },
      }),
      columnHelper.accessor('last_screened_at', {
        header: 'Last Screened',
        cell: (info) => {
          const date = info.getValue()
          if (!date) return <span className="text-terminal-text-dim">Never</span>
          return (
            <span className="text-terminal-text-dim text-sm">
              {safeFormat(date, 'MMM dd, yyyy', 'Never')}
            </span>
          )
        },
      }),
      columnHelper.accessor('data_available', {
        header: 'Status',
        cell: (info) => (
          <span
            className={
              info.getValue()
                ? 'text-gain text-xs'
                : 'text-loss text-xs'
            }
          >
            {info.getValue() ? 'Available' : 'Unavailable'}
          </span>
        ),
      }),
      columnHelper.display({
        id: 'investigated',
        header: 'Investigated',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const investigated = investigatedMap[ticker] ?? false
          return (
            <span
              className={
                investigated
                  ? 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono bg-accent text-terminal-bg'
                  : 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono bg-terminal-surface text-terminal-text-dim'
              }
            >
              {investigated ? 'Yes' : 'No'}
            </span>
          )
        },
      }),
      columnHelper.display({
        id: 'reviews',
        header: 'Reviews',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const s = decisionStatsMap[ticker]
          return <span className="font-mono text-xs">{s?.count ?? 0}</span>
        },
      }),
      columnHelper.display({
        id: 'decision_summary',
        header: 'Decisions',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const s = decisionStatsMap[ticker]
          if (!s || s.count === 0) {
            return <span className="text-terminal-text-dim text-xs">—</span>
          }
          const parts: string[] = []
          if (s.buy) parts.push(`B${s.buy}`)
          if (s.sell) parts.push(`S${s.sell}`)
          if (s.reduce) parts.push(`R${s.reduce}`)
          if (s.hold) parts.push(`H${s.hold}`)
          return <span className="text-terminal-text-dim text-xs font-mono">{parts.join(' / ')}</span>
        },
      }),
      columnHelper.display({
        id: 'holding',
        header: 'Holding',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const qty = holdingsMap[ticker] ?? 0
          return <span className="font-mono text-xs">{qty ? qty.toFixed(2) : '0'}</span>
        },
      }),
      columnHelper.display({
        id: 'sold',
        header: 'Sold',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const qty = soldMap[ticker] ?? 0
          return (
            <span
              className="font-mono text-xs"
              title={
                typeof qty === 'number'
                  ? `Total shares sold across live and dry-run cycles: ${qty.toFixed(2)}`
                  : undefined
              }
            >
              {qty ? qty.toFixed(2) : '0'}
            </span>
          )
        },
      }),
      columnHelper.display({
        id: 'uov_ewma',
        header: 'UOV (ewma)',
        cell: (info) => {
          const ticker = info.row.original.ticker
          const v = uovMap[ticker]
          return (
            <span className="font-mono text-xs">
              {v != null ? v.toFixed(3) : '—'}
            </span>
          )
        },
      }),
    ],
    [investigatedMap, decisionStatsMap, holdingsMap, soldMap, uovMap]
  )

  const filteredData = useMemo(() => {
    const scored = instruments.map((inst) => {
      const ticker = inst.ticker
      const investigated = investigatedMap[ticker] ?? false
      const uov = uovMap[ticker]
      const stats = decisionStatsMap[ticker]
      const reviews = stats?.count ?? 0
      return { inst, investigated, uov: uov ?? null, reviews }
    })

    const filtered = scored.filter(({ inst }) => {
      const matchesSearch =
        !search ||
        cleanTicker(inst.ticker).toLowerCase().includes(search.toLowerCase()) ||
        inst.name.toLowerCase().includes(search.toLowerCase())
      const matchesSector = !sectorFilter || inst.sector === sectorFilter
      return matchesSearch && matchesSector
    })

    filtered.sort((a, b) => {
      // Investigated first
      if (a.investigated !== b.investigated) {
        return a.investigated ? -1 : 1
      }
      // Higher UOV ewma first when available
      if (a.uov != null || b.uov != null) {
        if (a.uov == null) return 1
        if (b.uov == null) return -1
        if (b.uov !== a.uov) return b.uov - a.uov
      }
      // More reviews first
      if (b.reviews !== a.reviews) return b.reviews - a.reviews
      // Fallback: by last_screened_at desc
      const ad = a.inst.last_screened_at ?? ''
      const bd = b.inst.last_screened_at ?? ''
      if (ad < bd) return 1
      if (ad > bd) return -1
      return 0
    })

    return filtered.map(({ inst }) => inst)
  }, [instruments, search, sectorFilter])

  const table = useReactTable({
    data: filteredData,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-terminal-text-dim">Loading universe...</div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-bold">Stock Universe</h1>
        <div className="text-sm text-terminal-text-dim">
          {filteredData.length} of {instruments.length} stocks
        </div>
      </div>

      {/* Filters */}
      <div className="card flex gap-4 items-center">
        <div className="flex-1">
          <input
            type="text"
            placeholder="Search by ticker or name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-terminal-bg border border-terminal-border rounded px-3 py-2 text-terminal-text focus:outline-none focus:ring-2 focus:ring-neutral"
          />
        </div>
        <div>
          <select
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
            className="bg-terminal-bg border border-terminal-border rounded px-3 py-2 text-terminal-text focus:outline-none focus:ring-2 focus:ring-neutral"
          >
            <option value="">All Sectors</option>
            {sectors.map((sector) => (
              <option key={sector} value={sector}>
                {sector}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-terminal-border">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-terminal-text-dim">
                  No stocks found
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                const ticker = row.original.ticker
                const isExpanded = expandedTicker === ticker
                return (
                  <React.Fragment key={row.id}>
                    <tr
                      key={row.id}
                      onClick={() => setExpandedTicker(isExpanded ? null : ticker)}
                      className={`border-b border-terminal-border hover:bg-terminal-surface/50 transition-colors cursor-pointer ${
                        isExpanded ? 'bg-terminal-surface/70' : ''
                      }`}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-3">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                    {isExpanded && (
                      <tr key={`${row.id}-detail`}>
                        <td colSpan={columns.length} className="px-4 py-4 bg-terminal-bg/80">
                          {detailLoading ? (
                            <div className="text-terminal-text-dim text-sm">Loading...</div>
                          ) : detail ? (
                            <LLMOutputPanel
                              key={detail.ticker}
                              ticker={detail.ticker}
                              lastDecision={detail.last_decision}
                              label={detail.label}
                            />
                          ) : null}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
