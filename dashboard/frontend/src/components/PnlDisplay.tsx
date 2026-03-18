/**
 * Accessible P&L display with directional arrows.
 * Adds ▲/▼ alongside colour so information isn't colour-only.
 */
export function PnlValue({ value, suffix = '', className = '' }: { value: number; suffix?: string; className?: string }) {
  const isPositive = value >= 0
  const arrow = isPositive ? '▲' : '▼'
  const color = isPositive ? 'text-gain' : 'text-loss'
  const prefix = isPositive ? '+' : ''
  const label = `${isPositive ? 'Profit' : 'Loss'}: ${prefix}${value.toFixed(2)}${suffix}`

  return (
    <span className={`${color} ${className}`} aria-label={label}>
      <span className="text-[0.7em] mr-0.5">{arrow}</span>
      {prefix}{value.toFixed(2)}{suffix}
    </span>
  )
}

export function PnlCurrency({ value, currency = '£', className = '' }: { value: number; currency?: string; className?: string }) {
  const isPositive = value >= 0
  const arrow = isPositive ? '▲' : '▼'
  const color = isPositive ? 'text-gain' : 'text-loss'
  const prefix = isPositive ? '+' : ''
  const formatted = value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const label = `${isPositive ? 'Profit' : 'Loss'}: ${prefix}${currency}${formatted}`

  return (
    <span className={`${color} ${className}`} aria-label={label}>
      <span className="text-[0.7em] mr-0.5">{arrow}</span>
      {prefix}{currency}{formatted}
    </span>
  )
}
