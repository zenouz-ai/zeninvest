import { useEffect, useState } from 'react'

interface FreshnessIndicatorProps {
  lastUpdatedAt: Date | null
  isStale?: boolean
  className?: string
}

function formatAge(date: Date): string {
  const diffMs = Date.now() - date.getTime()
  const seconds = Math.floor(diffMs / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}

/**
 * Shows "Updated Xs ago" below a card/section.
 * Turns amber when isStale=true (data exists but last fetch failed).
 */
export function FreshnessIndicator({ lastUpdatedAt, isStale = false, className = '' }: FreshnessIndicatorProps) {
  const [, setTick] = useState(0)

  // Re-render every 10s to keep the age display current
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 10_000)
    return () => clearInterval(interval)
  }, [])

  if (!lastUpdatedAt) return null

  const ageStr = formatAge(lastUpdatedAt)
  const color = isStale ? 'text-warning' : 'text-terminal-text-dim'

  return (
    <span className={`text-xs ${color} ${className}`}>
      {isStale && '(stale) '}Updated {ageStr}
    </span>
  )
}
