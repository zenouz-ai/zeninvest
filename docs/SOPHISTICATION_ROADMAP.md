---
title: Sophistication Roadmap
tags: [roadmap, planning, user-stories, priorities]
status: active
last_updated: 2026-03-30
related: [ARCHITECTURE.md, GOVERNANCE.md, AUDIT_INDEX.md]
---

# Sophistication Roadmap

> Prioritised backlog of enhancements: user stories, acceptance criteria, and delivery status.
> **Canonical machine-readable source:** `dashboard/frontend/src/data/roadmap.ts`

---

## Overview

**At a glance:** Delivered **37** · Pipeline **14** · Total **51** · Progress **73%**

### Priority rules

1. **Production safety before new capability**
2. **Execution quality before any live-account posture change**
3. **Data-gated learning stories only after enough `trade_outcomes` exist**
4. **Lower-leverage investigations stay later unless tied to an immediate business need**

### Current delivery order

| Order | Story | Why now |
|-------|-------|---------|
| 1 | **US-1.11** Branch-Based Evolution Runner | Next evolution story now that learning-loop context, attribution, and CI are live |

### Near-term umbrella tracks

| Track | Stories | Status |
|-------|---------|--------|
| **Production Access & Safety** | US-7.8, US-7.7, US-7.5, US-7.3, US-7.2 | Delivered |
| **Conversational Operator Workflow** | US-1.6, US-1.9 | Delivered |
| **Zen Evolution Engine** | US-1.10 (Phase 1); US-1.11–1.14 gated | Phase 1 delivered |
| **Open-Source Launch** | US-8.1 | Delivered |
| **Execution Quality & Fill Recovery** | US-7.3, US-7.2 | Delivered |
| **Entry Quality Guards** | US-4.2, US-3.3 | Delivered |
| **Learning Loop & Attribution** | US-2.5, US-2.6 | Delivered |
| **Calibration & Adaptation** | US-2.1, US-2.2, US-2.3 | Data-gated |
| **Research / Advanced** | US-2.4, US-3.2, US-4.3, US-5.2, US-6.1–6.3 | Later / optional |

---

## Delivered stories (37)

Delivered stories are condensed here. Full acceptance criteria lived in earlier revisions of this file and in the feature-specific docs linked below.

