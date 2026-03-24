import { useEffect, useState } from 'react'
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
type ArchitectureBlock = {
  title: string
  subtitle: string
  stories: string[]
  bullets: string[]
}
type ArchitectureStage = {
  step: string
  title: string
  summary: string
  variant: PillVariant
  blocks: ArchitectureBlock[]
}

const TIMELINE_COLUMNS: TimelineColumnId[] = ['Delivered', 'Next', 'Soon', 'Later']
const HORIZON_ORDER: Horizon[] = ['Next', 'Soon', 'Later']

const ARCHITECTURE_CONTROL_PLANE = [
  {
    title: 'Scheduler & orchestrator',
    summary: 'Cron-driven cycles, one active run at a time, pause/resume, state transitions, and shared execution ownership.',
    chips: ['analysis cycles', 'manual trigger', 'state machine'],
  },
  {
    title: 'Budgets & safety rails',
    summary: 'Provider budgets, moderation/risk vetoes, large-order confirmations, and force-override audit handling.',
    chips: ['cost guardrails', 'risk vetoes', 'confirmation gate'],
  },
  {
    title: 'Shared data plane',
    summary: 'SQLite tables power the agent, dashboard APIs, SSE feed, commands audit trail, and chat session skeleton.',
    chips: ['runs', 'orders', 'command logs', 'chat turns'],
  },
] as const

