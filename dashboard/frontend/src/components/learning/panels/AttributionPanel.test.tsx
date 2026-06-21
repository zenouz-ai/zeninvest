// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

const getCommitteeDebateHealth = vi.fn()
const getCommitteeEvaluation = vi.fn()
const getResearchEvaluation = vi.fn()

vi.mock('../../../api/client', () => ({
  learningApi: {
    getCommitteeEvaluation: () => getCommitteeEvaluation(),
    getResearchEvaluation: () => getResearchEvaluation(),
    getCommitteeDebateHealth: () => getCommitteeDebateHealth(),
  },
}))

import { AttributionPanel } from './AttributionPanel'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const DEBATE_HEALTH = {
  days: 30,
  total_decisions: 12,
  debate_participation_rate: 1,
  debate_churn_rate: 0.25,
  per_moderator_churn: { 'gpt-4o': { n: 12, churn_rate: 0.33 } },
  rounds_distribution: { '2': 12 },
  consensus_mix: { APPROVED: 8, CAUTION: 4 },
  skeptic_tool_calls: 5,
  moderation_cost_gbp: 0.21,
}

describe('AttributionPanel committee debate health', () => {
  it('renders live debate health even below the 200-trade gate', async () => {
    getCommitteeDebateHealth.mockResolvedValue(DEBATE_HEALTH)
    getCommitteeEvaluation.mockResolvedValue(null)
    getResearchEvaluation.mockResolvedValue(null)

    render(<MemoryRouter><AttributionPanel closedTrades={10} /></MemoryRouter>)

    const section = await screen.findByTestId('committee-debate-health')
    expect(section).toBeTruthy()
    await waitFor(() => expect(section.textContent).toContain('verdict churn'))
    expect(section.textContent).toContain('skeptic tool calls: 5')
    expect(section.textContent).toContain('APPROVED: 8')
  })

  it('shows an empty hint when no decisions are in the window', async () => {
    getCommitteeDebateHealth.mockResolvedValue({ ...DEBATE_HEALTH, total_decisions: 0 })
    getCommitteeEvaluation.mockResolvedValue(null)
    getResearchEvaluation.mockResolvedValue(null)

    render(<MemoryRouter><AttributionPanel closedTrades={10} /></MemoryRouter>)

    const section = await screen.findByTestId('committee-debate-health')
    await waitFor(() => expect(section.textContent).toContain('No moderated decisions in the window yet'))
  })
})
