# Agentic Research

> Public-safe design for bounded tool use by strategy, skeptic, and risk roles inside the committee.

## Purpose

Agentic research changes the committee from a fixed-briefing system into a bounded tool-using system. Instead of forcing every model to rely on exactly the same pre-fetched payload, ZenInvest allows strategy, skeptical moderation, and risk moderation to request targeted external context during evaluation.

## Current Status

The public architecture reflects a delivered research stack with:

- a shared research executor
- provider routing and fallback
- cache and budget controls
- per-call research logging
- research-aware prompts for strategy and moderation

## Why Agentic Research Exists

Without tool use, the pipeline has several limitations:

- context can be stale by the time a decision is made
- every committee member sees the same perspective
- enrichment gets wasted on names that never receive deep review
- strategy cannot verify new hypotheses during evaluation
- moderation cannot independently falsify the strategy case

## Research Model

Three committee roles can use tools:

| Member | Goal | Typical angle |
|--------|------|---------------|
| `strategy` | build the long thesis | opportunity validation, earnings/news, filings, peer context |
| `skeptic` | challenge the thesis | bear cases, downgrades, regulatory risk, contradictory evidence |
| `risk` | surface fragility and macro downside | regime shifts, volatility, macro events, correlations |

The deterministic risk manager does **not** participate in open-ended research. It remains a hard-rule enforcement layer.

## Tooling Themes

The main research tools are:

- `web_search`
- `news_search`
- `sector_search`
- `sec_search`
- `macro_search`

These tools route through provider abstractions and normalised response models so the rest of the pipeline can audit tool use consistently.

## Search Provider Strategy

The current public-safe design is:

- one primary provider
- one fallback provider
- optional merged/additional behavior for selected search types

This supports:

- timeout recovery
- degraded-but-functional research
- cost control
- per-provider audit visibility

## Cache and Budget Controls

Agentic research is bounded, not open-ended.

### Cache

Research is cached by ticker, tool, and normalized query so identical requests across strategy and moderators do not repeatedly hit the network. The cache is durable (SQLite-backed), so results survive restarts and dedupe across cycles rather than resetting each run. The shared research budget is thread-safe, allowing the moderators to run concurrently.

### Per-member caps

Each committee member has a bounded number of tool calls per cycle.

### Pipeline-wide caps

There is also a shared total research-call cap across the whole evaluation pipeline.

### Monthly and provider controls

Search limits and model budgets are shared with the broader system so research cannot quietly consume the full operational budget.

## Research Audit Trail

Each research action can be recorded with fields such as:

- session or cycle context
- member
- tool
- provider
- query
- result summary
- cache hit status
- latency
- cost attribution

This makes research observable from the dashboard and supports later review of whether external context materially improved decision quality.

## Prompt Integration

Research is role-aware:

- strategy can look for confirming or explanatory evidence
- skeptic is explicitly tasked with falsification and downside framing
- risk focuses on macro, fragility, and second-order effects

The key point is that the roles do not merely share tools; they share tools with distinct mandates.

## Data Sources

Representative public-safe sources include:

- Brave Search
- Tavily
- SEC EDGAR
- existing market-data enrichers already used elsewhere in the system

The public mirror describes the source categories and integration shape while omitting internal experimentation notes and private operational tuning.

## Configuration

Typical configuration areas include:

- feature flags for strategy/skeptic/risk tool use
- provider routing order
- additional/fallback behavior
- cache TTL
- per-member cycle caps
- total research cap

## Environment Variables

Common environment variables for this feature include:

- search-provider credentials
- model credentials
- optional SEC identification headers or contact metadata

The exact public-safe variable names remain documented in `config/.env.example`.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| runaway API costs | per-member caps, shared caps, monthly limits |
| latency inflation | caching, bounded iterations, fallback routing |
| false confidence from bad external content | adversarial moderation and deterministic risk veto |
| tool loops that drift | bounded iterations and explicit planner/orchestrator control |
| duplicated effort across members | shared cache and normalized tooling |

## Success Criteria

Good agentic research should improve:

- decision freshness
- adversarial quality
- evidence depth
- follow-up handling
- operator inspectability

without causing:

- runaway cost
- unacceptable latency
- opaque non-auditable behavior

## Public vs Private

This public doc keeps the system design, role model, tooling concepts, and safety controls. It intentionally omits private investigation notebooks, internal rollout notes, and environment-specific production tuning.

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Conversational Trading Workflow](CONVERSATIONAL_TRADING_WORKFLOW.md)
- [Local Setup](LOCAL_SETUP.md)
