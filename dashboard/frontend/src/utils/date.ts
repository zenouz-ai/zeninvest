import { format, isValid } from 'date-fns'

/** Safely format a date string; returns fallback for null/undefined/invalid. */
export function safeFormat(
  ts: string | undefined | null,
  fmt: string,
  fallback = '—'
): string {
  if (!ts) return fallback
  const d = new Date(ts)
  return isValid(d) ? format(d, fmt) : fallback
}
