/**
 * @vitest-environment happy-dom
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { usePollingInterval } from './usePollingInterval'

describe('usePollingInterval', () => {
  beforeEach(() => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
      writable: true,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns true when enabled and tab visible', () => {
    const { result } = renderHook(() => usePollingInterval(true))
    expect(result.current).toBe(true)
  })

  it('invokes resume callback when tab becomes visible', () => {
    let visibility: DocumentVisibilityState = 'hidden'
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => visibility,
    })

    const onResume = vi.fn()
    renderHook(() => usePollingInterval(true, onResume))

    act(() => {
      visibility = 'visible'
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(onResume).toHaveBeenCalledTimes(1)
  })
})
