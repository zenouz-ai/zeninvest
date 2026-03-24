import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import {
  MILESTONES,
  TOPICS,
  PROJECT_START,
  DELIVERED_COUNT,
  PIPELINE_COUNT,
  PROGRESS_PCT,
  type Horizon,
  type Milestone,
  type Topic,
} from '../data/roadmap'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { StatusPill, type PillVariant } from '../components/StatusPill'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

type TabId = 'timeline' | 'roadmap' | 'architecture'
type TimelineColumnId = 'Delivered' | Horizon
type TimelineSection = {
  topic: Topic
  columns: Record<TimelineColumnId, Milestone[]>
}

const TIMELINE_COLUMNS: TimelineColumnId[] = ['Delivered', 'Next', 'Soon', 'Later']
const HORIZON_ORDER: Horizon[] = ['Next', 'Soon', 'Later']

const ARCHITECTURE_MERMAID = `
graph TB
    subgraph Ext["External APIs"]
        YF[yfinance<br/>OHLCV + Fundamentals]
        FH[Finnhub<br/>Analyst + Insider]
        AV[Alpha Vantage<br/>News + Sector]
        BRAVE[Brave Search<br/>+ Answers]
        TAVILY[Tavily<br/>fallback]
        SEC[SEC EDGAR<br/>filings]
        T212[Trading 212<br/>Practice API]
    end

    subgraph Data["Market Data - US-4.1, 4.2, 4.3, 4.5"]
        DF[Data Fetcher]
        UNIV[Universe Screener]
        MACRO[Macro Intelligence]
        PROMACRO[Proactive Macro Scan<br/>US-4.5 daily regime]
        FALLBACK[Web Search Fallback<br/>Brave Tavily]
    end

    subgraph LLM["LLM Providers"]
        ANTH[Anthropic<br/>Claude]
        OAI[OpenAI<br/>GPT-4o]
        GOOG[Google<br/>Gemini]
    end

    subgraph Research["Agentic Research - US-4.4"]
        REXEC["ResearchExecutor<br/>5 tools, shared budget 35/cycle"]
    end

    subgraph Strategy["Strategy Engine - US-2.1, 2.2, 4.4"]
        CLAUDE[Claude Synthesis<br/>+ Research tools]
    end

    subgraph Mod["Moderation - US-2.3, 4.4"]
        GPT4O[GPT-4o Skeptic<br/>+ Research tools]
        GEMRISK[Gemini Risk<br/>+ Research tools]
        CONS[Consensus]
    end

    subgraph RiskRules["Risk Agent - US-3.2, 3.3"]
        RULES["11 Hard Rules VETO"]
    end

    subgraph Opp["UOV - US-3.4"]
        UOV[Scorer + Optimizer]
    end

    subgraph Exec["Order Mgmt - US-3.5, 3.1"]
        OM["Order Manager<br/>+ retry"]
        SL["Stop-Loss Manager<br/>trailing + ATR"]
    end

    subgraph Out["Output"]
        JOUR[Trade Journal]
    end

    YF --> DF
    FH --> DF
    AV --> DF
    AV --> MACRO
    FH --> MACRO
    BRAVE --> REXEC
    TAVILY --> REXEC
    SEC --> REXEC
    BRAVE --> FALLBACK
    TAVILY --> FALLBACK
    BRAVE --> UNIV
    TAVILY --> UNIV

    DF --> UNIV
    DF --> CLAUDE
    MACRO --> CLAUDE
    PROMACRO --> CLAUDE
    PROMACRO --> CONS
    FALLBACK --> CLAUDE

    REXEC --> CLAUDE
    REXEC --> GPT4O
    REXEC --> GEMRISK

    ANTH --> CLAUDE
    CLAUDE --> GPT4O
    CLAUDE --> GEMRISK
    OAI --> GPT4O
    GOOG --> GEMRISK
    GPT4O --> CONS
    GEMRISK --> CONS

    CONS --> RULES
    RULES --> UOV
    UOV --> OM
    OM --> T212
    OM --> SL
    OM --> JOUR
`

export function resolveRoadmapTab(tabParam: string | null): TabId {
  if (tabParam === 'roadmap') return 'roadmap'
  if (tabParam === 'architecture') return 'architecture'
  return 'timeline'
}

function daysSince(start: string): number {
  const startDate = new Date(start)
  const today = new Date()
  const diff = today.getTime() - startDate.getTime()
  return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)))
}