| ID | Name | Delivered | Key docs |
|----|------|-----------|----------|
| **US-1.1** | Performance Tracking | 2026-03-05 | — |
| **US-1.2** | Trade Outcome Tracker | 2026-03-05 | — |
| **US-1.3** | Performance Dashboard (CLI) | 2026-03-05 | — |
| **US-1.4** | Deploy POC to VPS | 2026-03-06 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| **US-1.5** | Chat Interface & Trade Alerts | 2026-03-07 | — |
| **US-1.6** | Slack NL Trade Commands | 2026-03-15 | [CONVERSATIONAL_TRADING_WORKFLOW.md](CONVERSATIONAL_TRADING_WORKFLOW.md) |
| **US-1.7** | Dashboard & Visualisation | 2026-03-10 | [DASHBOARD.md](DASHBOARD.md), [UX_AUDIT.md](UX_AUDIT.md) |
| **US-1.7.1** | Dashboard UX Phase 1 | 2026-03-18 | [UX_AUDIT.md](UX_AUDIT.md) |
| **US-1.7.2** | Dashboard UX Phase 2 | 2026-03-18 | [UX_AUDIT.md](UX_AUDIT.md) |
| **US-1.7.3** | Visual Design System | 2026-03-19 | [dashboard-style-guide.md](../dashboard/frontend/dashboard-style-guide.md) |
| **US-1.8** | Dashboard VPS Deployment | 2026-03-10 | [DEPLOYMENT.md](DEPLOYMENT.md) §13 |
| **US-1.9** | Conversational Trading Workflow | 2026-03-28 | [CONVERSATIONAL_TRADING_WORKFLOW.md](CONVERSATIONAL_TRADING_WORKFLOW.md) |
| **US-1.10** | Evolution Planner Phase 1 | 2026-03-28 | [ZEN_EVOLUTION_ENGINE.md](ZEN_EVOLUTION_ENGINE.md) |
| **US-2.5** | Market Guidance Layer | 2026-03-29 | [MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md](MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md) |
| **US-2.6** | Strategy Episode Attribution | 2026-03-29 | [MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md](MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md) |
| **US-3.1** | Risk-Parity Position Sizing | 2026-03-22 | — |
| **US-3.3** | Correlation-Aware Screening | 2026-03-28 | — |
| **US-3.4** | UOV Ranking & Queueing | 2026-03-03 | — |
| **US-3.5** | Intelligent Order Management | 2026-03-08 | [ORDER_MANAGEMENT_PROJECT.md](ORDER_MANAGEMENT_PROJECT.md) |
| **US-3.5a** | Tiered Profit-Lock Floors | 2026-03-30 | [ORDER_MANAGEMENT_PROJECT.md](ORDER_MANAGEMENT_PROJECT.md) |
| **US-3.6** | Active Swing Rotation Strategy | 2026-03-12 | — |
| **US-4.1** | Volume-Weighted Signals | 2026-03-22 | — |
| **US-4.2** | Earnings Calendar | 2026-03-28 | — |
| **US-4.4** | Agentic Research | 2026-03-14 | [AGENTIC_RESEARCH.md](AGENTIC_RESEARCH.md) |
| **US-4.5** | Proactive Macro Intelligence | 2026-03-20 | [PROACTIVE_MACRO_NEWS_INTELLIGENCE.md](PROACTIVE_MACRO_NEWS_INTELLIGENCE.md), [WORLD_NEWS_DASHBOARD.md](WORLD_NEWS_DASHBOARD.md) |
| **US-5.1** | Backtesting Engine | 2026-03-04 | [BACKTESTING.md](BACKTESTING.md) |
| **US-7.0** | Production Audit & Safety Fixes | 2026-03-19 | [TRADING_SYSTEM_AUDIT.md](TRADING_SYSTEM_AUDIT.md) |
| **US-7.0a** | Agent Logic Audit Fixes | 2026-03-20 | [AGENT_LOGIC_AUDIT.md](AGENT_LOGIC_AUDIT.md) |
| **US-7.0b** | Formal Verification Fixes | 2026-03-21 | [FORMAL_VERIFICATION_AUDIT.md](FORMAL_VERIFICATION_AUDIT.md) |
| **US-7.1** | Dashboard Authentication | 2026-03-21 | — |
| **US-7.2** | Partial Fill Resubmission | 2026-03-29 | — |
| **US-7.3** | Execution Quality & Slippage | 2026-03-29 | — |
| **US-7.4** | Integration Test Coverage | 2026-03-22 | — |
| **US-7.5** | Quick Hardening Slice | 2026-03-27 | [TRADING_SYSTEM_AUDIT.md](TRADING_SYSTEM_AUDIT.md) |
| **US-7.6** | VPS Runtime Stability | 2026-03-24 | [DEPLOYMENT.md](DEPLOYMENT.md) |
| **US-7.7** | Dashboard HTTPS Domain | 2026-03-25 | [DEPLOYMENT.md](DEPLOYMENT.md) §13 |
| **US-7.8** | Safe Public Demo Dashboard | 2026-03-29 | — |
| **US-8.1** | Open-Source Launch Preparation | 2026-03-30 | [OPEN_SOURCE_LAUNCH.md](OPEN_SOURCE_LAUNCH.md) |

Operational update (2026-03-30): the US-2.6 attribution pipeline now includes daily automated git scanning (02:00 UTC) with auto-confirmed episode publication for dashboard visibility.

---

## Current state: POC (v1.0)

Fully functional autonomous trading agent on Trading 212 Practice API with a multi-LLM pipeline, running in Docker Compose on VPS.

**What the POC establishes:**
- End-to-end pipeline: Data → Screen → Strategy → Moderation → Risk → Execution → Journal → Notifications
- Multi-LLM adversarial architecture (Claude + GPT-4o + Gemini)
- Deterministic risk guardrails with VETO power
- UOV opportunity layer, active-swing exits, cost-aware degradation
- Performance tracking, trade outcomes, backtesting with walk-forward validation
- Full operator dashboard at `https://zeninvest.zenouz.ai`

**What the POC still lacks:**
- Calibration of strategy weights and conviction using enough live + backtest evidence
- Learning/adaptation beyond the delivered deterministic sizing and signal stack

---

## Design principles

1. **Measure before you build** — collect live data first; only build what the data justifies
2. **Incremental, not revolutionary** — each phase builds on the previous; no big rewrites
3. **POC compatibility** — all enhancements integrate with the existing pipeline
4. **Evidence-based decisions** — no technique adopted without literature review
5. **Personal quant experience first** — insights, dashboards, and learning over institutional features

