import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'
import type { PublicPortfolioHistoryPoint, PublicPortfolioSnapshot } from '../types'
import { PublicPortfolioPage } from './PublicPortfolio'

function renderPublicPortfolio(snapshot: PublicPortfolioSnapshot, history: PublicPortfolioHistoryPoint[]) {
  return renderToStaticMarkup(
    <StaticRouter location="/portfolio">
      <PublicPortfolioPage initialSnapshot={snapshot} initialHistory={history} />
    </StaticRouter>
  )
}

describe('PublicPortfolio page', () => {
  it('renders a sanitized portfolio surface without private operator actions', () => {
    const snapshot: PublicPortfolioSnapshot = {
      timestamp: '2026-03-29T12:00:00Z',
      num_positions: 8,
      positions_visible: 2,
      cash_pct: 24.5,
      invested_pct: 75.5,
      value_index: 118.2,
      pnl_band: 'Outperforming',
      positions: [
        {
          ticker: 'NVDA',
          sector: 'Technology',
          allocation_pct: 12.4,
          pnl_band: 'Outperforming',
          protection_status: 'Protected',
        },
        {
          ticker: 'MSFT',
          sector: 'Technology',
          allocation_pct: 10.1,
          pnl_band: 'Range Bound',
          protection_status: 'Needs Lock',
        },
      ],
      sector_allocations: [
        { sector: 'Technology', allocation_pct: 34.2 },
        { sector: 'Healthcare', allocation_pct: 12.1 },
      ],
      protection_summary: {
        protected_count: 3,
        needs_lock_count: 2,
        exit_required_count: 1,
        inactive_count: 2,
      },
    }
    const history: PublicPortfolioHistoryPoint[] = [
      { timestamp: '2026-03-27T12:00:00Z', value_index: 100.0 },
      { timestamp: '2026-03-28T12:00:00Z', value_index: 109.5 },
      { timestamp: '2026-03-29T12:00:00Z', value_index: 118.2 },
    ]

    const markup = renderPublicPortfolio(snapshot, history)

    expect(markup).toContain('Visible Holdings')
    expect(markup).toContain('Normalized Value History')
    expect(markup).toContain('Live Public Data')
    expect(markup).not.toContain('Force Sell')
    expect(markup).not.toContain('Actions')
    expect(markup).not.toContain('total_value_gbp')
  })
})
