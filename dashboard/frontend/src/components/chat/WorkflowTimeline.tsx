import type { ChatWorkflowStep } from '../../types'

interface WorkflowTimelineProps {
  steps: ChatWorkflowStep[]
  maxVisible?: number
}

function statusIcon(status: string): string {
  switch (status) {
    case 'completed':
      return '✓'
    case 'running':
      return '⟳'
    case 'failed':
      return '✗'
    default:
      return '·'
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'text-gain'
    case 'running':
      return 'text-cyan animate-pulse'
    case 'failed':
      return 'text-loss'
    default:
      return 'text-terminal-text-dim'
  }
}

export function WorkflowTimeline({ steps, maxVisible = 12 }: WorkflowTimelineProps) {
  const visible = steps.slice(-maxVisible)

  if (visible.length === 0) {
    return null
  }

  return (
    <div className="space-y-1.5">
      {visible.map((step) => (
        <div
          key={step.id}
          className="flex items-start gap-2 text-xs"
        >
          <span className={`mt-0.5 font-mono ${statusColor(step.status)}`}>
            {statusIcon(step.status)}
          </span>
          <div className="min-w-0 flex-1">
            <span className="text-terminal-text">{step.label || step.step_key}</span>
            {step.detail && (
              <p className="mt-0.5 text-terminal-text-dim line-clamp-2">{step.detail}</p>
            )}
            {step.model && (
              <span className="ml-1 text-[10px] text-terminal-text-dim">({step.model})</span>
            )}
          </div>
          {step.latency_ms != null && (
            <span className="shrink-0 text-[10px] text-terminal-text-dim">
              {step.latency_ms < 1000
                ? `${Math.round(step.latency_ms)}ms`
                : `${(step.latency_ms / 1000).toFixed(1)}s`}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
