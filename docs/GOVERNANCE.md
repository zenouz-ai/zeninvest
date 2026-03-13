---
tags: [governance, security, risk, cost-controls, audit]
status: current
last_updated: 2026-03-11
---

# Governance, Security & Cost Controls

> Governance framework, security measures, risk guardrails, cost management, and audit requirements.

## Purpose

This document defines the governance framework that ensures the investment agent operates safely, transparently, and within acceptable boundaries. It covers human oversight, defense in depth, security guardrails (API keys, prompt injection, rate limiting), the 9 hard risk rules, cost controls with graceful degradation, operational procedures, and the comprehensive audit trail.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Governance Principles](#2-governance-principles)
3. [Security Guardrails](#3-security-guardrails)
4. [Risk Guardrails](#4-risk-guardrails)
5. [Cost Controls](#5-cost-controls)
6. [Operational Controls](#6-operational-controls)
7. [Audit Trail](#7-audit-trail)
8. [Industry Best Practices & Regulatory Alignment](#8-industry-best-practices--regulatory-alignment)
9. [Future Improvements](#9-future-improvements)
10. [Appendix A: Configuration Reference](#appendix-a-configuration-reference)
11. [Appendix B: Database Schema Summary](#appendix-b-database-schema-summary)

---

## 1. Executive Summary

The Investment Agent is an autonomous trading system that uses a multi-LLM pipeline to identify, validate, and execute equity trades via the Trading 212 Practice API. The system is designed to outperform the S&P 500 by 10%+ over a 6-12 month horizon.

**Architecture at a glance:**

```
Orchestrator (every 12h, Mon-Fri)
  +-- Market Data Agent    -> yfinance + Finnhub + Alpha Vantage (per-ticker news, macro intelligence)
  +-- Universe Screener    -> Sector-balanced, cap-tiered candidate discovery
  +-- Strategy Agent       -> Momentum + Mean Reversion + Factor -> Claude Sonnet synthesis
  +-- Moderation Panel     -> GPT-4o (skeptical) + Gemini Flash (risk) -> consensus
  +--                         (receives Claude's market_assessment to challenge)
  +-- Risk Agent           -> Hard rules, VETO power, NEVER overridden by LLMs
  +-- Opportunity Agent    -> UOV scoring + BUY ranking/queueing (no sell authority)
  +-- Execution Agent      -> Market orders + stop-loss + dedup + rate limiting
  +-- Journal & Reporting  -> Per-trade journals, daily + weekly reports
```

This document defines the governance framework, security measures, risk controls, cost management, operational procedures, and audit requirements that ensure the system operates safely, transparently, and within acceptable boundaries at all times.

---

## 2. Governance Principles

### 2.1 Human Oversight

The system is designed as a **human-supervised autonomous agent**, not a fully unsupervised one. The following mechanisms ensure meaningful human oversight:

- **Practice/Demo mode by default.** The Trading 212 API integration targets the demo endpoint (`https://demo.trading212.com/api/v0`). Switching to a live endpoint requires an explicit configuration change and is treated as a major deployment decision requiring sign-off.
- **Pause/Resume control.** A human operator can pause all trading at any time via `--pause` and resume with `--resume`. The paused state is persisted in the database and survives restarts.
- **Force sell capability.** Any position can be force-liquidated immediately via `--force-sell <TICKER>`, bypassing the normal strategy-moderation-risk pipeline.
- **Scheduled execution only.** The system runs on a fixed schedule (configurable via `cycle_frequency`: intraday = 08/12/16 UTC, standard = 07/19 UTC, Monday-Friday). It does not react to intraday events autonomously.
- **Daily and weekly reports.** Automated reports are generated at 21:30 UTC daily and 22:00 UTC Fridays, providing full transparency into decisions, costs, and performance.

### 2.2 Defense in Depth

No single component has unchecked authority. Every trade must pass through multiple independent layers:

| Layer | Component | Authority | Can Be Overridden by LLMs? |
|-------|-----------|-----------|---------------------------|
| 1 | Strategy Agent (Claude Sonnet) | Proposes trades with conviction scores | N/A -- proposes only |
| 2 | Moderation Panel (GPT-4o + Gemini Flash) | Can BLOCK any trade via consensus | N/A -- reviews only |
| 3 | Risk Agent (deterministic Python) | Can REJECT or RESIZE any trade | **No -- never** |
| 4 | Opportunity Agent (UOV optimizer) | Ranks/queues approved BUYs only (shadow or active mode) | **No -- deterministic Python** |
| 5 | Execution Agent (T212 client) | Executes with deduplication | **No -- never** |

The Risk Agent is implemented as pure deterministic Python code (`src/agents/risk/risk_manager.py`). It does not call any LLM and cannot be influenced by prompt injection or model hallucination. Its decisions are final.

### 2.3 Fail-Safe Defaults

The system is designed to fail closed, not open:

- **If the state machine state is unknown, it defaults to ACTIVE with no positions.** The `StateMachine._ensure_state_exists()` method initialises to `ACTIVE` with `peak_portfolio_value=None` and `paused=False`.
- **If any LLM call fails, the trade is skipped.** The orchestrator catches exceptions at every stage and logs errors without proceeding.
- **If the T212 API is unreachable, no trades are placed.** In dry-run mode, a mock portfolio is used; in live mode, the cycle terminates with an error.
- **If cost budgets are exceeded, the system degrades gracefully** rather than spending more. See [Section 5: Cost Controls](#5-cost-controls).
- **If drawdown exceeds 15%, all positions are liquidated automatically.** This is a hard, non-negotiable safety threshold.
- **Order deduplication prevents double-execution.** A 5-minute dedup window (`DEDUP_WINDOW_MINUTES = 5`) prevents the same order from being placed twice.

---

## 3. Security Guardrails

### 3.1 API Key Management

**Principle:** API keys are secrets. They must never appear in source code, configuration files tracked by version control, logs, or LLM prompts.

**Current Implementation**

All API keys are loaded from environment variables via `src/utils/config.py`:

| Environment Variable | Service | Purpose |
|---------------------|---------|---------|
| `T212_API_KEY` | Trading 212 | Trade execution |
| `T212_API_SECRET` | Trading 212 | Authentication |
| `ANTHROPIC_API_KEY` | Anthropic | Claude Sonnet strategy synthesis |
| `OPENAI_API_KEY` | OpenAI | GPT-4o moderation |
| `GOOGLE_AI_API_KEY` | Google AI | Gemini Flash risk assessment |
| `FINNHUB_API_KEY` | Finnhub | Market data + sentiment |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | News sentiment + fundamentals |

Keys are loaded via `python-dotenv` from a `.env` file at the project root. The `.env` file must be listed in `.gitignore` and never committed.

**Key Rotation Schedule**

| Key | Rotation Frequency | Procedure |
|-----|--------------------|-----------|
| T212 API Key/Secret | Every 90 days | Regenerate in T212 dashboard, update `.env`, restart |
| Anthropic API Key | Every 90 days | Regenerate in Anthropic console, update `.env`, restart |
| OpenAI API Key | Every 90 days | Regenerate in OpenAI dashboard, update `.env`, restart |
| Google AI API Key | Every 90 days | Regenerate in Google AI Studio, update `.env`, restart |
| Finnhub API Key | Every 180 days | Regenerate in Finnhub dashboard, update `.env`, restart |
| Alpha Vantage API Key | Every 180 days | Regenerate in Alpha Vantage, update `.env`, restart |

**Key Management Rules**

1. **Never hardcode keys.** All keys are accessed via `Settings.get_env()` which raises `EnvironmentError` if a key is missing.
2. **Never log keys.** The logging configuration (`src/utils/logger.py`) must never include raw API key values. Log redaction should be applied to any output containing authorization headers.
3. **Never pass keys to LLM prompts.** The strategy and moderation prompts (`src/agents/strategy/prompts.py`, `src/agents/moderation/`) receive only market data, portfolio state, and structured signals -- never credentials.
4. **Use separate keys for Practice vs Live.** If migrating to a live T212 account, generate entirely new credentials.

### 3.2 LLM Prompt Injection Defense

Because the system uses three different LLMs, prompt injection is a material risk. The following defenses are in place:

**Structured JSON Output Enforcement**

- The Claude strategy synthesis prompt (`STRATEGY_SYSTEM_PROMPT`) explicitly instructs: *"You must respond with ONLY valid JSON matching the exact schema specified. No markdown, no explanation outside the JSON."*
- The strategy engine (`src/agents/strategy/engine.py`) parses the response as JSON and rejects any response that fails `json.loads()`.
- GPT-4o and Gemini moderation modules are expected to return structured dictionaries with specific keys (`verdict`, `reasoning`, `risk_score`, etc.).

**Input Sanitization**

- Market data inputs (from yfinance, Finnhub, Alpha Vantage) are numeric and structured. They are serialised to JSON strings with length caps before inclusion in prompts:
  - Analyst data: truncated to 3,000 characters
  - News sentiment: truncated to 3,000 characters
  - Portfolio state: truncated to 2,000 characters
- No user-generated free text is included in LLM prompts. All inputs are system-sourced data.

**Output Validation**

- Claude's JSON response is parsed and validated. If parsing fails, the cycle returns `"status": "strategy_error"` and no trades are placed.
- Moderation verdicts must be one of `AGREE`, `DISAGREE`, `MODIFY`, or `SKIP`. Any other value is treated as unavailable.
- The Risk Agent validates all numeric values (allocation percentages, drawdown calculations) independently of LLM outputs.

**Separation of Concerns**

- LLMs **propose** and **review** trades. They cannot **execute** trades directly.
- The Risk Agent and Execution Agent are pure Python with no LLM interaction.
- Even if an LLM were fully compromised, it could only propose trades that still need to pass deterministic risk checks.

### 3.3 Rate Limiting and Circuit Breakers

**Trading 212 API Rate Limiting**

The T212 client (`src/agents/execution/t212_client.py`) implements rate limiting:

- Tracks `x-ratelimit-remaining` from response headers.
- When remaining calls drop below 5, the client pauses for 2 seconds before the next request.
- All API calls use `tenacity` retry with exponential backoff: 3 attempts, 1-4 second wait.
- Every API call is logged to the `api_logs` database table with method, endpoint, status code, duration, and any errors.

**LLM Circuit Breakers**

- The cost tracker (`src/utils/cost_tracker.py`) acts as a circuit breaker for LLM calls.
- Before every LLM call, `check_budget()` is called. If the daily or monthly budget is exceeded, the call is skipped entirely.
- The degradation system (see [Section 5.3](#53-graceful-degradation)) progressively shuts down LLM providers as budgets are consumed.

**Order Deduplication and Stop-Loss**

- The `OrderManager._is_duplicate()` method checks for matching orders (same ticker, direction, and quantity) placed within the last 5 minutes.
- Duplicate orders are logged and skipped with `"status": "skipped", "reason": "duplicate"`.
- After successful BUY executions, the system automatically places a GTC stop-loss order via `OrderManager.place_stop_loss()` using the `stop_loss_pct` from Claude's decision. This protects against downside risk without requiring manual intervention.
- The REDUCE action is supported alongside BUY and SELL — it executes as a partial sell, allowing position trimming without full liquidation.

**Intelligent Order Management**

- **ATR-based stop reassessment**: After each cycle's execution phase, `StopLossManager.reassess_stops()` recalculates stop-loss levels for all held positions using 14-day ATR × configurable multiplier (default 2.0). Stops are clamped to `[min_stop_distance_pct, max_stop_distance_pct]`. By default, stops only tighten (never widen).
- **Software trailing stops**: `StopLossManager.apply_trailing_stops()` tracks a high-water mark (HWM) per position. When price exceeds previous HWM, the stop ratchets up to `HWM × (1 - trail_pct/100)`. Implemented by cancelling the existing T212 stop order and placing a new one (T212 has no native trailing stop API).
- **Limit dip-buy orders**: When strategy outputs `entry_type: "limit_dip"`, the orchestrator routes to `StopLossManager.place_limit_buy()` instead of a market order. The limit price is set at `current_price × (1 - offset_pct/100)`, with offset configurable per-decision or globally.
- All adjustments are persisted to the `stop_loss_adjustments` table and emitted as `order_adjustment` Slack notifications.
- The feature is gated behind `order_management.enabled` in `settings.yaml` (default: `true`). Each sub-feature (reassess_stops, trailing_stops, limit_orders) has its own enable switch.

### 3.4 Network Security

**HTTPS Only**

All external API communication uses HTTPS:

| Service | Base URL | Protocol |
|---------|----------|----------|
| Trading 212 | `https://demo.trading212.com/api/v0` | HTTPS |
| Finnhub | `https://finnhub.io/api/v1` | HTTPS |
| Alpha Vantage | `https://www.alphavantage.co/query` | HTTPS |
| Anthropic API | `https://api.anthropic.com` | HTTPS (via SDK) |
| OpenAI API | `https://api.openai.com` | HTTPS (via SDK) |
| Google AI API | `https://generativelanguage.googleapis.com` | HTTPS (via SDK) |

The T212 client uses `httpx.Client` with a 30-second timeout. All SDK clients (Anthropic, OpenAI, Google) enforce HTTPS by default.

**IP Allowlisting (Recommended)**

If deploying to a fixed infrastructure (e.g., a dedicated VPS or cloud VM), configure firewall rules to restrict outbound traffic to the specific API endpoints listed above. For Trading 212 specifically, restrict the source IP in the T212 API key settings if the feature is available.

### 3.5 Data Protection

**No PII in Prompts**

LLM prompts contain only:

- Portfolio positions (tickers, quantities, values)
- Market data (prices, indicators, fundamentals)
- News sentiment scores (numerical)
- Analyst recommendations (structured data)

No personally identifiable information (names, account numbers, addresses, etc.) is ever included in any LLM prompt.

**Log Redaction**

- API response bodies stored in `api_logs` are truncated to 5,000 characters maximum.
- The T212 client uses Basic Auth via `Authorization: Basic <encoded>` headers. These headers are not logged; only the request body and response body are stored.
- Cost logs (`cost_logs`) store provider name, model, token counts, and cost -- no prompt content.
- Moderation logs store verdicts and reasoning -- the reasoning is the LLM's output, not the input prompt.

**Data Retention**

- The SQLite database stores all historical data indefinitely by default.
- Implement a retention policy (recommended: 12 months for detailed logs, indefinite for portfolio snapshots and orders) as a future improvement.

---

## 4. Risk Guardrails

### 4.1 The 9 Hard Rules

The Risk Agent (`src/agents/risk/risk_manager.py`) enforces non-negotiable rules. These are implemented as deterministic Python functions with no LLM involvement. **No LLM output can override, modify, or bypass these rules.**

| # | Rule | Threshold | Enforcement | Method |
|---|------|-----------|-------------|--------|
| 1 | **Max Single Stock** | No single stock > 15% of portfolio | REJECT or RESIZE | `check_max_single_stock()` |
| 2 | **Max Sector Concentration** | No single sector > 35% of portfolio | REJECT or RESIZE | `check_max_sector()` |
| 3 | **Correlation Limit** | Portfolio avg pairwise correlation < 0.7 | REJECT | `check_correlation()` |
| 4 | **Drawdown State Machine** | >5% drawdown -> CAUTIOUS; >15% -> HALTED (liquidate all) | State transition + REJECT | `check_drawdown()` |
| 5 | **VIX-Based Position Limits** | VIX >25: max 8%; VIX >35: max 5% per position | RESIZE | `check_vix_limit()` |
| 6 | **Daily Loss Halt** | Daily loss >2%: no new buys for 24 hours | REJECT | `check_daily_loss_halt()` |
| 7 | **Cash Floor** | Always maintain >= 10% cash | REJECT or RESIZE | `check_cash_floor()` |
| 8 | **Min Positions** | Minimum 5 positions once invested (prevents over-concentration) | REJECT (on SELL or REDUCE) | `check_min_positions()` |
| 9 | **Cautious State Guard** | In CAUTIOUS mode: no new BUYs, only SELL/REDUCE/HOLD | REJECT (on BUY) | `check_cautious_state()` |

In addition to these risk rules, the Opportunity Agent enforces deterministic execution-capacity limits for BUY ordering (`max_positions` and investable cash above the configured cash floor) before order submission.

**Why These Rules Can Never Be Overridden**

The risk rules exist in a separate execution path from LLM outputs:

1. **Architectural isolation.** The `RiskManager` class imports only `numpy`, `json`, `dataclasses`, and internal config/database modules. It does not import any LLM SDK and has no mechanism to receive LLM instructions.
2. **Sequential gate.** In the orchestrator pipeline (`src/orchestrator/main.py`), every trade must pass through `risk_manager.evaluate_trade()` after moderation and before execution. There is no code path that skips this call.
3. **Deterministic logic.** All thresholds are read from `config/settings.yaml` at startup. The rules are pure mathematical comparisons -- they cannot be "convinced" or "reasoned with."
4. **Verdict finality.** If `evaluate_trade()` returns `verdict="REJECT"`, the orchestrator skips execution unconditionally:
   ```python
   if risk_verdict.verdict == "REJECT":
       logger.info(f"{ticker} REJECTED by risk: {risk_verdict.reasoning}")
       continue
   ```

### 4.2 State Machine Transitions

The system operates in one of three states, persisted in the `system_state` database table:

```
                  drawdown < 5%
              +------------------+
              |                  |
              v                  |
         +--------+         +----------+
         | ACTIVE | ------> | CAUTIOUS |
         +--------+  >5%    +----------+
              ^              |
              |  recovery    | >15% drawdown
              |              v
              |         +---------+
              +-------- | HALTED  |
               manual   +---------+
              recovery     |
                           | -> liquidate_all()
                           v
                      [all positions sold]
```

**State Behaviours**

| State | New Positions | Existing Positions | Max Position Size | Special Actions |
|-------|--------------|-------------------|-------------------|-----------------|
| **ACTIVE** | Allowed | Managed normally | 15% | Normal operation |
| **CAUTIOUS** | Blocked (except adding to winners) | Managed with reduced limits | 8% | Heightened conviction thresholds |
| **HALTED** | Blocked | All liquidated | N/A | `liquidate_all()` called, all trading suspended |

**Transition Logic**

State transitions are evaluated at the start of every cycle in `Orchestrator.run_cycle()`:

```python
drawdown_state = self.risk_manager.get_drawdown_state(current_value, peak_value)
if drawdown_state != current_state:
    self.state_machine.transition(drawdown_state, f"Drawdown check at {current_value:.2f}")
```

The `HALTED` state triggers immediate liquidation of all positions. Recovery from `HALTED` requires manual intervention -- the system does not automatically resume trading.

**Portfolio value for drawdown:** The system uses `totalValue` from T212's `/equity/account/summary` when available. This includes cash, investments, and reserved funds (pending orders). If the summary endpoint is unavailable, it falls back to `cash + invested + reservedForOrders` from the cash endpoint. This ensures pending orders are not misclassified as losses.

### 4.3 Additional CAUTIOUS Mode Restrictions

When in CAUTIOUS state, the `check_cautious_state()` rule enforces:

- **No new positions.** Only adding to existing winning positions is permitted.
- **Max 8% per position** (reduced from the normal 15% limit).
- Conviction thresholds are raised: trades require higher confidence scores to proceed through moderation.

---

## 5. Cost Controls

### 5.1 Per-Provider Daily Budgets

LLM API costs are tracked per-call in the `cost_logs` database table. Each provider has a daily budget:

| Provider | Model | Daily Budget | Cost Per 1M Input Tokens (USD) | Cost Per 1M Output Tokens (USD) |
|----------|-------|-------------|-------------------------------|--------------------------------|
| **Anthropic** | Claude Sonnet | **£1.00/day** | $3.00 | $15.00 |
| **OpenAI** | GPT-4o | **£0.75/day** | $2.50 | $10.00 |
| **Google** | Gemini 2.5 Flash | **£0.50/day** | $0.10 | $0.40 |
| **Total Daily** | -- | **£2.25/day** | -- | -- |

Costs are calculated in USD and converted to GBP at a rate of 0.79 (`USD_TO_GBP = 0.79` in `cost_tracker.py`).

### 5.2 Monthly Cap

- **Monthly total cap: £50.00**
- This cap applies across all providers combined.
- When the monthly cap is reached, **all LLM calls are halted** regardless of individual daily budgets.
- The monthly cap provides a hard ceiling even if daily budgets are not individually exceeded (e.g., during months with many trading days).

### 5.3 Graceful Degradation

When budgets are approached or exceeded, the system degrades gracefully rather than failing abruptly. The `DegradationLevel` enum defines five levels:

```
FULL -> NO_GEMINI -> NO_GPT4O -> NO_STRATEGY -> HALTED
```

| Level | Condition | Behaviour |
|-------|-----------|-----------|
| **FULL** | All budgets within limits | All 3 LLMs active. Full pipeline. |
| **NO_GEMINI** | Google daily budget exceeded | Skip Gemini Flash risk assessment. GPT-4o + Claude still active. |
| **NO_GPT4O** | OpenAI daily budget exceeded (or both moderators exceeded) | Skip GPT-4o moderation. Claude strategy synthesis still active. |
| **NO_STRATEGY** | Anthropic daily budget exceeded | Skip entire strategy cycle. No new trades proposed. |
| **HALTED** | Monthly cap exceeded | All LLM calls halted. System waits for next month. |

**Degradation Logic**

From `cost_tracker.py`:

```python
def get_degradation_level() -> DegradationLevel:
    if monthly_spent >= total_monthly_gbp:
        return DegradationLevel.HALTED
    if not anthropic_ok:
        return DegradationLevel.NO_STRATEGY
    if not openai_ok and not google_ok:
        return DegradationLevel.NO_GPT4O
    if not google_ok:
        return DegradationLevel.NO_GEMINI
    if not openai_ok:
        return DegradationLevel.NO_GPT4O
    return DegradationLevel.FULL
```

**Conviction Threshold Adjustments**

When moderators are unavailable due to budget constraints, conviction thresholds are raised to compensate:

| Moderators Available | Min Conviction to Proceed |
|---------------------|--------------------------|
| 2 (GPT-4o + Gemini) | 60 (standard) |
| 1 (either) | 75 |
| 0 (none) | 85 |

These thresholds are configured in `settings.yaml`:

```yaml
strategy:
  min_conviction: 75
  min_conviction_no_moderators: 85
  min_conviction_one_moderator: 75
```

### 5.4 Alert Thresholds

When any provider reaches **80%** of its daily budget or the monthly total reaches 80%, a warning is logged:

```python
if status.is_at_alert_threshold:
    logger.warning(
        f"{provider} approaching budget limit: "
        f"daily {status.daily_pct_used:.0f}%, monthly {status.monthly_pct_used:.0f}%"
    )
```

The 80% threshold is configurable via `cost_limits.alert_threshold_pct` in `settings.yaml`.

### 5.4.1 Search API Costs (Brave, Tavily)

Brave and Tavily are used for batch universe enrichment (sector/market_cap extraction) and planned Agentic Research. They are **not** tracked in `cost_logs`; usage is logged to `api_logs` and enforced via `search_api_tracker` (2,000 calls/month each).

| API | Pricing | Rate limit | Free tier |
|-----|---------|------------|-----------|
| **Brave Search** | $5.00 per 1,000 requests | 50 RPS | $5 credits/month |
| **Brave Answers** | $4.00 per 1,000 queries + $5/1M input + $5/1M output tokens | 2 RPS | $5 credits/month |
| **Tavily** | $0.008/credit pay-as-you-go; $30/month for 4,000 credits (Project) | — | 1,000 credits/month (Researcher) |

At 2,000 calls/month each: Brave Search ≈ $10 (or partly covered by $5 credits); Brave Answers ≈ $8+ token costs (or partly covered by $5 credits); Tavily ≈ $16 pay-as-you-go or Project plan $30 for 4,000 credits.

### 5.5 Cost Visibility

The system provides multiple cost visibility mechanisms:

- **Per-call logging.** Every LLM call logs provider, model, input/output token counts, cost in GBP, cycle ID, and purpose to the `cost_logs` table.
- **Daily cost summary.** The `get_cost_summary(days=1)` function returns costs grouped by provider.
- **Status command.** `--status` shows current degradation level and today's costs.
- **Daily reports.** Automated reports include cost breakdowns.

---

## 6. Operational Controls

### 6.1 Pause/Resume System

**Pausing**

```bash
poetry run python -m src.orchestrator.main --pause
```

- Sets `system_state.paused = True` in the database.
- All subsequent cycles check `self.state_machine.is_paused` at the start and skip execution if True.
- The paused state is persisted across restarts.

**Resuming**

```bash
poetry run python -m src.orchestrator.main --resume
```

- Sets `system_state.paused = False`.
- The next scheduled cycle will proceed normally.

### 6.2 Force Sell Capability

```bash
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
```

- Directly calls `T212Client.get_position()` to fetch the current holding.
- If a position exists, places a market sell order for the full quantity.
- **Bypasses** the strategy, moderation, and risk pipeline -- this is an emergency action.
- Logged to the `orders` table with `strategy="liquidation"`.

### 6.3 Manual Override Procedures

**Changing System State Manually**

If the system is in HALTED and the operator wants to resume after addressing the underlying issue:

1. **Assess the situation.** Review the daily report and logs.
2. **Pause the system** to prevent any automated action during recovery.
3. **Update the database** state to ACTIVE or CAUTIOUS as appropriate.
4. **Resume the system** when ready.

> **Warning:** Manual state changes should be rare and documented. The HALTED state exists to protect capital. Overriding it prematurely risks further losses.

**Adjusting Risk Thresholds**

Risk thresholds are configured in `config/settings.yaml`. To adjust:

1. Edit the relevant values in `settings.yaml`.
2. Restart the application (the `Settings` singleton is created once at startup).
3. New thresholds take effect on the next cycle.

> **Caution:** Loosening risk thresholds (e.g., increasing `max_single_stock_pct`) increases concentration risk. Any change should be documented with justification.

### 6.4 Incident Response Playbook

**Severity Levels**

| Level | Description | Examples | Response Time |
|-------|-------------|----------|---------------|
| **P1 -- Critical** | System executing unintended trades; data breach; >15% drawdown | Runaway orders, API key leaked | Immediate |
| **P2 -- High** | System not functioning correctly; unexpected losses | Strategy errors, T212 API failures, >5% drawdown | Within 1 hour |
| **P3 -- Medium** | Degraded functionality; cost overruns | LLM budget exceeded, data provider down | Within 4 hours |
| **P4 -- Low** | Minor issues; informational | Single failed API call, log rotation | Next business day |

**P1 Response Procedure**

1. **PAUSE the system immediately.**
   ```bash
   poetry run python -m src.orchestrator.main --pause
   ```
2. **Assess open positions.** Check the T212 dashboard or use `--status`.
3. **Liquidate if necessary.** If positions are at risk, use `--force-sell` for individual positions or manually liquidate via the T212 interface.
4. **Investigate root cause.** Review logs in `logs/`, `api_logs` table, and `risk_decisions` table.
5. **Rotate any compromised API keys.** If a key leak is suspected, regenerate all keys immediately.
6. **Document the incident.** Record timeline, root cause, and remediation steps.
7. **Resume only after root cause is resolved and verified.**

**P2 Response Procedure**

1. **Review system status.** `--status` and daily report.
2. **Check state machine.** If in CAUTIOUS, the system is already self-restricting.
3. **Review error logs** for the failing component.
4. **Fix and test** (dry-run mode first).
5. **Resume normal operation.**

---

## 7. Audit Trail

### 7.1 What Is Logged

The system maintains a comprehensive audit trail across ten database tables:

| Table | What Is Logged | Key Fields |
|-------|---------------|------------|
| `system_state` | Current state machine state, peak value, drawdown, pause status | `state`, `peak_portfolio_value`, `current_drawdown_pct`, `paused` |
| `orders` | Every order placed or attempted | `ticker`, `action`, `quantity`, `price`, `status`, `strategy`, `conviction`, `moderation_result`, `risk_result`, `dedup_key` |
| `strategy_decisions` | Every strategy proposal from Claude | `cycle_id`, `ticker`, `action`, `conviction`, `reasoning`, `raw_response_json` |
| `moderation_logs` | Every moderation verdict from GPT-4o and Gemini | `cycle_id`, `ticker`, `moderator`, `verdict`, `reasoning`, `growth_score`, `risk_score`, `consensus` |
| `risk_decisions` | Every risk evaluation | `cycle_id`, `ticker`, `verdict`, `rules_checked_json`, `triggered_rules_json`, `reasoning` |
| `cost_logs` | Every LLM API call cost | `provider`, `model`, `input_tokens`, `output_tokens`, `cost_gbp`, `cycle_id`, `purpose` |
| `api_logs` | Every external API call (T212, Finnhub, Alpha Vantage, brave_search, brave_answers, tavily) | `service`, `method`, `endpoint`, `status_code`, `duration_ms`, `error`; search APIs have monthly limits (2k Brave Search, 2k Brave Answers, 1k Tavily) via `search_api_tracker`. Web search fallback (Brave/Tavily for analyst/news when Finnhub/AV fail) is logged here. |
| `research_logs` | Agentic research tool calls (US-4.4) | `cycle_id`, `member` (strategy/skeptic/risk), `ticker`, `tool_name`, `query`, `provider`, `cache_hit`; per-member caps 20/8/7, total 35/cycle; budget monitoring via ResearchBudget. |
| `portfolio_snapshots` | Portfolio state at end of each cycle | `total_value_gbp`, `cash_gbp`, `num_positions`, `positions_json`, `state` |
| `instruments` | Company profiles and screening state | `ticker`, `sector`, `industry`, `market_cap`, `business_summary`, `data_available`, `last_screened_at` |
| `opportunity_score_snapshots` | Per-cycle UOV scores/components for every evaluated ticker | `cycle_id`, `ticker`, `stage`, `uov_raw`, `uov_z`, `uov_final`, `uov_ewma`, `moderation_consensus`, `risk_verdict`; for HOLD/QUEUED (stage `strategy_hold`/`strategy_queued`), moderation_consensus and risk_verdict are "not invoked" |
| `opportunity_queue` | Active queued BUY opportunities awaiting execution | `ticker`, `queued_cycles`, `last_uov_ewma`, `last_seen_cycle_id`, `metadata_json` |

### 7.2 Traceability

Every cycle generates a unique `cycle_id`. Scheduled cycles use `scheduled_YYYYMMDD_HHMMSS` (scheduler creates Run; orchestrator receives and updates it—one Run per cycle). Manual/dashboard-triggered cycles use `cycle_YYYYMMDD_HHMM_<6-hex>`. The cycle_id links all decisions, costs, and orders from that cycle across all tables, enabling end-to-end traceability for any trade:

```
cycle_20260225_0700_a1b2c3
  +-- strategy_decisions: Claude proposed BUY AAPL_US_EQ at 8% allocation
  +-- moderation_logs: GPT-4o AGREE, Gemini AGREE -> consensus APPROVED
  +-- risk_decisions: APPROVE (all 9 rules passed)
  +-- cost_logs: Anthropic £0.042, OpenAI £0.018, Google £0.003
  +-- orders: BUY 5 x AAPL_US_EQ @ $187.50 = £750.00 -> filled
```

### 7.2.1 Rejected Stock Tracking

Stocks considered but **not traded** are also fully traceable. The cycle output includes a `rejected_stocks` list recording every rejection with:

- **Stage** that blocked the trade: `strategy_hold` (HOLD), `strategy_queued` (QUEUED), `moderation` (BLOCKED), or `risk` (REJECT); for HOLD/QUEUED, moderation_consensus and risk_verdict are "not invoked"
- **Opportunity gate stage**: `opportunity_queue` when approved BUYs are deferred by UOV queueing/capacity rules; `opportunity_filtered` when below queue threshold or queue expiry
- **Stage reason**: structured human-readable explanation (e.g. "Awaiting 2nd cycle for promotion", "Capacity gated (no slot or cash)", "Below UOV queue threshold (uov_ewma X < Y)") included in cycle summaries and notifications
- **UOV diagnostics**: `uov_ewma` and `uov_z` included for opportunity-stage rejections to support threshold calibration
- **Company metadata**: industry, market cap, business description
- **Conviction** score from Claude's strategy assessment
- **Rejection reason**: Claude's HOLD/QUEUED reasoning, moderation consensus, or triggered risk rules; cycle summary includes `rejected_by_action` (counts by strategy action: BUY, HOLD, QUEUED)

This enables post-cycle analysis of missed opportunities and filter calibration. All rejections are also persisted in the `strategy_decisions`, `moderation_logs`, `risk_decisions`, and `opportunity_score_snapshots` tables for long-term querying across cycles.

### 7.3 Log Files

In addition to database logging, the system writes structured log files to the `logs/` directory:

- `orchestrator.log` -- Main control flow
- `strategy_engine.log` -- Strategy synthesis
- `moderation_panel.log` -- Moderation consensus
- `risk_manager.log` -- Risk evaluations
- `t212_client.log` -- API interactions
- `order_manager.log` -- Order execution
- `cost_tracker.log` -- Budget tracking

Each log entry includes timestamp, logger name, level, and message. File handlers log at DEBUG level for maximum detail; console handlers log at INFO level.

### 7.4 Trade Journals

Every executed trade generates a detailed Markdown journal file with:

- Trade details (action, ticker, shares, price, value, weight)
- Company profile (industry, market cap, business description)
- Strategy reasoning and conviction score
- Moderation panel results (all three verdicts)
- Risk verdict (rules checked, triggered rules, reasoning)
- Market context (regime, VIX, news sentiment)
- Technical indicators and fundamentals
- Exit conditions and targets
- Portfolio state at time of trade

---

## 8. Industry Best Practices & Regulatory Alignment

### 8.1 Regulatory Context

While this system currently operates in **Practice/Demo mode only** and does not execute real trades with real money, its design aligns with regulatory requirements for automated trading systems in anticipation of potential live deployment.

### 8.2 SEC Regulation SCI (Systems Compliance and Integrity)

The SEC's Regulation SCI requires entities with automated trading systems to:

- **Maintain comprehensive policies and procedures** for system capacity, integrity, resiliency, and security. This document and the accompanying codebase address these requirements.
- **Have business continuity and disaster recovery plans.** The pause/resume mechanism and state persistence provide basic continuity. See [Section 9](#9-future-improvements) for planned enhancements.
- **Provide notification of systems disruptions.** The logging and reporting infrastructure enables timely identification and communication of issues.

### 8.3 FCA Algorithmic Trading Requirements

The UK Financial Conduct Authority (FCA), under MiFID II implementation, requires firms using algorithmic trading to:

- **Have effective systems and risk controls** to ensure trading systems are resilient and have sufficient capacity. The 9 hard risk rules, state machine, and circuit breakers address this.
- **Have appropriate thresholds and limits** to prevent erroneous orders. Position limits, sector caps, and cash floors prevent outsized or erroneous exposures.
- **Prevent the system from creating or contributing to disorderly trading conditions.** The daily loss halt, VIX-based limits, and drawdown state machine prevent the system from trading aggressively during market stress.
- **Ensure the system cannot be used for market abuse.** The system trades only on the basis of quantitative signals and publicly available data.

### 8.4 MiFID II Algorithmic Trading (Article 17)

Key MiFID II requirements for algorithmic trading and their mapping to this system:

| MiFID II Requirement | System Implementation |
|---------------------|----------------------|
| Kill functionality to urgently cancel orders | `--pause` command, `--force-sell`, `liquidate_all()` |
| Pre-trade risk controls | 9 hard rules in Risk Agent, checked before every order |
| Post-trade monitoring | Portfolio snapshots, daily/weekly reports, order history |
| Real-time monitoring | Cycle-level logging, cost tracking, state machine |
| Annual self-assessment | This governance document; to be reviewed annually |
| Record keeping (5 years) | All decisions, orders, and costs stored in SQLite |
| Stress testing | Dry-run mode, configurable risk thresholds |

### 8.5 Best Practices Adopted

- **Separation of signal generation and execution.** Strategy (LLM) and execution (T212 client) are separate modules.
- **Independent risk management.** The Risk Agent is architecturally independent of the strategy pipeline.
- **Order deduplication.** Prevents flash-crash-style repeated order submission.
- **Rate limiting.** Respects API rate limits to prevent market disruption.
- **Deterministic risk rules.** Not subject to model drift, hallucination, or prompt injection.
- **Comprehensive logging.** Full audit trail for regulatory review.

---

## 9. Future Improvements

The following enhancements are planned or recommended to strengthen the governance framework:

### 9.1 Multi-Factor Authentication

- Require MFA for any operation that changes system state (pause/resume, force sell, threshold changes).
- Implement a simple challenge-response or TOTP mechanism for CLI commands.

### 9.2 Real-Time Alerting

- **Slack integration.** Send alerts to a dedicated Slack channel for:
  - State machine transitions (ACTIVE -> CAUTIOUS -> HALTED)
  - Budget threshold warnings (80% daily/monthly)
  - Trade executions (all BUY/SELL actions)
  - System errors (P1/P2 incidents)
- **Email notifications.** Daily summary emails with portfolio performance and cost breakdown.
- **PagerDuty/Opsgenie integration.** For P1 critical incidents requiring immediate human response.

### 9.3 Kill Switch Webhook

- Expose an HTTP endpoint (authenticated) that immediately pauses the system and optionally liquidates all positions.
- Enables remote emergency shutdown from a mobile device or monitoring dashboard.
- Webhook should be protected with API key + IP allowlisting at minimum.

### 9.4 Human-in-the-Loop for Large Trades

- For trades exceeding a configurable threshold (e.g., >10% of portfolio or >£1,000 in value):
  - Pause execution and send an approval request via Slack/email.
  - Wait for human confirmation before proceeding.
  - Time out and cancel the trade if no response within a configurable window (e.g., 30 minutes).
- This adds a critical safety layer for significant portfolio changes while maintaining autonomy for smaller trades.

### 9.5 Backtesting Validation

- **Implemented.** A backtesting engine, paper broker, walk-forward runner, and promotion report (safe to deploy / hold) are in place. See `docs/BACKTESTING.md` and `docs/WALK_FORWARD_VALIDATION.md`.
- Before deploying any strategy change to the live pipeline:
  - Run the updated strategy against 12+ months of historical data via the backtest CLI.
  - Compare Sharpe ratio, max drawdown, and alpha vs. the benchmark.
  - Require backtested performance (and walk-forward promotion outcome) to meet minimum thresholds before approval.

### 9.6 Enhanced Data Protection

- **Encryption at rest.** Encrypt the SQLite database file.
- **Log rotation and retention.** Implement automatic log rotation (e.g., 30 days for detailed logs) and archival.
- **Data anonymization.** For any shared reporting, strip identifying information.

### 9.7 Infrastructure Improvements

- **Health check endpoint.** Expose a simple HTTP health check for monitoring tools.
- **Metrics export.** Export key metrics (portfolio value, drawdown, cost, cycle duration) to Prometheus/Grafana.
- **Containerised deployment.** The existing `docker-compose.yml` provides a foundation; add health checks, resource limits, and restart policies.
- **Secret management.** Migrate from `.env` files to a proper secret manager (HashiCorp Vault, AWS Secrets Manager, or similar).

### 9.8 Governance Process Improvements

- **Quarterly governance review.** Review this document quarterly and update thresholds, procedures, and future plans.
- **Change management.** Any change to risk thresholds, LLM models, or trading parameters requires a documented change request with justification and rollback plan.
- **Incident post-mortems.** After any P1 or P2 incident, conduct a blameless post-mortem and document learnings.

---

## Appendix A: Configuration Reference

All configurable parameters are in `config/settings.yaml`:

```yaml
trading:
  mode: active                            # active or practice
  base_url: https://demo.trading212.com/api/v0
  cycle_frequency: intraday                # intraday (3 cycles) or standard (2 cycles)
  cycle_hours: 4
  cycle_times_utc: ["08:00", "12:00", "16:00"]  # when intraday; ["07:00", "19:00"] when standard
  market_days: [0, 1, 2, 3, 4]           # Mon-Fri
  max_positions: 15
  min_position_pct: 2
  max_position_pct: 15
  cash_floor_pct: 10
  benchmark_ticker: "^GSPC"

risk:
  max_single_stock_pct: 15
  max_sector_pct: 35
  max_correlation: 0.7
  cautious_drawdown_pct: 5
  halt_drawdown_pct: 15
  daily_loss_halt_pct: 2
  vix_high: 25
  vix_extreme: 35
  min_positions: 5

strategy:
  momentum_weight: 0.35
  mean_reversion_weight: 0.30
  factor_weight: 0.35
  min_conviction: 75
  min_conviction_no_moderators: 85
  min_conviction_one_moderator: 75

moderation:
  require_consensus: true
  consensus_threshold: 2

models:
  strategy: claude-sonnet-4-5-20250929
  moderator_1: gpt-4o
  moderator_2: gemini-2.5-flash

universe:
  max_candidates: 30              # New stocks screened per cycle
  candidates_per_sector: 3        # Min per sector (avoid concentration)
  large_cap_pct: 0.70             # 70% large cap ($10B+)
  mid_cap_pct: 0.20               # 20% mid cap ($2B-$10B)
  small_cap_pct: 0.10             # 10% small cap ($300M-$2B)
  large_cap_min: 10000000000
  mid_cap_min: 2000000000
  small_cap_min: 300000000
  screening_cooldown_hours: 24    # Hours before re-screening a stock

cost_limits:
  anthropic_daily_gbp: 1.00
  openai_daily_gbp: 0.75
  google_daily_gbp: 0.50
  total_monthly_gbp: 50.00
  alert_threshold_pct: 80

opportunity:
  enabled: true
  mode: shadow                      # shadow or active
  immediate_threshold_z: 1.0
  queue_threshold_z: 0.2
  queue_ttl_cycles: 3
  swap_delta_z: 1.0
  ewma_half_life_cycles: 6
  weights: {...}                    # deterministic weighted hybrid features
  penalties: {...}                  # stage penalties (HOLD/BLOCKED/REJECT/RESIZE)
```

---

## Appendix B: Database Schema Summary

All data is stored in a SQLite database managed via SQLAlchemy + Alembic migrations.

| Table | Purpose | Records Per Cycle |
|-------|---------|-------------------|
| `system_state` | Singleton state machine row | Updated 1x |
| `instruments` | Cached T212 instrument metadata + `last_screened_at` cooldown | Refreshed weekly; `last_screened_at` updated per cycle |
| `portfolio_snapshots` | Portfolio state at each cycle end | 1 per cycle |
| `orders` | All orders (placed, dry-run, failed) | 0-15 per cycle |
| `strategy_decisions` | Claude's trade proposals | 0-15 per cycle |
| `moderation_logs` | GPT-4o + Gemini verdicts | 0-45 per cycle (3 per trade) |
| `risk_decisions` | Risk agent evaluations | 0-15 per cycle |
| `opportunity_score_snapshots` | UOV scoring output per evaluated ticker | 0-30+ per cycle |
| `opportunity_queue` | Active queued BUY opportunities | 0-30 active rows |
| `cost_logs` | LLM API call costs | 1-5 per cycle |
| `api_logs` | All external API calls | 10-50 per cycle |
| `market_data_cache` | Cached OHLCV and fundamentals | Varies |
| `news_sentiment_cache` | Cached news sentiment data | Varies |
| `performance_metrics` | Rolling Sharpe, Sortino, drawdown, win rates by strategy | Updated per cycle / daily |
| `trade_outcomes` | Per-trade P&L (BUY→SELL), conviction and moderator linkage | 0-15+ per cycle (on SELL) |
| `notification_logs` | Outbound alert attempts (Slack/email): sent, failed, skipped, deduped | 0-20+ per cycle |
| *(planned)* `slack_command_log` | Inbound Slack trade command audit: raw message, parsed intent, cycle_id, order_id, status | When US-1.6 implemented |

---

*This document should be reviewed and updated at least quarterly, or whenever significant changes are made to the system architecture, risk parameters, or operational procedures.*

---

## Related Notes

- [Architecture](ARCHITECTURE.md) — pipeline flow, state machine, database schema
- [Deployment](DEPLOYMENT.md) — VPS setup, Docker, monitoring, backups
- [Order Management](ORDER_MANAGEMENT_PROJECT.md) — stop-loss, trailing stops, limit orders
- [Data Rationale](DATA_RATIONALE.md) — data sources, indicators, fundamental metrics
- [Sophistication Roadmap](SOPHISTICATION_ROADMAP.md) — planned enhancements and prioritisation
