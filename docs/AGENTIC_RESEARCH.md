# Agentic Research

ZenInvest allows the committee pipeline to use live research tools instead of
relying only on a fixed precomputed briefing payload.

## Research Model

- strategy, moderation, and risk stages can request supporting evidence
- provider usage is budgeted rather than unbounded
- research calls are logged so operators can inspect what influenced a decision

## Current Tooling Themes

- general web search
- news search
- sector and macro context
- SEC filing lookup

## Operational Constraints

- budgets are capped per cycle and by provider
- fallback providers are used when the preferred provider is unavailable
- deterministic safeguards still control trade approval and execution

This public mirror keeps the high-level behavior and engineering intent. Private
operational recipes and infrastructure-specific runbooks are not published here.
