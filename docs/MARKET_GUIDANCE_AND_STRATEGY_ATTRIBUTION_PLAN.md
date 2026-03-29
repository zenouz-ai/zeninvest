---
tags: [market-guidance, learning-loop, strategy-attribution, roadmap]
status: current
last_updated: 2026-03-29
---

# Market Guidance and Strategy Attribution Plan

> Convert existing macro, micro, and repo-change data into a reusable learning loop that can influence future cycles in an auditable way.

## Purpose

This document captures the first implementation plan for two connected stories:

- `US-2.5` Market Guidance Layer
- `US-2.6` Strategy Episode Attribution

The goal is not to add another opaque intelligence layer. The goal is to create a
point-in-time guidance system and a repo-linked attribution system so future
changes can be measured instead of guessed.

## Locked Product Decisions

- Market guidance is **screening tilt plus committee context**, not hard trade gating.
- Strategy changes are tracked as **reviewed episodes**, not raw commits.
- First rollout is **dashboard + DB first**.
- The first pass includes a **best-effort backfill** over recent git history.
- Attribution is **observational**, not causal.
- Guidance ships **active immediately** with fail-open baseline screening when stale or unavailable.
- Prompt hashing is based on the **static prompt template surface**, not the rendered per-cycle prompt.

## User Story 1: Market Guidance Layer

### Desired outcome

Use existing macro and micro information from daily runs to shape what the agent
looks at next, so the system can lean away from weak sectors and toward stronger
opportunity pockets without introducing silent execution rules.

### Core capability

Build a point-in-time guidance pipeline that reads only data that existed before
the cycle started and produces:

- current regime, confidence, and freshness
- favored, neutral, and avoid sectors
- sector-level rationale and supporting evidence
- screening tilt values that can be applied to the next cycle
- a record of which tilt actually influenced a given cycle

### Inputs

- `macro_state`
- `macro_signal_logs`
- `macro_headlines`
- `strategy_decisions` (structured fields only)
- `opportunity_score_snapshots`
- `trade_outcomes`
- `portfolio_snapshots`
- `instruments`

### Output objects

1. `guidance_snapshots`
   - one row per daily or per-cycle guidance snapshot
   - stores regime, confidence, freshness, rationale, and summary evidence
2. `guidance_sector_scores`
   - one row per sector per guidance snapshot
   - stores tilt score, label (`favored`, `neutral`, `avoid`), and explanation
3. `cycle_context_snapshots`
   - one row per cycle
   - stores which guidance snapshot was active, what screening bias was applied,
     and whether the cycle was running in `shadow` or `active` guidance mode

### Influence tracking requirement

The Market Guidance Layer is only useful if the repo can later answer:

- which guidance snapshot was active for cycle `X`
- what sector tilts were applied
- how candidate selection changed relative to baseline
- whether the cycle only consumed guidance as context or also used screening tilt

This means each cycle context snapshot should persist:

- `cycle_id`
- `guidance_snapshot_id`
- `guidance_mode`
- `applied_screening_bias_json`
- `pre_guidance_sector_distribution_json`
- `post_guidance_sector_distribution_json`
- `pre_guidance_candidate_count`
- `post_guidance_candidate_count`
- `prompt_guidance_summary`

### V1 behavior

- Guidance can change sector ordering, per-sector caps, and candidate priority.
- Guidance can be injected into strategy and moderation prompts.
- Guidance cannot veto risk-approved trades in v1.
- V1 supports both `active` and `shadow`, but the production default is `active`.

## User Story 2: Strategy Episode Attribution

### Desired outcome

Track strategy changes over time so the system can later compare which prompt,
config, screening, risk, or execution changes helped and which changes hurt.

### Core capability

Create a repo-linked strategy episode registry rather than relying on commit
messages or memory.

### Output objects

1. `strategy_change_episodes`
   - reviewed change episodes with title, summary, change type, effective start,
     review status, confidence, and notes
2. `strategy_change_evidence`
   - supporting commit-level evidence, affected files, hashes, and optional
     LLM-produced summaries
3. `cycle_context_snapshots`
   - per-cycle repo and config fingerprints so each cycle can be tied back to the
     active strategy episode set

### Cycle linkage requirement

Each cycle should capture the minimum versioning fields needed for later analysis:

- repo SHA
- config hash
- prompt hash
- strategy fingerprint hash
- risk fingerprint hash
- execution fingerprint hash
- active strategy episode IDs

### Backfill requirement

The first implementation should reconstruct recent history using git:

- scan recent `main` commits for strategy-affecting paths
- group adjacent strategy-affecting commits into candidate episodes
- summarize candidate episodes deterministically first
- allow optional LLM summaries for operator review
- require a human confirmation step before an episode becomes canonical

### V1 attribution outputs

Each confirmed strategy episode should support:

- pre/post cycle performance windows
- 1d / 7d / 30d portfolio change windows
- trade-outcome deltas
- screening conversion deltas
- low-sample warnings
- overlapping-change warnings

## Dashboard Surface

Add an Insights surface with a public/private split:

1. `Market Guidance`
   - latest guidance snapshot
   - sector heat map
   - guidance history and freshness
   - cycle influence audit
   - public mode exposes a sanitized guidance-only view via `/api/public/insights/guidance/*`
2. `Strategy Attribution`
   - proposed and confirmed strategy episodes
   - commit evidence
   - effective windows
   - pre/post impact summaries
   - remains operator-only; public `/insights` shows preview-only messaging for this tab

Keep existing pages lightweight:

- Dashboard Home gets compact cards for active guidance regime and active strategy episodes.
- World News can deep-link into guidance details, but it should not become the full operator analytics surface.

## Rollout Order

1. Persist `cycle_context_snapshots` with repo/config/prompt fingerprints at cycle start.
2. Build and persist `guidance_snapshots` / `guidance_sector_scores` before screening each cycle.
3. Apply active screening tilt and persist pre/post candidate distributions per cycle.
4. Expose authenticated `/insights` views for guidance history and cycle influence audit.
5. Add strategy episode ingestion, best-effort 30-day git backfill, and operator confirmation.
6. Expose observational pre/post attribution summaries with low-sample and overlap warnings.

## Guardrails

- No future-data leakage in guidance generation.
- No direct claim that a single commit caused a performance change.
- No automatic self-modification from attribution results.
- No hidden execution vetoes from market guidance in v1.

## Related roadmap entries

- `docs/SOPHISTICATION_ROADMAP.md` under `US-2.5` and `US-2.6`
- `dashboard/frontend/src/data/roadmap.ts` mirrored roadmap metadata for the Roadmap page
