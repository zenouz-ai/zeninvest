import { describe, expect, it } from 'vitest'
import { getNavigationItems } from './navigation'

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
      'Opportunity',
      'Order Mgmt',
      'Chat',
      'Evolution',
      'Costs',
    ])
  })

  it('keeps operator dashboard nav separate from the public overview', () => {
    const labels = getNavigationItems(true).map((item) => item.label)

    expect(labels).toContain('Dashboard')
    expect(labels).not.toContain('Overview')
  })
})
