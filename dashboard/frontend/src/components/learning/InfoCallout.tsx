import { Link } from 'react-router-dom'

interface InfoCalloutProps {
  why: string
  freshAsOf?: string | null
  freshSource?: string
  action?: string
  roadmapId?: string
}

export function InfoCallout({ why, freshAsOf, freshSource, action, roadmapId }: InfoCalloutProps) {
  return (
    <div className="rounded-panel border border-terminal-border/80 bg-terminal-surface/60 px-3 py-2 text-xs text-terminal-text-muted space-y-1 mb-3">
      <p>
        <span className="text-terminal-text-dim uppercase tracking-wide mr-1">Why:</span>
        {why}
        {roadmapId ? (
          <>
            {' '}
            <Link to={`/roadmap?tab=roadmap`} className="text-cyan hover:underline">
              {roadmapId}
            </Link>
          </>
        ) : null}
      </p>
      {freshAsOf ? (
        <p>
          <span className="text-terminal-text-dim uppercase tracking-wide mr-1">Fresh as of:</span>
          {freshAsOf}
          {freshSource ? ` · ${freshSource}` : ''}
        </p>
      ) : freshSource ? (
        <p>
          <span className="text-terminal-text-dim uppercase tracking-wide mr-1">Source:</span>
          {freshSource}
        </p>
      ) : null}
      {action ? (
        <p>
          <span className="text-terminal-text-dim uppercase tracking-wide mr-1">Action:</span>
          <code className="text-terminal-text">{action}</code>
        </p>
      ) : null}
    </div>
  )
}
