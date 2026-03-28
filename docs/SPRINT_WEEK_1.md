---
tags: [sprint, planning, week-1, delivery, zeninvest]
status: active
created: 2026-03-21
last_updated: 2026-03-28
---

# Sprint Plan — Week 1 (ZenInvest)

> This sprint doc is a synchronized view of `docs/SOPHISTICATION_ROADMAP.md`, which is now the planning source of truth.
> Current delivery order below reflects the agreed sequence as of 2026-03-27.

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
| US-1.9 | Conversational Trading Workflow MVP implementation | In validation | Shared Slack/dashboard conversational flow is implemented in repo; final test/deploy checklist still open |
| US-7.7 | Dashboard HTTPS Domain & Canonical Access | Delivered | Canonical `https://zeninvest.zenouz.ai`, internal-only dashboard app, public raw `:8000` removed |
| US-7.5 | Quick Hardening Slice | Delivered | Off-hours order annotations, HALTED auto-recovery, peak inflation detection, DB constraints, dashboard visibility |

---

## Current Delivery Order

| Order | ID | Story | Why now | Success criteria |
|-------|----|-------|---------|------------------|
| 1 | US-1.9 | Conversational Trading Workflow MVP | Builds directly on the delivered Slack/chat foundation and adds real operator value | Real operator workflow MVP, not just CRUD skeleton |
| 2 | US-8.1 | Open-Source Launch Preparation | Repo must be public-ready once posture and workflow priorities are in place | Repo can be made public without legal, CI, or contributor-experience gaps |
| 3 | US-7.3 | Execution Quality & Slippage Monitoring | First execution-quality gate after posture/workflow work | Slippage becomes measurable before any live-account posture change |

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

### Conversational Operator Workflow

- `US-1.6` is the delivered foundation.
- `US-1.9` implementation has landed in repo this week, but it should not be treated as fully closed until the final validation and deployment checklist is complete.
- This sprint’s `US-1.9` scope is:
  - multi-turn continuity
  - explicit confirmation before execution
  - preserved deterministic risk veto
  - auditable session flow across Slack and dashboard

### Open-Source Launch Readiness

- `US-8.1` stays in the current week, but after the production posture and operator-workflow work above.
- `US-7.7` is already delivered and now acts as a practical prerequisite for a clean community/operator posture.

### Learning Loop & Attribution

- `US-2.5` and `US-2.6` are now defined as the next learning-loop track after the current execution-quality and entry-quality bundle.
- `US-2.5` must persist which guidance snapshot influenced each cycle so future analysis can reuse the evidence trail instead of inferring it later.
- `US-2.6` must map repo/config/prompt changes onto cycle-level fingerprints so strategy shifts can be reviewed against later outcomes.

---

## Next After 8.1

- `US-7.3` then `US-7.2` as one execution-quality and fill-recovery track.
- `US-4.2` + `US-3.3` as the next small, high-value entry-quality bundle.
- `US-2.5` + `US-2.6` as the next learning-loop and attribution bundle once the execution-quality and entry-quality work above is complete.
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
