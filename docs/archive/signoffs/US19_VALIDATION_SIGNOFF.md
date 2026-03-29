---
tags: [us-1.9, validation, signoff, chat, dashboard, slack]
status: archived
last_updated: 2026-03-29
archived: true
---

# US-1.9 Validation Signoff

> **Archived 2026-03-29:** Delivery evidence for US-1.9. See [CONVERSATIONAL_TRADING_WORKFLOW.md](CONVERSATIONAL_TRADING_WORKFLOW.md) for the active spec.

Repeatable signoff checklist and evidence log for closing `US-1.9` Conversational Trading Workflow.

## Current status

- Local automated validation is passing.
- Local schema verification is passing.
- VPS walkthrough and deployment signoff were completed on 2026-03-28.
- `US-1.9` is marked delivered.

## Local automated gate

Run from the project root:

```bash
poetry run pytest -q \
  tests/test_chat_api.py \
  tests/test_chat_api_v2.py \
  tests/test_chat_session_stub.py \
  tests/test_session_concurrency.py \
  tests/test_conversation_orchestrator.py \
  tests/test_slack_listener.py \
  tests/test_slack_normalization.py \
  tests/test_trade_command_parser.py \
  tests/test_intent_classifier.py \
  tests/test_commands_api.py \
  tests/test_us19_schema_contract.py

cd dashboard/frontend && npm run build
```

Recorded local result on 2026-03-28:

- Chat/backend/API regression slice: `236 passed, 1 warning in 5.28s`
- Frontend production build: passing
- Full local suite follow-up: `1008 passed, 1 warning in 153.33s`

## Schema and migration verification

Run these locally and on the VPS deployment target:

```bash
poetry run alembic current
poetry run alembic heads
poetry run python scripts/verify_us19_schema.py
```

Required outcome:

- Alembic current matches head
- `chat_sessions`, `chat_turns`, `chat_actions`, `chat_research_logs`, `chat_workflow_steps` exist
- `cost_logs` and `research_logs` include `chat_session_id` and `chat_turn_id`
- Confirm/reject versioning fields and typed session-context fields are present in the live DB

Recorded local result on 2026-03-28:

- `poetry run alembic current` -> `v8w9x0y1z2a3 (head)`
- `poetry run alembic heads` -> `v8w9x0y1z2a3 (head)`
- `poetry run python scripts/verify_us19_schema.py` -> `"ok": true`

Recorded VPS result on 2026-03-28:

- Operator-confirmed Alembic/schema check passed on deployed environment
- Operator-confirmed dashboard, Slack, cross-channel, beta-path, and audit walkthroughs passed

## VPS manual validation matrix

### Dashboard flow

- [x] `/chat` renders as the canonical chat surface
- [x] `/commands` still works as the backward-compatible alias
- [x] Research-only turn renders thread, evidence panels, workflow rail, research trace, and spend
- [x] Trade proposal does not execute before explicit confirm
- [x] Reject path updates cleanly and places no order
- [x] Confirm path updates execution summary and audit trail
- [x] Stale `expected_version` returns `409` and latest action payload
- [x] `Legacy Slack Audit` is clearly separate from the conversation archive

### Slack thread flow

- [x] New Slack thread creates or resumes a conversational session
- [x] Bullet/list normalization keeps intended routing
- [x] Explicit threaded commands stay on the deterministic preview path
- [x] Compare prompt with 2-3 names resolves correctly
- [x] `compare X and Y, then buy £20 of the stronger one` stages a preview and still requires confirm
- [x] Confirm and reject both behave correctly in-thread
- [x] Pending-action expiry behaves correctly
- [x] Risk-veto or blocked reply remains deterministic and explicit

### Cross-channel continuity

- [x] Slack-backed session appears in the dashboard session rail
- [x] Dashboard session detail shows actions, research logs, workflow steps, and spend for the Slack-backed thread
- [x] Dashboard-to-Slack reply mirroring works for Slack-backed sessions
- [x] Same-user dashboard follow-up behavior preserves intended prior context

### Agentic beta path

- [x] Planner-led turn produces evidence-rich output and workflow-step trace
- [x] Degraded-turn warnings surface when fallback occurs
- [x] Hidden specialist opinions still resolve to one assistant voice
- [x] Beta path never bypasses confirmation or deterministic risk checks

### Audit and attribution

- [x] `chat_session_id` / `chat_turn_id` attribution appears on relevant research and cost records
- [x] Action, execution, rejection, and expiry states remain queryable after walkthroughs
- [x] No successful conversation path leaves an incomplete audit trail

## Closeout summary

- `US-1.9` was marked delivered on 2026-03-28 after:

1. Local automated gate passed.
2. Schema verification passed locally and on the deployed VPS.
3. Dashboard and Slack walkthroughs passed.
4. Cross-channel continuity and auditability were verified.
5. The agentic beta path cleared the same safety bar.

Retained for evidence:

- The roadmap/status docs were updated from `In validation` to `Delivered`
- This file remains the dated signoff artifact
- The exact commands and walkthrough evidence used for closure are preserved here
