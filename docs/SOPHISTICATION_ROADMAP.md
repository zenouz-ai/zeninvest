# Sophistication Roadmap

> Public roadmap for delivered capabilities, active waves, and later-stage enhancement themes.

## Overview

ZenInvest is still positioned as a proof-of-concept system, but it already contains substantial end-to-end functionality across trading, observability, research, backtesting, and operator tooling.

The roadmap uses a **Wave + Gate + ICE** framework (see the canonical repo for full story IDs):

1. **Production safety** before new capability
2. **Execution quality** before live-account posture change
3. **Live influence** stays data-gated; **diagnostics and shadow** work does not
4. Lower-leverage investigations stay in later waves unless tied to an active epic

**Current counts (machine-readable source in the repo):** **54 delivered · 24 pipeline · 78 total (~69%)**.

## Delivered Themes

Major delivered themes include:

- end-to-end pipeline execution
- dashboard and observability (including per-phase timing, latency spine US-9.1/US-9.11, production scorecard US-9.12)
- conversational trading workflows
- backtesting and walk-forward validation
- opportunity ranking and queueing
- agentic research
- macro intelligence
- execution-quality hardening
- authentication and safe public demo surfaces
- evolution planner Phase 1 (planner-only)
- pace-aligned exits with north-star KPIs
- decision-quality evaluation foundation (US-6.6) and moderator effectiveness (US-2.3)
- committee debate telemetry (US-9.13)
- **Wave 1 decision-quality depth:** rejected-decision funnel diagnostics (US-6.7 Tier 1)
- **Wave 1 Track B memory (shadow-only):** vector similar-case search (US-6.2), optional Neo4j sector/regime panel (US-6.4), Graphiti-ready episodes JSON (US-6.5)
- agentic-operability hardening: prompt hashing 3/3, chat/embedding budgets, durable research cache, parallel moderation, failure-mode catalog, golden tests

## Wave 1 — Evidence & Ops (data/memory **complete**; verification foundation **active**)

Wave 1 data/memory pipeline stories delivered (2026-06-21):

| Epic | Stories | Outcome |
|------|---------|---------|
| **OPS-1** | US-9.12 | Production latency scorecard — US-9.5 exit confirmed (truncation 0%) |
| **EQ-1** | US-6.7 | Rejected-decision funnel Tier 1 — parquet, dashboard, evaluate funnel block |
| **MEM-1** | US-6.2 → US-6.4 → US-6.5 | Track B operator tools: embeddings search, **optional** Neo4j graph panel, episodes JSON |

**Verification foundation (active):** Before any learning policy can influence live decisions, the promotion verifier is being hardened — benchmark-relative alpha (not beta-contaminated raw PnL), regime-stratified gates (RISK_ON / RISK_OFF / NEUTRAL), power-calibrated thresholds, and a pre-registered committee-debate ablation. This is a prerequisite for all Wave 2 learning promotion.

**Track B clarifications (public):**

- Full live audit lives in **SQLite** — not Neo4j.
- **Embeddings**, **Neo4j**, and **episodes JSON** are independent paths from the same weekly export; use only what you need.
- The live committee does **not** query Neo4j or embeddings today (`memory_inject_strategy` false and unwired).
- Shadow `challenger_memory` reads exported JSONL — not the graph.

These Wave 1 items do **not** require live ML influence gates.

## Wave 2 — Data-gated calibration (**active next**)

Blocked until enough `trade_outcomes` exist:

- conviction calibration (US-2.1)
- dynamic strategy weighting (US-2.2)
- memory curation policy — typed lesson schema, dedup/decay/value-weighting, regime-stratified precision gate (prerequisite before any memory influences live decisions)
- MLflow platform when experiment volume warrants (US-6.8)
- US-6.7 Tier 2 reject-inference research (only if diagnostics show material bias)

## Wave 3 — Evolution automation

Zen Evolution Engine follow-ons (after Wave 1 foundations):

- branch-based change execution (US-1.11)
- policy-gated promotion (US-1.12)
- low-risk auto-promotion only after manual trust (US-1.13)
- system-initiated improvements (US-1.14)

## Wave 4 — Parked optional

- alternative provider investigations
- gradient-boosted trade scoring and RL research (shadow only)
- enhanced regime detection, sector rotation, parameter sensitivity
- relational / supply-chain graph (**US-9.7** — prefer embedded Kùzu over expanding Neo4j if ever built)
- Phoenix traces, Opik pilot

## Agentic maturity (delivered + deferred)

**Delivered zero-infra slices:** per-phase timing, committee prompt hashing, budget enforcement, durable research cache, parallel moderation, committee debate telemetry, failure modes catalog, golden tests, latency observability platform, production latency scorecard.

**Deferred:** supply-chain graph, distributed trace stacks, external prompt playgrounds — judged unnecessary at single-VPS scale until a concrete debugging need arises.

## Public Roadmap Use

This public version answers:

- what is already real
- what Wave 2 is building next
- which ideas are evidence-gated
- where the system is deliberately conservative

It is less operational than the canonical internal planning material and excludes environment-specific launch mechanics.

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Dashboard](DASHBOARD.md)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
