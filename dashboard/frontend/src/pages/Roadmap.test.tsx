import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'
import {
  DELIVERED_COUNT,
  MILESTONES,
  PIPELINE_COUNT,
  PROGRESS_PCT,
} from '../data/roadmap'
import Roadmap, { getTimelineSections, resolveRoadmapTab } from './Roadmap'

function renderRoadmap(initialEntry = '/roadmap'): string {
  return renderToStaticMarkup(
    <StaticRouter location={initialEntry}>
      <Roadmap />
    </StaticRouter>
  )
}

describe('resolveRoadmapTab', () => {
  it('defaults to timeline for missing, legacy, and unknown tab params', () => {
    expect(resolveRoadmapTab(null)).toBe('timeline')
    expect(resolveRoadmapTab('timeline')).toBe('timeline')
    expect(resolveRoadmapTab('gantt')).toBe('timeline')
    expect(resolveRoadmapTab('unknown')).toBe('timeline')
  })

  it('keeps roadmap and architecture tabs addressable', () => {
    expect(resolveRoadmapTab('roadmap')).toBe('roadmap')
    expect(resolveRoadmapTab('architecture')).toBe('architecture')
  })
})

describe('Roadmap page rendering', () => {
  it('opens the redesigned timeline board by default', () => {
    const markup = renderRoadmap('/roadmap')

    expect(markup).toContain('data-testid="timeline-board"')
    expect(markup).toContain('Short-cycle roadmap by work stream')
    expect(markup).not.toContain('data-testid="roadmap-detail-view"')
    expect(markup).not.toContain('gantt')
  })

  it('treats tab=gantt as a backward-compatible alias to the timeline view', () => {
    const markup = renderRoadmap('/roadmap?tab=gantt')

    expect(markup).toContain('data-testid="timeline-board"')
    expect(markup).toContain('Timeline')
    expect(markup).not.toContain('data-testid="architecture-view"')
  })

  it('renders the detailed roadmap tab and architecture tab when requested', () => {
    const roadmapMarkup = renderRoadmap('/roadmap?tab=roadmap')
    const architectureMarkup = renderRoadmap('/roadmap?tab=architecture')

    expect(roadmapMarkup).toContain('data-testid="roadmap-detail-view"')
    expect(roadmapMarkup).toContain('Readable story cards with factual history')
    expect(architectureMarkup).toContain('data-testid="architecture-view"')
    expect(architectureMarkup).toContain('Readable flow from signals to execution')
    expect(architectureMarkup).toContain('docs/ARCHITECTURE.md')
    expect(architectureMarkup).not.toContain('<svg')
  })

  it('renders one uniform timeline card per milestone with factual delivered dates and short-cycle planned windows', () => {
    const markup = renderRoadmap('/roadmap')
    const cardCount = markup.match(/data-uniform-card="true"/g)?.length ?? 0

    expect(cardCount).toBe(MILESTONES.length)
    expect(markup).toContain('23 Mar 2026')
    expect(markup).toContain('2 days')
    expect(markup).not.toContain('<svg')
  })
})

describe('timeline section grouping', () => {
  it('places every milestone exactly once in the correct topic section', () => {
    const sections = getTimelineSections()
    const seen = new Set<string>()

    for (const section of sections) {
      for (const column of ['Delivered', 'Next', 'Soon', 'Later'] as const) {
        for (const milestone of section.columns[column]) {
          expect(seen.has(milestone.id)).toBe(false)
          seen.add(milestone.id)
          expect(milestone.topic).toBe(section.topic)
        }
      }
    }

    expect(seen.size).toBe(MILESTONES.length)
  })

  it('keeps pipeline milestones in their configured horizon buckets', () => {
    const sections = getTimelineSections()
    const calibration = sections.find((section) => section.topic === 'Calibration')
    const hardening = sections.find((section) => section.topic === 'Hardening')

    expect(calibration?.columns.Next.map((milestone) => milestone.id)).toContain('US-2.4')
    expect(calibration?.columns.Soon.map((milestone) => milestone.id)).toContain('US-2.1')
    expect(calibration?.columns.Later.map((milestone) => milestone.id)).toContain('US-2.2')
    expect(hardening?.columns.Next.map((milestone) => milestone.id)).toContain('US-7.5')
    expect(hardening?.columns.Soon.map((milestone) => milestone.id)).toContain('US-7.3')
  })

  it('preserves roadmap counts after the redesign', () => {
    expect(DELIVERED_COUNT + PIPELINE_COUNT).toBe(MILESTONES.length)
    expect(PROGRESS_PCT).toBe(Math.round((DELIVERED_COUNT / MILESTONES.length) * 100))
  })
})
