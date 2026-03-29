import { useEffect, useMemo, useState } from 'react'
import { insightsApi } from '../api/client'
import type { CycleContextSnapshot, GuidanceSnapshot, StrategyChangeEpisode } from '../types'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { Panel } from '../components/Panel'
import { SectionHeader } from '../components/SectionHeader'
import { StatusPill } from '../components/StatusPill'
import { SkeletonCard } from '../components/Skeleton'
import { safeFormat } from '../utils/date'

type TabKey = 'guidance' | 'attribution'

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-2 rounded-panel text-sm border transition-colors ${
        active
          ? 'border-cyan/30 bg-cyan/10 text-cyan'
          : 'border-terminal-border text-terminal-text-dim hover:text-terminal-text hover:bg-white/5'
      }`}
    >
      {label}
    </button>
  )
}

export default function Insights() {
  const [tab, setTab] = useState<TabKey>('guidance')
  const [guidanceLatest, setGuidanceLatest] = useState<GuidanceSnapshot | null>(null)
  const [guidanceHistory, setGuidanceHistory] = useState<GuidanceSnapshot[]>([])
  const [cycleImpact, setCycleImpact] = useState<CycleContextSnapshot[]>([])
  const [episodes, setEpisodes] = useState<StrategyChangeEpisode[]>([])
  const [selectedEpisode, setSelectedEpisode] = useState<StrategyChangeEpisode | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [backfillLoading, setBackfillLoading] = useState(false)

  async function fetchData() {
    setError(null)
    try {
      const [latest, history, impact, episodeList] = await Promise.all([
        insightsApi.getLatestGuidance(),
        insightsApi.getGuidanceHistory(14),
        insightsApi.getGuidanceCycleImpact(20),
        insightsApi.listEpisodes(),
      ])
      setGuidanceLatest(latest)
      setGuidanceHistory(history)
      setCycleImpact(impact)
      setEpisodes(episodeList)
      const preferredEpisode = selectedEpisode
        ? episodeList.find((item) => item.id === selectedEpisode.id)
        : episodeList[0]
      if (preferredEpisode) {
        const detail = await insightsApi.getEpisode(preferredEpisode.id)
        setSelectedEpisode(detail)
      } else {
        setSelectedEpisode(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load insights')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchData()
  }, [])

  const activeEpisodes = useMemo(
    () => episodes.filter((item) => item.status === 'confirmed').slice(0, 3),
    [episodes]
  )

  if (loading) return <SkeletonCard lines={10} />

  return (
    <div className="space-y-6">
      <PageBrandHeader
        eyebrow="INSIGHTS"
        title="Market Guidance & Attribution"
        description="Operator-only audit surfaces for sector tilts, cycle influence, and repo-linked strategy episodes."
      />

      <Panel>
        <div className="flex items-center gap-2 flex-wrap">
          <TabButton active={tab === 'guidance'} label="Market Guidance" onClick={() => setTab('guidance')} />
          <TabButton active={tab === 'attribution'} label="Strategy Attribution" onClick={() => setTab('attribution')} />
        </div>
      </Panel>

      {error && (
        <Panel>
          <p className="text-loss text-sm">{error}</p>
        </Panel>
      )}

      {tab === 'guidance' && (
        <>
          <Panel hero>
            <SectionHeader eyebrow="LATEST" title="Current Guidance Snapshot" subtitle={guidanceLatest ? safeFormat(guidanceLatest.timestamp, 'MMM dd, HH:mm', '—') : 'No snapshot yet'} />
            {guidanceLatest ? (
              <div className="mt-4 space-y-4">
                <div className="flex items-center gap-3 flex-wrap">
                  <StatusPill label={guidanceLatest.regime} variant={guidanceLatest.regime === 'RISK_OFF' ? 'alert' : guidanceLatest.regime === 'RISK_ON' ? 'active' : 'dim'} dot />
                  <StatusPill label={guidanceLatest.status} variant={guidanceLatest.status === 'active' ? 'live' : guidanceLatest.status === 'stale' ? 'warning' : 'alert'} />
                  <StatusPill label={`${Math.round(guidanceLatest.confidence_score * 100)}% confidence`} variant="dim" />
                </div>
                <p className="text-sm text-terminal-text">{guidanceLatest.prompt_summary ?? guidanceLatest.rationale}</p>
                <div className="grid gap-3 md:grid-cols-3">
                  {guidanceLatest.sector_scores
                    .filter((item) => item.label !== 'neutral')
                    .slice(0, 6)
                    .map((item) => (
                      <div key={item.sector} className="rounded-panel border border-terminal-border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-terminal-text">{item.sector}</span>
                          <StatusPill
                            label={item.label}
                            variant={item.label === 'favored' ? 'active' : item.label === 'avoid' ? 'alert' : 'dim'}
                          />
                        </div>
                        <p className="mt-2 text-sm text-terminal-text-dim">{item.rationale}</p>
                      </div>
                    ))}
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-terminal-text-dim">No guidance snapshot has been persisted yet.</p>
            )}
          </Panel>

          <Panel>
            <SectionHeader eyebrow="CYCLE IMPACT" title="Recent Screening Influence" subtitle="Pre/post candidate distributions from recent cycles" />
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-left text-terminal-text-dim">
                  <tr>
                    <th className="py-2 pr-4">Cycle</th>
                    <th className="py-2 pr-4">Guidance</th>
                    <th className="py-2 pr-4">Candidates</th>
                    <th className="py-2 pr-4">Active Episodes</th>
                  </tr>
                </thead>
                <tbody>
                  {cycleImpact.map((item) => (
                    <tr key={item.cycle_id} className="border-t border-terminal-border">
                      <td className="py-3 pr-4 font-mono text-xs text-terminal-text">{item.cycle_id}</td>
                      <td className="py-3 pr-4 text-terminal-text-dim">{item.prompt_guidance_summary ?? item.guidance_mode ?? 'baseline'}</td>
                      <td className="py-3 pr-4 text-terminal-text-dim">
                        {item.pre_guidance_candidate_count ?? 0} → {item.post_guidance_candidate_count ?? 0}
                      </td>
                      <td className="py-3 pr-4 text-terminal-text-dim">{item.active_strategy_episode_ids.join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel>
            <SectionHeader eyebrow="HISTORY" title="Recent Guidance History" subtitle={`Snapshots persisted: ${guidanceHistory.length}`} />
            <div className="mt-4 space-y-3">
              {guidanceHistory.map((item) => (
                <div key={item.id} className="rounded-panel border border-terminal-border p-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <StatusPill label={item.regime} variant={item.regime === 'RISK_OFF' ? 'alert' : item.regime === 'RISK_ON' ? 'active' : 'dim'} dot />
                      <StatusPill label={item.status} variant={item.status === 'active' ? 'live' : item.status === 'stale' ? 'warning' : 'alert'} />
                    </div>
                    <span className="text-xs text-terminal-text-dim">{safeFormat(item.timestamp, 'MMM dd, HH:mm', '—')}</span>
                  </div>
                  <p className="mt-2 text-sm text-terminal-text-dim">{item.prompt_summary ?? item.rationale}</p>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      {tab === 'attribution' && (
        <>
          <Panel>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <SectionHeader eyebrow="EPISODES" title="Strategy Change Episodes" subtitle={`${episodes.length} tracked episodes`} />
              <button
                type="button"
                className="btn-secondary"
                onClick={async () => {
                  setBackfillLoading(true)
                  try {
                    await insightsApi.backfillEpisodes(30)
                    await fetchData()
                  } finally {
                    setBackfillLoading(false)
                  }
                }}
              >
                {backfillLoading ? 'Backfilling…' : 'Backfill Last 30d'}
              </button>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div className="space-y-3">
                {episodes.map((episode) => (
                  <button
                    key={episode.id}
                    type="button"
                    onClick={async () => setSelectedEpisode(await insightsApi.getEpisode(episode.id))}
                    className={`w-full text-left rounded-panel border p-3 transition-colors ${
                      selectedEpisode?.id === episode.id
                        ? 'border-cyan/30 bg-cyan/10'
                        : 'border-terminal-border hover:bg-white/5'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium text-terminal-text">{episode.title}</span>
                      <StatusPill
                        label={episode.status}
                        variant={episode.status === 'confirmed' ? 'active' : episode.status === 'rejected' ? 'alert' : 'warning'}
                      />
                    </div>
                    <p className="mt-2 text-sm text-terminal-text-dim">{episode.summary}</p>
                  </button>
                ))}
              </div>
              <div className="rounded-panel border border-terminal-border p-4">
                {selectedEpisode ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <StatusPill
                        label={selectedEpisode.status}
                        variant={selectedEpisode.status === 'confirmed' ? 'active' : selectedEpisode.status === 'rejected' ? 'alert' : 'warning'}
                      />
                      <StatusPill label={selectedEpisode.change_type} variant="dim" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-terminal-text">{selectedEpisode.title}</h3>
                      <p className="mt-2 text-sm text-terminal-text-dim">{selectedEpisode.summary}</p>
                    </div>
                    {selectedEpisode.impact_summary && (
                      <div className="grid gap-3 md:grid-cols-3">
                        <div className="rounded-panel border border-terminal-border p-3">
                          <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Windows</div>
                          <div className="mt-2 text-sm text-terminal-text">
                            1d {selectedEpisode.impact_summary.window_1d_cycles} · 7d {selectedEpisode.impact_summary.window_7d_cycles} · 30d {selectedEpisode.impact_summary.window_30d_cycles}
                          </div>
                        </div>
                        <div className="rounded-panel border border-terminal-border p-3">
                          <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Conversion Delta</div>
                          <div className="mt-2 text-sm text-terminal-text">{selectedEpisode.impact_summary.screening_conversion_delta.toFixed(3)}</div>
                        </div>
                        <div className="rounded-panel border border-terminal-border p-3">
                          <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Warnings</div>
                          <div className="mt-2 text-sm text-terminal-text">
                            {selectedEpisode.impact_summary.low_sample_warning ? 'Low sample' : 'Sample OK'}
                            {' · '}
                            {selectedEpisode.impact_summary.overlap_warning ? 'Overlap' : 'No overlap'}
                          </div>
                        </div>
                      </div>
                    )}
                    <div>
                      <div className="text-xs uppercase tracking-wider text-terminal-text-dim">Evidence</div>
                      <div className="mt-2 space-y-2">
                        {(selectedEpisode.evidence ?? []).map((item) => (
                          <div key={item.id} className="rounded-panel border border-terminal-border p-3">
                            <div className="font-mono text-xs text-terminal-text-dim">{item.commit_sha.slice(0, 12)}</div>
                            <div className="mt-1 text-sm text-terminal-text">{item.title}</div>
                            <div className="mt-1 text-xs text-terminal-text-dim">{item.affected_files.join(', ')}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    {selectedEpisode.status === 'proposed' && (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          className="btn-primary"
                          onClick={async () => {
                            await insightsApi.confirmEpisode(selectedEpisode.id)
                            await fetchData()
                          }}
                        >
                          Confirm Episode
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={async () => {
                            await insightsApi.rejectEpisode(selectedEpisode.id)
                            await fetchData()
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-terminal-text-dim">No strategy episode selected.</p>
                )}
              </div>
            </div>
          </Panel>

          {activeEpisodes.length > 0 && (
            <Panel>
              <SectionHeader eyebrow="ACTIVE" title="Confirmed Episodes" subtitle="These episodes are eligible to attach to new cycles" />
              <div className="mt-4 grid gap-3 md:grid-cols-3">
                {activeEpisodes.map((episode) => (
                  <div key={episode.id} className="rounded-panel border border-terminal-border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-terminal-text">{episode.title}</span>
                      <StatusPill label="confirmed" variant="active" />
                    </div>
                    <p className="mt-2 text-sm text-terminal-text-dim">{episode.summary}</p>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
