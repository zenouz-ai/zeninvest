import * as d3 from 'd3'
import type { UniverseBubbleItem } from '../types'
import { cleanTicker } from '../types'

function formatMarketCap(value: number | null | undefined): string {
  if (value == null) return 'N/A'
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
  if (value >= 1e6) return `$${(value / 1e6).toFixed(2)}M`
  return `$${value.toLocaleString()}`
}

type PackNode = d3.HierarchyCircularNode<{ id: string; item?: UniverseBubbleItem; value: number }>

export function UniverseBubbleChart({
  data,
  width,
  height,
  onTickerClick,
}: {
  data: UniverseBubbleItem[]
  width: number
  height: number
  onTickerClick?: (ticker: string) => void
}) {
  // Pure (non-hook) computation of packed bubbles
  const sectorMap = new Map<string, UniverseBubbleItem[]>()
  for (const item of data) {
    const sector = item.sector && item.sector.trim() ? item.sector : 'Other'
    if (!sectorMap.has(sector)) sectorMap.set(sector, [])
    sectorMap.get(sector)!.push(item)
  }

  type NodeData = { id: string; item?: UniverseBubbleItem; value: number; children?: NodeData[] }
  const rootChildren: NodeData[] = []
  for (const [sectorName, items] of sectorMap.entries()) {
    rootChildren.push({
      id: sectorName,
      value: 0,
      children: items.map((item) => ({
        id: item.ticker,
        item,
        value: Math.max(0.15, (item.uov_ewma ?? 0) + 0.5),
      })),
    })
  }

  const rootData: NodeData = { id: 'root', value: 0, children: rootChildren }
  const root = d3.hierarchy(rootData, (d: NodeData) => d.children)
  root.sum((d: NodeData) => d.value ?? 0)
  const pack = d3.pack<NodeData>().size([width, height]).padding(3)
  const packed = pack(root)
  const nodes: PackNode[] = []
  const sectorNodes: PackNode[] = []
  packed.each((node) => {
    const n = node as PackNode
    if (n.data.item) nodes.push(n)
    else if (n.data.id !== 'root' && n.children?.length) sectorNodes.push(n)
  })

  return (
    <div className="relative">
      <svg width={width} height={height} className="overflow-visible">
        {sectorNodes.map((sector) => (
          <g key={sector.data.id}>
            <circle
              cx={sector.x}
              cy={sector.y}
              r={sector.r}
              fill="none"
              stroke="var(--color-terminal-border)"
              strokeWidth={1}
              strokeDasharray="4 2"
              opacity={0.6}
            />
            <text
              x={sector.x}
              y={sector.y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="text-[10px] fill-[var(--color-terminal-text-dim)] font-medium"
            >
              {sector.data.id}
            </text>
          </g>
        ))}
        {nodes.map((node) => {
          const item = node.data.item!
          const investigated = item.investigated
          return (
            <g
              key={item.ticker}
              transform={`translate(${node.x},${node.y})`}
              onClick={() => onTickerClick?.(item.ticker)}
              style={{ cursor: onTickerClick ? 'pointer' : 'default' }}
            >
              <circle
                r={node.r - 0.5}
                fill={investigated ? 'var(--color-accent)' : 'var(--color-terminal-surface)'}
                stroke={investigated ? 'var(--color-accent)' : 'var(--color-terminal-border)'}
                strokeWidth={1}
                opacity={investigated ? 0.9 : 0.7}
              />
              <text
                textAnchor="middle"
                dominantBaseline="middle"
                className="text-[9px] fill-[var(--color-terminal-text)] font-mono"
                style={{ pointerEvents: 'none' }}
              >
                {cleanTicker(item.ticker)}
              </text>
              <title>
                {cleanTicker(item.ticker)}
                {item.name ? ` – ${item.name}` : ''}
                {'\n'}
                Industry: {item.industry || 'N/A'}
                {'\n'}
                Market cap: {formatMarketCap(item.market_cap)}
                {'\n'}
                Screened: {item.last_screened_at ? 'Yes' : 'No'}
                {item.data_available ? ' · Data OK' : ' · No data'}
                {'\n'}
                Investigated: {item.investigated ? 'Yes' : 'No'}
                {'\n'}
                UOV ewma: {item.uov_ewma != null ? item.uov_ewma.toFixed(3) : '—'} / z:{' '}
                {item.uov_z != null ? item.uov_z.toFixed(3) : '—'}
              </title>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
