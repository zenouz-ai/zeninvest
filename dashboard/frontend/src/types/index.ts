// API Response Types
export interface Event {
  id: number
  timestamp: string
  event_type: string
  source: string
  message: string
  metadata_json?: Record<string, any>
}

export interface Run {
  id: number
  cycle_id: string
  run_type: 'scheduled' | 'manual' | 'dry_run' | 'slack_command'
  started_at: string
  completed_at: string | null
  status: 'running' | 'completed' | 'failed'
  summary_json?: {
    stocks_screened?: number
    num_trades?: number
    num_rejected?: number
    duration_seconds?: number
    stocks_reviewed?: number
    decisions_made?: number
    orders_placed?: number
    counts?: {
      broker_orders_submitted?: number
      stop_adjustments?: number
      queued?: number
      skipped?: number
      risk_rejected?: number
      strategy_deferred?: number
    }
  }
}

export interface Instrument {
  ticker: string
  name: string
  sector: string
  industry: string
  market_cap: number
  last_screened_at: string | null
  data_available: boolean
}

export interface UniverseBubbleItem extends Instrument {
  investigated: boolean
  uov_raw: number | null
  uov_z: number | null
  uov_ewma: number | null
  decision_count: number
  buy_count: number
  sell_count: number
  reduce_count: number
  hold_count: number
  hold_qty: number
  sold_qty: number
  research_calls: number
  research_calls_latest_cycle: number
}

/** Single moderator output in committee */
export interface ModerationEntry {
  moderator: string
  verdict: string
  reasoning?: string
  growth_score?: number
  risk_score?: number
  confidence_score?: number
  consensus?: string
}

/** Full strategy LLM output */
export interface StrategyFull {
  action: string
  conviction?: number
  target_allocation_pct?: number
  risk_parity_target_allocation_pct?: number
  risk_parity_trailing_vol_pct?: number
  risk_parity_applied?: boolean
  primary_strategy?: string
  reasoning?: string
  timestamp: string
  growth_potential?: string
  risk_level?: string
  exit_conditions?: string
  news_sentiment_summary?: string
  market_assessment?: string
  portfolio_commentary?: string
  stop_loss_pct?: number
  expected_holding_period?: string
  upside_target_pct?: number
  raw_response_json?: unknown
}

/** Full risk LLM output */
export interface RiskFull {
  verdict: string
  reasoning?: string
  proposed_allocation_pct?: number
  adjusted_allocation_pct?: number
  triggered_rules_json?: string
  rules_checked_json?: string
  triggered_rules?: unknown
}

/** Single agentic research call made during a cycle for a ticker */
export interface ResearchCall {
  member: string
  tool_name: string
  query: string
  num_results: number | null
  provider: string | null
  cache_hit: boolean
  latency_ms: number | null
  cost_usd: number | null
  results_summary: string | null
  created_at: string | null
}

export interface InstrumentDetail extends Instrument {
  label: string | null
  last_decision: {
    cycle_id?: string
    strategy?: StrategyFull
    moderation?: ModerationEntry[] | null
    risk?: RiskFull
    research?: ResearchCall[] | null
    scope_note?: string | null
    pipeline_note?: string | null
    latest_cycle_research_calls?: number
    total_research_calls?: number
    execution_summary?: {
      last_buy?: {
        timestamp: string
        status: string
        quantity: number
      }
      last_sell?: {
        timestamp: string
        status: string
        quantity: number
      }
    }
  } | null
}

export interface Position {
  ticker: string
  quantity: number
  value_gbp: number
  pnl_gbp: number
  pnl_pct: number
  sector: string | null
}

export interface PortfolioSnapshot {
  timestamp: string
  total_value_gbp: number
  cash_gbp: number
  invested_gbp: number
  pnl_gbp: number
  pnl_pct: number
  num_positions: number
  positions: Position[]
}

export interface PortfolioHistoryStart {
  timestamp: string | null
}

export interface Order {
  id: number
  timestamp: string
  ticker: string
  action: 'BUY' | 'SELL' | 'REDUCE'
  order_type: string
  quantity: number
  price: number | null
  limit_price?: number | null
  stop_price?: number | null
  value_gbp: number | null
  status: string
  strategy: string | null
  conviction: number | null
  t212_order_id?: string | null
  error_message?: string | null
}

// --- Macro / World News ---

export interface MacroState {
  id: number
  timestamp: string
  regime: 'RISK_ON' | 'RISK_OFF' | 'NEUTRAL'
  confidence_score: number
  source: string
  top_signals: Array<{ signal_type: string; signal_text: string; source: string }>
  action_plan: {
    summary?: string
    portfolio_bias?: string
    confidence_score?: number
    sector_implications?: Array<{ sector: string; bias: string; confidence: number; rationale: string }>
    risks?: string[]
    opportunities?: string[]
  }
  sector_summary: string | null
  economic_highlights: string | null
}

