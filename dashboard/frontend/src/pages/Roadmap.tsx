import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import {
  MILESTONES,
  TOPICS,
  PROJECT_START,
  DELIVERED_COUNT,
  PIPELINE_COUNT,
  PROGRESS_PCT,
  type Milestone,
  type Topic,
} from '../data/roadmap'
import { safeFormat } from '../utils/date'
import { PageBrandHeader } from '../components/PageBrandHeader'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

type TabId = 'gantt' | 'roadmap' | 'architecture'

/** Full pipeline Mermaid with external APIs and US annotations */
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

    subgraph Data["Market Data - US-4.1, 4.2, 4.3"]
        DF[Data Fetcher]
        UNIV[Universe Screener]
        MACRO[Macro Intelligence]
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

/** Topic-to-color mapping for Gantt sections (work streams). Mermaid cycles section colors; order determines palette. */
const TOPIC_ORDER = [...TOPICS]

/** Build Mermaid gantt diagram from milestones. Sections = work streams (topics); bars colored by topic. */
function buildGanttMermaid(): string {
  const delivered = MILESTONES.filter((m) => m.status === 'delivered' && m.start && m.end)
  const pipeline = MILESTONES.filter((m) => m.status === 'pipeline')
  const effortDays: Record<string, number> = { S: 5, M: 10, L: 20, 'M–L': 14 }
  const lastEnd = delivered.length
    ? delivered.reduce((max, m) => (m.end! > max ? m.end! : max), delivered[0]!.end!)
    : PROJECT_START
  const plannedStart = lastEnd ? new Date(lastEnd) : new Date(PROJECT_START)
  plannedStart.setDate(plannedStart.getDate() + 1)
  const plannedStartStr = plannedStart.toISOString().slice(0, 10)

  const lines: string[] = [
    'gantt',
    '    title Project Roadmap',
    '    dateFormat YYYY-MM-DD',
    '    axisFormat %b %Y',
  ]
  const sections = new Map<string, string[]>()
  for (const m of delivered) {
    const sec = m.topic
    if (!sections.has(sec)) sections.set(sec, [])
    const label = `${m.id} ${m.name}`.replace(/:/g, '')
    sections.get(sec)!.push(`    ${label} :done, ${m.id.replace(/[.-]/g, '_')}, ${m.start}, ${m.end}`)
  }
  let cursor = plannedStartStr
  for (const m of pipeline) {
    const sec = m.topic
    if (!sections.has(sec)) sections.set(sec, [])
    const dur = effortDays[m.effort] ?? 10
    const label = `${m.id} ${m.name}`.replace(/:/g, '')
    const end = new Date(cursor)
    end.setDate(end.getDate() + dur)
    const endStr = end.toISOString().slice(0, 10)
    sections.get(sec)!.push(`    ${label} : ${m.id.replace(/[.-]/g, '_')}, ${cursor}, ${endStr}`)
    cursor = endStr
  }
  for (const topic of TOPIC_ORDER) {
    const tasks = sections.get(topic)
    if (!tasks || tasks.length === 0) continue
    lines.push(`    section ${topic}`)
    lines.push(...tasks)
  }
  return lines.join('\n')
}

function daysSince(start: string): number {
  const startDate = new Date(start)
  const today = new Date()
  const diff = today.getTime() - startDate.getTime()
  return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)))
}

function MilestoneRow({ m }: { m: Milestone }) {
  const [expanded, setExpanded] = useState(false)
  const dateRange =
    m.status === 'delivered' && m.start && m.end
      ? `${safeFormat(m.start, 'd MMM yyyy')} – ${safeFormat(m.end, 'd MMM yyyy')}`
      : m.status === 'pipeline'
        ? 'Planned'
        : '—'

  return (
    <div className="border-l-2 border-terminal-border pl-4 py-2 hover:border-neutral/50 transition-colors">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left flex items-start gap-3"
      >
        <span className={m.status === 'delivered' ? 'text-gain' : 'text-terminal-text-dim'}>
          {m.status === 'delivered' ? '●' : '○'}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-accent">{m.id}</span>
            <span className="font-medium">{m.name}</span>
            <span
              className={`text-xs px-1.5 py-0.5 rounded ${
                m.status === 'delivered'
                  ? 'bg-gain/20 text-gain'
                  : 'bg-terminal-border/50 text-terminal-text-dim'
              }`}
            >
              {m.status}
            </span>
            <span className="text-terminal-text-dim text-sm">{dateRange}</span>
            <span className="text-xs text-terminal-text-dim">
              {m.effort} · {m.priority}
            </span>
          </div>
          {expanded && (
            <div className="mt-2 text-sm text-terminal-text-dim space-y-1">
              <p>{m.description}</p>
              {m.architectureComponents && m.architectureComponents.length > 0 && (
                <p className="text-xs">
                  Components: {m.architectureComponents.join(', ')}
                </p>
              )}
            </div>
          )}
        </div>
      </button>
    </div>
  )
}

function GanttTabContent() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const id = 'gantt-diagram'
    if (!containerRef.current) return
    const mermaidCode = buildGanttMermaid()

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
        gantt: {
          barHeight: 20,
          barGap: 4,
          useMaxWidth: true,
          numberSectionStyles: 6,
        },
      })
      mermaid
        .render(id, mermaidCode)
        .then(({ svg: rendered }) => setSvg(rendered))
        .catch((err: Error) => setError(err.message))
    })
  }, [])

  return (
    <div className="space-y-4">
      <p className="text-terminal-text-dim text-sm">
        Timeline by work stream (topic). Each section is a different colour. Green bars = delivered; grey = planned.
      </p>
      <div ref={containerRef} className="card overflow-x-auto bg-terminal-bg/50">
        {error && <p className="text-loss text-sm">{error}</p>}
        {svg && (
          <div
            className="mermaid-render flex justify-center min-w-[600px]"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        )}
        {!svg && !error && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin h-8 w-8 border-2 border-accent border-t-transparent rounded-full" />
          </div>
        )}
      </div>
    </div>
  )
}

