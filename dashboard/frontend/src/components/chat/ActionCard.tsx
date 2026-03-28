import { StatusPill } from '../StatusPill'
import type { PillVariant } from '../StatusPill'
import type { ChatAction } from '../../types'

const STATUS_VARIANT: Record<string, PillVariant> = {
  awaiting_confirmation: 'warning',
  confirmed: 'live',
  executed: 'active',
  rejected: 'alert',
  expired: 'warning',
  executing: 'warning',
  draft: 'dim',
}

interface ActionCardProps {
  action: ChatAction
  onConfirm?: (actionId: number) => void
  onReject?: (actionId: number) => void
}

export function ActionCard({ action, onConfirm, onReject }: ActionCardProps) {
  const isPending = action.status === 'awaiting_confirmation'

  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-surface/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-terminal-text">
            {action.title || action.action_type}
          </p>
          {action.ticker && (
            <p className="mt-1 text-xs text-cyan">{action.ticker}</p>
          )}
        </div>
        <StatusPill
          variant={STATUS_VARIANT[action.status] || 'dim'}
          label={action.status.replace(/_/g, ' ')}
        />
      </div>

      {action.preview_text && (
        <p className="mt-2 text-xs text-terminal-text-muted leading-relaxed">
          {action.preview_text}
        </p>
      )}

      {action.rejection_reason && (
        <p className="mt-2 text-xs text-loss">
          {action.rejection_reason}
        </p>
      )}

      {isPending && (
        <div className="mt-3 flex gap-2">
          {onConfirm && (
            <button
              onClick={() => onConfirm(action.id)}
              className="rounded-lg bg-gain/20 px-4 py-1.5 text-xs font-medium text-gain transition-colors hover:bg-gain/30"
              aria-label={`Confirm ${action.title || action.action_type}`}
            >
              Confirm
            </button>
          )}
          {onReject && (
            <button
              onClick={() => onReject(action.id)}
              className="rounded-lg bg-loss/20 px-4 py-1.5 text-xs font-medium text-loss transition-colors hover:bg-loss/30"
              aria-label={`Reject ${action.title || action.action_type}`}
            >
              Reject
            </button>
          )}
        </div>
      )}
    </div>
  )
}
