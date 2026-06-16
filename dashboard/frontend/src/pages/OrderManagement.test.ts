import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), 'OrderManagement.tsx'),
  'utf8',
)

describe('OrderManagement polling', () => {
  it('does not pass reconcile_pending true on interval poll', () => {
    expect(source).toContain('fetchData(false)')
    expect(source).toContain('await fetchData(true)')
    expect(source).not.toMatch(/setInterval\([^)]*fetchData\(true\)/)
    expect(source).not.toMatch(/setInterval\([^)]*reconcile_pending:\s*true/)
  })
})
