import React, { useEffect, useState, useMemo } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table'
import { universeApi } from '../api/client'
import type { Instrument, InstrumentDetail, UniverseBubbleItem } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'
import { LLMOutputPanel } from '../components/LLMOutputBlocks'

type UniverseRow = Instrument & {
  _investigated: boolean
  _reviews: number
  _holding: number
  _sold: number
  _uov_ewma: number | null
}

const columnHelper = createColumnHelper<UniverseRow>()

function SortIndicator({ column }: { column: { getIsSorted: () => false | 'asc' | 'desc' } }) {
  const sort = column.getIsSorted()
  if (!sort) return <span className="opacity-40 ml-1">⇅</span>
  return (
    <span className="ml-1 text-accent">
      {sort === 'asc' ? '↑' : '↓'}
    </span>
  )
}

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
  const [sorting, setSorting] = useState<SortingState>([])

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
        enableSorting: true,
        cell: (info) => (
          <span className="font-mono font-semibold">
            {cleanTicker(info.getValue())}
          </span>
        ),
      }),
      columnHelper.accessor('name', {
        header: 'Name',
        enableSorting: true,
        cell: (info) => (
          <span className="truncate max-w-[160px] inline-block align-middle">
            {info.getValue()}
          </span>
        ),
      }),
      columnHelper.accessor('sector', {
        header: 'Sector',
        enableSorting: true,
        cell: (info) => (
          <span className="text-terminal-text-dim">{info.getValue() || 'N/A'}</span>
        ),
      }),
      columnHelper.accessor('industry', {
        header: 'Industry',
        enableSorting: true,
        cell: (info) => (
          <span className="text-terminal-text-dim text-sm">
            {info.getValue() || 'N/A'}
          </span>
        ),
      }),
      columnHelper.accessor('market_cap', {
        header: 'Market Cap',
        enableSorting: true,
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
        enableSorting: true,
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
        enableSorting: true,
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
      columnHelper.accessor('_investigated', {
        header: 'Investigated',
        enableSorting: true,
        cell: (info) => {
          const v = info.getValue()
          return (
            <span
              className={
                v
                  ? 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono bg-accent text-terminal-bg'
                  : 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono bg-terminal-surface text-terminal-text-dim'
              }
            >
              {v ? 'Yes' : 'No'}
            </span>
          )
        },
      }),
      columnHelper.accessor('_reviews', {
        header: 'Reviews',
        enableSorting: true,
        cell: (info) => (
          <span className="font-mono text-xs">{info.getValue()}</span>
        ),
      }),
      columnHelper.display({
        id: 'decision_summary',
        header: 'Decisions',
        enableSorting: false,
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
      columnHelper.accessor('_holding', {
        header: 'Holding',
        enableSorting: true,
        cell: (info) => (
          <span className="font-mono text-xs">
            {info.getValue() ? info.getValue().toFixed(2) : '0'}
          </span>
        ),
      }),
      columnHelper.accessor('_sold', {
        header: 'Sold',
        enableSorting: true,
        cell: (info) => {
          const qty = info.getValue()
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
      columnHelper.accessor('_uov_ewma', {
        header: 'UOV (ewma)',
        enableSorting: true,
        sortingFn: (rowA, rowB) => {
          const a = rowA.getValue('_uov_ewma') as number | null
          const b = rowB.getValue('_uov_ewma') as number | null
          if (a == null && b == null) return 0
          if (a == null) return 1
          if (b == null) return -1
          return a - b
        },
        cell: (info) => {
          const v = info.getValue()
          return (
            <span className="font-mono text-xs">
              {v != null ? v.toFixed(3) : '—'}
            </span>
          )
        },
      }),
    ],
    [decisionStatsMap]
  )

  const filteredData = useMemo(() => {
    const scored = instruments.map((inst): UniverseRow => {
      const ticker = inst.ticker
      const investigated = investigatedMap[ticker] ?? false
      const uov = uovMap[ticker]
      const stats = decisionStatsMap[ticker]
      const reviews = stats?.count ?? 0
      const holding = holdingsMap[ticker] ?? 0
      const sold = soldMap[ticker] ?? 0
      return {
        ...inst,
        _investigated: investigated,
        _reviews: reviews,
        _holding: holding,
        _sold: sold,
        _uov_ewma: uov ?? null,
      }
    })

    const filtered = scored.filter((row) => {
      const matchesSearch =
        !search ||
        cleanTicker(row.ticker).toLowerCase().includes(search.toLowerCase()) ||
        row.name.toLowerCase().includes(search.toLowerCase())
      const matchesSector = !sectorFilter || row.sector === sectorFilter
      return matchesSearch && matchesSector
    })

    // Default order when no user sort applied
    filtered.sort((a, b) => {
      if (a._investigated !== b._investigated) return a._investigated ? -1 : 1
      if (a._uov_ewma != null || b._uov_ewma != null) {
        if (a._uov_ewma == null) return 1
        if (b._uov_ewma == null) return -1
        if (b._uov_ewma !== a._uov_ewma) return b._uov_ewma - a._uov_ewma
      }
      if (b._reviews !== a._reviews) return b._reviews - a._reviews
      const ad = a.last_screened_at ?? ''
      const bd = b.last_screened_at ?? ''
      if (ad < bd) return 1
      if (ad > bd) return -1
      return 0
    })

    return filtered
  }, [instruments, search, sectorFilter, investigatedMap, decisionStatsMap, holdingsMap, soldMap, uovMap])

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
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
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort()
                  return (
                    <th
                      key={header.id}
                      className="px-4 py-3 text-left text-sm font-semibold text-terminal-text-dim"
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={() => header.column.toggleSorting(header.column.getIsSorted() === 'asc')}
                          className="flex items-center hover:text-terminal-text transition-colors"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <SortIndicator column={header.column} />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  )
                })}
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
