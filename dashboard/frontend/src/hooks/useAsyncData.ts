import { useState, useEffect, useCallback, useRef } from 'react'
import { usePollingInterval } from './usePollingInterval'

interface UseAsyncDataOptions {
  /** Refresh interval in ms. 0 = no auto-refresh. Default: 0 */
  refreshInterval?: number
  /** Whether to fetch immediately on mount. Default: true */
  enabled?: boolean
}

interface UseAsyncDataResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  /** Timestamp of last successful fetch */
  lastUpdatedAt: Date | null
  /** True when data exists but the last fetch failed (showing stale data) */
  isStale: boolean
  refetch: () => void
}

/**
 * Hook for independent async data loading with auto-refresh.
 * Each instance manages its own loading/error state so one failing
 * endpoint doesn't take down the whole page.
 *
 * When a fetch fails but old data exists, the old data is preserved
 * and `isStale` is set to true.
 */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: UseAsyncDataOptions = {}
): UseAsyncDataResult<T> {
  const { refreshInterval = 0, enabled = true } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)
  const mountedRef = useRef(true)

  const fetchData = useCallback(async () => {
    if (!enabled) return
    try {
      const result = await fetcher()
      if (mountedRef.current) {
        setData(result)
        setError(null)
        setLastUpdatedAt(new Date())
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false)
      }
    }
  }, [fetcher, enabled])

  const pollingActive = usePollingInterval(enabled && refreshInterval > 0, fetchData)

  useEffect(() => {
    mountedRef.current = true
    setLoading(true)
    fetchData()

    let interval: ReturnType<typeof setInterval> | undefined
    if (refreshInterval > 0 && pollingActive) {
      interval = setInterval(fetchData, refreshInterval)
    }

    return () => {
      mountedRef.current = false
      if (interval) clearInterval(interval)
    }
  }, [...deps, fetchData, refreshInterval, pollingActive])

  const isStale = error != null && data != null

  return { data, loading, error, lastUpdatedAt, isStale, refetch: fetchData }
}