function sortDelivered(a: Milestone, b: Milestone): number {
  return (b.end ?? '').localeCompare(a.end ?? '') || a.id.localeCompare(b.id)
}

function sortPipeline(a: Milestone, b: Milestone): number {
  const aHorizon = HORIZON_ORDER.indexOf(a.horizon ?? 'Later')
  const bHorizon = HORIZON_ORDER.indexOf(b.horizon ?? 'Later')
  if (aHorizon !== bHorizon) return aHorizon - bHorizon
  if ((a.timeboxDays ?? 2) !== (b.timeboxDays ?? 2)) return (a.timeboxDays ?? 2) - (b.timeboxDays ?? 2)
  return a.id.localeCompare(b.id)
}

export function getTimelineSections(milestones: Milestone[] = MILESTONES): TimelineSection[] {
  return TOPICS.map((topic) => {
    const items = milestones.filter((milestone) => milestone.topic === topic)
    return {
      topic,
      columns: {
        Delivered: items
          .filter((milestone) => milestone.status === 'delivered')
          .sort(sortDelivered),
        Next: items
          .filter((milestone) => milestone.status === 'pipeline' && milestone.horizon === 'Next')
          .sort(sortPipeline),
        Soon: items
          .filter((milestone) => milestone.status === 'pipeline' && milestone.horizon === 'Soon')
          .sort(sortPipeline),
        Later: items
          .filter((milestone) => milestone.status === 'pipeline' && milestone.horizon === 'Later')
          .sort(sortPipeline),
      },
    }
  })
}

function formatDeliveredDateRange(milestone: Milestone): string {
  if (!milestone.start || !milestone.end) return 'Delivered'
  if (milestone.start === milestone.end) {
    return safeFormat(milestone.end, 'd MMM yyyy')
  }
  return `${safeFormat(milestone.start, 'd MMM')} - ${safeFormat(milestone.end, 'd MMM yyyy')}`
}

function formatMilestoneWindow(milestone: Milestone): string {
  if (milestone.status === 'delivered') return formatDeliveredDateRange(milestone)
  if (milestone.timeboxDays) return `${milestone.timeboxDays} day${milestone.timeboxDays === 1 ? '' : 's'}`
  return 'TBD'
}

function timelinePillVariant(column: TimelineColumnId): PillVariant {
  if (column === 'Delivered') return 'active'
  if (column === 'Next') return 'live'
  if (column === 'Soon') return 'warning'
  return 'dim'
}

function priorityPillVariant(priority: Milestone['priority']): PillVariant {
  if (priority === 'P0') return 'alert'
  if (priority === 'P1') return 'active'
  if (priority === 'P2') return 'warning'
  return 'dim'
}

function timelineCardClass(column: TimelineColumnId): string {
  if (column === 'Delivered') {
    return 'border-emerald/45 bg-emerald/8'
  }
  if (column === 'Next') {
    return 'border-cyan/45 bg-cyan/8'
  }
  if (column === 'Soon') {
    return 'border-warning/45 bg-warning/10'
  }
  return 'border-terminal-border bg-terminal-surface/60'
}

function clampTextStyle(lines: number) {
  return {
    display: '-webkit-box',
    WebkitLineClamp: lines,
    WebkitBoxOrient: 'vertical' as const,
    overflow: 'hidden',
  }
}

