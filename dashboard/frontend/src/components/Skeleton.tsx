/** Pulsing skeleton placeholder blocks for loading states (ES-2). */

export function SkeletonBlock({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-terminal-border/30 ${className}`} />
  )
}

/** Card-shaped skeleton with a header line and body lines. */
export function SkeletonCard({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`card space-y-3 ${className}`}>
      <SkeletonBlock className="h-4 w-1/3" />
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBlock key={i} className={`h-3 ${i % 2 === 0 ? 'w-full' : 'w-4/5'}`} />
      ))}
    </div>
  )
}

/** Full-page skeleton layout matching Dashboard structure. */
export function DashboardSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading dashboard">
      {/* Header skeleton */}
      <div className="space-y-2">
        <SkeletonBlock className="h-3 w-24" />
        <SkeletonBlock className="h-7 w-48" />
        <SkeletonBlock className="h-3 w-72" />
      </div>
      {/* Top cards row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card space-y-2">
            <SkeletonBlock className="h-3 w-16" />
            <SkeletonBlock className="h-6 w-20" />
          </div>
        ))}
      </div>
      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        <div className="space-y-6">
          <SkeletonCard lines={5} />
          <SkeletonCard lines={4} />
        </div>
        <div className="space-y-6">
          <SkeletonCard lines={4} />
          <SkeletonCard lines={3} />
        </div>
      </div>
    </div>
  )
}

/** Table skeleton with header row and body rows. */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="card space-y-3" role="status" aria-label="Loading table">
      <SkeletonBlock className="h-5 w-40" />
      <div className="space-y-2">
        {/* Header */}
        <div className="flex gap-4">
          {Array.from({ length: cols }).map((_, i) => (
            <SkeletonBlock key={i} className="h-3 flex-1" />
          ))}
        </div>
        {/* Rows */}
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-4">
            {Array.from({ length: cols }).map((_, c) => (
              <SkeletonBlock key={c} className="h-3 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
