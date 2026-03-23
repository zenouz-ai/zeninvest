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
  'Hardening',
  'ML / Advanced',
  'Open-Source / Community',
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

/** All milestones from SOPHISTICATION_ROADMAP shown in dashboard roadmap */
export const MILESTONES: Milestone[] = [
  // --- Delivered ---
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
  {
    id: 'US-7.0',
    name: 'Production Audit & Safety Fixes',
    topic: 'Hardening',
    status: 'delivered',
    start: '2026-03-19',
    end: '2026-03-20',
    effort: 'M',
    priority: 'P0',
    description:
      '34 findings (3C+6H+12M+13L). Phase 1: no-retry on POST/DELETE, write-before-execute, liquidate_all status mapping, stop atomicity, parse-failure safety, session leaks. Phase 2: committed cash tracking, cycle timeout, exception safety. 12 of 34 fixed.',
    architectureComponents: ['Order Manager', 'Execution', 'Risk Agent', 'Orchestrator'],
  },
  {
    id: 'US-7.0a',
    name: 'Agent Logic Audit Fixes',
    topic: 'Hardening',
    status: 'delivered',
    start: '2026-03-20',
    end: '2026-03-20',
    effort: 'M',
    priority: 'P0',
    description:
      '27 findings (5C+7H+9M+6L). All Critical+High fixed: MODIFY verdicts as conditional AGREE, CAUTION 25% allocation reduction, conviction/allocation clamping, Gemini score bounds, orphaned "submitting" sync, ticker dedup. 36 new tests.',
    architectureComponents: ['Strategy Engine', 'Moderation Panel', 'Order Manager', 'Orchestrator'],
  },
  {
    id: 'US-7.0b',
    name: 'Formal Verification Fixes',
    topic: 'Hardening',
    status: 'delivered',
    start: '2026-03-21',
    end: '2026-03-21',
    effort: 'M',
    priority: 'P0',
    description:
      '18 findings (3C+7W+8I). Phase 1: scheduler max_instances=1, resume warnings. Phase 2: trade_without_stop alert, OpportunityQueue QUEUED→EXECUTING→EXECUTED lifecycle, portfolio re-query before BUY, decision chain integrity check. 18 new tests. 12 invariants verified.',
    architectureComponents: ['Scheduler', 'Orchestrator', 'Opportunity Optimizer', 'Notifications'],
  },
  {
    id: 'US-7.1',
    name: 'Dashboard Authentication',
    topic: 'Hardening',
    status: 'delivered',
    start: '2026-03-21',
    end: '2026-03-21',
    effort: 'S',
    priority: 'P0',
    description:
      'APIKeyMiddleware on all /api/* endpoints; DASHBOARD_API_KEY env var; configurable public_routes for GET-only demo exposure; write endpoints always protected; 33 tests',
    architectureComponents: ['Dashboard', 'FastAPI'],
  },
  {
    id: 'US-1.7.3',
    name: 'Dashboard Visual Design System',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-22',
    end: '2026-03-22',
    effort: 'M',
    priority: 'P1',
    description:
      'Syne heading font, full CSS token system (--color-*, --shadow-*, --radius-*, --transition-*), glass-dark panels, 72px violet grid, brand gradient violet→cyan→emerald, blurred nav, pill active state, 4 shared primitives (Panel, MetricCard, StatusPill, SectionHeader)',
    architectureComponents: ['Dashboard', 'React'],
  },
  {
    id: 'US-4.5',
    name: 'Proactive Macro News Intelligence',
    topic: 'Signals',
    status: 'delivered',
    start: '2026-03-22',
    end: '2026-03-23',
    effort: 'L',
    priority: 'P1',
    description:
      'Daily scheduled macro_scan (06:00 UTC), persisted MacroState (regime/confidence/top_signals/action_plan) + MacroSignalLog audit trail, deterministic regime derivation (RISK_ON/RISK_OFF/NEUTRAL) with optional Claude-backed second-order reasoning, cycle-time injection into strategy prompt and moderation market context, 48h staleness guard, 25 tests',
    architectureComponents: ['Data Fetcher', 'Scheduler', 'Strategy Engine', 'Risk Agent'],
  },
  {
    id: 'US-1.7.4',
    name: 'World News Dashboard Tab',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-23',
    end: '2026-03-23',
    effort: 'M',
    priority: 'P1',
    description:
      'Persistent MacroHeadline archive with keyword-based categorisation (fed, rates, trade, earnings, inflation, jobs, gdp, market), 5 REST endpoints (/api/macro/*), World News page with regime card, regime timeline, expandable headline feed with category filters, action plan section, sector snapshot. Compact macro conditions bar on Dashboard Home. No LLMs/Brave/Tavily required — uses existing Finnhub + AV data. 23 new tests.',
    architectureComponents: ['Dashboard', 'Data Fetcher', 'React'],
  },
  // --- Pipeline ---
  {
    id: 'US-1.6',
    name: 'Slack NL Trade Commands',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-23',
    end: '2026-03-23',
    effort: 'M–L',
    priority: 'P1',
    description:
      'Inbound Slack trade commands via Socket Mode: regex-first NL parser (BUY/SELL/REVIEW + ticker + quantity/amount), single-ticker pipeline with user intent override, CommandGateway, large order confirmation flow, SlackCommandLog audit trail, CLI entry point. 43 new tests.',
    architectureComponents: ['Notifications', 'Orchestrator'],
  },
  {
    id: 'US-1.9',
    name: 'Conversational Trading Workflow',
    topic: 'Foundation',
    status: 'delivered',
    start: '2026-03-23',
    end: '2026-03-23',
    effort: 'L',
    priority: 'P1',
    description:
      'Skeleton delivered: ChatSession/ChatTurn DB models, SessionManager CRUD stub, dashboard chat API endpoints. Full multi-turn workflow (LLM reasoning, Slack thread continuity, research tools) deferred.',
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
    status: 'delivered',
    start: '2026-03-22',
    end: '2026-03-22',
    effort: 'M',
    priority: 'P1',
    description:
      '60-day inverse-vol BUY overlay with vol floor + target-vol scaler; persist Claude size vs risk-parity size; BUY execution uses delta-to-target semantics',
    architectureComponents: ['Strategy Engine', 'Risk Agent', 'Order Manager', 'Dashboard'],
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
    status: 'delivered',
    start: '2026-03-22',
    end: '2026-03-22',
    effort: 'S',
    priority: 'P2',
    description:
      'OBV + 20-day volume ratio in indicator output; momentum and mean-reversion scoring; moderator context surfaced',
    architectureComponents: ['Data Fetcher', 'Strategy Engine', 'Moderation Panel'],
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
  {
    id: 'US-7.2',
    name: 'Partial Fill Resubmission',
    topic: 'Hardening',
    status: 'pipeline',
    effort: 'M',
    priority: 'P2',
    description:
      'Detect partial fills and resubmit unfilled remainder in the next cycle',
    architectureComponents: ['Order Manager', 'Execution'],
  },
  {
    id: 'US-7.3',
    name: 'Execution Quality & Slippage',
    topic: 'Hardening',
    status: 'pipeline',
    effort: 'M',
    priority: 'P2',
    description:
      'Track slippage and improve execution quality with timing and benchmark metrics',
    architectureComponents: ['Order Manager', 'Reporting'],
  },
  {
    id: 'US-7.4',
    name: 'Integration Test Coverage',
    topic: 'Hardening',
    status: 'delivered',
    start: '2026-03-22',
    end: '2026-03-22',
    effort: 'M',
    priority: 'P1',
    description:
      'Shared in-memory orchestrator harness; end-to-end run_cycle coverage, orphaned-decision detection, live state transitions, and manual reset recovery',
    architectureComponents: ['Orchestrator', 'State Machine', 'Testing'],
  },
  {
    id: 'US-7.5',
    name: 'Remaining Audit Backlog',
    topic: 'Hardening',
    status: 'pipeline',
    effort: 'L',
    priority: 'P2',
    description:
      'Consolidated backlog: 15 medium/low (agent logic), 22 medium/low (trading system), 7 phase 3+4 (formal verification). Includes HALTED auto-recovery, market hours check, DB constraints, atomic cost budget.',
    architectureComponents: ['Orchestrator', 'Order Manager', 'Risk Agent', 'Scheduler'],
  },
  {
    id: 'US-8.1',
    name: 'Open-Source Launch Preparation',
    topic: 'Open-Source / Community',
    status: 'pipeline',
    effort: 'M',
    priority: 'P0',
    description:
      'Remove nested repo, clean git remotes, add MIT LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, GitHub issue/PR templates, and GitHub Actions CI (pytest + mypy). Prerequisite for zenouz-ai/zeninvest going public.',
    architectureComponents: ['CI/CD', 'GitHub Actions'],
  },
]

export const DELIVERED_COUNT = MILESTONES.filter((m) => m.status === 'delivered').length
export const PIPELINE_COUNT = MILESTONES.filter((m) => m.status === 'pipeline').length
export const TOTAL_COUNT = MILESTONES.length
export const PROGRESS_PCT = Math.round((DELIVERED_COUNT / TOTAL_COUNT) * 100)
