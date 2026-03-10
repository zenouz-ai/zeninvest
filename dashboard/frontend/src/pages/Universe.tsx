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
import type { Instrument, InstrumentDetail } from '../types'
import { cleanTicker } from '../types'
import { safeFormat } from '../utils/date'

const columnHelper = createColumnHelper<Instrument>()

export default function Universe() {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sectorFilter, setSectorFilter] = useState<string>('')
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null)
  const [detail, setDetail] = useState<InstrumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    const fetchUniverse = async () => {
      try {
        const data = await universeApi.list()
        setInstruments(data)
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
        cell: (info) => <span className="truncate max-w-xs">{info.getValue()}</span>,
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
    ],
    []
  )

  const filteredData = useMemo(() => {
    return instruments.filter((inst) => {
      const matchesSearch =
        !search ||
        cleanTicker(inst.ticker).toLowerCase().includes(search.toLowerCase()) ||
        inst.name.toLowerCase().includes(search.toLowerCase())
      const matchesSector = !sectorFilter || inst.sector === sectorFilter
      return matchesSearch && matchesSector
    })
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
      <div className="flex items-center justify-between">
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

      {/* Table */}
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
                            <div className="space-y-3 text-sm">
                              <div className="flex items-center gap-2 mb-2">
                                <span className="font-semibold text-accent">
                                  Committee reasoning — {cleanTicker(detail.ticker)}
                                </span>
                                {detail.label && (
                                  <span className="text-xs px-2 py-0.5 rounded bg-terminal-surface">
                                    {detail.label}
                                  </span>
                                )}
                              </div>
                              {detail.last_decision?.strategy && (
                                <div>
                                  <div className="text-terminal-text-dim text-xs mb-1">Strategy</div>
                                  <div className="text-terminal-text">
                                    {detail.last_decision.strategy.action} @ conviction{' '}
                                    {detail.last_decision.strategy.conviction}
                                  </div>
                                  <div className="text-terminal-text-dim text-xs mt-1">
                                    {detail.last_decision.strategy.reasoning}
                                  </div>
                                </div>
                              )}
                              {detail.last_decision?.moderation && (
                                <div>
                                  <div className="text-terminal-text-dim text-xs mb-1">
                                    Moderation — {detail.last_decision.moderation.verdict}
                                  </div>
                                  {detail.last_decision.moderation.reasoning && (
                                    <div className="text-terminal-text-dim text-xs">
                                      {detail.last_decision.moderation.reasoning}
                                    </div>
                                  )}
                                </div>
                              )}
                              {detail.last_decision?.risk && (
                                <div>
                                  <div className="text-terminal-text-dim text-xs mb-1">
                                    Risk — {detail.last_decision.risk.verdict}
                                    {detail.last_decision.risk.triggered_rules?.length
                                      ? ` (${detail.last_decision.risk.triggered_rules.join(', ')})`
                                      : ''}
                                  </div>
                                </div>
                              )}
                              {!detail.last_decision && (
                                <div className="text-terminal-text-dim">No decision data</div>
                              )}
                            </div>
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
