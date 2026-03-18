import { useState, useEffect, useCallback, useRef } from 'react'

interface UseAsyncDataOptions {
  /** Refresh interval in ms. 0 = no auto-refresh. Default: 30000 */
  refreshInterval?: number
  /** Whether to fetch immediately on mount. Default: true */
  enabled?: boolean
}

interface UseAsyncDataResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
}

/**
 * Hook for independent async data loading with auto-refresh.
 * Each instance manages its own loading/error state so one failing
 * endpoint doesn't take down the whole page.
 */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: UseAsyncDataOptions = {}
): UseAsyncDataResult<T> {
  const { refreshInterval = 30_000, enabled = true } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchData = useCallback(async () => {
    if (!enabled) return
    try {
      const result = await fetcher()
      if (mountedRef.current) {
        setData(result)
        setError(null)
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

  useEffect(() => {
    mountedRef.current = true
    setLoading(true)
    fetchData()

    let interval: ReturnType<typeof setInterval> | undefined
    if (refreshInterval > 0) {
      interval = setInterval(fetchData, refreshInterval)
    }

    return () => {
      mountedRef.current = false
      if (interval) clearInterval(interval)
    }
  }, [...deps, fetchData, refreshInterval])

  return { data, loading, error, refetch: fetchData }
}
