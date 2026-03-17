/**
 * Project roadmap data for the Roadmap & Architecture dashboard tab.
 * Dates derived from git log. See docs/SOPHISTICATION_ROADMAP.md for full specs.
 */

export const PROJECT_START = '2026-02-22'

export const TOPICS = [
  'Foundation',
  'Calibration',
  'Portfolio & Risk',
  'Signals',
  'Validation',
  'ML / Advanced',
] as const

export type Topic = (typeof TOPICS)[number]

export type MilestoneStatus = 'delivered' | 'pipeline'

export type Priority = 'P0' | 'P1' | 'P2' | 'P3'
export type Effort = 'S' | 'M' | 'L' | 'M–L'

export interface Milestone {
  id: string
  name: string
  topic: Topic
  status: MilestoneStatus
  /** ISO date string; only for delivered items */
  start?: string
  /** ISO date string; only for delivered items; pipeline items have no end */
  end?: string
  effort: Effort
  priority: Priority
  description: string
  /** Architecture component(s) this US maps to */
  architectureComponents?: string[]
}

/** All 28 milestones from SOPHISTICATION_ROADMAP (11 delivered, 17 pipeline) */
export const MILESTONES: Milestone[] = [
  // --- Delivered (11) ---
  {
    id: 'US-1.1',
    name: 'Performance Tracking',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-03',
    end: '2026-03-05',
    effort: 'M',
    priority: 'P0',
    description:
      'Daily Sharpe/Sortino/drawdown, win rate by strategy, alpha vs benchmark; performance_metrics table, CLI --performance',
    architectureComponents: ['Orchestrator', 'Reporting'],
  },
  {
    id: 'US-1.2',
    name: 'Trade Outcome Tracker',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-03',
    end: '2026-03-05',
    effort: 'M',
    priority: 'P0',
    description:
      'Link each BUY to SELL/REDUCE; per-trade P&L, conviction linkage; trade_outcomes table',
    architectureComponents: ['Orchestrator', 'Reporting'],
  },
  {
    id: 'US-1.3',
    name: 'CLI Dashboard',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-02-24',
    end: '2026-02-24',
    effort: 'S',
    priority: 'P1',
    description:
      'CLI --dashboard: portfolio value, Sharpe, win rate, costs, active positions',
    architectureComponents: ['Orchestrator', 'Reporting'],
  },
  {
    id: 'US-1.4',
    name: 'Deploy POC to VPS',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-09',
    end: '2026-03-10',
    effort: 'S',
    priority: 'P0',
    description:
      'Docker on VPS, health check, backup, first cycle logged',
    architectureComponents: ['Docker', 'VPS', 'systemd'],
  },
  {
    id: 'US-1.5',
    name: 'Chat Interface & Trade Alerts',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-02',
    end: '2026-03-04',
    effort: 'M',
    priority: 'P1',
    description:
      'Outbound Slack + Email alerts for trades, cycle summary, state transitions, failures; notification_logs',
    architectureComponents: ['Notifications', 'Orchestrator'],
  },
  {
    id: 'US-1.7',
    name: 'Dashboard & Visualisation',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-09',
    end: '2026-03-10',
    effort: 'L',
    priority: 'P1',
    description:
      'Web dashboard: 8 pages (Home, Universe, Run History, Portfolio, Opportunity, Order Mgmt, Costs, Roadmap & Architecture); full API',
    architectureComponents: ['Dashboard', 'FastAPI', 'React'],
  },
  {
    id: 'US-1.8',
    name: 'Dashboard VPS Deployment',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-10',
    end: '2026-03-10',
    effort: 'S',
    priority: 'P1',
    description:
      'Deploy dashboard to VPS via Docker; access via VPS IP',
    architectureComponents: ['Dashboard', 'Docker'],
  },
  {
    id: 'US-3.4',
    name: 'UOV Ranking & Queue',
    topic: 'Portfolio & Risk',
    status: 'delivered',
    start: '2026-03-02',
    end: '2026-03-03',
    effort: 'M',
    priority: 'P1',
    description:
      'Hybrid score, z-score, EWMA; ranked BUY execution; queue + swap suggestions',
    architectureComponents: ['UOV Scorer', 'Opportunity Optimizer'],
  },
  {
    id: 'US-3.5',
    name: 'Intelligent Order Management',
    topic: 'Portfolio & Risk',
    status: 'delivered',
    start: '2026-03-05',
    end: '2026-03-06',
    effort: 'M',
    priority: 'P1',
    description:
      'Stop-loss (GTC) after BUY, ATR reassessment, trailing stops, limit dip-buy orders',
    architectureComponents: ['Order Manager', 'Stop-Loss Manager'],
  },
  {
    id: 'US-5.1',
    name: 'Backtesting Engine',
    topic: 'Validation',
    status: 'delivered',
    start: '2026-03-05',
    end: '2026-03-06',
    effort: 'L',
    priority: 'P1',
    description:
      'Replay history, paper broker, walk-forward, promotion report; yfinance + CSV cache',
    architectureComponents: ['Backtesting module'],
  },
  {
    id: 'US-4.4',
    name: 'Agentic Research',
    topic: 'Signals',
    status: 'delivered',
    start: '2026-03-10',
    end: '2026-03-13',
    effort: 'L',
    priority: 'P1',
    description:
      '5 tools (web_search, news_search, sector_search, sec_search, macro_search); all 3 members (Strategy, GPT-4o Skeptic, Gemini Risk) have tool-use loops; shared pipeline-wide budget (35/cycle); Brave primary, Tavily fallback; 37 unit tests',
    architectureComponents: ['Strategy Engine', 'Moderation Panel', 'Research Executor'],
  },
  // --- Pipeline (17) ---
  {
    id: 'US-4.5',
    name: 'Proactive Macro News Intelligence',
    topic: 'Signals',
    status: 'pipeline',
    effort: 'L',
    priority: 'P1',
    description:
      'Scheduled macro/geopolitical scans, second-order impact reasoning, persistent macro state, confidence-scored signals, and auditable macro action planning',
    architectureComponents: ['Data Fetcher', 'Scheduler', 'Strategy Engine', 'Risk Agent'],
  },
  {
    id: 'US-1.6',
    name: 'Slack NL Trade Commands',
    topic: 'Foundation',
    status: 'pipeline',
    effort: 'M–L',
    priority: 'P1',
    description:
      'Inbound Slack: BUY/SELL/REVIEW + ticker; single-ticker pipeline, user intent overwrites decision; Risk can veto',
    architectureComponents: ['Notifications', 'Orchestrator'],
  },
  {
    id: 'US-1.9',
    name: 'Conversational Trading Workflow',
    topic: 'Foundation',
    status: 'pipeline',
    effort: 'L',
    priority: 'P1',
    description:
      'Multi-turn Slack + dashboard chat sessions with shared context, explicit action confirmation, and full conversation/research/action audit trail',
    architectureComponents: ['Notifications', 'Dashboard', 'Orchestrator'],
  },
  {
    id: 'US-2.4',
    name: 'Nemotron Integration Investigation',
    topic: 'Calibration',
    status: 'pipeline',
    effort: 'S',
    priority: 'P2',
    description:
      'Investigate Nemotron 3 Super as candidate moderator/risk model with smoke tests, shadow comparison, and promotion gates',
    architectureComponents: ['Moderation Panel', 'Risk Agent'],
  },
  {
    id: 'US-2.1',
    name: 'Conviction Calibration',
    topic: 'Calibration',
    status: 'pipeline',
    effort: 'M',
    priority: 'P1',
    description:
      'Calibration curve: conviction vs win rate; position sizing by calibrated confidence',
    architectureComponents: ['Strategy Engine'],
  },
  {
    id: 'US-2.2',
    name: 'Dynamic Strategy Weighting',
    topic: 'Calibration',
    status: 'pipeline',
    effort: 'M',
    priority: 'P1',
    description:
      'Rolling hit rate per sub-strategy; weights adjusted by performance, floor/cap',
    architectureComponents: ['Strategy Engine'],
  },
  {
    id: 'US-2.3',
    name: 'Moderator Effectiveness',
    topic: 'Calibration',
    status: 'pipeline',
    effort: 'S',
    priority: 'P2',
    description:
      'Track correct blocks vs opportunity cost per moderator; monthly value-add vs cost',
    architectureComponents: ['Moderation Panel'],
  },
  {
    id: 'US-3.1',
    name: 'Risk-Parity Position Sizing',
    topic: 'Portfolio & Risk',
    status: 'pipeline',
    effort: 'M',
    priority: 'P1',
    description:
      'Size positions inversely to trailing volatility; equal risk contribution',
    architectureComponents: ['Order Manager', 'Risk Agent'],
  },
  {
    id: 'US-3.2',
    name: 'Enhanced Regime Detection',
    topic: 'Portfolio & Risk',
    status: 'pipeline',
    effort: 'M',
    priority: 'P2',
    description:
      'Continuous regime score (VIX, S&P, yields); regime-aware strategy weighting',
    architectureComponents: ['Data Fetcher', 'Strategy Engine'],
  },
  {
    id: 'US-3.3',
    name: 'Correlation-Aware Screening',
    topic: 'Portfolio & Risk',
    status: 'pipeline',
    effort: 'S',
    priority: 'P2',
    description:
      'Flag BUY candidates with high avg correlation to portfolio',
    architectureComponents: ['Risk Agent', 'Universe Screener'],
  },
  {
    id: 'US-4.1',
    name: 'Volume-Weighted Signals',
    topic: 'Signals',
    status: 'pipeline',
    effort: 'S',
    priority: 'P2',
    description:
      'OBV, volume SMA ratio; feed into sub-strategy scoring',
    architectureComponents: ['Data Fetcher', 'Strategy Engine'],
  },
  {
    id: 'US-4.2',
    name: 'Earnings Calendar',
    topic: 'Signals',
    status: 'pipeline',
    effort: 'M',
    priority: 'P2',
    description:
      'Next earnings date; flag "earnings imminent"; post-earnings drift signal',
    architectureComponents: ['Data Fetcher'],
  },
  {
    id: 'US-4.3',
    name: 'Sector Rotation Signal',
    topic: 'Signals',
    status: 'pipeline',
    effort: 'M',
    priority: 'P3',
    description:
      '11 GICS sectors via ETFs; 3-month momentum; overweight/underweight in screening',
    architectureComponents: ['Data Fetcher', 'Universe Screener'],
  },
  {
    id: 'US-5.2',
    name: 'Parameter Sensitivity',
    topic: 'Validation',
    status: 'pipeline',
    effort: 'M',
    priority: 'P2',
    description:
      'Vary RSI, MA, weights, limits; heat maps; robust vs fragile ranges',
    architectureComponents: ['Backtesting module'],
  },
  {
    id: 'US-6.1',
    name: 'ML Trade Scoring (investigation)',
    topic: 'ML / Advanced',
    status: 'pipeline',
    effort: 'L',
    priority: 'P2',
    description:
      'Investigation then (if justified) XGBoost on indicators + fundamentals → forward return',
    architectureComponents: ['Strategy Engine', 'Future ML layer'],
  },
  {
    id: 'US-6.2',
    name: 'Journal Embeddings',
    topic: 'ML / Advanced',
    status: 'pipeline',
    effort: 'M',
    priority: 'P3',
    description:
      'Embeddings for journals; similarity search on new proposals',
    architectureComponents: ['Reporting', 'Future ML layer'],
  },
  {
    id: 'US-6.3',
    name: 'RL Investigation',
    topic: 'ML / Advanced',
    status: 'pipeline',
    effort: 'M',
    priority: 'P3',
    description:
      'Literature + data assessment; decision gate before any implementation',
    architectureComponents: ['Future ML layer'],
  },
]

export const DELIVERED_COUNT = MILESTONES.filter((m) => m.status === 'delivered').length
export const PIPELINE_COUNT = MILESTONES.filter((m) => m.status === 'pipeline').length
export const TOTAL_COUNT = MILESTONES.length
export const PROGRESS_PCT = Math.round((DELIVERED_COUNT / TOTAL_COUNT) * 100)
