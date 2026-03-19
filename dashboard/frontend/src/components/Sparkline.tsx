/** Inline SVG sparkline — renders a compact line chart from numeric data points (3A bonus). */

type SparklineProps = {
  data: number[]
  width?: number
  height?: number
  className?: string
  /** Line colour. Defaults to accent colour. */
  color?: string
  /** If true, colour line green/red based on start-to-end direction. */
  directional?: boolean
}

export function Sparkline({
  data,
  width = 80,
  height = 24,
  className = '',
  color,
  directional = false,
}: SparklineProps) {
  if (data.length < 2) return null

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const padding = 1

  const points = data
    .map((v, i) => {
      const x = padding + (i / (data.length - 1)) * (width - 2 * padding)
      const y = padding + (1 - (v - min) / range) * (height - 2 * padding)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  let stroke = color ?? '#00d4ff'
  if (directional) {
    stroke = data[data.length - 1] >= data[0] ? '#00ffa3' : '#ff4466'
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={`inline-block ${className}`}
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
