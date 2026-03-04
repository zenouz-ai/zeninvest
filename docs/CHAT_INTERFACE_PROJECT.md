# Chat Interface & Real-Time Trade Alerts Project

## Objective

Add a chat-ready notification interface so operators receive immediate alerts whenever BUY/SELL/REDUCE actions are instructed or executed, and provide a secure foundation for future two-way control (ChatOps) via Slack, Telegram, WhatsApp, and email.

This project is designed to integrate with the existing orchestrator pipeline and governance model.

---

## Why this matters

- **Operational visibility:** Immediate awareness of agent intent and execution outcomes.
- **Faster intervention:** Human can pause/resume/force-sell quickly when needed.
- **Safer autonomy:** Supports future human-in-the-loop approval on high-risk trades.
- **Roadmap fit:** Extends existing reporting and governance controls with real-time communication.

---

## Scope

## Phase 1 — Outbound Alerts (MVP)

### Channels (initial)
- Slack (incoming webhook)
- Email (SMTP)

### Event types
- Trade instruction approved (after moderation + risk, before execution)
- Trade execution result (filled / dry_run / failed / skipped)
- State machine transitions (ACTIVE -> CAUTIOUS -> HALTED)
- Critical cycle failures

### Non-functional requirements
- Notification failure must never block trading flow.
- Per-channel retry with bounded backoff and timeout.
- Message dedup/idempotency key to prevent duplicates.
- Structured audit trail of all sends.

---

## Phase 2 — Inbound Chat Commands (ChatOps)

### Supported commands
- `/status`
- `/pause`
- `/resume`
- `/force-sell <ticker>`

### Security requirements
- Provider signature verification (Slack/Telegram webhook validation where available)
- Optional shared secret / API key for command endpoint
- Command allow-list by role/user ID/channel
- Full command audit logs (who, what, when, result)

---

## Proposed architecture

```text
Orchestrator / State Machine
   ├─ emits domain events
   │    (trade_instruction, trade_execution, state_transition, system_error)
   │
   └─ NotificationService (non-blocking)
         ├─ SlackProvider
         ├─ EmailProvider
         ├─ TelegramProvider (future)
         └─ WhatsAppProvider (future)

Inbound Command Gateway (future)
   └─ validates/authenticates command
   └─ maps to existing orchestrator actions
```

---

## Integration points in current codebase

- `Orchestrator._execute_trade()` for trade execution outcomes.
- Decision pipeline section after moderation+risk verdict for “instruction approved” alerts.
- `StateMachine.transition()` for state transition alerts.
- Existing CLI actions (`--status`, `--pause`, `--resume`, `--force-sell`) as command targets for inbound chat controls.

---

## Data model additions

Add a new table: `notification_logs`

Suggested fields:
- `id`
- `timestamp`
- `cycle_id`
- `event_type`
- `channel` (slack/email/telegram/whatsapp)
- `status` (sent/failed/skipped)
- `idempotency_key`
- `payload_hash`
- `error_message`
- `recipient`

This supports incident review, reliability metrics, and compliance audit needs.

---

## Configuration additions

### `config/settings.yaml`
- `notifications.enabled`
- `notifications.channels`
- `notifications.trade_instruction_alerts`
- `notifications.trade_execution_alerts`
- `notifications.state_transition_alerts`
- `notifications.error_alerts`
- `notifications.max_retries`
- `notifications.timeout_seconds`

### `.env`
- `SLACK_WEBHOOK_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `ALERT_EMAIL_TO`
- `TELEGRAM_BOT_TOKEN` (future)
- `TELEGRAM_CHAT_ID` (future)
- `WHATSAPP_PROVIDER_TOKEN` (future)

---

## Acceptance criteria

- [ ] Alerts are emitted for all configured events in Phase 1.
- [ ] Alerts include ticker, action, allocation, conviction, moderation, risk verdict, and execution status when applicable.
- [ ] Notification sending is non-blocking and resilient to provider outages.
- [ ] Every send attempt is recorded in `notification_logs`.
- [ ] Feature is fully disable-able via config flag.
- [ ] Unit tests cover formatting, routing, retries, and failure isolation.
- [ ] Inbound command endpoints (Phase 2) enforce authentication and audit logging.

---

## Delivery plan

1. Implement provider-agnostic notification interface.
2. Implement Slack + email providers.
3. Wire outbound hooks in orchestrator + state machine.
4. Add database logging and migration.
5. Add tests + dry-run verification.
6. Add inbound command gateway (Phase 2).
7. Add Telegram/WhatsApp providers as incremental extensions.

---

## Risks and mitigations

- **Alert spam/noise** -> severity routing + digest mode + channel filters.
- **Provider outages** -> retries + fail-open behavior (trading continues).
- **Unauthorized control commands** -> signature checks + allow-lists + auditable deny logs.
- **Message duplication** -> idempotency keys and dedup checks.

---

## Success metrics

- P95 alert delivery latency < 10 seconds for outbound alerts.
- >99% successful send rate across channels (excluding provider outages).
- 0 trading cycles blocked by notification failures.
- 100% command actions attributable in audit logs (Phase 2).
