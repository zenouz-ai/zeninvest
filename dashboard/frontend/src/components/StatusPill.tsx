import { clsx } from 'clsx'

export type PillVariant = 'live' | 'active' | 'draft' | 'alert' | 'warning' | 'dim'

interface StatusPillProps {
  label: string
  variant?: PillVariant
  /** Optional leading dot indicator */
  dot?: boolean
  className?: string
}

const variantClass: Record<PillVariant, string> = {
  live:    'pill pill-cyan',
  active:  'pill pill-emerald',
  draft:   'pill pill-violet',
  alert:   'pill pill-loss',
  warning: 'pill pill-warning',
  dim:     'pill pill-dim',
}

const dotColor: Record<PillVariant, string> = {
  live:    'bg-cyan',
  active:  'bg-emerald',
  draft:   'bg-violet',
  alert:   'bg-loss',
  warning: 'bg-warning',
  dim:     'bg-terminal-text-dim',
}

/**
 * Brand pill / badge — rounded-full, mono uppercase, tinted background.
 *
 * Variants: live (cyan) | active (emerald) | draft (violet) | alert (red) | warning | dim
 */
export function StatusPill({ label, variant = 'dim', dot = false, className }: StatusPillProps) {
  return (
    <span className={clsx(variantClass[variant], className)}>
      {dot && (
        <span
          className={clsx('inline-block w-1.5 h-1.5 rounded-full', dotColor[variant])}
          aria-hidden
        />
      )}
      {label}
    </span>
  )
}
