import { type ReactNode } from 'react'
import { clsx } from 'clsx'

interface PanelProps {
  children: ReactNode
  /** Hero panels get cyan/violet atmospheric glow and stronger border */
  hero?: boolean
  className?: string
}

/**
 * Glass-dark surface panel — primary layout primitive.
 *
 * Regular: glass-dark card, 1.5rem radius, panel shadow.
 * Hero: deeper glass, atmospheric cyan/violet glow, 2rem radius — for key decision areas.
 */
export function Panel({ children, hero = false, className }: PanelProps) {
  return (
    <div
      className={clsx('animate-fade-up', className)}
      style={
        hero
          ? {
              border: '1px solid var(--color-border-strong)',
              background: `
                radial-gradient(ellipse at top left, rgba(99, 50, 255, 0.08), transparent 50%),
                radial-gradient(circle at top right, rgba(0, 212, 255, 0.06), transparent 40%),
                rgba(14, 16, 28, 0.92)
              `,
              boxShadow: 'var(--shadow-glow-strong)',
              borderRadius: 'var(--radius-lg)',
              padding: 'var(--space-6)',
            }
          : {
              border: '1px solid var(--color-border)',
              background: `
                radial-gradient(circle at top, rgba(255, 255, 255, 0.06), transparent 42%),
                rgba(14, 16, 28, 0.86)
              `,
              boxShadow: 'var(--shadow-panel)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-5)',
              transition: 'box-shadow var(--transition-base)',
            }
      }
    >
      {children}
    </div>
  )
}
