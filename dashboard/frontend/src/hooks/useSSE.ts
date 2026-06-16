import { useEffect, useRef, useState } from 'react'
import type { Event } from '../types'
import { clearDashboardAuthRequired, setDashboardAuthRequired } from '../utils/authErrorBridge'
import { dispatchDashboardSse } from '../utils/sseEventBridge'
import { drainSseBuffer, reconnectDelayMs } from '../utils/sseStream'

export type SseConnectionState = 'connecting' | 'open' | 'disconnected'

interface UseSSEOptions {
  enabled?: boolean
  onEvent?: (event: Event) => void
  /** Bump to force a new stream connection (e.g. after Retry from auth banner). */
  reconnectNonce?: number
}

const DISCONNECT_ALERT_MS = 10_000

export function useSSE(options: UseSSEOptions = {}) {
  const { enabled = true, onEvent, reconnectNonce = 0 } = options
  const [events, setEvents] = useState<Event[]>([])
  const [connectionState, setConnectionState] = useState<SseConnectionState>(enabled ? 'connecting' : 'disconnected')
  const [error, setError] = useState<Error | null>(null)
  const [sseDisconnectedAlert, setSseDisconnectedAlert] = useState(false)

  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!enabled) {
      setSseDisconnectedAlert(false)
      return
    }
    if (connectionState === 'open' || connectionState === 'connecting') {
      setSseDisconnectedAlert(false)
      return
    }
    const started = Date.now()
    const tick = () => {
      setSseDisconnectedAlert(Date.now() - started >= DISCONNECT_ALERT_MS)
    }
    tick()
    const id = window.setInterval(tick, 2000)
    return () => window.clearInterval(id)
  }, [connectionState, enabled])

  useEffect(() => {
    if (!enabled) {
      setConnectionState('disconnected')
      return
    }

    let cancelled = false
    let reconnectAttempt = 0
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let abort: AbortController | null = null

    const API_BASE = import.meta.env.VITE_API_URL ?? ''
    const streamUrl = API_BASE ? `${API_BASE}/api/events/stream` : '/api/events/stream'

    const runOneConnection = async () => {
      if (cancelled) return
      setConnectionState('connecting')
      setError(null)
      abort = new AbortController()
      const headers: Record<string, string> = { Accept: 'text/event-stream' }

      let res: Response
      try {
        res = await fetch(streamUrl, {
          headers,
          signal: abort.signal,
          credentials: 'include',
        })
      } catch (e) {
        if (cancelled || abort.signal.aborted) return
        setConnectionState('disconnected')
        setError(e instanceof Error ? e : new Error('SSE fetch failed'))
        scheduleReconnect()
        return
      }

      if (!res.ok) {
        if (cancelled || abort.signal.aborted) return
        setConnectionState('disconnected')
        setError(new Error(`SSE HTTP ${res.status}`))
        if (res.status === 401 || res.status === 403) {
          setDashboardAuthRequired(true)
          return
        }
        scheduleReconnect()
        return
      }

      const body = res.body
      if (!body) {
        if (cancelled || abort.signal.aborted) return
        setConnectionState('disconnected')
        setError(new Error('SSE response has no body'))
        scheduleReconnect()
        return
      }

      setConnectionState('open')
      reconnectAttempt = 0
      clearDashboardAuthRequired()

      const reader = body.getReader()
      const decoder = new TextDecoder()
      let sseBuf = ''

      try {
        while (!cancelled) {
          const { done, value } = await reader.read()
          if (done) break
          const chunk = decoder.decode(value, { stream: true })
          const drained = drainSseBuffer(sseBuf, chunk)
          sseBuf = drained.buffer

          for (const jsonStr of drained.dataJsonStrings) {
            let data: Record<string, unknown>
            try {
              data = JSON.parse(jsonStr) as Record<string, unknown>
            } catch {
              continue
            }
            if (data.timestamp && data.event_type) {
              const event = data as unknown as Event
              setEvents((prev) => [event, ...prev].slice(0, 100))
              onEventRef.current?.(event)
              dispatchDashboardSse(event)
            }
          }
        }
      } catch (e) {
        if (cancelled || abort.signal.aborted) return
        setError(e instanceof Error ? e : new Error('SSE read error'))
      } finally {
        try {
          reader.releaseLock()
        } catch {
          /* ignore */
        }
      }

      if (cancelled) return
      setConnectionState('disconnected')
      scheduleReconnect()
    }

    function scheduleReconnect() {
      if (cancelled) return
      const delay = reconnectDelayMs(reconnectAttempt)
      reconnectAttempt += 1
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        void runOneConnection()
      }, delay)
    }

    void runOneConnection()

    return () => {
      cancelled = true
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      abort?.abort()
      setConnectionState('disconnected')
    }
  }, [enabled, reconnectNonce])

  return {
    events,
    connectionState,
    /** True when `open` — same as legacy `isConnected`. */
    isConnected: connectionState === 'open',
    sseDisconnectedAlert,
    error,
  }
}
