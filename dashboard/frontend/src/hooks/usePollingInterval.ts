import { useEffect, useRef, useState } from 'react'

/**
 * Returns whether polling should run (tab visible) and registers a callback
 * to run immediately when the tab becomes visible again.
 */
export function usePollingInterval(enabled: boolean, onResume?: () => void) {
  const [active, setActive] = useState(() =>
    typeof document === 'undefined' ? true : document.visibilityState !== 'hidden',
  )
  const onResumeRef = useRef(onResume)

  useEffect(() => {
    onResumeRef.current = onResume
  }, [onResume])

  useEffect(() => {
    if (!enabled || typeof document === 'undefined') return

    const handleVisibility = () => {
      const visible = document.visibilityState !== 'hidden'
      setActive(visible)
      if (visible) {
        onResumeRef.current?.()
      }
    }

    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [enabled])

  return active
}

/**
 * Run fn once after idle (or after a short timeout when idle is unavailable).
 */
export function runWhenIdle(fn: () => void, timeoutMs = 1500): () => void {
  if (typeof window === 'undefined') {
    fn()
    return () => {}
  }
  if (typeof window.requestIdleCallback === 'function') {
    const id = window.requestIdleCallback(fn, { timeout: timeoutMs })
    return () => window.cancelIdleCallback(id)
  }
  const id = window.setTimeout(fn, 100)
  return () => window.clearTimeout(id)
}
