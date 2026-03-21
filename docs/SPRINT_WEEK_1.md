# Sprint Plan — Week 1 (ZenInvest)

> **Created:** 2026-03-21
> **Branch:** `claude/review-roadmap-priorities-9F67J`
> **Goal:** Deliver 7 user stories across 8 days in priority order.

---

## Schedule at a glance

| Days  | ID      | Story                        | Status     | Notes                                          |
|-------|---------|------------------------------|------------|------------------------------------------------|
| 1     | US-7.1  | Dashboard Authentication     | ✅ Done     | Already delivered; unblocks safe VPS exposure  |
| 1–2   | US-4.1  | Volume Signals               | ⬜ Pending  | Small, self-contained, ~1 day                  |
| 2–4   | US-7.4  | Integration Test Coverage    | ⬜ Pending  | Can run in parallel with US-3.1                |
| 2–5   | US-3.1  | Risk-Parity Sizing           | ⬜ Pending  | No deps, ~3 days                               |
| 3–7   | US-4.5  | Proactive Macro Intelligence | ⬜ Pending  | Largest; phased delivery                       |
| 5–7   | US-1.6  | Slack NL Commands            | ⬜ Pending  | Builds on existing notifications module        |
| 6–7   | US-1.9  | Conversational WF            | ⬜ Pending  | Skeleton only this week; US-1.6 must land first|
| 8     | US-8.1  | Open-Source Launch Prep      | ⬜ Pending  | Repo hygiene + legal + CI; roadmap doc done    |

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
**Days:** 1–2 | **Effort:** Small (~1 day) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-4.1

**What to build:**
- OBV (On-Balance Volume) and volume SMA ratio indicators
- Feed into sub-strategy scoring (momentum / mean-reversion / factor)
- No new DB tables needed; indicators added to existing `market_data_cache` OHLCV payload
- Disable switch: `data_providers.volume_signals_enabled` in `settings.yaml`

**Key files to touch:**
- `src/agents/strategy/momentum.py` — add OBV signal
- `src/agents/strategy/mean_reversion.py` — add volume SMA ratio
- `src/agents/market_data/` — compute indicators during OHLCV fetch
- `config/settings.yaml` — `volume_signals_enabled: true`
- Tests: `tests/test_volume_signals.py` (new)

**Acceptance criteria:**
- [ ] OBV computed from OHLCV and included in strategy context
- [ ] Volume SMA ratio (current vol / 20-day avg) computed and included
- [ ] Both signals feed into at least one sub-strategy score
- [ ] `volume_signals_enabled: false` disables both with no behaviour change
- [ ] Unit tests for indicator computation with synthetic OHLCV data

---

## US-7.4 — Integration Test Coverage
**Days:** 2–4 | **Effort:** Medium (~2 days) | **Priority:** P1 (can run parallel with US-3.1)
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-7.4
**Audit refs:** findings I4, I5 from `docs/TRADING_SYSTEM_AUDIT.md`

**What to build:**
- End-to-end `orchestrator.run_cycle()` integration test (dry-run, in-memory SQLite)
- State machine transition tests: ACTIVE → CAUTIOUS → HALTED and manual recovery
- Pipeline chain integrity test: strategy decision flows correctly through moderation → risk → execution
- Stub all external API calls (T212, LLMs, yfinance) via `unittest.mock`

**Key files to touch:**
- `tests/test_integration_orchestrator.py` (new)
- `tests/test_state_machine_transitions.py` (new)
- May need a `conftest.py` fixture for a fully-mocked pipeline context

**Acceptance criteria:**
- [ ] `run_cycle(dry_run=True)` completes without error against mocked deps
- [ ] ACTIVE → CAUTIOUS transition triggers at correct drawdown threshold
- [ ] CAUTIOUS → HALTED transition triggers at correct threshold
- [ ] HALTED blocks new BUYs; SELL/REDUCE still allowed
- [ ] Decision chain integrity: every approved BUY has a matching moderation + risk record
- [ ] All new tests use in-memory SQLite (`INVESTMENT_AGENT_USE_INMEMORY_DB=1`)

