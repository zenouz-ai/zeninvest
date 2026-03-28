import { type ReactNode } from 'react'
import { clsx } from 'clsx'

export type DeltaColor = 'emerald' | 'cyan' | 'violet' | 'loss' | 'warning' | 'dim'

interface MetricCardProps {
  /** Mono uppercase eyebrow label */
  label: string
  /** Large hero value — rendered in Syne bold */
  value: ReactNode
  /** Optional supporting sentence below value */
  subtitle?: ReactNode
  /** Optional delta chip (e.g. "+2.4%") */
  delta?: string
  /** Colour of the delta chip */
  deltaColor?: DeltaColor
  className?: string
}

const deltaClasses: Record<DeltaColor, string> = {
  emerald: 'pill pill-emerald',
  cyan:    'pill pill-cyan',
  violet:  'pill pill-violet',
  loss:    'pill pill-loss',
  warning: 'pill pill-warning',
  dim:     'pill pill-dim',
}

/**
 * Hero KPI card — label → value → subtitle with optional delta chip.
 *
 * Sits inside a Panel or dashboard-panel. Does not apply its own surface.
 */
export function MetricCard({ label, value, subtitle, delta, deltaColor = 'dim', className }: MetricCardProps) {
  return (
    <div className={clsx('flex min-h-[9rem] flex-col gap-1.5', className)}>
      <span className="label-mono">{label}</span>
      <div className="flex items-end gap-2 flex-wrap">
        <span
          className="text-[clamp(1.6rem,2.6vw,2.5rem)] font-bold tracking-[-0.03em] leading-none text-terminal-text"
          style={{ fontFamily: 'var(--font-heading)' }}
        >
          {value}
        </span>
        {delta && (
          <span className={deltaClasses[deltaColor]}>{delta}</span>
        )}
      </div>
      {subtitle && (
        <div className="max-w-xs text-xs leading-relaxed text-terminal-text-dim">{subtitle}</div>
      )}
    </div>
  )
}
