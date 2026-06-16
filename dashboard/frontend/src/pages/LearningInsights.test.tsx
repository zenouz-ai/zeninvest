import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { describe, expect, it, vi } from 'vitest'
import LearningInsights from './LearningInsights'

vi.mock('../components/learning/hooks/useLearningPageData', () => ({
  useLearningPageData: () => ({
    loading: false,
    error: null,
    status: {
      dataset_version: 'v6',
      latest_export: {
        id: 1,
        run_id: 'export-1',
        dataset_version: 'v6',
        status: 'completed',
        rows: 2500,
        text_corpus_rows: 2500,
        checksum: null,
        duration_sec: 10,
        created_at: new Date().toISOString(),
        artifact_paths: {},
      },
      latest_evaluation: {
        run_id: 'eval-1',
        created_at: new Date().toISOString(),
        gates: { tiers: [{ tier_id: 'shadow_ok', label: 'Shadow OK', passed: true }] },
        metrics: { policies: {} },
        report_available: false,
      },
      latest_train_run: null,
      shadow_summary: { days: 30, total_scores: 0, by_policy: {} },
      exports_preview: [],
      staleness_warnings: [],
    },
    northStar: {
      window_days: 90,
      total_trades: 45,
      sufficient_data: true,
      big_winner_hit_rate: 0.2,
      stall_rate: 0.35,
      big_loser_rate: 0.1,
      slow_win_rate: null,
      avg_gain_per_day_pct: 0.1,
      expectancy_gbp: 12.5,
      avg_pnl_pct: null,
      targets: {
        big_winner_hit_rate_interim: 0.35,
        big_winner_hit_rate_stretch: 0.5,
        stall_rate_max: 0.35,
        big_loser_rate_max: 0.25,
        min_trades_for_display: 30,
      },
      thresholds: { success_min_profit_per_day_pct: 0.25 },
    },
    evaluation: {
      run_id: 'eval-1',
      created_at: new Date().toISOString(),
      gates: { tiers: [{ tier_id: 'shadow_ok', label: 'Shadow OK', passed: true }] },
      metrics: { policies: {} },
      report_available: false,
    },
    runs: [],
    activeTab: 'shadow' as const,
    setActiveTab: vi.fn(),
    refresh: vi.fn(),
  }),
}))

vi.mock('../api/client', () => ({
  learningApi: {
    getShadowSummary: vi.fn().mockResolvedValue({ days: 30, total_scores: 0, by_policy: {} }),
    getShadowDisagreements: vi.fn().mockResolvedValue({ disagreements: [], count: 0 }),
    getEntryAdvisory: vi.fn().mockResolvedValue(null),
    getLatestEvaluation: vi.fn(),
    getCommitteeEvaluation: vi.fn(),
    getResearchEvaluation: vi.fn(),
    listExports: vi.fn(),
    listDatasetVersions: vi.fn(),
    getRun: vi.fn(),
    reportUrl: vi.fn(),
    evaluationReportUrl: vi.fn(),
  },
  memoryApi: {
    similar: vi.fn(),
  },
}))

function renderLearning(): string {
  return renderToStaticMarkup(
    <StaticRouter location="/learning">
      <LearningInsights />
    </StaticRouter>,
  )
}

describe('LearningInsights page', () => {
  it('renders north-star-first shell with tabs and data lab', () => {
    const markup = renderLearning()
    expect(markup).toContain('data-testid="learning-page"')
    expect(markup).toContain('Learning &amp; shadow evaluation')
    expect(markup).toContain('North-star KPIs')
    expect(markup).toContain('Promotion gates')
    expect(markup).toContain('Artifact freshness')
    expect(markup).toContain('data-testid="learning-tabs"')
    expect(markup).toContain('Live shadow')
    expect(markup).toContain('Data lab (advanced)')
    expect(markup).not.toContain('Static insight figures')
    expect(markup).not.toContain('On-disk v2 parquet')
  })
})