---

## Pipeline stories (full detail)

### US-8.1: Open-Source Launch Preparation

**Value:** Community-ready infrastructure enabling the repo to go public as ZenInvest by Zenouz.ai
**Effort:** Medium (2–3 days)
**Stage:** Delivered (2026-03-30)
**Detailed plan:** [OPEN_SOURCE_LAUNCH.md](OPEN_SOURCE_LAUNCH.md)

**Phase A — Repo hygiene:** Remove nested `Investment-agent/` subdirectory; remove `old-origin` remote; confirm `origin → https://github.com/zenouz-ai/zeninvest.git`.

**Phase B — Legal & community:** `LICENSE` (MIT), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1), `SECURITY.md` (responsible disclosure).

**Phase C — GitHub infrastructure:** Issue/PR templates, `.github/workflows/ci.yml` (pytest + mypy, `INVESTMENT_AGENT_USE_INMEMORY_DB=1`).

**Acceptance Criteria:**
- [x] No nested `Investment-agent/` directory; all tests pass
- [x] `git remote -v` shows only `origin → https://github.com/zenouz-ai/zeninvest.git`
- [x] `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` present
- [x] `.github/` issue templates, PR template, and CI workflow present
- [x] CI runs pytest + mypy on push/PR to main; green without external API keys

---

### US-1.11: Branch-Based Evolution Runner

**Value:** Isolated branch workspace, scoped code edits, semantic change summary, validation artifact pack, and review-ready PR generation
**Effort:** Medium–Large
**Stage:** Later / gated (requires CI and branch governance foundations)

---

### US-1.12–US-1.14: Evolution Engine follow-on phases

| ID | Name | Value |
|----|------|-------|
| **US-1.12** | Policy-Gated Promotion | Manual build/deploy approvals, environment protections, rollback metadata |
| **US-1.13** | Low-Risk Auto-Promotion | Selective autonomy for docs/dashboard polish after manual promotion proves reliable |
| **US-1.14** | System-Initiated Improvements | Suggest-first cleanup, tests, docs using branch/validation/approval gates |

**Guardrails:** No unrestricted strategy/risk/execution/allocation promotion. No secrets or broker credentials. Manual approval mandatory for financially sensitive changes.

---

### US-2.1: Conviction Calibration

**Value:** Position sizing by calibrated conviction (potential +2–5% annually)
**Effort:** Medium (3–4 days)
**Stage:** Data-gated (requires ~50 trades per calibration bin)

**Acceptance Criteria:**
- [ ] Calibration curve: conviction vs win rate (bins 50–60, 60–70, 70–80, 80+)
- [ ] Min 30 trades per bin before activating
- [ ] Position sizing: `size = base_size * calibration_factor`
- [ ] Logged for audit; fallback to current behaviour if insufficient data

---

### US-2.2: Dynamic Strategy Weighting

**Value:** Stops allocating to strategies that aren't working in current regime
**Effort:** Medium (3–4 days)
**Stage:** Data-gated (requires ~50 trades)

**Acceptance Criteria:**
- [ ] Rolling 30-day hit rate per sub-strategy (momentum, mean_reversion, factor)
- [ ] Weights: `new_weight = base_weight * rolling_hit_rate / avg_hit_rate`; floor 15%, cap 50%
- [ ] Weight changes logged; configurable `dynamic_weighting: true/false`

---

### US-2.3: Moderator Effectiveness Analysis

**Value:** Understand which moderator adds value; informs cost optimisation
**Effort:** Small (2–3 days)
**Stage:** Data-gated (requires ~100 trades)

**Acceptance Criteria:**
- [ ] Track: trades GPT-4o/Gemini blocked that would have lost (correct) vs made money (opportunity cost)
- [ ] Monthly report: moderator value-add vs API cost
- [ ] Flag if moderator blocks wrong >60% of the time

---

### US-2.4: Nemotron Integration Investigation

**Value:** Potential moderation/risk cost reduction and provider diversification
**Effort:** Investigation (2–4 days)
**Stage:** Later / optional
**Plan:** [Nemotron_3_Super_Integration_Investigation.md](Nemotron_3_Super_Integration_Investigation.md) (archived — investigation stalled)

---

### US-3.2: Enhanced Regime Detection

**Value:** Regime-aware strategy selection improves hit rate
**Effort:** Medium (3–4 days)
**Stage:** Later / optional

