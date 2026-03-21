import { describe, expect, it } from 'vitest'
import { drainSseBuffer, extractDataPayload, reconnectDelayMs } from './sseStream'

describe('extractDataPayload', () => {
  it('returns null for comment-only blocks', () => {
    expect(extractDataPayload(': keepalive')).toBeNull()
  })

  it('parses single data line', () => {
    expect(extractDataPayload('data: {"a":1}')).toBe('{"a":1}')
  })

  it('joins multi-line data fields per SSE spec', () => {
    const block = 'data: {"part":\ndata: "two"}'
    expect(extractDataPayload(block)).toBe('{"part":\n"two"}')
  })
})

describe('drainSseBuffer', () => {
  it('returns remainder when no complete event', () => {
    const { buffer, dataJsonStrings } = drainSseBuffer('', 'data: {"x":1}')
    expect(dataJsonStrings).toEqual([])
    expect(buffer).toBe('data: {"x":1}')
  })

  it('drains one complete event and keeps partial tail', () => {
    const chunk = 'data: {"ok":true}\n\ndata: {"in'
    const { buffer, dataJsonStrings } = drainSseBuffer('', chunk)
    expect(dataJsonStrings).toEqual(['{"ok":true}'])
    expect(buffer).toBe('data: {"in')
  })

  it('ignores keepalive-only blocks', () => {
    const { buffer, dataJsonStrings } = drainSseBuffer('', ': keepalive\n\n')
    expect(dataJsonStrings).toEqual([])
    expect(buffer).toBe('')
  })

  it('accumulates across chunks', () => {
    let buf = ''
    let all: string[] = []
    ;({ buffer: buf, dataJsonStrings: all } = drainSseBuffer(buf, 'data: {"a":'))
    expect(all).toEqual([])
    ;({ buffer: buf, dataJsonStrings: all } = drainSseBuffer(buf, '1}\n\n'))
    expect(all).toEqual(['{"a":1}'])
    expect(buf).toBe('')
  })
})

describe('reconnectDelayMs', () => {
  it('stays within expected bounds for low attempts', () => {
    for (let i = 0; i < 20; i++) {
      const d = reconnectDelayMs(0, 1000, 30_000)
      expect(d).toBeGreaterThanOrEqual(750)
      expect(d).toBeLessThanOrEqual(1000)
    }
  })

  it('respects max cap for large attempts', () => {
    for (let i = 0; i < 10; i++) {
      const d = reconnectDelayMs(20, 1000, 30_000)
      expect(d).toBeLessThanOrEqual(30_000)
      expect(d).toBeGreaterThan(0)
    }
  })
})
