# Chat Interface & Real-Time Trade Alerts Project

## Objective

Build a reliable chat/notification layer for the Investment Agent that:

1. Gives operators immediate visibility into trade decisions and outcomes.
2. Never interferes with execution safety or core trading flow.
3. Provides a secure, auditable foundation for future inbound ChatOps commands.

This spec tightens US-1.5 into implementation-ready requirements that align with the current codebase and governance model.

---

## Product Outcomes

- **Operational visibility:** Know what the agent is about to do and what actually happened.
- **Faster intervention:** Receive HALTED/critical failures instantly.
- **Auditability:** Every send attempt is persisted and attributable.
- **Roadmap alignment:** Phase 1 delivers outbound alerts only; Phase 2 adds inbound control safely.

---

## Scope

## Phase 1 (MVP): Outbound Alerts Only

### In scope
- Slack webhook alerts.
- Email alerts (SMTP).
- Event triggers from orchestrator/state machine:
  - `trade_instruction_approved` (post moderation+risk, pre execution)
  - `trade_execution_result` (filled/dry_run/failed/skipped)
  - `cycle_run_summary` (end-of-run report with all ticker decisions)
  - `state_transition` (ACTIVE/CAUTIOUS/HALTED)
  - `critical_cycle_failure` (cycle-aborting exceptions)
- `notification_logs` database table.
- Config flags, channel routing, retries/timeouts, dedup/idempotency.
- Unit tests + integration-style dry-run checks.

### Out of scope (Phase 1)
- Inbound commands.
- Human approval workflows.
- Telegram and WhatsApp transport implementations.
- Rich interactive UI blocks/buttons.

## Phase 2 (Future): Inbound Chat Commands

Commands to support:
- `/status`
- `/pause`
- `/resume`
- `/force-sell <ticker>`

Security and governance requirements are defined in this doc but implementation is deferred.

---

## Architecture (Target)

```text
Orchestrator + StateMachine + CLI actions
   └─ emit typed notification events
        └─ NotificationService (fail-open, non-blocking)
             ├─ Router (event -> channels)
             ├─ Formatter (event -> channel payload)
             ├─ Sender (retry + timeout + dedup)
             ├─ SlackProvider
             └─ EmailProvider
                  └─ NotificationLogRepository (persistent audit trail)

Phase 2:
Inbound Command Gateway
   └─ authenticate + authorize + audit
   └─ map to existing orchestrator/state-machine actions
```

### Non-blocking contract
- Notification send failures must be isolated from trade execution.
- `NotificationService` must catch/log all provider exceptions and return control immediately.
- Delivery is **at-least-once** (with idempotency key dedup on provider side where possible).

---

## Integration Points in Current Codebase

- `src/orchestrator/main.py`
  - Decision loop after moderation+risk approval emits `trade_instruction_approved`.
  - `Orchestrator._execute_trade()` emits `trade_execution_result`.
  - Top-level cycle exception handling emits `critical_cycle_failure`.
- `src/orchestrator/state_machine.py`
  - `StateMachine.transition()` emits `state_transition`.
- Existing command surface for Phase 2 mapping:
  - `--status`, `--pause`, `--resume`, `--force-sell`.

---

## Event Contract (Canonical)

Each outbound event must include:
- `event_id` (uuid4)
- `event_type`
- `occurred_at` (UTC ISO8601)
- `cycle_id` (nullable for non-cycle events)
- `severity` (`info|warning|critical`)
- `source` (`orchestrator|state_machine|command_gateway`)
- `dedup_key` (stable hashable key per event intent)
- `payload` (typed object)

### `trade_instruction_approved` payload
- `ticker`
- `action`
- `target_allocation_pct`
- `conviction`
- `moderation_consensus`
- `risk_verdict`
- `reasoning_summary`

### `trade_execution_result` payload
- `ticker`
- `action`
- `target_allocation_pct`
- `execution_status`
- `quantity`
- `price`
- `value_gbp`
- `order_id` (nullable)
- `stop_loss_status` (nullable)
- `error_message` (nullable)

### `state_transition` payload
- `old_state`
- `new_state`
- `reason`
- `drawdown_pct` (nullable)

### `critical_cycle_failure` payload
- `stage`
- `error_type`
- `error_message`
- `trace_id` (if available)

---

## Message Rendering Requirements

- Slack: concise, single-message summary with severity prefix.
- Email: subject line includes `[Investment-Agent][SEVERITY]` and body contains full event details.
- Messages must always include:
  - environment (`practice`/`live`)
  - cycle ID when available
  - timestamp in UTC

