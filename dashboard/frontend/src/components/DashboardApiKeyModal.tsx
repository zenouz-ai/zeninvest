import { useState, useEffect } from 'react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { clearDashboardAuthRequired } from '../utils/authErrorBridge'

const LS_KEY = 'dashboard_api_key'

interface DashboardApiKeyModalProps {
  open: boolean
  onClose: () => void
}

export function DashboardApiKeyModal({ open, onClose }: DashboardApiKeyModalProps) {
  const [value, setValue] = useState('')
  const trapRef = useFocusTrap(open, onClose)

  useEffect(() => {
    if (!open) return
    try {
      setValue(localStorage.getItem(LS_KEY) ?? '')
    } catch {
      setValue('')
    }
  }, [open])

  if (!open) return null

  const save = () => {
    try {
      const trimmed = value.trim()
      if (trimmed) {
        localStorage.setItem(LS_KEY, trimmed)
      } else {
        localStorage.removeItem(LS_KEY)
      }
      clearDashboardAuthRequired()
      onClose()
      window.location.reload()
    } catch {
      /* ignore */
    }
  }

  const clearKey = () => {
    try {
      localStorage.removeItem(LS_KEY)
      setValue('')
      clearDashboardAuthRequired()
      onClose()
      window.location.reload()
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70"
      role="presentation"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="api-key-modal-title"
        className="w-full max-w-md rounded-lg border border-terminal-border bg-terminal-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="api-key-modal-title" className="text-lg font-semibold text-terminal-text tracking-wide">
          Dashboard API key
        </h2>
        <p className="mt-2 text-sm text-terminal-text-dim">
          Shared secret for this dashboard (not a personal password vault). Stored in{' '}
          <code className="text-xs text-accent">localStorage</code>. Build-time{' '}
          <code className="text-xs text-accent">VITE_API_KEY</code> overrides this when set.
        </p>
        <label htmlFor="dashboard-api-key-input" className="sr-only">
          API key
        </label>
        <input
          id="dashboard-api-key-input"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mt-4 w-full rounded border border-terminal-border bg-terminal-bg px-3 py-2 text-sm text-terminal-text focus:outline-none focus:ring-2 focus:ring-accent"
          placeholder="Paste key (matches DASHBOARD_API_KEY on server)"
        />
        <div className="mt-6 flex flex-wrap gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-terminal-border text-terminal-text hover:border-accent focus:outline-none focus:ring-2 focus:ring-neutral"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={clearKey}
            className="px-3 py-1.5 text-sm rounded text-loss hover:underline focus:outline-none focus:ring-2 focus:ring-neutral"
          >
            Clear stored key
          </button>
          <button
            type="button"
            onClick={save}
            className="px-3 py-1.5 text-sm rounded bg-accent text-terminal-bg font-medium hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-accent"
          >
            Save &amp; reload
          </button>
        </div>
      </div>
    </div>
  )
}