**Acceptance Criteria:**
- [ ] Continuous regime score (VIX level/trend, S&P vs 50/200 MA, yield curve slope)
- [ ] Regime feeds dynamic strategy weighting (US-2.2)
- [ ] Logged for post-hoc analysis

---

### US-4.3: Sector Rotation Signal

**Value:** Sector momentum over long term
**Effort:** Medium (3–5 days)
**Stage:** Later / optional

**Acceptance Criteria:**
- [ ] 11 GICS sectors via ETF proxies; 3-month momentum ranking
- [ ] Overweight top 3, underweight bottom 3 in screening
- [ ] Sector momentum score to Claude as context

---

### US-5.2: Parameter Sensitivity Analysis

**Value:** Focus tuning on parameters that matter
**Effort:** Medium (3–4 days)
**Stage:** Later / optional

**Acceptance Criteria:**
- [ ] Vary RSI, MA periods, strategy weights, allocation limits
- [ ] Heat maps: return/Sharpe sensitivity
- [ ] Document robust vs fragile parameter ranges

---

### US-6.1: Gradient-Boosted Trade Scoring

**Value:** Potentially +3–7% annual (requires 500+ trade outcomes)
**Effort:** Large (investigation + implementation)
**Stage:** Later / optional

**Investigation:** Literature review; feature importance on trade data; cross-validation >5% improvement required. If negative, skip and document.

---

### US-6.2: Trade Journal Embeddings & Similarity Search

**Value:** "Have we seen this pattern before?" context for proposals
**Effort:** Medium (3–5 days)
**Stage:** Later / optional

---

### US-6.3: Reinforcement Learning Investigation

**Value:** Uncertain; investigate only
**Effort:** Investigation (3–5 days)
**Stage:** Later / optional

**Gate:** Proceed only if expected Sharpe improvement > 0.3 with interpretable policy.

---

### US-7.5 (remaining backlog)

The quick hardening slice is delivered. Broader backlog remains parked:
- [ ] Remaining medium/low agent-logic and trading-system findings
- [ ] P4-1: SQL-level atomic cost budget
- [ ] P4-2: DB thread safety
- [ ] P4-4: Halted ticker denial list

---

## Resource allocation

| Resource | Availability | Strengths |
|----------|-------------|-----------|
| **Project Lead** | Part-time (evenings/weekends) | PhD Mathematics, DS in finance, strategy, final approver |
| **Claude Code Opus 4.6** | Cloud, primary | Architecture, complex logic, strategy, investigation |
| **Codex 5.3+** | Local VS Code, secondary | Implementation, tests |

| Task Type | Primary | Reviewer |
|-----------|---------|----------|
| Architecture & complex logic | Claude Code | Project Lead |
| New DB models & migrations | Claude Code | Codex (tests) |
| Signal/indicator additions | Codex | Claude Code |
| Dashboard & reporting | Codex | Project Lead |
| ML investigation & maths | Claude Code + Project Lead | Project Lead |
| VPS deployment & ops | Project Lead | — |

---

## Integration guarantees

1. **Database:** New tables via Alembic migrations; no breaking changes
2. **Pipeline:** New steps as post-cycle or pre-strategy hooks; orchestrator flow unchanged
3. **Config:** New keys in settings.yaml with defaults; existing config unchanged
4. **Tests:** New features use in-memory SQLite fixture pattern
5. **Fallback:** Every feature has a disable switch
6. **Logging:** New computations logged to database for audit

---

## Data enrichment

**Instrument enrichment (delivered):** ~5,477 US equities have sector, market_cap, industry, and business_summary from bulk/backfill. Strategy prompt uses Instrument as fallback when yfinance returns sparse data.

---

## Related notes

- [Architecture](ARCHITECTURE.md) — pipeline flow, state machine, database schema
- [Audit Index](AUDIT_INDEX.md) — cross-reference of all audit findings
- [Agentic Research](AGENTIC_RESEARCH.md) — US-4.4 tool access plan
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md) — US-1.9 unified multi-turn plan
- [Proactive Macro Intelligence](PROACTIVE_MACRO_NEWS_INTELLIGENCE.md) — US-4.5 macro scanning
- [Governance](GOVERNANCE.md) — risk rules, cost controls, audit trail
- [Competitive Analysis](COMPETITIVE_ANALYSIS.md) — positioning vs alternatives
- [Presentation](PRESENTATION.md) — stakeholder deck overview
