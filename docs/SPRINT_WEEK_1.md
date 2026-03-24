---
tags: [sprint, planning, week-1, delivery, zeninvest]
status: active
created: 2026-03-21
last_updated: 2026-03-24
---

# Sprint Plan — Week 1 (ZenInvest)

> Planned delivery of 8 user stories across 8 days in priority order.
> Branch: `claude/review-roadmap-priorities-9F67J`
> See `docs/SOPHISTICATION_ROADMAP.md` for full backlog context.

---

## Schedule at a glance

| Days  | ID        | Story                        | Status     | Notes                                          |
|-------|-----------|------------------------------|------------|------------------------------------------------|
| 1     | US-7.1    | Dashboard Authentication     | ✅ Done     | Already delivered; unblocks safe VPS exposure  |
| 1–2   | US-4.1    | Volume Signals               | ✅ Done     | Delivered: indicators, scoring, config, tests  |
| 2–4   | US-7.4    | Integration Test Coverage    | ✅ Done     | Delivered: orchestrator + state transition coverage |
| 2–5   | US-3.1    | Risk-Parity Sizing           | ✅ Done     | Delivered: inverse-vol overlay, persistence, dashboard/API, tests |
| 2–5   | US-1.7.3  | Dashboard Visual Design System | ✅ Done   | Syne font, token system, glass panels, 4 primitives |
| 3–7   | US-4.5    | Proactive Macro Intelligence | ✅ Done     | Scheduled scan + persisted context + action plan |
| 5–7   | US-1.6    | Slack NL Commands            | ✅ Done     | Delivered + hardened: real confirmation, audit/status cleanup |
| 6–7   | US-1.9    | Conversational WF            | ✅ Done     | Skeleton delivered + hardened: 404/422/integrity protections |
| 8     | US-8.1    | Open-Source Launch Prep      | ⬜ Pending  | Repo hygiene + legal + CI; roadmap doc done    |

---

## US-7.1 — Dashboard Authentication
**Status:** ✅ Delivered (2026-03-21)
**Spec:** `SOPHISTICATION_ROADMAP.md` § US-7.1; tests in `tests/test_dashboard_auth.py` (33 tests)

**What was done:**
- `APIKeyMiddleware` on all `/api/*` endpoints; `DASHBOARD_API_KEY` env var
- `public_routes` config in `settings.yaml` — GET-only bypass for demo exposure
- Write endpoints (`/api/system/*`, `/api/runs/trigger*`) always protected
- `dashboard_public_routes` property on `Settings`
- 33 tests (21 original + 12 new for public routes)