---

## US-3.1 — Risk-Parity Position Sizing
**Days:** 2–5 | **Effort:** Large (~3 days) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-3.1

**What to build:**
- Size positions inversely to trailing volatility (e.g. 20-day realised vol)
- Equal risk contribution across positions: `weight_i = (1/vol_i) / Σ(1/vol_j)`
- Applied as a cap/adjustment on top of existing `max_single_stock_pct` logic
- Configurable: target portfolio vol, lookback window, vol floor
- Disable switch: `risk.risk_parity_enabled` (defaults to false until calibrated)
- No change to RiskManager VETO logic — sizing is pre-risk adjustment

**Key files to touch:**
- `src/agents/risk/` — new `risk_parity.py` module
- `src/orchestrator/main.py` — call risk-parity sizing after strategy, before RiskManager
- `src/utils/config.py` — new `risk_parity_*` settings properties
- `config/settings.yaml` — `risk_parity_enabled`, `risk_parity_lookback_days: 20`, `risk_parity_vol_floor: 0.05`, `risk_parity_target_vol: 0.15`
- Tests: `tests/test_risk_parity.py` (new)

**Acceptance criteria:**
- [ ] Volatility computed from OHLCV close prices over configurable lookback
- [ ] Position size adjusted proportionally to inverse volatility
- [ ] Allocation capped at `max_single_stock_pct` regardless of risk-parity output
- [ ] `risk_parity_enabled: false` reverts to current sizing with no behaviour change
- [ ] Unit tests with synthetic price series (low-vol vs high-vol stock)
- [ ] Integration: sizing adjustment visible in strategy decision context sent to moderation

---

## US-4.5 — Proactive Macro News Intelligence
**Days:** 3–7 | **Effort:** Large (phased delivery) | **Priority:** P1
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-4.5
**Spec doc:** `docs/PROACTIVE_MACRO_NEWS_INTELLIGENCE.md`

**What to build (phased):**

**Phase 1 — Scheduled macro scan:**
- New `MacroIntelligenceAgent` that runs once per day (not per cycle)
- Sources: Finnhub general news + Alpha Vantage sector + yfinance macro ETFs (TLT, GLD, VIX proxies)
- Outputs: `macro_state` dict with regime (RISK_ON / RISK_OFF / NEUTRAL), top 3 signals, confidence score
- Persisted to `macro_state` table (new Alembic migration)
- Disable switch: `macro.proactive_scan_enabled`

**Phase 2 — Second-order reasoning:**
- Claude prompt receives `macro_state` + top signals
- Prompt asks for second-order portfolio implications (e.g. "rising yields → REIT headwind")
- Output: structured `macro_action_plan` with affected sectors, directional bias, confidence

**Phase 3 — Pipeline integration:**
- `macro_state` and `macro_action_plan` injected into strategy prompt context each cycle
- Moderation committee receives `sector_headwind` and `economic_highlights` (already partially done via `macro_intelligence.py`)
- Risk: macro regime feeds a soft signal (no hard VETO from macro alone)

**Phase 4 — Audit trail:**
- `macro_signal_logs` table: timestamp, signal source, signal text, confidence, regime classification
- Dashboard Costs page: macro scan cost band (if LLM used)

**Key files to touch:**
- `src/agents/market_data/macro_intelligence.py` — extend existing module
- `src/data/models.py` — new `MacroState`, `MacroSignalLog` models
- `src/data/migrations/` — Alembic migration for new tables
- `src/scheduler/scheduler.py` — add daily macro scan job
- `config/settings.yaml` — `macro.proactive_scan_enabled`, `macro.scan_time_utc: "06:00"`
- Tests: extend `tests/test_macro_intelligence.py` (new phases)

**Acceptance criteria:**
- [ ] Daily macro scan runs independently of trading cycles
- [ ] Regime classification (RISK_ON/RISK_OFF/NEUTRAL) persisted to DB
- [ ] Second-order reasoning prompt produces structured sector implications
- [ ] `macro_state` injected into strategy context each cycle when enabled
- [ ] Full audit trail: every signal logged with source, confidence, timestamp
- [ ] `proactive_scan_enabled: false` leaves existing macro behaviour unchanged
- [ ] All new tables created via Alembic migration

