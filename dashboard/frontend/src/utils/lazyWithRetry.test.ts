import { describe, expect, it } from 'vitest'
import { isChunkLoadError } from './lazyWithRetry'

describe('isChunkLoadError', () => {
  it('detects Safari chunk load failures', () => {
    expect(isChunkLoadError(new Error('Importing a module script failed.'))).toBe(true)
    expect(isChunkLoadError(new Error('Failed to fetch dynamically imported module'))).toBe(true)
    expect(isChunkLoadError(new Error('Loading chunk 123 failed.'))).toBe(true)
  })

  it('ignores unrelated errors', () => {
    expect(isChunkLoadError(new Error('Network Error'))).toBe(false)
    expect(isChunkLoadError('bad')).toBe(false)
  })
})