function RoadmapTabContent({
  topicFilter,
  setTopicFilter,
}: {
  topicFilter: Topic | 'All'
  setTopicFilter: (t: Topic | 'All') => void
}) {
  const filtered =
    topicFilter === 'All'
      ? MILESTONES
      : MILESTONES.filter((m) => m.topic === topicFilter)

  const byTopic = TOPICS.reduce<Record<string, Milestone[]>>((acc, t) => {
    const items = filtered.filter((m) => m.topic === t)
    if (items.length > 0) acc[t] = items
    return acc
  }, {})

  const topicsToShow = topicFilter === 'All' ? TOPICS : [topicFilter]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setTopicFilter('All')}
          className={`rounded px-2 py-1 text-sm border transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            topicFilter === 'All' ? 'border-accent text-accent' : 'border-terminal-border text-terminal-text'
          }`}
        >
          All
        </button>
        {TOPICS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTopicFilter(t)}
            className={`rounded px-2 py-1 text-sm border transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
              topicFilter === t ? 'border-accent text-accent' : 'border-terminal-border text-terminal-text'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="space-y-6">
        {topicsToShow.map((topic) => {
          const items = topicFilter === 'All' ? byTopic[topic] : filtered
          if (!items || items.length === 0) return null
          return (
            <div key={topic} className="card">
              <h3 className="text-lg font-semibold tracking-wide mb-4 text-accent">{topic}</h3>
              <div className="space-y-0">
                {items.map((m) => (
                  <MilestoneRow key={m.id} m={m} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
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
      .then((r) => setContent(r.data))
      .catch((e) => setError(e?.response?.status === 404 ? 'Document not found' : String(e?.message ?? e)))
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
        onClick={(e) => e.stopPropagation()}
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
            <pre className="whitespace-pre-wrap font-mono text-sm text-terminal-text">
              {content}
            </pre>
          )}
          {!content && !error && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin h-8 w-8 border-2 border-accent border-t-transparent rounded-full" />
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
    <div className="space-y-4">
      <p className="text-terminal-text-dim text-sm">
        Pipeline diagram with component-to-US mapping. See{' '}
        <button
          type="button"
          onClick={() => setDocModal({ key: 'ARCHITECTURE', title: 'docs/ARCHITECTURE.md' })}
          className="text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg rounded"
        >
          docs/ARCHITECTURE.md
        </button>{' '}
        and{' '}
        <button
          type="button"
          onClick={() => setDocModal({ key: 'SOPHISTICATION_ROADMAP', title: 'docs/SOPHISTICATION_ROADMAP.md' })}
          className="text-neutral hover:underline focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg rounded"
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
        {error && (
          <p className="text-loss text-sm">{error}</p>
        )}
        {svg && (
          <div
            className="mermaid-render flex justify-center"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        )}
        {!svg && !error && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin h-8 w-8 border-2 border-accent border-t-transparent rounded-full" />
          </div>
        )}
      </div>
    </div>
  )
}

export default function Roadmap() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const activeTab: TabId =
    tabParam === 'roadmap'
      ? 'roadmap'
      : tabParam === 'architecture'
        ? 'architecture'
        : 'gantt'
  const setActiveTab = (t: TabId) => {
    if (t === 'gantt') setSearchParams({ tab: 'gantt' })
    else if (t === 'roadmap') setSearchParams({ tab: 'roadmap' })
    else setSearchParams({ tab: 'architecture' })
  }
  const [topicFilter, setTopicFilter] = useState<Topic | 'All'>('All')
  const daysDev = daysSince(PROJECT_START)

  return (
    <div className="space-y-6">
      <PageBrandHeader
        title="Roadmap & Architecture"
        description={`Project evolution from day 0 (${safeFormat(PROJECT_START, 'd MMM yyyy')}) to now. ${daysDev} days in development.`}
      />

      <div className="flex flex-wrap gap-4">
        <div className="card flex-1 min-w-[140px]">
          <div className="text-terminal-text-dim text-sm">Delivered</div>
          <div className="text-2xl font-bold text-gain">{DELIVERED_COUNT}</div>
        </div>
        <div className="card flex-1 min-w-[140px]">
          <div className="text-terminal-text-dim text-sm">Pipeline</div>
          <div className="text-2xl font-bold">{PIPELINE_COUNT}</div>
        </div>
        <div className="card flex-1 min-w-[140px]">
          <div className="text-terminal-text-dim text-sm">Progress</div>
          <div className="text-2xl font-bold text-accent">{PROGRESS_PCT}%</div>
        </div>
      </div>

      <div className="flex gap-1 border-b border-terminal-border">
        <button
          type="button"
          onClick={() => setActiveTab('gantt')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'gantt'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
          }`}
        >
          Gantt
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('roadmap')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'roadmap'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
          }`}
        >
          Roadmap
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('architecture')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors focus:outline-none focus:ring-2 focus:ring-neutral focus:ring-offset-2 focus:ring-offset-terminal-bg ${
            activeTab === 'architecture'
              ? 'border-accent text-accent'
              : 'border-transparent text-terminal-text hover:text-accent hover:border-accent'
          }`}
        >
          Architecture
        </button>
      </div>

      {activeTab === 'gantt' && <GanttTabContent />}
      {activeTab === 'roadmap' && (
        <RoadmapTabContent topicFilter={topicFilter} setTopicFilter={setTopicFilter} />
      )}
      {activeTab === 'architecture' && <ArchitectureTabContent />}
    </div>
  )
}
