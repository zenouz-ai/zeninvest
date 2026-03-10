import { useEffect, useRef, useState } from 'react'
import type { Event } from '../types'

interface UseSSEOptions {
  enabled?: boolean
  onEvent?: (event: Event) => void
}

export function useSSE(options: UseSSEOptions = {}) {
  const { enabled = true, onEvent } = options
  const [events, setEvents] = useState<Event[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!enabled) {
      return
    }

    const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    const eventSource = new EventSource(`${API_BASE_URL}/api/events/stream`)

    eventSource.onopen = () => {
      setIsConnected(true)
      setError(null)
    }

    eventSource.onmessage = (e) => {
      try {
        const event: Event = JSON.parse(e.data)
        setEvents((prev) => [event, ...prev].slice(0, 100)) // Keep last 100 events
        onEvent?.(event)
      } catch (err) {
        console.error('Failed to parse SSE event:', err)
      }
    }

    eventSource.onerror = (err) => {
      console.error('SSE error:', err)
      setError(new Error('SSE connection error'))
      setIsConnected(false)
      // Attempt to reconnect after 3 seconds
      setTimeout(() => {
        if (eventSource.readyState === EventSource.CLOSED) {
          eventSource.close()
          eventSourceRef.current = null
        }
      }, 3000)
    }

    eventSourceRef.current = eventSource

    return () => {
      eventSource.close()
      eventSourceRef.current = null
      setIsConnected(false)
    }
  }, [enabled, onEvent])

  return { events, isConnected, error }
}