---

## US-1.6 — Slack NL Trade Commands
**Days:** 5–7 | **Effort:** Medium (~2 days) | **Priority:** P2
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-1.6
**Depends on:** Existing notifications module (`src/agents/notifications/`)

**What to build:**
- Inbound Slack slash commands or keyword parsing: `BUY <ticker>`, `SELL <ticker>`, `REVIEW <ticker>`
- Single-ticker pipeline: user intent triggers a focused run_cycle for that ticker only
- User intent overwrites strategy decision (BUY/SELL forced); Risk can still VETO
- Slack webhook listener (new endpoint or polling)
- Response: confirmation message back to Slack with decision outcome

**Key files to touch:**
- `src/agents/notifications/command_gateway.py` — enable the scaffold (currently `enabled: false`)
- `src/agents/notifications/slack_listener.py` (new) — inbound webhook handler
- `src/orchestrator/main.py` — `run_single_ticker(ticker, forced_action)` method
- `dashboard/backend/app/routers/` — optional: expose command via dashboard API too
- `config/settings.yaml` — `notifications.command_gateway.enabled: true`
- Tests: `tests/test_slack_commands.py` (new)

**Acceptance criteria:**
- [ ] `BUY AAPL` from Slack triggers a focused BUY pipeline for AAPL_US_EQ
- [ ] `SELL AAPL` triggers forced SELL; Risk VETO respected (no execution if vetoed)
- [ ] `REVIEW AAPL` triggers data fetch + strategy analysis; no order placed
- [ ] Response message sent back to Slack within 30 seconds
- [ ] Full audit trail: command logged to `notification_logs` with source=slack_command
- [ ] `command_gateway.enabled: false` disables all inbound handling
- [ ] Unit tests with mocked Slack payloads

---

## US-1.9 — Conversational Trading Workflow (skeleton only this week)
**Days:** 6–7 | **Effort:** Large (8–12 days total; skeleton only in Week 1) | **Priority:** P2
**Roadmap:** `docs/SOPHISTICATION_ROADMAP.md` § US-1.9
**Spec doc:** `docs/CONVERSATIONAL_TRADING_WORKFLOW.md`
**Depends on:** US-1.6 (must land first)

**What to build this week (skeleton / Phase A only):**
- `ChatSession` and `ChatTurn` DB models + Alembic migration (tables only, no logic yet)
- `SessionManager` stub: `create_session()`, `add_turn()`, `get_session()`, `end_session()`
- Minimal FastAPI endpoints: `POST /api/chat/sessions`, `POST /api/chat/sessions/{id}/turns`
- No LLM calls yet; no Slack integration yet; no execution yet
- Returns hardcoded `{"status": "received"}` — just the plumbing

**Deferred to Week 2+:**
- Full conversation orchestrator with LLM reasoning
- Slack thread continuity
- Explicit confirmation gate before execution
- Research tool integration
- Dashboard chat panel UI

**Key files to touch:**
- `src/data/models.py` — `ChatSession`, `ChatTurn` models
- `src/data/migrations/` — Alembic migration
- `src/agents/notifications/session_manager.py` (new stub)
- `dashboard/backend/app/routers/chat.py` (new, minimal)
- Tests: `tests/test_chat_session_stub.py` (new, basic CRUD)

**Acceptance criteria (Week 1 scope only):**
- [ ] `chat_sessions` and `chat_turns` tables created via migration
- [ ] `POST /api/chat/sessions` creates a session record, returns session_id
- [ ] `POST /api/chat/sessions/{id}/turns` appends a turn record
- [ ] `GET /api/chat/sessions/{id}` returns session + turns
- [ ] No LLM calls, no execution, no Slack integration
- [ ] Tests pass against in-memory SQLite

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
- US-3.1 can be started in parallel with US-7.4 from Day 2
- US-1.9 skeleton cannot start until US-1.6 is merged
- US-8.1 is pure file work — no test impact expected
