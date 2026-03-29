import { Link } from 'react-router-dom'
import { Panel } from './Panel'
import { StatusPill, type PillVariant } from './StatusPill'

const VARIANT_MAP: Record<'live' | 'preview' | 'signin', PillVariant> = {
  live: 'live',
  preview: 'draft',
  signin: 'warning',
}

const LABEL_MAP: Record<'live' | 'preview' | 'signin', string> = {
  live: 'Live Public Data',
  preview: 'Preview Only',
  signin: 'Operator Sign-In Required',
}

export function PublicPageBanner({
  mode,
  message,
}: {
  mode: 'live' | 'preview' | 'signin'
  message: string
}) {
  return (
    <Panel className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="space-y-2">
        <StatusPill label={LABEL_MAP[mode]} variant={VARIANT_MAP[mode]} dot />
        <p className="max-w-3xl text-sm leading-6 text-terminal-text-dim">{message}</p>
      </div>
      <Link to="/login" className="btn-secondary w-fit">
        Operator sign in
      </Link>
    </Panel>
  )
}