function TimelineMilestoneCard({
  milestone,
  column,
  sequence,
}: {
  milestone: Milestone
  column: TimelineColumnId
  sequence: number
}) {
  return (
    <article
      data-testid={`timeline-card-${milestone.id}`}
      data-horizon={column}
      data-uniform-card="true"
      className={`relative flex min-h-[15rem] flex-col justify-between rounded-[1.35rem] border p-4 shadow-[0_14px_32px_rgba(0,0,0,0.24)] transition-colors ${timelineCardClass(column)}`}
    >
      <div className="absolute right-4 top-4 rounded-full border border-terminal-border bg-terminal-bg/85 px-2.5 py-1 text-[11px] font-mono text-terminal-text-dim">
        #{sequence}
      </div>

      <div className="space-y-3 pr-12">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase tracking-[0.18em] text-accent">{milestone.id}</span>
          <StatusPill label={column} variant={timelinePillVariant(column)} dot />
          <StatusPill label={milestone.priority} variant={priorityPillVariant(milestone.priority)} />
        </div>

        <div className="space-y-2">
          <h3
            className="text-lg font-semibold leading-tight text-terminal-text"
            style={{ fontFamily: 'var(--font-heading)' }}
          >
            {milestone.name}
          </h3>
          <p className="text-sm leading-relaxed text-terminal-text-dim" style={clampTextStyle(4)}>
            {milestone.description}
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-2 border-t border-terminal-border/80 pt-3 text-xs text-terminal-text-dim">
        <div className="flex items-center justify-between gap-3">
          <span>{column === 'Delivered' ? 'Completed' : 'Timebox'}</span>
          <span className="font-medium text-terminal-text">{formatMilestoneWindow(milestone)}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>Complexity</span>
          <span className="font-medium text-terminal-text">{milestone.effort}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span>Scope</span>
          <span className="font-medium text-terminal-text">
            {milestone.architectureComponents?.length ?? 0} component{milestone.architectureComponents?.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>
    </article>
  )
}

function EmptyTimelineColumn({ column }: { column: TimelineColumnId }) {
  return (
    <div className="flex min-h-[15rem] items-center justify-center rounded-[1.35rem] border border-dashed border-terminal-border bg-terminal-surface/35 p-5 text-center text-sm text-terminal-text-dim">
      {column === 'Delivered'
        ? 'No shipped stories yet in this stream.'
        : `No ${column.toLowerCase()} stories queued right now.`}
    </div>
  )
}

function TimelineTabContent() {
  const sections = getTimelineSections()

  return (
    <div className="space-y-6" data-testid="timeline-board">
      <Panel hero className="animate-none">
        <div className="flex flex-col gap-5">
          <SectionHeader
            eyebrow="Primary View"
            title="Short-cycle roadmap by work stream"
            subtitle="Uniform cards keep future stories readable and honest. Delivered items show actual dates; planned work is grouped into Next, Soon, and Later 1-2 day slices."
          />
          <div className="flex flex-wrap gap-2 text-xs">
            <StatusPill label="Delivered" variant="active" dot />
            <StatusPill label="Next" variant="live" dot />
            <StatusPill label="Soon" variant="warning" dot />
            <StatusPill label="Later" variant="dim" dot />
          </div>
        </div>
      </Panel>

      {sections.map((section) => {
        const deliveredCount = section.columns.Delivered.length
        const plannedCount = section.columns.Next.length + section.columns.Soon.length + section.columns.Later.length

        return (
          <Panel key={section.topic}>
            <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <SectionHeader
                eyebrow="Work Stream"
                title={section.topic}
                subtitle={`${deliveredCount} delivered • ${plannedCount} planned in compact 1-2 day increments.`}
              />
              <div className="text-xs uppercase tracking-[0.18em] text-terminal-text-dim">
                Sequence cues show the order inside each planning bucket.
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
              {TIMELINE_COLUMNS.map((column) => {
                const items = section.columns[column]
                return (
                  <section
                    key={`${section.topic}-${column}`}
                    data-testid={`timeline-column-${section.topic}-${column}`}
                    className="space-y-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <StatusPill label={column} variant={timelinePillVariant(column)} dot />
                      <span className="text-xs text-terminal-text-dim">{items.length} stories</span>
                    </div>
                    <div className="grid gap-3">
                      {items.length === 0 && <EmptyTimelineColumn column={column} />}
                      {items.map((milestone, index) => (
                        <TimelineMilestoneCard
                          key={milestone.id}
                          milestone={milestone}
                          column={column}
                          sequence={index + 1}
                        />
                      ))}
                    </div>
                  </section>
                )
              })}
            </div>
          </Panel>
        )
      })}
    </div>
  )
}

function MilestoneDetailCard({ milestone }: { milestone: Milestone }) {
  const statusLabel = milestone.status === 'delivered' ? 'Delivered' : milestone.horizon ?? 'Planned'
  const windowLabel = milestone.status === 'delivered'
    ? formatDeliveredDateRange(milestone)
    : `${formatMilestoneWindow(milestone)} · ${milestone.horizon ?? 'Planned'}`

  return (
    <article className="rounded-[1.35rem] border border-terminal-border bg-terminal-surface/55 p-5 shadow-[0_10px_28px_rgba(0,0,0,0.2)]">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs uppercase tracking-[0.18em] text-accent">{milestone.id}</span>
            <StatusPill label={statusLabel} variant={timelinePillVariant(statusLabel === 'Planned' ? 'Later' : statusLabel as TimelineColumnId)} dot />
            <StatusPill label={milestone.priority} variant={priorityPillVariant(milestone.priority)} />
            <StatusPill label={milestone.effort} variant="dim" />
          </div>
          <div>
            <h3
              className="text-lg font-semibold leading-tight text-terminal-text"
              style={{ fontFamily: 'var(--font-heading)' }}
            >
              {milestone.name}
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-terminal-text-dim">{milestone.description}</p>
          </div>
        </div>

        <div className="min-w-[12rem] rounded-2xl border border-terminal-border/70 bg-terminal-bg/45 p-3 text-sm text-terminal-text-dim">
          <div className="flex items-center justify-between gap-3">
            <span>Window</span>
            <span className="font-medium text-terminal-text">{windowLabel}</span>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <span>Components</span>
            <span className="font-medium text-terminal-text">{milestone.architectureComponents?.length ?? 0}</span>
          </div>
        </div>
      </div>

      {milestone.architectureComponents && milestone.architectureComponents.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {milestone.architectureComponents.map((component) => (
            <span
              key={`${milestone.id}-${component}`}
              className="rounded-full border border-terminal-border/80 bg-terminal-bg/60 px-3 py-1 text-xs text-terminal-text-dim"
            >
              {component}
            </span>
          ))}
        </div>
      )}
    </article>
  )
}

