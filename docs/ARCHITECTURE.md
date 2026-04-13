# Architecture

ZenInvest is an orchestrated trading research pipeline built around a
multi-model committee and deterministic execution guardrails.

## Core Flow

```text
Data collection
  -> universe screening
  -> strategy synthesis
  -> moderation review
  -> deterministic risk checks
  -> opportunity prioritisation
  -> execution and stop management
  -> run / order / outcome persistence
```

## Main Subsystems

- **Market data**: price, fundamentals, and macro context used for screening
  and strategy prompts
- **Strategy**: proposes actions and allocations
- **Moderation**: challenges or supports the proposed action
- **Risk**: deterministic guardrails that remain authoritative
- **Execution**: broker-facing order, cancel, and stop workflows
- **Dashboard**: authenticated operator views plus a sanitized public surface
- **Reporting**: snapshots, trade outcomes, run history, and cost tracking

## Persistence

The project uses SQLite by default for local and single-operator workflows.
Application state covers orders, portfolio snapshots, run metadata, strategy
decisions, moderation outcomes, risk decisions, and related audit tables.

## Public vs Private

The product includes both public-safe and operator-authenticated surfaces. This
public mirror keeps only the high-level architecture needed to understand the
system; deployment topology and operator runbooks are intentionally omitted.