const ARCHITECTURE_STAGES: ArchitectureStage[] = [
  {
    step: '01',
    title: 'Inputs & providers',
    summary: 'Raw market data, web context, broker state, and specialist model providers enter the system here.',
    variant: 'live',
    blocks: [
      {
        title: 'Market + broker APIs',
        subtitle: 'Price, fundamentals, account cash, positions, and orders',
        stories: ['US-4.1', 'US-4.5', 'US-3.5'],
        bullets: [
          'yfinance, Finnhub, Alpha Vantage, Trading 212',
          'Ticker alias resolution and broker-specific instrument mapping',
        ],
      },
      {
        title: 'Research sources',
        subtitle: 'Web and filing context for deeper review loops',
        stories: ['US-4.4'],
        bullets: [
          'Brave primary, Tavily fallback, SEC EDGAR filings',
          'Shared search surface for strategy and moderators',
        ],
      },
      {
        title: 'Committee model providers',
        subtitle: 'Independent model roles rather than one monolith',
        stories: ['US-2.3', 'US-2.4', 'US-4.4'],
        bullets: [
          'Claude for synthesis, GPT-4o for skepticism, Gemini for risk framing',
          'Model choice and spend tracked separately in cost logs',
        ],
      },
    ],
  },
  {
    step: '02',
    title: 'Context & research',
    summary: 'The system normalises raw inputs into reusable context before any trade decision is made.',
    variant: 'warning',
    blocks: [
      {
        title: 'Data fetcher + screener',
        subtitle: 'Indicators, fundamentals, and candidate preparation',
        stories: ['US-3.4', 'US-4.1', 'US-4.3'],
        bullets: [
          'OHLCV + factor preparation feeds ranking, screening, and review',
          'Universe screener and UOV inputs share the same base data layer',
        ],
      },
      {
        title: 'Macro + news intelligence',
        subtitle: 'Scheduled regime context and persistent world-news archive',
        stories: ['US-4.5', 'US-1.7.4'],
        bullets: [
          'macro_scan produces regime, confidence, signals, and action plan',
          'World News page exposes the same archive to operators',
        ],
      },
      {
        title: 'Research executor',
        subtitle: 'Tool-use loops with budget, caching, and auditability',
        stories: ['US-4.4'],
        bullets: [
          '5 tool families shared by Strategy, Skeptic, and Risk',
          'Each research step logs provider, latency, cache hit, and summary',
        ],
      },
    ],
  },
  {
    step: '03',
    title: 'Decision committee',
    summary: 'Strategy proposes, moderation challenges, and the risk agent enforces hard rules before execution.',
    variant: 'draft',
    blocks: [
      {
        title: 'Strategy engine',
        subtitle: 'Synthesis over quant, macro, research, and portfolio state',
        stories: ['US-2.1', 'US-2.2', 'US-3.1'],
        bullets: [
          'Claude produces action, conviction, reasoning, and target sizing',
          'Risk-parity overlay can adjust BUY sizing before execution',
        ],
      },
      {
        title: 'Moderation panel',
        subtitle: 'Independent challenge function with explicit consensus',
        stories: ['US-2.3', 'US-2.4', 'US-1.6'],
        bullets: [
          'GPT-4o Skeptic + Gemini Risk yield APPROVED, CAUTION, or BLOCKED',
          'Explicit Slack force overrides are audited instead of silently bypassing review',
        ],
      },
      {
        title: 'Risk agent',
        subtitle: 'Non-negotiable portfolio and execution constraints',
        stories: ['US-3.2', 'US-3.3', 'US-7.0'],
        bullets: [
          '11 hard veto rules, cash floor, allocation limits, and correlation checks',
          'Triggered rules persist to risk decisions and Slack/dashboard explanations',
        ],
      },
    ],
  },
  {
    step: '04',
    title: 'Execution & visibility',
    summary: 'Approved decisions become broker actions, operator workflows, and durable audit trails.',
    variant: 'active',
    blocks: [
      {
        title: 'Opportunity + order management',
        subtitle: 'Queueing, execution, stops, and post-trade lifecycle',
        stories: ['US-3.4', 'US-3.5', 'US-7.2', 'US-7.3'],
        bullets: [
          'UOV ranking selects what moves first; order manager owns T212 interactions',
          'Stop-loss manager, pending status mapping, and reconciliation protect state consistency',
        ],
      },
      {
        title: 'Slack + dashboard surfaces',
        subtitle: 'Human operator layer for commands, review, and monitoring',
        stories: ['US-1.6', 'US-1.7', 'US-1.9'],
        bullets: [
          'Always-on Slack listener, Commands page, live dashboard APIs, and SSE activity feed',
          'ChatSession and ChatTurn provide the skeleton for future conversational workflows',
        ],
      },
      {
        title: 'Journals, logs, and reports',
        subtitle: 'Everything needed for auditability and iteration',
        stories: ['US-1.1', 'US-1.2', 'US-7.0'],
        bullets: [
          'Runs, orders, trade outcomes, cost logs, API logs, command logs, and snapshots',
          'Daily and weekly reporting consume the same persisted state as the dashboard',
        ],
      },
    ],
  },
] as const

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
      className={`relative min-w-0 overflow-hidden flex min-h-[15rem] flex-col justify-between rounded-[1.35rem] border p-4 shadow-[0_14px_32px_rgba(0,0,0,0.24)] transition-colors ${timelineCardClass(column)}`}
    >
      <div className="absolute right-4 top-4 rounded-full border border-terminal-border bg-terminal-bg/85 px-2.5 py-1 text-[11px] font-mono text-terminal-text-dim">
        #{sequence}
      </div>

      <div className="min-w-0 space-y-3 pr-12">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase tracking-[0.18em] text-accent">{milestone.id}</span>
          <StatusPill label={column} variant={timelinePillVariant(column)} dot />
          <StatusPill label={milestone.priority} variant={priorityPillVariant(milestone.priority)} />
        </div>

        <div className="space-y-2">
          <h3
            className="break-words text-lg font-semibold leading-tight text-terminal-text"
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
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
          <span>{column === 'Delivered' ? 'Completed' : 'Timebox'}</span>
          <span className="min-w-0 text-right font-medium text-terminal-text break-words">
            {formatMilestoneWindow(milestone)}
          </span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
          <span>Complexity</span>
          <span className="min-w-0 text-right font-medium text-terminal-text break-words">{milestone.effort}</span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
          <span>Scope</span>
          <span className="min-w-0 text-right font-medium text-terminal-text break-words">
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

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {TIMELINE_COLUMNS.map((column) => {
                const items = section.columns[column]
                return (
                  <section
                    key={`${section.topic}-${column}`}
                    data-testid={`timeline-column-${section.topic}-${column}`}
                    className="min-w-0 space-y-3"
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

function ArchitectureBlockCard({
  block,
  variant,
}: {
  block: ArchitectureBlock
  variant: PillVariant
}) {
  return (
    <div className="rounded-[1.25rem] border border-terminal-border bg-terminal-surface/65 p-4 shadow-[0_10px_28px_rgba(0,0,0,0.22)]">
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3
              className="text-base font-semibold leading-tight text-terminal-text"
              style={{ fontFamily: 'var(--font-heading)' }}
            >
              {block.title}
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-terminal-text-dim">{block.subtitle}</p>
          </div>
          <StatusPill label={`${block.stories.length} story${block.stories.length === 1 ? '' : 'ies'}`} variant={variant} />
        </div>

        <div className="flex flex-wrap gap-2">
          {block.stories.map((story) => (
            <span
              key={`${block.title}-${story}`}
              className="rounded-full border border-terminal-border/80 bg-terminal-bg/60 px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.18em] text-accent"
            >
              {story}
            </span>
          ))}
        </div>

        <ul className="space-y-2 text-sm leading-relaxed text-terminal-text-dim">
          {block.bullets.map((bullet) => (
            <li key={`${block.title}-${bullet}`} className="flex gap-2">
              <span className="mt-1 text-accent">•</span>
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function ArchitectureStageCard({
  stage,
  isLast,
}: {
  stage: ArchitectureStage
  isLast: boolean
}) {
  return (
    <div className="relative min-w-0">
      {!isLast && (
        <div className="pointer-events-none absolute right-[-1.35rem] top-12 hidden xl:flex h-8 w-8 items-center justify-center rounded-full border border-terminal-border bg-terminal-bg/90 text-accent">
          →
        </div>
      )}
      <Panel className="h-full animate-none">
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill label={`Step ${stage.step}`} variant="dim" />
            <StatusPill label={stage.title} variant={stage.variant} dot />
          </div>
          <div>
            <h2
              className="text-xl font-semibold leading-tight text-terminal-text"
              style={{ fontFamily: 'var(--font-heading)' }}
            >
              {stage.title}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-terminal-text-dim">{stage.summary}</p>
          </div>
          <div className="space-y-4">
            {stage.blocks.map((block) => (
              <ArchitectureBlockCard key={`${stage.step}-${block.title}`} block={block} variant={stage.variant} />
            ))}
          </div>
        </div>
      </Panel>
    </div>
  )
}

function ArchitectureTabContent() {
  const [docModal, setDocModal] = useState<{ key: string; title: string } | null>(null)

  return (
    <div className="space-y-6" data-testid="architecture-view">
      <Panel hero className="animate-none">
        <div className="space-y-5">
          <SectionHeader
            eyebrow="System Map"
            title="Readable flow from signals to execution"
            subtitle="This view maps the current production system as a staged operating model: inputs and providers feed context and research, the decision committee applies moderation and risk, then execution surfaces and audit trails make the system observable."
          />
          <div className="flex flex-wrap gap-2">
            <StatusPill label="Inputs" variant="live" dot />
            <StatusPill label="Context" variant="warning" dot />
            <StatusPill label="Decision" variant="draft" dot />
            <StatusPill label="Execution" variant="active" dot />
          </div>
        </div>
      </Panel>

      <Panel className="animate-none">
        <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <SectionHeader
            eyebrow="Control Plane"
            title="Shared orchestration and guardrails"
            subtitle="These capabilities cut across every stage rather than belonging to one box."
          />
          <div className="text-xs uppercase tracking-[0.18em] text-terminal-text-dim">
            Persistent state, budgets, and operator controls span the full pipeline.
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {ARCHITECTURE_CONTROL_PLANE.map((item) => (
            <div
              key={item.title}
              className="rounded-[1.25rem] border border-terminal-border bg-terminal-surface/60 p-4 shadow-[0_10px_28px_rgba(0,0,0,0.22)]"
            >
              <h3
                className="text-base font-semibold text-terminal-text"
                style={{ fontFamily: 'var(--font-heading)' }}
              >
                {item.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-terminal-text-dim">{item.summary}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {item.chips.map((chip) => (
                  <span
                    key={`${item.title}-${chip}`}
                    className="rounded-full border border-terminal-border/80 bg-terminal-bg/60 px-2.5 py-1 text-[11px] font-mono uppercase tracking-[0.18em] text-terminal-text-dim"
                  >
                    {chip}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid gap-5 xl:grid-cols-4">
        {ARCHITECTURE_STAGES.map((stage, index) => (
          <ArchitectureStageCard
            key={stage.step}
            stage={stage}
            isLast={index === ARCHITECTURE_STAGES.length - 1}
          />
        ))}
      </div>

      <Panel className="animate-none">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <p className="text-sm leading-relaxed text-terminal-text-dim">
            Need the full narrative and data model references? Open{' '}
            <button
              type="button"
              onClick={() => setDocModal({ key: 'ARCHITECTURE', title: 'docs/ARCHITECTURE.md' })}
              className="rounded text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg"
            >
              docs/ARCHITECTURE.md
            </button>{' '}
            or{' '}
            <button
              type="button"
              onClick={() => setDocModal({ key: 'SOPHISTICATION_ROADMAP', title: 'docs/SOPHISTICATION_ROADMAP.md' })}
              className="rounded text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg"
            >
              docs/SOPHISTICATION_ROADMAP.md
            </button>{' '}
            directly from the dashboard.
          </p>
          <div className="text-xs uppercase tracking-[0.18em] text-terminal-text-dim">
            Architecture tab is now a custom system map, not a compressed Mermaid export.
          </div>
        </div>
      </Panel>

      {docModal && (
        <DocViewerModal
          docKey={docModal.key}
          title={docModal.title}
          onClose={() => setDocModal(null)}
        />
      )}
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
