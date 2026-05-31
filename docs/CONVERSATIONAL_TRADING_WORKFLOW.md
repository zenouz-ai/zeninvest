# Conversational Trading Workflow

> Unified public-safe specification for session-based trading conversations across Slack-style and dashboard channels.

## Purpose

This workflow defines how ZenInvest handles multi-turn trading conversations, explicit confirmations, research-backed replies, and execution requests without collapsing into unsafe free-form automation.

It unifies:

- inbound command handling
- session-based chat
- planner/orchestrator routing
- explicit confirmation before execution
- deterministic post-analysis execution gating

## Command Modes

The deterministic command layer supports four main modes:

- `review` — analysis only, no execution
- `direct_trade` — direct broker path with explicit preflight and confirmation
- `strategy_trade` — committee evaluation followed by execution only if approved
- `cancel` — cancel matching pending broker orders

This bounded command layer coexists with broader conversational analysis and follow-up flows.

## Scope

### In scope

- multi-turn session state
- shared Slack-style and dashboard session logic
- entity/ticker resolution across turns
- explicit confirm/reject flow for proposed trades
- research-backed analysis during conversations
- session and action audit trails
- real-time UI updates through event streaming

### Out of scope

- autonomous execution from ambiguous language
- unrestricted portfolio-wide destructive actions without explicit confirmation
- multi-user collaborative trust models as a default assumption
- non-text interfaces such as voice

## User Journey

1. The user starts a session with a question or trade-oriented request.
2. The system creates or resumes a session and resolves subjects.
3. The assistant returns analysis, comparison, or clarification.
4. The user follows up with more questions or a trade request.
5. The assistant stages a proposal and asks for explicit confirmation.
6. On confirm, the risk and execution path runs.
7. The system returns filled, pending, failed, or vetoed results and records the full trace.

## Workflow Characteristics

- explicit confirmation is required before execution
- confirmation is bound to a pending proposal and can expire
- ambiguous or under-specified requests trigger clarification instead of execution
- deterministic risk remains the final gate
- action state is durable and auditable

## Architecture

### High-level components

- conversation gateway
- session manager
- conversation planner/orchestrator
- research orchestration
- deterministic risk and execution adapters
- persistence layer
- SSE-backed dashboard activity updates

### Main modules

Representative modules include:

- session management
- planner/composer routing
- specialist or hidden-role assistance
- conversation orchestration
- Slack/listener integration
- dashboard chat routes
- frontend chat console

These components are designed so deterministic trade commands can still take precedence when the user issues a bounded explicit action inside a broader conversation.

## Execution and Safety Flow

1. User requests an action.
2. The orchestrator gathers context and optionally research.
3. The assistant stages a structured proposal.
4. The user confirms or rejects.
5. Risk validates the intended action.
6. Execution either proceeds or is vetoed.
7. The result is logged and surfaced back to the active channel.

## Session and Persistence Model

The conversation system uses durable entities such as:

- `chat_sessions`
- `chat_turns`
- `chat_actions`
- `chat_research_logs`
- `chat_workflow_steps`

This supports:

- follow-up continuity
- explicit pending-action tracking
- research attribution
- session-level spend visibility
- operator-visible workflow traces

## Dashboard Chat API

The dashboard layer exposes endpoints for:

- session list/detail
- turn submission
- explicit confirm/reject
- end/archive behavior
- session-scoped action and spend visibility

Public-safe documentation focuses on the workflow shape rather than every private operator endpoint.

## Phased Implementation Model

The conversational workflow naturally breaks into phases:

- session core and logging
- Slack-style conversational interface
- dashboard chat console
- cross-channel continuity
- deeper research-aware routing

This is useful both for understanding the current implementation and for planning future extensions.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| ambiguous execution intent | explicit confirmation and clarifying questions |
| stale or incorrect context carry-over | structured session context and subject resolution |
| loss of auditability | persistent turns, actions, and workflow steps |
| chat cost sprawl | session-scoped cost and research attribution |
| unsafe free-form execution | deterministic command routing plus risk veto |

## Acceptance Criteria

A successful conversational trading workflow should:

- preserve context across turns
- show its proposal clearly before execution
- require explicit confirmation
- record actions and research durably
- let deterministic risk veto unsafe outcomes
- keep Slack-style and dashboard channels aligned

## Public vs Private

This doc keeps the architecture, flow, and safety model. It intentionally omits private validation signoff artifacts, environment-specific operator runbooks, and production-only integration details.

## Related Docs

- [Architecture](ARCHITECTURE.md)
- [Dashboard](DASHBOARD.md)
- [Agentic Research](AGENTIC_RESEARCH.md)
