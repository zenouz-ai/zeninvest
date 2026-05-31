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
  run_type: 'scheduled' | 'manual' | 'dry_run' | 'slack_command' | 'refresh'
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
    audit_summary?: {
      datasets_total?: number
      succeeded?: number
      failed?: number
      partial?: number
      skipped?: number
      degraded?: boolean
      failed_keys?: string[]
      partial_keys?: string[]
    } | null
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
  profit_lock_status?: string | null
  profit_lock_required_price_gbp?: number | null
  profit_lock_stop_price_gbp?: number | null
  profit_lock_protected_qty?: number | null
  held_hours?: number | null
  held_days?: number | null
  profit_per_day_pct?: number | null
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

export interface PublicUniverseItem {
  ticker: string
  name: string | null
  sector: string | null
  industry: string | null
  market_cap_bucket: string
  status: string
  last_screened_at: string | null
}

export interface PublicPortfolioPosition {
  ticker: string
  sector: string | null
  allocation_pct: number
  pnl_band: string
  protection_status: string
}

export interface PublicPortfolioSector {
  sector: string
  allocation_pct: number
}

export interface PublicPortfolioProtectionSummary {
  protected_count: number
  needs_lock_count: number
  exit_required_count: number
  inactive_count: number
}

export interface PublicPortfolioSnapshot {
  timestamp: string
  num_positions: number
  positions_visible: number
  cash_pct: number
  invested_pct: number
  value_index: number
  pnl_band: string
  positions: PublicPortfolioPosition[]
  sector_allocations: PublicPortfolioSector[]
  protection_summary: PublicPortfolioProtectionSummary
}

export interface PublicPortfolioHistoryPoint {
  timestamp: string
  value_index: number
}

export interface PublicRunSummary {
  started_at: string
  completed_at: string | null
  run_type: string
  status: string
  duration_seconds: number | null
  stocks_screened: number | null
  decisions_made: number | null
  orders_placed: number | null
  audit_status: string
  audit_degraded: boolean
}

export interface PublicOpportunityPreview {
  ticker: string
  name: string | null
  sector: string | null
  stage: string
  action: string
  score_band: string
  last_updated: string
}

export interface StopLossCurrent {
  ticker: string
  stop_price: number | null
  source: string
  profit_lock_status?: string | null
  profit_lock_required_price_gbp?: number | null
  profit_lock_stop_price_gbp?: number | null
  profit_lock_protected_qty?: number | null
}

export interface Order {
  id: number
  timestamp: string
  ticker: string
  action: 'BUY' | 'SELL' | 'REDUCE'
  order_type: string
  quantity: number
  price: number | null
  decision_price?: number | null
  limit_price?: number | null
  stop_price?: number | null
  value_gbp: number | null
  filled_quantity?: number | null
  remaining_quantity?: number | null
  slippage_bps?: number | null
  status: string
  strategy: string | null
  conviction: number | null
  t212_order_id?: string | null
  resubmitted_from_order_id?: number | null
  warning_note?: string | null
  error_message?: string | null
}

export interface ExecutionQualitySummary {
  count: number
  mean_bps: number | null
  p50_bps: number | null
  p95_bps: number | null
  best_bps: number | null
  worst_bps: number | null
}

export interface RecentPartialFill {
  id: number
  timestamp: string
  ticker: string
  action: 'BUY' | 'SELL' | 'REDUCE'
  requested_quantity: number
  filled_quantity: number
  remaining_quantity: number
  status: string
  strategy: string | null
  resubmission_eligible: boolean
  resubmitted_from_order_id?: number | null
}

