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
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-start">
      <div>
        {eyebrow && (
          <p className="text-xs uppercase tracking-[0.22em] text-terminal-text-dim">
            {eyebrow}
          </p>
        )}
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <h1 className={`text-2xl font-bold ${eyebrow ? 'mt-1' : ''}`}>{title}</h1>
          {titleMeta && <div className="text-sm text-terminal-text-dim">{titleMeta}</div>}
        </div>
        <p className="text-terminal-text-dim text-sm mt-1 max-w-2xl">{description}</p>
      </div>
      <div className="flex items-center justify-start sm:justify-center lg:justify-end pointer-events-none select-none">
        <img
          src={hybridZBold}
          alt="ZENOUZ hybrid bold Z symbol"
          className="h-24 w-auto sm:h-28 lg:h-32 opacity-70 contrast-90 saturate-90"
        />
      </div>
    </div>
  )
}
