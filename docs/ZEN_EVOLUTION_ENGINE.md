---
tags: [evolution, dashboard, planning, governance]
status: current
last_updated: 2026-03-29
---

# Zen Evolution Engine

> Policy-constrained software evolution for ZenInvest.

## Purpose

Zen Evolution Engine is the change-management workflow for operator-requested system evolution. It turns natural-language change requests into repo-grounded implementation plans, risk classifications, validation recommendations, and auditable workflow state without granting direct code or deploy authority in the initial phase.

The design goal is **semi-autonomous software evolution with hard control gates**:

- The system can understand intent, scope a change, and recommend the right validation path.
- The system can preserve an audit trail across requests, clarifications, plans, approvals, and later promotion records.
- High-risk financial changes remain gated by policy.

## Phase 1 Scope (Delivered)

The delivered `US-1.10 Evolution Planner Phase 1` slice is **planner-only**:

- authenticated dashboard-first operator workflow
- natural-language request intake
- deterministic intent normalization
- repo-context retrieval from roadmap, architecture, governance, deployment, and likely code areas
- risk classification (`LOW`, `MEDIUM`, `HIGH`)
- validation matrix generation based on touched area
- clarifying-question loop
- full request/message/plan/run/artifact audit trail

Delivery audit on 2026-03-28 confirmed that the shipped slice is real and working, but still intentionally narrower than the broader software-evolution track:

- targeted backend planner tests pass
- dashboard frontend production build passes
- auth and router gating exist in the real app
- repo-context retrieval is currently static mapping, not deep live repo analysis
- no branch execution, code edits, build workers, or deployment authority exist yet

Phase 1 intentionally **does not**:

- modify code
- create branches
- run build workers
- run deployments
- auto-promote changes

The remaining scope is now represented only by later pipeline stories:

- `US-1.11` Branch-Based Evolution Runner
- `US-1.12` Policy-Gated Promotion
- `US-1.13` Low-Risk Auto-Promotion
- `US-1.14` System-Initiated Improvements

This project no longer uses a partial roadmap status. Delivered slices are marked delivered, and unfinished work stays in separate pipeline stories.

## Policy Model

### Low risk

Examples:
- dashboard copy
- cosmetic UI changes
- isolated documentation updates

Expected path:
- plan
- recommend validation
- later branch-based review path
- no auto-promotion in Phase 1

### Medium risk

Examples:
- non-trading dashboard backend behavior
- notifications
- reporting logic
- feature-flagged operator workflow changes

Expected path:
- plan
- recommend validation
- later manual review flow
- deploy remains approval-gated

### High risk

Examples:
- strategy logic
- execution paths
- position sizing
- risk controls
- deployment/infrastructure changes touching protected runtime surfaces

Expected path:
- plan
- recommend strict validation
- dry-run plus backtesting evidence
- explicit approval
- no early-phase auto-promotion

## Workflow Model

Target workflow state machine:

`DRAFT -> NEEDS_CLARIFICATION -> PLANNED -> APPROVED_FOR_BUILD -> IMPLEMENTING -> VALIDATING -> READY_FOR_REVIEW -> APPROVED_FOR_DEPLOY -> DEPLOYING -> DEPLOYED | REJECTED | ROLLED_BACK`

Phase 1 uses only the planning subset:

`DRAFT -> NEEDS_CLARIFICATION | PLANNED`

Build and deploy approvals are intentionally blocked and recorded as policy-gated attempts.

## Data Model

The evolution workflow uses a separate domain from trading chat:

- `evolution_requests`
- `evolution_messages`
- `evolution_plans`
- `evolution_runs`
- `evolution_artifacts`
- `evolution_approvals`
- `evolution_deployments`

This keeps software-evolution state separate from operator trading sessions.

## Current Constraints

- Dashboard-first only; Slack is out of scope in the initial phase.
- Production control plane remains Docker Compose on the VPS.
- Financially sensitive changes remain review-only.
- Secrets, broker credentials, unrestricted infrastructure rewiring, and unrestricted live trading changes remain out of scope.

## Planned Follow-On Phases

- **US-1.11** Branch-Based Evolution Runner
- **US-1.12** Policy-Gated Promotion
- **US-1.13** Low-Risk Auto-Promotion
- **US-1.14** System-Initiated Improvements

These later phases should only expand authority once the current production posture, operator workflow, and CI/branch governance foundations are stable.
