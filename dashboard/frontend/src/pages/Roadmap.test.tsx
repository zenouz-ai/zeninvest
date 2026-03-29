import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it } from 'vitest'
import {
  DELIVERED_COUNT,
  MILESTONES,
  PIPELINE_COUNT,
  PROGRESS_PCT,
  TOTAL_COUNT,
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
    expect(markup).toContain('Safety first, evidence before adaptation')
    expect(markup).toContain('Delivered')
    expect(markup).toContain('Pipeline')
    expect(markup).toContain('Total')
    expect(markup).toContain('Delivered Progress')
    expect(markup).not.toContain('<div class="text-sm text-terminal-text-dim">Partial</div>')
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
    expect(roadmapMarkup).toContain('Track bundle:')
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
    const foundation = sections.find((section) => section.topic === 'Foundation')

    expect(foundation?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-1.9')
    expect(foundation?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-1.7.1')
    expect(foundation?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-1.7.2')
    expect(calibration?.columns.Later.map((milestone) => milestone.id)).toContain('US-2.4')
    expect(calibration?.columns.Later.map((milestone) => milestone.id)).toContain('US-2.2')
    expect(calibration?.columns.Later.map((milestone) => milestone.id)).toContain('US-2.1')
    expect(hardening?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-7.5')
    expect(hardening?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-7.3')
    expect(hardening?.columns.Delivered.map((milestone) => milestone.id)).toContain('US-7.2')
  })

  it('preserves roadmap counts after the redesign', () => {
    expect(DELIVERED_COUNT + PIPELINE_COUNT).toBe(TOTAL_COUNT)
    expect(TOTAL_COUNT).toBe(MILESTONES.length)
    expect(PROGRESS_PCT).toBe(Math.round((DELIVERED_COUNT / TOTAL_COUNT) * 100))
    expect(DELIVERED_COUNT).toBe(33)
    expect(PIPELINE_COUNT).toBe(17)
    expect(TOTAL_COUNT).toBe(50)
    expect(PROGRESS_PCT).toBe(66)
    expect(MILESTONES.find((milestone) => milestone.id === 'US-1.10')?.status).toBe('delivered')
    expect(MILESTONES.find((milestone) => milestone.id === 'US-1.10')?.name).toBe('Evolution Planner Phase 1')
  })
})
