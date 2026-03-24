/**
 * Bridges protected API 401/403 responses to React without importing React here.
 * App subscribes via useSyncExternalStore or a small hook wrapper.
 */

let authRequired = false
const listeners = new Set<() => void>()

export function getDashboardAuthRequired(): boolean {
  return authRequired
}

export function setDashboardAuthRequired(value: boolean): void {
  if (authRequired === value) return
  authRequired = value
  listeners.forEach((fn) => fn())
}

export function clearDashboardAuthRequired(): void {
  setDashboardAuthRequired(false)
}

export function subscribeDashboardAuth(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
