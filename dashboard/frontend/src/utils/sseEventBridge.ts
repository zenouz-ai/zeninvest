import type { Event } from '../types'

type SseHandler = (event: Event) => void

const handlers = new Set<SseHandler>()

/** Register a dashboard SSE listener (e.g. Chat page). Returns unsubscribe. */
export function subscribeDashboardSse(handler: SseHandler): () => void {
  handlers.add(handler)
  return () => {
    handlers.delete(handler)
  }
}

/** Dispatch an SSE event to all registered listeners. */
export function dispatchDashboardSse(event: Event): void {
  handlers.forEach((handler) => {
    try {
      handler(event)
    } catch {
      // ignore listener errors
    }
  })
}
