import { describe, expect, it } from 'vitest'
import { getNavigationItems, getNavLabel } from './navigation'

describe('navigation', () => {
  it('shows the full public product surface to anonymous users', () => {
    const labels = getNavigationItems(false).map((item) => item.label)

    expect(labels).toEqual([
      'Overview',
      'Universe',
      'Portfolio',
      'Runs',
      'World News',
      'Roadmap',
      'Insights',
      'Opportunity',
      'Order Mgmt',
      'Chat',
      'Evolution',
      'Costs & Latency',
    ])
  })

  it('keeps operator dashboard nav separate from the public overview', () => {
    const labels = getNavigationItems(true).map((item) => item.label)

    expect(labels).toContain('Dashboard')
    expect(labels).not.toContain('Overview')
  })

  it('uses Costs & Latency nav label for public and operator', () => {
    const publicItem = getNavigationItems(false).find((item) => item.to === '/costs')
    const operatorItem = getNavigationItems(true).find((item) => item.to === '/costs')
    expect(publicItem?.label).toBe('Costs & Latency')
    expect(operatorItem?.label).toBe('Costs & Latency')
    expect(getNavLabel(publicItem!, false)).toBe('Costs & Latency')
    expect(getNavLabel(operatorItem!, true)).toBe('Costs & Latency')
  })
})