function RoadmapTabContent({
  topicFilter,
  setTopicFilter,
}: {
  topicFilter: Topic | 'All'
  setTopicFilter: (t: Topic | 'All') => void
}) {
  const filtered = topicFilter === 'All'
    ? MILESTONES
    : MILESTONES.filter((milestone) => milestone.topic === topicFilter)

  const topicsToShow = topicFilter === 'All' ? TOPICS : [topicFilter]

  return (
    <div className="space-y-6" data-testid="roadmap-detail-view">
      <Panel hero className="animate-none">
        <SectionHeader
          eyebrow="Detailed View"
          title="Readable story cards with factual history"
          subtitle="This view keeps the full milestone inventory, but uses larger cards, stronger badges, and clear delivered-vs-planned windows instead of tiny bars."
        />
      </Panel>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setTopicFilter('All')}
          className={`rounded-full border px-3 py-1.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            topicFilter === 'All'
              ? 'border-accent bg-accent/10 text-accent'
              : 'border-terminal-border text-terminal-text hover:border-accent hover:text-accent'
          }`}
        >
          All streams
        </button>
        {TOPICS.map((topic) => (
          <button
            key={topic}
            type="button"
            onClick={() => setTopicFilter(topic)}
            className={`rounded-full border px-3 py-1.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
              topicFilter === topic
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-terminal-border text-terminal-text hover:border-accent hover:text-accent'
            }`}
          >
            {topic}
          </button>
        ))}
      </div>

      {topicsToShow.map((topic) => {
        const items = filtered
          .filter((milestone) => milestone.topic === topic)
          .sort((a, b) => (a.status === 'delivered' && b.status === 'pipeline' ? -1 : a.status === 'pipeline' && b.status === 'delivered' ? 1 : a.status === 'delivered' ? sortDelivered(a, b) : sortPipeline(a, b)))

        if (items.length === 0) return null

        return (
          <Panel key={topic}>
            <div className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
              <SectionHeader
                eyebrow="Topic"
                title={topic}
                subtitle={`${items.filter((milestone) => milestone.status === 'delivered').length} delivered • ${items.filter((milestone) => milestone.status === 'pipeline').length} planned`}
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              {items.map((milestone) => (
                <MilestoneDetailCard key={milestone.id} milestone={milestone} />
              ))}
            </div>
          </Panel>
        )
      })}
    </div>
  )
}