---

## Delivery and Reliability Requirements

- Per-channel timeout: configurable (default 5s).
- Retry policy: configurable bounded retries with exponential backoff (default 2 retries, 0.5s then 1.5s).
- Dedup:
  - compute `dedup_key` from event intent fields.
  - do not send duplicate event to same channel within configurable window (default 300s).
- Fail-open:
  - notification failures never raise to trading path.
  - all failures recorded in logs + `notification_logs`.

---

## Data Model Additions

Add table: `notification_logs`

Required fields:
- `id` (PK)
- `timestamp` (UTC, indexed)
- `event_id` (indexed)
- `cycle_id` (nullable, indexed)
- `event_type` (indexed)
- `severity`
- `channel` (`slack|email|telegram|whatsapp`)
- `recipient` (nullable)
- `status` (`sent|failed|skipped|deduped`)
- `attempt_number` (int)
- `dedup_key` (indexed)
- `payload_hash`
- `error_message` (nullable)
- `latency_ms` (nullable)

Recommended constraints/indexes:
- index on `(event_type, timestamp)`
- index on `(channel, timestamp)`
- unique constraint on `(channel, dedup_key, attempt_number)` to simplify replay auditing

---

## Configuration Additions

## `config/settings.yaml`

```yaml
notifications:
  enabled: true
  channels: ["slack", "email"]
  routes:
    trade_instruction_approved: ["slack"]
    trade_execution_result: ["slack", "email"]
    cycle_run_summary: ["slack"]
    state_transition: ["slack", "email"]
    critical_cycle_failure: ["slack", "email"]
  timeout_seconds: 5
  max_retries: 2
  dedup_window_seconds: 300
  include_dry_run_alerts: false
  command_gateway:
    enabled: false
```

## `.env` additions

- `SLACK_WEBHOOK_URL`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_USE_TLS`

Phase 2 (future only):
- `COMMAND_GATEWAY_SHARED_SECRET`
- Provider-specific signature secrets (e.g., Slack signing secret)

---

## Phase 2 Security Requirements (Locked Before Build)

- Verify provider signatures where supported.
- Reject unauthenticated requests with auditable deny log entries.
- Enforce allow-list by user ID and/or channel ID.
- Require command idempotency key and replay window checks.
- Record full command audit trail: principal, command, args, timestamp, auth result, execution result.

---

## Acceptance Criteria

### Phase 1
- [x] Notification service exists under `src/agents/notifications/` with provider abstraction.
- [x] Five event types emit from the defined integration points (`trade_instruction_approved`, `trade_execution_result`, `cycle_run_summary`, `state_transition`, `critical_cycle_failure`).
- [x] Slack and email channels work independently and can be enabled/disabled by config.
- [x] Notification failures never block or fail a trading cycle.
- [x] Retries/timeouts/dedup operate as configured.
- [x] Every send attempt persists to `notification_logs`.
- [x] Dry-run cycles produce alerts when `include_dry_run_alerts=true`.
- [x] Unit tests cover formatter correctness, routing, retry, dedup, and fail-open behavior.
- [ ] End-to-end dry-run validation demonstrates event emission and persisted logs.

### Phase 2
- [ ] Inbound command gateway supports `/status`, `/pause`, `/resume`, `/force-sell <ticker>`.
- [ ] Authentication, authorization, and command audit logging are mandatory and tested.

---

## Delivery Plan (Implementation Sequence)

1. Add notification domain models/events and provider interfaces.
2. Implement `NotificationService` with router, retries, dedup, fail-open handling.
3. Add Slack provider.
4. Add SMTP email provider.
5. Wire orchestrator/state-machine integration hooks.
6. Add `notification_logs` model + Alembic migration + repository methods.
7. Add config keys + `.env.example` placeholders + `Settings` accessors.
8. Add tests and run dry-run verification.
9. Phase 2: implement inbound command gateway only after Phase 1 stability criteria are met.

---

## Risks and Mitigations

- **Alert noise/spam:** Severity routing and per-event channel selection.
- **Provider outage:** Timeouts + bounded retries + fail-open.
- **Duplicate sends:** Dedup keys + dedup window + dedup status logging.
- **Security regression in Phase 2:** Signature validation + allow-list + full audit requirements as release gate.

---

## Success Metrics

- P95 alert send latency < 10 seconds.
- >99% successful sends excluding provider outages.
- 0 trading cycles blocked by notification subsystem failures.
- 100% send attempts represented in `notification_logs`.
- Phase 2: 100% command actions attributable in audit logs.