**To generate key on VPS:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
echo "DASHBOARD_API_KEY=<key>" >> .env
docker compose up -d --build
```

---

## US-4.1 — Volume-Weighted Signals
**Status:** ✅ Delivered (2026-03-22)
**Days:** 1–2 | **Effort:** Small (~1 day) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-4.1

**What was done:**
- OBV (On-Balance Volume) and volume SMA ratio indicators
- Feed into sub-strategy scoring (momentum / mean-reversion)
- No new DB tables needed; indicators added to existing `market_data_cache` OHLCV payload
- Disable switch: `data_providers.volume_signals_enabled` in `settings.yaml`
- Surface the new fields in moderator context formatting for review transparency
- Runtime-validated after scoped refresh of `market_data_cache` `lite_analysis` / `full_analysis` rows; fresh cache payloads now include the new volume fields

**Key files to touch:**
- `src/agents/strategy/momentum.py` — add OBV signal
- `src/agents/strategy/mean_reversion.py` — add volume SMA ratio
- `src/agents/market_data/` — compute indicators during OHLCV fetch
- `src/agents/moderation/context.py` — expose OBV / volume ratio in committee context
- `config/settings.yaml` — `volume_signals_enabled: true`
- Tests: `tests/test_volume_signals.py` (new)

**Acceptance criteria:**
- [x] OBV computed from OHLCV and included in strategy context
- [x] Volume SMA ratio (current vol / 20-day avg) computed and included
- [x] Both signals feed into at least one sub-strategy score
- [x] `volume_signals_enabled: false` disables both with no behaviour change
- [x] Unit tests for indicator computation with synthetic OHLCV data

---

## US-7.4 — Integration Test Coverage
**Status:** ✅ Delivered (2026-03-22)
**Days:** 2–4 | **Effort:** Medium (~2 days) | **Priority:** P1 (can run parallel with US-3.1)
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-7.4
**Audit refs:** findings I4, I5 from `docs/TRADING_SYSTEM_AUDIT.md`

**What was done:**
- Added a shared orchestrator integration harness in `tests/conftest.py` using in-memory SQLite and broad `get_session()` patching
- Added `tests/test_integration_orchestrator.py` covering happy-path `run_cycle(dry_run=True)` and orphaned decision detection
- Added `tests/test_state_machine_transitions.py` covering live ACTIVE → CAUTIOUS, live HALTED liquidation path, and manual reset recovery
- Kept production behavior unchanged: all external boundaries are mocked while the real orchestrator, strategy logging, moderation logging, risk logging, run records, and dry-run order logging execute normally

**Key files to touch:**
- `tests/test_integration_orchestrator.py` (new)
- `tests/test_state_machine_transitions.py` (new)
- `tests/conftest.py` — shared mocked pipeline fixture / harness

**Acceptance criteria:**
- [x] `run_cycle(dry_run=True)` completes without error against mocked deps
- [x] ACTIVE → CAUTIOUS transition triggers at correct drawdown threshold
- [x] CAUTIOUS → HALTED transition triggers at correct threshold
- [x] HALTED blocks new BUYs; SELL/REDUCE still allowed
- [x] Decision chain integrity: every approved BUY has a matching moderation + risk record
- [x] All new tests use in-memory SQLite (`INVESTMENT_AGENT_USE_INMEMORY_DB=1`)

---

## US-3.1 — Risk-Parity Position Sizing
**Status:** ✅ Delivered (2026-03-22)
**Days:** 2–5 | **Effort:** Large (~3 days) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-3.1

**What was delivered:**
- New `src/agents/risk/risk_parity.py` engine for 60-day annualized inverse-vol BUY sizing
- BUY-only overlay across current holdings + approved BUYs, treating existing positions as fixed background risk in v1
- Configurable controls: `risk_parity_enabled`, `risk_parity_lookback_days`, `risk_parity_vol_floor`, `risk_parity_target_vol`
- Strategy decisions now persist Claude size, risk-parity size, trailing vol, and whether the overlay was applied
- Dashboard/API waterfall exposes Claude proposed size, risk-parity target, and final risk-adjusted size
- BUY execution now uses total-target semantics and trades only the delta needed to reach the target weight
- RiskManager remains the final veto/hard-cap layer; REDUCE/SELL behaviour unchanged

**Key files to touch:**
- `src/agents/risk/` — new `risk_parity.py` module
- `src/orchestrator/main.py` — call risk-parity sizing after strategy, before RiskManager
- `src/agents/strategy/engine.py` — persist risk-parity metadata on strategy decisions
- `src/data/models.py` + Alembic migration — add risk-parity audit fields to `strategy_decisions`
- `dashboard/backend/app/schemas.py` + `dashboard/backend/app/routers/universe.py` — expose new sizing fields
- `dashboard/frontend/src/components/LLMOutputBlocks.tsx` — show Claude vs risk-parity sizing in the decision waterfall
- `src/utils/config.py` — new `risk_parity_*` settings properties
- `config/settings.yaml` — `risk_parity_enabled`, `risk_parity_lookback_days: 60`, `risk_parity_vol_floor: 0.05`, `risk_parity_target_vol: 0.15`
- Tests: `tests/test_risk_parity.py`, `tests/test_integration_orchestrator.py`, `tests/test_dashboard_decisions.py`

**Acceptance criteria:**
- [x] Volatility computed from OHLCV close prices over configurable lookback
- [x] Position size adjusted proportionally to inverse volatility
- [x] Allocation capped at `max_single_stock_pct` regardless of risk-parity output
- [x] `risk_parity_enabled: false` reverts to current sizing with no behaviour change
- [x] Unit tests with synthetic price series (low-vol vs high-vol stock)
- [x] Integration: sizing adjustment visible in strategy decision context sent to moderation

**Validation:**
- `tests/test_risk_parity.py` covers inverse-vol sizing, lookback sensitivity, vol floor, missing-history fallback, target-vol scaling, and already-above-target filtering
- Orchestrator integration confirms risk parity runs before moderation/risk, persists both Claude and risk-parity sizes, and BUY execution uses delta-to-target semantics for existing holdings
- Dashboard/API coverage confirms the decision waterfall exposes the new risk-parity fields

---

## US-1.7.3 — Dashboard Visual Design System
**Status:** ✅ Delivered (2026-03-22)
**Days:** 2–5 (parallel with US-3.1) | **Effort:** Small (~1 day) | **Priority:** P2
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-1.7.3
**Spec:** `dashboard/frontend/dashboard-style-guide.md`

**What was delivered:**

- **Syne font** added to `index.html` (400/600/700); headings globally set to Syne via CSS layer
- **Full CSS token system** in `index.css`:
  - Background, surface, border, and text tokens aligned to style guide (`--color-bg`, `--color-surface`, `--color-text-muted`, `--color-text-dim`, `--color-border-strong`)
  - Soft accent fills: `--color-violet-soft`, `--color-cyan-soft`, `--color-emerald-soft`
  - Shadow system: `--shadow-panel`, `--shadow-glow`, `--shadow-glow-strong`, `--shadow-card-hover`
  - Radius tokens: `--radius-xs` (0.75rem) through `--radius-lg` (2rem)
  - Transition tokens: `--transition-fast`, `--transition-base`
  - Brand gradient updated: violet→cyan→emerald (was cyan→emerald)
- **Glass-dark panel treatment**: `.card` rebuilt with `radial-gradient` top highlight + dark fill + 1.5rem radius + `--shadow-panel`; hover lifts to `--shadow-card-hover`
- **Atmospheric grid**: 72px violet lines (`rgba(99,50,255,0.05)`) — replaces 24px white grid
- **Updated buttons**: `.btn-primary` uses brand gradient fill + `--shadow-glow`; `.btn-secondary` border-strong + hover cyan
- **Pill classes**: `.pill` base + 6 variant classes (`pill-cyan/emerald/violet/loss/warning/dim`) for use by `StatusPill`
- **Tailwind extensions**: `font-heading` (Syne), `borderRadius.panel/hero`, `boxShadow.panel/glow/glow-strong/card-hover`, `animate-fade-up` keyframe
- **App shell** (`App.tsx`): sticky blurred nav (`backdrop-blur: 16px`, 80% opacity dark), `border-terminal-border-strong`, pill active state (`bg-cyan/10 text-cyan border-cyan/25`) replacing `border-b-2`, dropdown uses panel shadow + blur
- **`prefers-reduced-motion`** respected globally

**New primitives created:**

| File | Usage |
|------|-------|
| `src/components/Panel.tsx` | `<Panel>` (glass-dark, 1.5rem) or `<Panel hero>` (atmospheric glow, 2rem) |
| `src/components/MetricCard.tsx` | `<MetricCard label="PORTFOLIO" value="£12,450" delta="+2.4%" deltaColor="emerald" />` |
| `src/components/StatusPill.tsx` | `<StatusPill label="ACTIVE" variant="active" dot />` |
| `src/components/SectionHeader.tsx` | `<SectionHeader eyebrow="Overview" title="Portfolio" subtitle="..." />` |

**Key files changed:**
- `dashboard/frontend/index.html` — Syne font
- `dashboard/frontend/src/index.css` — token system + component classes
- `dashboard/frontend/tailwind.config.js` — Tailwind extensions
- `dashboard/frontend/src/App.tsx` — nav blur + pill active state + dropdown
- `dashboard/frontend/src/components/Panel.tsx` (new)
- `dashboard/frontend/src/components/MetricCard.tsx` (new)
- `dashboard/frontend/src/components/StatusPill.tsx` (new)
- `dashboard/frontend/src/components/SectionHeader.tsx` (new)

**Next pass:** Migrate the 8 existing pages to use `Panel`, `MetricCard`, and `StatusPill` primitives in place of ad-hoc markup.

---

## US-4.5 — Proactive Macro News Intelligence
**Days:** 3–7 | **Effort:** Large (phased delivery) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-4.5
**Spec doc:** `docs/PROACTIVE_MACRO_NEWS_INTELLIGENCE.md`
**Status:** ✅ Delivered (2026-03-23)

**What was delivered:**
- Dedicated daily `macro_scan` scheduler job gated by `macro.proactive_scan_enabled`
- Persisted `macro_state` snapshots with regime, confidence, top signals, raw payload, and `macro_action_plan`
- Normalized `macro_signal_logs` audit trail for each persisted top signal
- Deterministic proactive state builder plus structured second-order `macro_action_plan` generation with Claude-backed path and deterministic fallback
- Cycle-time injection of persisted macro context into both strategy prompt context and moderation market context
- Static-first runtime behavior: existing cached `macro_intelligence` remains in place, while persisted proactive state is layered on when available

**Acceptance criteria:**
- [x] Daily macro scan runs independently of trading cycles
- [x] Regime classification (RISK_ON/RISK_OFF/NEUTRAL) persisted to DB
- [x] Second-order reasoning prompt produces structured sector implications
- [x] `macro_state` injected into strategy context each cycle when enabled
- [x] Full audit trail: every signal logged with source, confidence, timestamp
- [x] `proactive_scan_enabled: false` leaves existing macro behaviour unchanged
- [x] All new tables created via Alembic migration

---

## US-1.6 — Slack NL Trade Commands ✅
**Days:** 5–7 | **Effort:** Medium (~2 days) | **Priority:** P2 | **Status:** Delivered
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-1.6
**Depends on:** Existing notifications module (`src/agents/notifications/`)

**What was built:**
- Regex-first NL parser (`trade_command_parser.py`) with Claude fallback for ambiguous messages
- Single-ticker pipeline (`single_ticker_run.py`): 8-phase pipeline reusing all existing agents
- User intent overrides strategy decision; moderation now reviews the final user-intended action/size
- Slack Socket Mode listener (`slack_listener.py`) with background thread processing
- CommandGateway evolved from disabled scaffold to functional command router
- Large order confirmation flow (prepare → prompt → yes/no/expiry execution path)
- `SlackCommandLog` DB model for full audit trail
- Command logs persist `review_only`, `awaiting_confirmation`, `cancelled`, `expired`, and final `response_message`
- CLI entry point: `poetry run python -m src.agents.notifications.slack_trade_listener`

**Key files created/modified:**
- `src/agents/notifications/trade_command_parser.py` (new) — NL parser with 5 regex patterns
- `src/agents/notifications/slack_listener.py` (new) — Socket Mode listener
- `src/agents/notifications/slack_trade_listener.py` (new) — CLI entry point
- `src/agents/notifications/command_gateway.py` — evolved from scaffold
- `src/agents/notifications/formatters.py` — trade command reply formatters
- `src/orchestrator/single_ticker_run.py` (new) — single-ticker pipeline
- `src/utils/ticker_utils.py` — `resolve_ticker_to_t212()`
- `src/agents/execution/order_manager.py` — `quantity_override` parameter
- `src/data/models.py` — `SlackCommandLog` model
- `config/settings.yaml` — `slack_trade_commands` config block
- `src/utils/config.py` — 6 new settings properties

**Acceptance criteria:**
- [x] `BUY AAPL` from Slack triggers a focused BUY pipeline for AAPL_US_EQ
- [x] `SELL AAPL` triggers forced SELL; Risk VETO respected (no execution if vetoed)
- [x] `REVIEW AAPL` triggers data fetch + strategy analysis; no order placed
- [x] Large orders now wait for explicit `yes` confirmation before execution
- [x] Non-command Slack chatter no longer leaves a stray processing reply
- [x] Response message sent back to Slack within 30 seconds (async background thread)
- [x] Full audit trail: `slack_command_log` with cycle_id, order_id, status, and `response_message`
- [x] `slack_trade_commands.enabled: false` disables all inbound handling
- [x] Focused US-1.6/US-1.9 regression suite: 113 passing tests

---

## US-1.9 — Conversational Trading Workflow (skeleton only this week) ✅
**Days:** 6–7 | **Effort:** Large (8–12 days total; skeleton only in Week 1) | **Priority:** P2 | **Status:** Skeleton delivered
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-1.9
**Spec doc:** `docs/CONVERSATIONAL_TRADING_WORKFLOW.md`
**Depends on:** US-1.6 (delivered)

**What was built (skeleton / Phase A):**
- `ChatSession` and `ChatTurn` DB models + Alembic migration (combined with `SlackCommandLog`)
- `SessionManager` with real DB CRUD: `create_session()`, `add_turn()`, `get_session()`, `end_session()`
- FastAPI endpoints: `POST /api/chat/sessions`, `POST /sessions/{id}/turns`, `GET /sessions/{id}`, `POST /sessions/{id}/end`
- Request validation for `channel_type` / `role`; missing sessions now return `404`
- Schema hardening: `chat_turns.session_id` FK and unique `(session_id, turn_index)` constraint
- No LLM calls; no Slack integration; no execution — just the plumbing

**Key files created:**
- `src/data/models.py` — `ChatSession`, `ChatTurn` models
- `src/data/migrations/versions/l7m8n9o0p1q2_add_slack_command_log_and_chat_tables.py`
- `src/data/migrations/versions/m9n0o1p2q3r4_add_chat_turn_constraints.py`
- `src/agents/conversation/session_manager.py` (new)
- `dashboard/backend/app/routers/chat.py` (new)
- `tests/test_chat_session_stub.py` and `tests/test_chat_api.py` — skeleton guardrail coverage

**Deferred to Week 2+:**
- Full conversation orchestrator with LLM reasoning
- Slack thread continuity
- Explicit confirmation gate before execution
- Research tool integration
- Dashboard chat panel UI

**Acceptance criteria (Week 1 scope only):**
- [x] `chat_sessions` and `chat_turns` tables created via migration
- [x] `POST /api/chat/sessions` creates a session record, returns session_id
- [x] `POST /api/chat/sessions/{id}/turns` appends a turn record
- [x] `GET /api/chat/sessions/{id}` returns session + turns
- [x] Missing sessions return `404`; invalid request shapes fail with `422`
- [x] No LLM calls, no execution, no Slack integration
- [x] Tests pass against in-memory SQLite

---

## US-8.1 — Open-Source Launch Preparation
**Day:** 8 | **Effort:** Medium (~1 day) | **Priority:** P0 for launch
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-8.1
**Spec doc:** `docs/OPEN_SOURCE_LAUNCH.md` ✅ (already written)

**What to build:**

**Phase A — Repo hygiene:**
```bash
git rm -r Investment-agent/      # remove nested duplicate
git remote remove old-origin     # remove KayvanNejabati remote
```

**Phase B — Legal & community files:**
- `LICENSE` (MIT, copyright Zenouz.ai 2026)
- `CONTRIBUTING.md` (poetry install, pytest, mypy, black/isort, PR process)
- `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1, contact zenouz.ai@gmail.com)
- `SECURITY.md` (email-only disclosure, 48h SLA)

**Phase C — GitHub infrastructure:**
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/ci.yml` (ubuntu-latest, python 3.11, poetry install → pytest -v → mypy src/)

**Acceptance criteria:** see `docs/OPEN_SOURCE_LAUNCH.md` checklist

---

## Session handoff notes

- All work goes on branch `claude/review-roadmap-priorities-9F67J`
- Run `poetry run pytest -v` before every push; 441 tests must pass (or higher)
- Each story should be committed separately with a clear message
- US-4.1 and US-7.4 can be started in parallel (independent)
- US-3.1 delivered in parallel with US-7.4 on 2026-03-22
- US-1.9 skeleton cannot start until US-1.6 is merged
- US-8.1 is pure file work — no test impact expected
