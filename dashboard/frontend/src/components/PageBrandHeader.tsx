import type { ReactNode } from 'react'
import hybridZBold from '../assets/hybrid-z-bold.svg'

type PageBrandHeaderProps = {
  title: string
  description: string
  eyebrow?: string
  titleMeta?: ReactNode
}

export function PageBrandHeader({ title, description, eyebrow, titleMeta }: PageBrandHeaderProps) {
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_240px] lg:items-start">
      <div className="space-y-3">
        {eyebrow && (
          <p className="label-mono tracking-[0.22em]">
            {eyebrow}
          </p>
        )}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-2">
            <h1 className={`text-3xl font-bold tracking-[-0.03em] sm:text-4xl lg:text-[2.8rem] ${eyebrow ? 'mt-1' : ''}`}>
              {title}
            </h1>
            <div className="h-px w-20 brand-gradient opacity-80" />
          </div>
          {titleMeta && <div className="pt-1 text-sm text-terminal-text-dim">{titleMeta}</div>}
        </div>
        <p className="max-w-3xl text-sm leading-6 text-terminal-text-muted sm:text-[0.98rem]">
          {description}
        </p>
      </div>
      <div className="pointer-events-none select-none">
        <div
          className="flex items-center justify-center rounded-hero border border-terminal-border-strong px-6 py-5"
          style={{
            background: `
              radial-gradient(circle at top, rgba(0, 212, 255, 0.16), transparent 45%),
              radial-gradient(circle at bottom left, rgba(99, 50, 255, 0.16), transparent 48%),
              rgba(14, 16, 28, 0.68)
            `,
            boxShadow: 'var(--shadow-panel)',
          }}
        >
          <img
            src={hybridZBold}
            alt="Graph Theory Z symbol"
            className="h-24 w-auto opacity-80 contrast-100 saturate-100 sm:h-28 lg:h-32"
          />
        </div>
      </div>
    </div>
  )
}
