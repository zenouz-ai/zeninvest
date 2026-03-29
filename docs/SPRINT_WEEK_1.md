---
title: Sprint Plan — Week 1
tags: [sprint, planning, week-1, delivery, zeninvest]
status: active
created: 2026-03-21
last_updated: 2026-03-29
---

# Sprint Plan — Week 1 (ZenInvest)

> This sprint doc is a synchronized view of `docs/SOPHISTICATION_ROADMAP.md`, which is now the planning source of truth.
> Current delivery order below reflects the agreed sequence as of 2026-03-29.

---

## Delivered earlier this week

| ID | Story | Status | Notes |
|----|-------|--------|-------|
| US-4.1 | Volume Signals | Delivered | OBV + 20-day volume ratio in indicators and strategy scoring |
| US-7.4 | Integration Test Coverage | Delivered | Real `run_cycle()` dry-run coverage plus state transition tests |
| US-3.1 | Risk-Parity Position Sizing | Delivered | Inverse-vol BUY overlay with dashboard/API audit fields |
| US-1.7.3 | Dashboard Visual Design System | Delivered | Shared design tokens, primitives, and navigation refresh |
| US-4.5 | Proactive Macro News Intelligence | Delivered | Scheduled macro scan, persisted state, and action-plan context |
| US-1.6 | Slack NL Trade Commands | Delivered | Slack review/buy/sell workflow with confirmations and audit trail |
| US-1.9 | Conversational Trading Workflow MVP implementation | Delivered | Shared Slack/dashboard conversational flow, explicit confirm/reject APIs, audited session flow, and agentic beta transparency are shipped; local validation and VPS signoff completed |
| US-7.7 | Dashboard HTTPS Domain & Canonical Access | Delivered | Canonical `https://zeninvest.zenouz.ai`, internal-only dashboard app, public raw `:8000` removed |
| US-7.5 | Quick Hardening Slice | Delivered | Off-hours order annotations, HALTED auto-recovery, peak inflation detection, DB constraints, dashboard visibility |
| US-3.3 | Correlation-Aware Screening | Delivered | Candidate-vs-portfolio overlap warnings now reach strategy, moderation, and risk reasoning without changing the hard veto |
| US-4.2 | Earnings Calendar | Delivered | Earnings imminence and post-earnings drift context now flow through screening, prompting, moderation, and soft risk advisories |
| US-1.10 | Evolution Planner Phase 1 | Delivered | Authenticated planner-only slice is shipped; `US-1.11`–`US-1.14` now represent the remaining execution and promotion pipeline |

---

## Delivered This Week

| Order | ID | Story | Why now | Success criteria |
|-------|----|-------|---------|------------------|
| 1 | US-7.3 | Execution Quality & Slippage Monitoring | Market-order telemetry and operator visibility were the smallest materially useful pre-live gate | Decision-time price, slippage rollups, threshold alerting, and open partial-fill visibility are live |
| 2 | US-7.2 | Partial Fill Resubmission | Fill recovery only mattered once telemetry existed and could be shown safely | BUY-only remainder retry is gated, audited, and never bypasses the normal committee path |

## Current Delivery Order

| Order | ID | Story | Why now | Success criteria |
|-------|----|-------|---------|------------------|
| 1 | US-8.1 | Open-Source Launch Preparation | Repo is now the highest-leverage next unblocker after workflow delivery | Repo can be made public without legal, CI, or contributor-experience gaps |
| 2 | US-1.11 | Branch-Based Evolution Runner | Next evolution story now that learning-loop context and attribution are first-class | Low-risk repo changes can be prepared in isolated branches with validation artifacts |

---

## Active Track Notes

### Production Access & Safety

- `US-7.7` is delivered and should now be treated as the canonical production ingress posture.
- `US-7.5` shipped as the narrow hardening slice only:
  - off-hours order annotations
  - HALTED auto-recovery
  - peak inflation detection
  - DB-level constraints
- Broader audit backlog items remain parked under the same story for later follow-up.
- `US-7.3` + `US-7.2` are now delivered as one lean execution-quality slice:
  - market-order decision-vs-fill telemetry
  - partial-fill remainder tracking
  - BUY-only one-retry remainder resubmission when a later approved cycle still covers it
  - dashboard rollups and threshold warning alerting

### Conversational Operator Workflow

- `US-1.6` is the delivered foundation.
- `US-1.9` is now delivered after the local signoff gate, schema verification, and VPS walkthrough completed on 2026-03-28.
- Delivered `US-1.9` scope:
  - multi-turn continuity
  - explicit confirmation before execution
  - preserved deterministic risk veto
  - auditable session flow across Slack and dashboard

### Open-Source Launch Readiness

- `US-8.1` is now the lead current-week item after the production posture and operator-workflow work above.
- `US-7.7` is already delivered and now acts as a practical prerequisite for a clean community/operator posture.

### Zen Evolution Engine

- `US-1.10 Evolution Planner Phase 1` is delivered.
- Remaining scope is explicitly separated into pipeline stories:
  - `US-1.11` branch execution
  - `US-1.12` policy-gated promotion
  - `US-1.13` low-risk auto-promotion
  - `US-1.14` system-initiated improvements

### Entry Quality Guards

- `US-4.2` and `US-3.3` are now delivered as one backend bundle.
- Shipped scope:
  - per-ticker earnings awareness and post-earnings drift context
  - candidate-vs-portfolio correlation warnings
  - strategy/moderation/risk plumbing for soft advisories without changing the existing hard correlation veto

### Learning Loop & Attribution

- `US-2.5` and `US-2.6` are now delivered as one shared metadata track.
- Shipped scope:
  - `guidance_snapshots`, `guidance_sector_scores`, and `cycle_context_snapshots`
  - active screening tilt with fail-open baseline fallback
  - strategy/moderation guidance context injection
  - git-backed `strategy_change_episodes` + `strategy_change_evidence`
  - authenticated `/insights` route with `Market Guidance` and `Strategy Attribution` tabs

---

## Next After 8.1

- `US-1.11` as the next evolution story once CI, branch governance, and the post-launch posture are ready.
- `US-2.1` + `US-2.2` + `US-2.3` only after trade-outcome volume is high enough to justify calibration work.

---

## Explicitly De-Prioritized For Now

- `US-2.4` Nemotron investigation
- `US-3.2` enhanced regime detection
- `US-4.3` sector rotation
- `US-5.2` parameter sensitivity
- `US-6.1`, `US-6.2`, `US-6.3`

These remain valid backlog items, but they are not materially more important than the current production, workflow, and repo-readiness work.

---

## Consistency Rules

- `docs/SOPHISTICATION_ROADMAP.md` owns story status, order, and rationale.
- `README.md`, this sprint doc, and `dashboard/frontend/src/data/roadmap.ts` must be updated together whenever priority or story state changes.
- Stories may be grouped into tracks, but legacy US IDs remain the reference language for implementation and history.
