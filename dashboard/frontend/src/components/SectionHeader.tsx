import { clsx } from 'clsx'

interface SectionHeaderProps {
  /** Mono uppercase eyebrow line above the title */
  eyebrow?: string
  /** Main section title — rendered in Syne */
  title: string
  /** Optional supporting subtitle */
  subtitle?: string
  className?: string
}

/**
 * Section heading — optional mono eyebrow, Syne title, muted subtitle.
 *
 * Use for page sections, table headers, and panel titles.
 * For page-level titles use a larger clamp size directly.
 */
export function SectionHeader({ eyebrow, title, subtitle, className }: SectionHeaderProps) {
  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      {eyebrow && (
        <span className="label-mono">{eyebrow}</span>
      )}
      <h2
        className="text-xl font-semibold text-terminal-text leading-snug"
        style={{ fontFamily: 'var(--font-heading)' }}
      >
        {title}
      </h2>
      {subtitle && (
        <p className="text-sm text-terminal-text-dim leading-relaxed">{subtitle}</p>
      )}
    </div>
  )
}
