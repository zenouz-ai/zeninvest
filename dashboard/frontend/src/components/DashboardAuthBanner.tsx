import { clearDashboardAuthRequired } from '../utils/authErrorBridge'

interface DashboardAuthBannerProps {
  /** Increment so useSSE reconnects after operator fixes the key without full reload. */
  onRetry: () => void
  /** Open API key modal (Phase 2). */
  onOpenApiKey: () => void
}

export function DashboardAuthBanner({ onRetry, onOpenApiKey }: DashboardAuthBannerProps) {
  return (
    <div
      className="border-b border-loss/50 bg-loss/15 px-4 py-3"
      role="alert"
      aria-live="polite"
    >
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="text-sm text-terminal-text">
          <p className="font-semibold text-loss">Dashboard API access denied (403)</p>
          <p className="mt-1 text-terminal-text-dim">
            The server requires a valid <code className="text-accent">X-API-Key</code> matching{' '}
            <code className="text-accent">DASHBOARD_API_KEY</code>. Set{' '}
            <code className="text-xs bg-terminal-bg px-1 rounded">VITE_API_KEY</code> at build time, or use{' '}
            <strong className="text-terminal-text">API key</strong> in the nav to store a key in the browser
            (shared secret — same XSS exposure as today).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={onOpenApiKey}
            className="px-3 py-1.5 text-sm rounded bg-accent text-terminal-bg font-medium hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-accent"
          >
            API key…
          </button>
          <button
            type="button"
            onClick={() => {
              clearDashboardAuthRequired()
              onRetry()
            }}
            className="px-3 py-1.5 text-sm rounded border border-terminal-border text-terminal-text hover:border-accent focus:outline-none focus:ring-2 focus:ring-neutral"
          >
            Retry
          </button>
          <button
            type="button"
            onClick={() => clearDashboardAuthRequired()}
            className="px-3 py-1.5 text-sm text-terminal-text-dim hover:text-terminal-text focus:outline-none focus:ring-2 focus:ring-neutral rounded"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}