function DocViewerModal({
  docKey,
  title,
  onClose,
}: {
  docKey: string
  title: string
  onClose: () => void
}) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    axios
      .get(`${API_BASE}/api/docs/${docKey}`, { responseType: 'text' })
      .then((response) => setContent(response.data))
      .catch((err) => setError(err?.response?.status === 404 ? 'Document not found' : String(err?.message ?? err)))
  }, [docKey])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-lg border border-terminal-border bg-terminal-bg shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-terminal-border px-4 py-2">
          <h2 className="text-lg font-semibold tracking-wide text-accent">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-terminal-text-dim hover:bg-terminal-border hover:text-terminal-text"
          >
            Close
          </button>
        </div>
        <div className="max-h-[70vh] overflow-auto p-4">
          {error && <p className="text-loss text-sm">{error}</p>}
          {content && (
            <pre className="whitespace-pre-wrap font-mono text-sm text-terminal-text">{content}</pre>
          )}
          {!content && !error && (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ArchitectureTabContent() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [docModal, setDocModal] = useState<{ key: string; title: string } | null>(null)

  useEffect(() => {
    const id = 'architecture-diagram'
    if (!containerRef.current) return

    import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: {
          primaryColor: '#1f2937',
          primaryTextColor: '#00d4ff',
          primaryBorderColor: '#374151',
          lineColor: '#4b5563',
          secondaryColor: '#111827',
          tertiaryColor: '#06060a',
        },
      })
      mermaid
        .render(id, ARCHITECTURE_MERMAID.trim())
        .then(({ svg: rendered }) => {
          setSvg(rendered)
        })
        .catch((err: Error) => {
          setError(err.message)
        })
    })
  }, [])

  return (
    <div className="space-y-4" data-testid="architecture-view">
      <p className="text-sm text-terminal-text-dim">
        Pipeline diagram with component-to-US mapping. See{' '}
        <button
          type="button"
          onClick={() => setDocModal({ key: 'ARCHITECTURE', title: 'docs/ARCHITECTURE.md' })}
          className="rounded text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg"
        >
          docs/ARCHITECTURE.md
        </button>{' '}
        and{' '}
        <button
          type="button"
          onClick={() => setDocModal({ key: 'SOPHISTICATION_ROADMAP', title: 'docs/SOPHISTICATION_ROADMAP.md' })}
          className="rounded text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg"
        >
          docs/SOPHISTICATION_ROADMAP.md
        </button>{' '}
        for full detail.
      </p>
      {docModal && (
        <DocViewerModal
          docKey={docModal.key}
          title={docModal.title}
          onClose={() => setDocModal(null)}
        />
      )}
      <div ref={containerRef} className="card overflow-x-auto bg-terminal-bg/50">
        {error && <p className="text-loss text-sm">{error}</p>}
        {svg && (
          <div
            className="mermaid-render flex justify-center"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        )}
        {!svg && !error && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          </div>
        )}
      </div>
    </div>
  )
}

export default function Roadmap() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = resolveRoadmapTab(searchParams.get('tab'))
  const setActiveTab = (tab: TabId) => {
    if (tab === 'timeline') {
      setSearchParams({ tab: 'timeline' })
      return
    }
    if (tab === 'roadmap') {
      setSearchParams({ tab: 'roadmap' })
      return
    }
    setSearchParams({ tab: 'architecture' })
  }

  const [topicFilter, setTopicFilter] = useState<Topic | 'All'>('All')
  const daysDev = daysSince(PROJECT_START)

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Roadmap & Architecture"
        description={`Project evolution from day 0 (${safeFormat(PROJECT_START, 'd MMM yyyy')}) to now. ${daysDev} days in development.`}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Delivered</div>
          <div className="text-2xl font-bold text-gain">{DELIVERED_COUNT}</div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Pipeline</div>
          <div className="text-2xl font-bold">{PIPELINE_COUNT}</div>
        </div>
        <div className="card">
          <div className="text-sm text-terminal-text-dim">Progress</div>
          <div className="text-2xl font-bold text-accent">{PROGRESS_PCT}%</div>
        </div>
      </div>

      <div className="flex gap-1 border-b border-terminal-border">
        <button
          type="button"
          onClick={() => setActiveTab('timeline')}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'timeline'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:border-accent hover:text-accent'
          }`}
        >
          Timeline
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('roadmap')}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'roadmap'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:border-accent hover:text-accent'
          }`}
        >
          Roadmap
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('architecture')}
          className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'architecture'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:border-accent hover:text-accent'
          }`}
        >
          Architecture
        </button>
      </div>

      {activeTab === 'timeline' && <TimelineTabContent />}
      {activeTab === 'roadmap' && (
        <RoadmapTabContent topicFilter={topicFilter} setTopicFilter={setTopicFilter} />
      )}
      {activeTab === 'architecture' && <ArchitectureTabContent />}
    </div>
  )
}
