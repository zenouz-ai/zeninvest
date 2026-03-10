import { useEffect, useState, useMemo } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
} from '@tanstack/react-table'
import { universeApi } from '../api/client'
import type { Instrument } from '../types'
import { cleanTicker } from '../types'
import { format } from 'date-fns'

const columnHelper = createColumnHelper<Instrument>()

export default function Universe() {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [sectorFilter, setSectorFilter] = useState<string>('')

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
              {format(new Date(date), 'MMM dd, yyyy')}
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
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-terminal-border hover:bg-terminal-surface/50 transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