export interface MacroHeadline {
  id: number
  headline: string
  source: string
  published_at: string
  url: string | null
  category: string | null
}

export interface MacroSummary {
  regime: string | null
  confidence_score: number | null
  top_signal: string | null
  headline_count_7d: number
  category_counts: Record<string, number>
  last_updated: string | null
}

// --- Slack Trade Commands ---

export interface SlackCommand {
  id: number
  timestamp: string | null
  channel_id: string | null
  user_id: string | null
  raw_message: string
  ticker: string | null
  action: string | null
  cycle_id: string | null
  order_id: number | null
  status: string
  rejection_reason: string | null
  response_message: string | null
}

export interface CommandStats {
  total: number
  by_status: Record<string, number>
  by_action: Record<string, number>
}

// --- Evolution Planner ---

export interface EvolutionValidationCheck {
  id: string
  label: string
  scope: string
  required: boolean
}

export interface EvolutionRepoDoc {
  title: string
  path: string
  reason: string
}

export interface EvolutionCodeArea {
  label: string
  paths: string[]
  reason: string
}

export interface EvolutionRepoContext {
  touched_areas: string[]
  docs: EvolutionRepoDoc[]
  code_areas: EvolutionCodeArea[]
  repo_constraints: string[]
  related_roadmap_items: string[]
}

export interface EvolutionRiskPolicy {
  risk_class: 'LOW' | 'MEDIUM' | 'HIGH'
  touched_areas: string[]
  phase_1_gate: string
  future_build_mode: string
  future_deploy_gate: string
  backtest_required: boolean
  protected_surfaces: string[]
}

export interface EvolutionPhaseCapabilities {
  mode: string
  planning_enabled: boolean
  build_enabled: boolean
  deploy_enabled: boolean
  auto_promote_enabled: boolean
  reason: string
}

export interface EvolutionPlan {
  id: number
  version: number
  status: string
  summary: string
  objective: string | null
  touched_areas: string[]
  excluded_areas: string[]
  assumptions: string[]
  clarification_questions: string[]
  confidence_score: number | null
  risk_class: 'LOW' | 'MEDIUM' | 'HIGH'
  risk_reasons: string[]
  repo_context: EvolutionRepoContext
  implementation_steps: string[]
  validation_matrix: EvolutionValidationCheck[]
  risk_policy: EvolutionRiskPolicy
  phase_capabilities: EvolutionPhaseCapabilities
  created_at: string | null
}

export interface EvolutionMessage {
  id: number
  role: 'operator' | 'planner' | 'system'
  message_type: string
  message_text: string
  metadata: Record<string, unknown>
  created_at: string | null
}

export interface EvolutionRun {
  id: number
  run_kind: string
  status: string
  summary: Record<string, unknown>
  worker_label: string | null
  branch_name: string | null
  commit_sha: string | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface EvolutionArtifact {
  id: number
  run_id: number | null
  artifact_type: string
  title: string
  content: unknown
  created_at: string | null
}

export interface EvolutionApproval {
  id: number
  approval_type: string
  status: string
  requested_by: string | null
  decided_by: string | null
  notes: string | null
  created_at: string | null
  decided_at: string | null
}

export interface EvolutionDeployment {
  id: number
  approval_id: number | null
  environment: string
  status: string
  deploy_ref: string | null
  rollback_ref: string | null
  metadata: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface EvolutionRequestSummary {
  id: number
  status: string
  title: string
  objective: string | null
  risk_class: 'LOW' | 'MEDIUM' | 'HIGH' | null
  requested_by: string | null
  source_channel: string
  touched_areas: string[]
  open_questions_count: number
  latest_plan_version: number
  created_at: string | null
  updated_at: string | null
}

export interface EvolutionRequestDetail extends EvolutionRequestSummary {
  request_text: string
  excluded_areas: string[]
  assumptions: string[]
  clarification_questions: string[]
  required_validations: EvolutionValidationCheck[]
  phase_capabilities: EvolutionPhaseCapabilities
  latest_plan: EvolutionPlan
  messages: EvolutionMessage[]
  runs: EvolutionRun[]
  artifacts: EvolutionArtifact[]
  approvals: EvolutionApproval[]
  deployments: EvolutionDeployment[]
}

// Utility function to clean ticker format for display
export function cleanTicker(ticker: string): string {
  return ticker.replace(/_US_EQ$/, '').replace(/_UK_EQ$/, '').replace(/\._/g, '.')
}
