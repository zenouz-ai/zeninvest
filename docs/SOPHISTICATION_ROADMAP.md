# Sophistication Roadmap

> Public roadmap for delivered capabilities, active tracks, and later-stage enhancement themes.

## Overview

ZenInvest is still positioned as a proof-of-concept system, but it already contains a substantial amount of end-to-end functionality across trading, observability, research, backtesting, and operator tooling.

The roadmap is organized around a few principles:

1. safety before new capability
2. execution quality before more aggressive live posture
3. evidence-gated learning loops
4. incremental delivery over broad rewrites

The canonical machine-readable roadmap remains in the frontend data model, while this public doc explains the direction at a human level.

## Delivered Themes

Major delivered themes include:

- end-to-end pipeline execution
- dashboard and observability
- conversational trading workflows
- backtesting and walk-forward validation
- opportunity ranking and queueing
- agentic research
- macro intelligence
- execution-quality hardening
- authentication and safe public demo surfaces
- early evolution-planner capability
- pace-aligned exits with north-star KPIs
- agentic-operability hardening (per-phase timing, prompt hashing, budget enforcement, durable research cache, parallel moderation, failure-mode catalog, golden tests)

## Current State

The current POC establishes:

- data -> screening -> strategy -> moderation -> risk -> execution -> reporting flow
- multi-LLM adversarial committee design
- deterministic risk veto power
- practice-oriented broker integration
- dashboard and public-safe observability surfaces
- backtesting and trade-outcome infrastructure

What remains intentionally unfinished:

- deeper calibration of conviction and sizing
- more adaptive learning loops
- broader execution-quality optimization
- carefully gated autonomy in software evolution workflows

## Active and Near-Term Themes

### Evolution Engine follow-ons

- branch-based change execution
- validation packs and promotion gates
- low-risk auto-promotion only after manual trust is established

### Calibration and adaptation

- conviction calibration
- dynamic strategy weighting
- moderator effectiveness analysis
- rejected-decision counterfactual and selection-bias diagnostics (shadow/evidence only): a read-only, per-stage view of whether the funnel declined names that would have lost (good miss) or won (false reject), with a dashboard surface delivered and deeper debiasing kept as gated research

These are data-gated and should only move once enough trade-outcome evidence exists.

### Regime and factor expansion

- enhanced regime detection
- sector rotation signals
- parameter sensitivity analysis

### Agentic maturity (operability)

A set of low-cost, high-leverage operability slices, prioritized by impact over effort and each tied to a measured baseline rather than a guess. The **zero-infra slices are now delivered**:

- per-phase cycle timing/observability (so latency work targets the real driver)
- prompt versioning/hashing across the full committee (file-based, not a heavyweight registry)
- enforcement of the chat and embedding budget caps as truly-separate categories
- a durable research cache (replacing the in-memory one that reset on restart)
- parallel moderation (the two moderators now run concurrently, behind a kill switch)
- a failure-mode catalog with stable error codes, plus golden prompt/tool tests in CI

These deliberately avoid new infrastructure: heavier observability stacks, database-backed prompt registries, and orchestration frameworks were assessed and judged unnecessary at the current single-host scale.

## Later / Optional Themes

These are interesting but intentionally later:

- alternative provider investigations
- gradient-boosted trade scoring
- embeddings and similarity search for journal learning
- reinforcement-learning investigations
- relational / supply-chain graph context (preferring an embedded graph store over standing up more services)
- distributed trace observability (only if simpler audit and per-phase timing prove insufficient)

The roadmap treats these as optional until the simpler, higher-leverage foundations are mature.

## Resource Allocation Heuristic

The roadmap implicitly prioritizes:

- reliability and safety first
- observability before optimization
- data collection before adaptive logic
- low-complexity/high-leverage work over novelty for its own sake

## Public Roadmap Use

This public version is intended to answer:

- what is already real
- what the next meaningful steps are
- which ideas are evidence-gated
- where the system is deliberately conservative

It is intentionally less operational than the canonical internal planning material and excludes environment-specific or private launch mechanics.

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Dashboard](DASHBOARD.md)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