export interface ExecutionQuality {
  window_days: number
  warning_threshold_bps: number
  warning_min_fills: number
  warning_breached: boolean
  warning_message: string | null
  overall: ExecutionQualitySummary
  buy: ExecutionQualitySummary
  exit: ExecutionQualitySummary
  recent_partial_fills: RecentPartialFill[]
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

export interface PublicMacroState {
  timestamp: string
  regime: 'RISK_ON' | 'RISK_OFF' | 'NEUTRAL'
  confidence_score: number
  top_signals: Array<{ signal_type: string; signal_text: string; source: string }>
  action_plan: {
    summary?: string
    sector_implications?: Array<{ sector: string; bias: string; confidence: number; rationale: string }>
    risks?: string[]
    opportunities?: string[]
  }
  sector_summary: string | null
  economic_highlights: string | null
}

export interface GuidanceSectorScore {
  sector: string
  score: number
  label: 'favored' | 'neutral' | 'avoid'
  rationale: string | null
  evidence: string[]
}

export interface PublicGuidanceSectorScore {
  sector: string
  label: 'favored' | 'neutral' | 'avoid'
  rationale: string | null
}

export interface PublicGuidanceSnapshot {
  timestamp: string
  mode: 'active' | 'shadow'
  status: string
  regime: string
  confidence_score: number
  freshness_hours: number | null
  rationale: string | null
  prompt_summary: string | null
  sector_scores: PublicGuidanceSectorScore[]
}

export interface GuidanceSnapshot {
  id: number
  cycle_id: string
  timestamp: string
  mode: 'active' | 'shadow'
  status: string
  regime: string
  confidence_score: number
  freshness_hours: number | null
  rationale: string | null
  prompt_summary: string | null
  bias_payload: Record<string, unknown>
  evidence_summary: Record<string, unknown>
  sector_scores: GuidanceSectorScore[]
}

export interface CycleContextSnapshot {
  cycle_id: string
  run_type: string
  captured_at: string
  repo_sha: string | null
  config_hash: string | null
  strategy_prompt_hash: string | null
  strategy_fingerprint_hash: string | null
  risk_fingerprint_hash: string | null
  execution_fingerprint_hash: string | null
  guidance_snapshot_id: number | null
  guidance_mode: string | null
  prompt_guidance_summary: string | null
  applied_screening_bias: Record<string, unknown>
  pre_guidance_candidate_count: number | null
  post_guidance_candidate_count: number | null
  pre_guidance_sector_distribution: Record<string, number>
  post_guidance_sector_distribution: Record<string, number>
  active_strategy_episode_ids: number[]
}

export interface EpisodeImpactSummary {
  window_1d_cycles: number
  window_7d_cycles: number
  window_30d_cycles: number
  pre_cycle_count: number
  post_cycle_count: number
  screening_conversion_delta: number
  low_sample_warning: boolean
  overlap_warning: boolean
  observational_only: boolean
}

export interface StrategyChangeEvidence {
  id: number
  commit_sha: string
  committed_at: string
  author_name: string | null
  title: string
  summary: string | null
  affected_files: string[]
}

export interface StrategyChangeEpisode {
  id: number
  status: 'proposed' | 'confirmed' | 'rejected'
  title: string
  summary: string
  change_type: string
  review_confidence: number
  commit_start_sha: string | null
  commit_end_sha: string | null
  effective_start_at: string
  effective_end_at: string | null
  confirmed_at: string | null
  rejected_at: string | null
  notes: string | null
  evidence?: StrategyChangeEvidence[]
  impact_summary?: EpisodeImpactSummary | null
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
  command_kind?: string | null
  execution_mode?: string | null
  target_order_class?: string | null
  target_tickers_json?: string | null
  rejection_reason: string | null
  response_message: string | null
  result_json?: string | null
}

export interface CommandStats {
  total: number
  by_status: Record<string, number>
  by_action: Record<string, number>
}

// --- Conversational Trading ---

export interface ChatTurn {
  id: number
  session_id: number
  turn_index: number
  role: 'user' | 'assistant' | 'system'
  channel_type: 'dashboard' | 'slack' | null
  message_text: string
  intent_json?: Record<string, unknown> | null
  resolution_json?: Record<string, unknown> | null
  response_json?: Record<string, unknown> | null
  created_at: string | null
}

export interface ChatWorkflowStep {
  id: number
  session_id: number
  turn_id: number | null
  step_key: string
  status: string
  label: string | null
  detail: string | null
  provider: string | null
  model: string | null
  tool_name: string | null
  cost_gbp: number | null
  latency_ms: number | null
  detail_json?: Record<string, unknown> | null
  started_at: string | null
  completed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ChatAction {
  id: number
  session_id: number
  turn_id: number | null
  action_type: string
  status: string
  title: string | null
  ticker: string | null
  payload_json?: Record<string, unknown> | null
  preview_text: string | null
  result_json?: Record<string, unknown> | null
  requires_confirmation: boolean
  rejection_reason: string | null
  expires_at: string | null
  confirmed_at: string | null
  executed_at: string | null
  created_at: string | null
  updated_at: string | null
  version: number
}

export interface ChatResearchLog {
  id: number
  session_id: number
  turn_id: number | null
  tool_name: string
  provider: string | null
  query: string | null
  result_summary: string | null
  cache_hit: boolean
  latency_ms: number | null
  created_at: string | null
}

export interface ChatCostSummary {
  llm_calls: number
  llm_cost_gbp: number
  research_calls: number
  research_cost_usd: number
  research_cost_gbp: number
  total_cost_gbp: number
  by_provider_gbp: Record<string, number>
  by_model_gbp: Record<string, number>
  research_by_provider_gbp: Record<string, number>
}

export interface ChatSessionSummary {
  id: number
  status: string
  channel_type: 'dashboard' | 'slack'
  channel_session_key: string | null
  last_channel_type: 'dashboard' | 'slack' | null
  user_id: string | null
  title: string | null
  started_at: string | null
  last_activity_at: string | null
  ended_at: string | null
  linked_cycle_id: string | null
  last_message_text: string | null
  last_message_role: 'user' | 'assistant' | 'system' | null
  pending_actions_count: number
}

export interface ChatSessionDetail extends ChatSessionSummary {
  context_json?: Record<string, unknown> | null
  turns: ChatTurn[]
  actions: ChatAction[]
  research_logs: ChatResearchLog[]
  workflow_steps: ChatWorkflowStep[]
  cost_summary?: ChatCostSummary | null
  turn_mode?: string | null
  evidence_blocks?: Record<string, unknown> | null
  citations?: Array<Record<string, unknown>>
  related_tickers?: Array<Record<string, unknown>>
  committee_views?: Array<Record<string, unknown>>
  confidence?: number | null
  next_actions?: string[]
  warnings?: Array<Record<string, unknown>>
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
