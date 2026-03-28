# Investment Agent

Autonomous investment agent that trades via the Trading 212 API (Practice/Demo mode) using a multi-LLM strategy pipeline. Currently deployed as a **Proof of Concept (v1.0)** to gather live performance data, with a [sophistication roadmap](docs/SOPHISTICATION_ROADMAP.md) for systematic improvement based on evidence.

**Status:** POC — **1008 pytest cases currently pass**, with the dashboard frontend type-check and production build clean. Coverage includes performance/trade-outcome, backtesting, order management, notifications, macro intelligence, proactive macro scans, volume signals, risk-parity sizing, orchestrator integration coverage, scheduler/runtime locking, dry-run state isolation, dashboard backend, research router, search API tracker, daily/weekly reports, market holidays, opportunity optimizer edge cases, agent logic audit fixes, formal verification phase 2, dashboard auth hardening with explicit public/private split, dashboard orders health semantics, FX-aware BUY quantity correction, trailing stop cancel-first ratchet + invalid-stop guard, intraday refresh scheduling/status flows, run dataset audit persistence, conversational trading workflow delivery, and the Zen Evolution Engine planner workflow. Deployment-ready for VPS. **Current production control plane remains Docker Compose.** **US-1.9 Conversational Trading Workflow delivered** (shared Slack/dashboard conversational sessions, explicit confirm/reject/expiry flow, audited actions/research/workflow steps, agentic beta path with workflow transparency, and persistent LLM intent-detection cache reuse for repeated ambiguous requests). **Intraday broker/data refresh lane delivered** (Mon–Fri pre/post-cycle refreshes plus Sat/Sun 17:00 America/New_York weekend refreshes; broker order sync, fresh portfolio snapshots, held/pending/queued market-data warming, stop/profit-lock maintenance, compact dashboard freshness metadata, and per-run dataset audits). **US-7.7 Dashboard HTTPS Domain & Canonical Access delivered** (canonical Cloudflare + nginx HTTPS ingress, internal-only dashboard service, no public raw `:8000`, and a narrow anonymous read-only surface for Overview, Portfolio, World News, and Roadmap). **US-7.5 Quick Hardening Slice delivered** (off-hours order annotations, HALTED auto-recovery after 3 clean live cycles, peak inflation detection, DB-level guardrails, and dashboard visibility for the new hardening signals). **US-7.6 VPS Runtime Stability & Service Isolation delivered** (runtime locks, single-process API entrypoint, bounded Slack/manual trigger execution, separate migration service, plus an optional non-Docker `systemd` path for small VPS use). **US-4.5 Proactive Macro News Intelligence delivered** (scheduled macro scan, persisted `macro_state`, `macro_signal_logs`, structured `macro_action_plan`, strategy/moderation context injection). **US-1.10 Evolution Planner partially delivered** (Phase 1 planner-only slice: authenticated dashboard-first change planning with intent normalization, static repo-context mapping, risk classification, validation matrices, clarification loop, and audit trail; no code, branch, build, or deploy authority yet). US-1.8 Dashboard VPS Deployment implemented (Docker, multi-stage frontend build, SPA fallback). US-7.1 Dashboard Authentication hardened (server-issued operator sessions, secure cookies, explicit `/api/public/*` routes, no frontend secret injection). US-4.1 Volume Signals delivered (`volume_signals_enabled`, OBV + 20-day volume ratio in indicator output, momentum/mean-reversion scoring). US-7.4 Integration Test Coverage delivered (`run_cycle()` end-to-end dry-run coverage, orphaned-decision detection, live state transitions, manual reset). US-3.1 Risk-Parity Position Sizing delivered (`risk_parity_enabled`, 60-day inverse-vol sizing overlay, Claude-vs-risk-parity sizing audit fields, delta-to-target BUY execution). **US-1.7.3 Dashboard Visual Design System delivered** (Syne font, full CSS token system, glass-dark panels, 72px violet grid, brand gradient, blurred nav, pill active state, 4 shared primitives: `Panel`/`MetricCard`/`StatusPill`/`SectionHeader`). See [Dashboard Deployment](docs/DASHBOARD_DEPLOYMENT.md), [VPS Runtime Stability Plan](docs/VPS_RUNTIME_STABILITY_PLAN.md), [UX Audit](docs/UX_AUDIT.md), and [Zen Evolution Engine](docs/ZEN_EVOLUTION_ENGINE.md).

**Active roadmap order:** `US-8.1` Open-Source Launch Preparation -> `US-7.3` Execution Quality & Slippage Monitoring -> `US-7.2` Partial Fill Resubmission. `US-1.9` is now delivered, `US-1.10` is partially delivered as a planner-only parallel foundation, and `US-1.11+` remain gated behind the posture/workflow/CI sequence above. A planned learning-loop track now captures `US-2.5` Market Guidance Layer and `US-2.6` Strategy Episode Attribution so future cycles can record which guidance influenced screening and which repo-level strategy changes were active. See [`docs/SOPHISTICATION_ROADMAP.md`](docs/SOPHISTICATION_ROADMAP.md), [`docs/SPRINT_WEEK_1.md`](docs/SPRINT_WEEK_1.md), and [`docs/MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md`](docs/MARKET_GUIDANCE_AND_STRATEGY_ATTRIBUTION_PLAN.md).

## Architecture

```
Orchestrator (configurable: intraday = 10:00/12:30/15:15 America/New_York, standard = 07:00/19:00 UTC)
  ├── Market Data Agent    → yfinance + Finnhub + Alpha Vantage (per-ticker news)
  ├── Universe Screener    → Sector-balanced, cap-tiered candidate discovery
  ├── Strategy Agent       → Momentum + Mean Reversion + Factor → Claude Sonnet synthesis
  ├── Moderation Panel     → GPT-4o (skeptic) + Gemini (risk assessor) → consensus
  ├── Risk Agent           → Hard rules, VETO power, never overridden by LLMs
  ├── Opportunity Agent    → Universal Opportunity Value (UOV) scoring + ranked BUY queue
  ├── Execution Agent      → Trading 212 API: market orders + stop-loss + dedup
  ├── Refresh Lane         → T212 sync + fresh snapshots + held-book stop/profit-lock maintenance
  ├── Notification Agent   → Slack webhook + SMTP email alerts + notification_logs audit trail
  └── Journal & Reporting  → Per-trade journals, daily + weekly reports
```

**State Machine:** ACTIVE → CAUTIOUS (>30% drawdown, configurable) → HALTED (>40% drawdown, liquidate all)

## Setup

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation)
- API keys: Trading 212, Anthropic, OpenAI, Google AI, Finnhub, Alpha Vantage

### Installation

```bash
# Clone and install
git clone <repo-url> && cd investment-agent
poetry install

# Configure environment
cp config/.env.example .env
# Edit .env with your API keys

# Initialize database
poetry run alembic upgrade head
```

### Configuration

Edit `config/settings.yaml` for trading parameters, risk limits, cost budgets, and model selection.

Key settings:
- **Trading:** `cycle_frequency` (intraday | standard), `schedule_mode`, cycle times, position limits, cash floor
- **Risk:** drawdown thresholds, VIX limits, sector caps, correlation limits, risk-parity overlay (`risk_parity_enabled`, `risk_parity_lookback_days`, `risk_parity_vol_floor`, `risk_parity_target_vol`)
- **Universe:** candidate count, sector balance, market-cap tiers, screening cooldown
- **Opportunity:** UOV mode (`shadow|active`), thresholds (`immediate_threshold_z`, `queue_threshold_z`), EWMA half-life, queue TTL, swap delta
- **Data Providers:** `macro_intelligence_enabled`, `volume_signals_enabled`, per-source cache TTLs
- **Notifications:** channel routes, retries/timeouts, dedup window, dry-run alert policy
- **Cost:** daily per-provider budgets, monthly total cap
- **Models:** Claude Sonnet (strategy), GPT-4o + Gemini Flash (moderation)

## Usage

### Run a single cycle

```bash
# Dry run (no real trades)
poetry run python -m src.orchestrator.main --dry-run

# Live cycle
poetry run python -m src.orchestrator.main
```

### CLI commands

```bash
poetry run python -m src.orchestrator.main --status       # System status
poetry run python -m src.orchestrator.main --performance  # Performance metrics summary
poetry run python -m src.orchestrator.main --dashboard   # Dashboard: portfolio, metrics, costs, positions
poetry run python -m src.orchestrator.main --pause        # Pause trading
poetry run python -m src.orchestrator.main --resume       # Resume trading
poetry run python -m src.orchestrator.main --reset-peak   # Reset peak to current, clear CAUTIOUS if incorrect
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ  # Force sell
poetry run python -m src.orchestrator.main --report       # Generate daily report
poetry run python -m src.orchestrator.main --uov-diagnostic  # Run with UOV in shadow mode, emit scores for calibration
```

### Backtesting

```bash
# Run with real data (fetches from yfinance if data/backtest/ empty; caches to CSV)
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward

# Synthetic data (no network, fast sanity check)
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
poetry run python -m src.backtesting.main --scenario bull --synthetic
```

See [Backtesting](docs/BACKTESTING.md) (includes walk-forward validation and promotion report) for details.

### Run the scheduler (continuous)

```bash
poetry run python -m src.scheduler.scheduler
```

### Dashboard (Phase 1 + Phase 1.5 Analytics Lite)

Run the backend from the project root (so `src` and `dashboard` are importable):

```bash
# Start the dashboard API server (local dev)
poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000

# API at http://localhost:8000, OpenAPI docs at http://localhost:8000/docs
```

**Endpoints:**
- `GET /api/runs/`, `GET /api/runs/diff`, `GET /api/runs/cycle/{cycle_id}`, `POST /api/runs/trigger`, `POST /api/runs/trigger-live` — Run history and dry/live cycle trigger
- `GET /api/status/` — Next run, next refresh, cycle_frequency, local refresh schedule, system state (ACTIVE/CAUTIOUS/HALTED), paused, HALTED auto-recovery progress, last refresh status, and current peak-inflation warning note when active
- `GET /api/universe/`, `GET /api/universe/{ticker}` — Universe and instrument detail
- `GET /api/portfolio/`, `GET /api/portfolio/history` — Portfolio snapshot and history
- `GET /api/public/portfolio`, `GET /api/public/portfolio/history` — Public read-only portfolio snapshot and history
- `GET /api/orders/`, `GET /api/orders/health` — Order history plus broker-sync health, unresolved failures, and pending local-vs-live reconciliation
- `GET /api/events/`, `GET /api/events/stream` — Event log and SSE stream
- `GET /api/decisions/`, `GET /api/decisions/waterfall`, `GET /api/decisions/{cycle_id}`, `GET /api/decisions/ticker/{ticker}` — Strategy decisions and pipeline waterfall
- `GET /api/moderation/{cycle_id}`, `GET /api/moderation/ticker/{ticker}` — Moderation logs
- `GET /api/risk/{cycle_id}` — Risk decisions
- `GET /api/opportunity/config/`, `GET /api/opportunity/scores/`, `GET /api/opportunity/scores/{cycle_id}`, `GET /api/opportunity/queue/`, `GET /api/opportunity/history/{ticker}` — UOV config, scores and queue
- `GET /api/outcomes/`, `GET /api/outcomes/stats` — Trade outcomes and aggregate stats
- `GET /api/stop-loss/current`, `GET /api/stop-loss/adjustments` — Stop-loss levels and adjustment history
- `GET /api/performance/metrics`, `GET /api/performance/history` — Performance metrics
- `GET /api/public/macro/state`, `GET /api/public/macro/state/history`, `GET /api/public/macro/headlines`, `GET /api/public/macro/summary` — Public read-only World News / macro archive
- `GET /api/costs/daily`, `GET /api/costs/monthly`, `GET /api/costs/degradation` — Cost breakdown and degradation
- `GET /api/api-usage/daily` — API call counts and error rates
- `GET /api/system/state`, `POST /api/system/trigger-cycle`, `POST /api/system/trigger-refresh`, `POST /api/system/pause`, `POST /api/system/resume` — System state and controls, including HALTED recovery streak/target, refresh trigger, and any active peak-inflation warning note
- `GET /api/commands/`, `GET /api/commands/stats` — Slack trade command audit log (filter by ticker, action, status)
- `GET /api/chat/sessions`, `POST /api/chat/sessions`, `GET /api/chat/sessions/{id}`, `GET /api/chat/sessions/{id}/turns`, `GET /api/chat/sessions/{id}/actions`, `GET /api/chat/sessions/{id}/spend`, `POST /api/chat/sessions/{id}/turns`, `POST /api/chat/sessions/{id}/actions/{action_id}/confirm`, `POST /api/chat/sessions/{id}/actions/{action_id}/reject`, `POST /api/chat/sessions/{id}/end`, `DELETE /api/chat/sessions/{id}` — Shared Slack/dashboard conversational trading session APIs for `US-1.9`, including paginated history, spend summaries, and archive support. Turn submits return refreshed session detail synchronously; confirm/reject requests require `expected_version` and return `409` with the latest action payload if the proposal changed.
- `GET /api/evolution/requests`, `POST /api/evolution/requests`, `GET /api/evolution/requests/{id}`, `GET /api/evolution/requests/{id}/plan`, `POST /api/evolution/requests/{id}/messages`, `GET /api/evolution/requests/{id}/runs`, `GET /api/evolution/requests/{id}/artifacts`, `POST /api/evolution/requests/{id}/approve-build`, `POST /api/evolution/requests/{id}/approve-deploy`, `GET /api/evolution/requests/{id}/deployments` — Zen Evolution Engine Phase 1 planner workflow (approvals intentionally blocked and audited in `US-1.10`)

**Configuration:** Set `dashboard.enabled: true` and `dashboard.events_enabled: true` in `config/settings.yaml`.

### Dashboard Frontend

**Brand:** `ZENOUZ.ai` is the company brand, `ZenInvest` is the product, and the authenticated dashboard home is titled `ZenInvest Agent`. The frontend uses the Graph Theory Z logo family, a cyan→emerald brand gradient, a dark base (`#06060a`), Syne for hero headings/KPIs, Outfit for body/UI copy, and JetBrains Mono for data labels. The shared page header across dashboard tabs includes a right-aligned hybrid bold Z mark inside a subtle glass panel. See `/branding/BRAND.md` for the full brand guide.

```bash
cd dashboard/frontend
nvm use    # Node 20 LTS (see dashboard/frontend/.nvmrc)
npm install
npm run dev    # Dev server on http://localhost:3000 (proxies API)
npm run build  # Production build (outputs to dist/)
```

**Pages:** Dashboard Home (alert banner on all pages; system state badge with distinct PAUSED colour; Pause/Resume toggle; Dry Run/Live Run/**Refresh** buttons; compact 5-card operator hero — next cycle, next refresh, portfolio value, performance 30d, monthly summary; rounded hero portfolio value; labeled snapshot/refresh freshness row; subtle cycle/refresh audit health line; always-visible cycle summary, positions snapshot with P&L bars and sparklines, real-time activity feed; independent section loading via `useAsyncData`; skeleton loading screens; follow-up refetch after manual refresh; AlertBanner now also surfaces HALTED auto-recovery progress and active peak-inflation warnings when present), Stock Universe (searchable, sortable-by-column table with `Investigated`, `Reviews`, `Decisions`, `Holding`, `Sold`, `UOV (ewma)` columns plus expandable rows with pipeline waterfall visualisation and committee reasoning and **full LLM outputs** — strategy reasoning, exit conditions, news/market/portfolio text, raw JSON; all moderators’ verdicts and reasoning; risk reasoning and triggered rules; deep-linkable via `/universe/:ticker`; auto-refreshes every 30s). The Universe `Sold` metric is computed from both executed and dry-run SELL orders (SELL quantities stored as negative; the dashboard reports `abs(sum(quantity))`), and the detail panel shows whether any live BUY/SELL executions exist in Trading 212 for the ticker. Additional pages: Run History (timeline, run diff view, including `refresh` runs and per-run dataset audit details), Portfolio (positions with inline sparklines, P&L chart, sector allocation, public read-only when signed out, Force Sell only after operator sign-in, auto-refresh every 30s from the latest snapshot), Opportunity Pipeline (UOV scores and queue; queue shows when/why queued, when action taken, action), Order Management (broker-sync health, active vs archived unresolved failures, separate history/live sync warnings with timestamps, recent orders, stop-loss levels, adjustment history, and scheduled refresh summary; auto-refresh every 30s), Chat (`/chat`, with `/commands` retained as a backward-compatible alias: chat-first conversational operator console with session rail, live thread, planner-led mode chips, agent activity rail, evidence panels, degraded-turn warnings, pending proposal/action rail, research trace, session spend, and a secondary **Legacy Slack Audit** tab that is not the full conversation archive and auto-refreshes while open), World News (macro regime + headline archive + action plan; public read-only when signed out; auto-refresh every 30s), Costs (daily/monthly cost charts, degradation; auto-refresh every 30s), Roadmap (default **Timeline** board with near-uniform story cards grouped into Delivered / Next / Soon / Later, plus a secondary detailed roadmap tab and a custom staged architecture map), and Evolution (authenticated operator-only natural-language change planning, clarification loop, validation matrix, repo context, and audit trail for `US-1.10`). 11 pages total. Anonymous surface: Overview, Portfolio, World News, and Roadmap. Operator-only pages and controls remain authenticated. Navigation: primary 5 pages for signed-in operators (`Dashboard`, `Universe`, `Portfolio`, `Runs`, `Roadmap`) + `More` dropdown for secondary pages, while signed-out visitors see a reduced public nav. UX: skeleton loading screens, mobile card layouts, responsive column hiding, `aria-expanded`/`aria-live` accessibility, focus-trapped modals, directional P&L arrows (▲/▼) for colour-blind safety. All 28 UX audit findings resolved (score 9.0/10). See `docs/UX_AUDIT.md` for full audit.

**Dashboard roadmap data:** `docs/SOPHISTICATION_ROADMAP.md` is the planning source of truth. The Roadmap page reads synchronized milestone data from `dashboard/frontend/src/data/roadmap.ts`, which should be updated alongside the master roadmap whenever priority, status, or grouping changes. Pipeline items should carry `horizon` (`Next` / `Soon` / `Later`) and `timeboxDays` (`1` or `2`), and grouped work should use `track`, `legacyIds`, `materiality`, `gate`, and `activeOrder` so the dashboard reflects the same planning model as the docs.

**Testing the dashboard:** Ensure `dashboard.enabled: true` in `config/settings.yaml`. Start the backend: `poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000`. Run the endpoint check: `poetry run python dashboard/backend/test_endpoints.py`. Then run the frontend (`npm run dev` in `dashboard/frontend` or open `http://localhost:8000` after `npm run build`). See `dashboard/backend/TESTING.md` for the full 11-page and API check.

**Docker:** `docker compose up -d` runs the scheduler, always-on Slack listener, the internal-only `dashboard` service, and the public `nginx` ingress. Production access is now the canonical HTTPS domain `https://zeninvest.zenouz.ai` via Cloudflare + Nginx; public raw `:8000` exposure is intentionally removed. Public read-only pages work anonymously (Overview, Portfolio, World News, Roadmap); operator pages and controls require sign-in and are intentionally blocked over plain HTTP unless you are tunnelling to localhost in dev mode. The Nginx service expects a Cloudflare Origin CA cert/key at `/home/deploy_invest_ai/certs/zeninvest.zenouz.ai/`; see `docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md` and `docs/DASHBOARD_DEPLOYMENT.md`. Use the **Dry Run** or **Live Run** buttons only after operator sign-in, or: `docker exec -it investment-agent poetry run python -m src.orchestrator.main` (live); add `--dry-run` for dry-run.

**Schedule (configurable):**

| Job | When | Notes |
|-----|------|-------|
| Analysis cycles | Mon–Fri, from configured schedule mode | `intraday`: `10:00`, `12:30`, `15:15` America/New_York (DST-aware; resolves to `14:00`, `16:30`, `19:15` UTC during US EDT). `standard`: `07:00`, `19:00` UTC (2 cycles). |
| Intraday refresh lane | Mon–Fri `09:50`, `10:10`, `12:20`, `12:40`, `15:05`, `15:25` America/New_York; Sat/Sun `17:00` America/New_York | Broker truth sync, portfolio snapshot refresh, held/pending/queued market-data warming, deterministic stop/profit-lock maintenance, and dashboard freshness updates. |
| Daily snapshot | 21:30 UTC daily | Portfolio snapshot + daily report |
| Weekly report | Friday 22:00 UTC | End-of-week summary |
| Instrument refresh | Sunday 12:00 UTC | Update tradable universe from T212 |

Set `cycle_frequency: intraday`, `schedule_mode: market_session`, `schedule_timezone: America/New_York`, and `cycle_times_local: ["10:00", "12:30", "15:15"]` in `config/settings.yaml` for DST-aware regular-session scheduling. Use `standard` for the original 2-cycle fixed-UTC cadence.

### Docker

Two Dockerfiles: `Dockerfile.agent` (Python-only, reused for the scheduler and the always-on Slack listener) and `Dockerfile` (multi-stage Node + Python, builds the frontend and runs the dashboard). The `investment-agent` and `slack-listener` services use `Dockerfile.agent`; the `dashboard` service uses `Dockerfile`; the public HTTPS ingress uses `nginx:alpine` with repo-managed config under `deploy/nginx/conf.d/`. This avoids building the frontend twice and halves memory usage during builds on low-RAM VPS instances.

```bash
# Build and run all services (scheduler + Slack listener + dashboard + nginx ingress)
docker compose up -d --build

# Rebuild only the dashboard app (e.g. after frontend changes)
docker compose up -d --build dashboard

# Rebuild only the scheduler (e.g. after strategy/risk changes)
docker compose up -d --build investment-agent

# Rebuild only the always-on Slack listener
docker compose up -d --build slack-listener

# Recreate the nginx ingress after config changes
docker compose up -d --force-recreate nginx

# View logs
docker compose logs -f investment-agent
docker compose logs -f slack-listener
docker compose logs -f dashboard
docker compose logs -f nginx

# Verify nginx config inside the ingress container
docker compose exec nginx nginx -t

# Dashboard at https://zeninvest.zenouz.ai in production
# Activity feed: Dashboard Home page; Run History: runs table (one row per cycle; scheduled cycles use single Run, no duplicates)

# One-off live cycle (in addition to scheduler)
docker exec -it investment-agent poetry run python -m src.orchestrator.main

# One-off dry-run cycle
docker exec -it investment-agent poetry run python -m src.orchestrator.main --dry-run
```

## Chat Notifications (US-1.5 Delivered)

Outbound chat interface v1 is live with persistent audit logging.

- **Delivered (US-1.6):** Inbound Slack natural language trade commands now support 4 explicit modes:
  - `review` — e.g. `REVIEW MSFT`, strategy/moderation/risk analysis only, no execution
  - `direct_trade` — plain `BUY AAPL`, `SELL 10 TSLA`, `BUY £500 NVDA`; bypasses strategy, moderation, and risk and goes straight to quote lookup, preflight checks, confirmation, and execution
  - `strategy_trade` — e.g. `review Apple and buy`, `buy Apple and trigger strategy`; runs the full single-ticker committee path first, then executes the user-requested trade
  - `cancel` — e.g. `cancel buy Apple`, `cancel sell TSLA`, `cancel stop sell NVDA, Microsoft`; resolves one or more tickers and cancels matching pending Trading 212 orders without triggering strategy
  Direct trades keep existing broker-side safety rails such as cash/position preflight, order deduplication, min-order handling, stop-cancel preflight for SELL, and large-order confirmation. Strategy-triggered trades preserve moderation/risk behavior and `force` overrides. Cancel commands are immediate and keep a per-message audit trail with target tickers, target order class, and cancellation result details in `SlackCommandLog`. Explicit GBP orders remain FX-aware for `_US_EQ` / OTC names, so `BUY £550 ENGGY` targets the requested GBP amount instead of dividing by the native USD quote. Regex-first parsing now covers direct, strategy-triggered, and cancel commands, with Claude fallback for ambiguous phrasing. **Dashboard Chat page** (`/chat`, legacy `/commands` alias) surfaces execution mode, cancel metadata, and expanded result payloads. CLI: `poetry run python -m src.agents.notifications.slack_trade_listener`. Docker deployment includes an always-on `slack-listener` service so Slack access survives deploys and reboots. See [Chat & Commands](docs/CHAT_AND_COMMANDS.md).
- **US-1.9 conversational workflow delivered:** shared conversational trading sessions now span Slack threads and the dashboard Chat console (`/chat`, legacy `/commands` alias), with `chat_actions`, `chat_research_logs`, and `chat_workflow_steps`; explicit confirm/reject/expiry flow; versioned confirm/reject APIs that require `expected_version` and return `409` with the latest action payload on conflicts; portfolio-rule previews, stop updates, cancel proposals, session-level spend attribution, and persistent intent-detection cache reuse for successful LLM fallback parses. The agentic beta path adds planner-led routing, evidence blocks, citations, related-ticker scans, committee views, and a transparent step-by-step workflow rail. Turn submissions return refreshed session state synchronously, while SSE continues to broadcast chat updates. The `Legacy Slack Audit` tab remains a secondary one-shot audit view, not the full conversation archive, and now auto-refreshes while open. Execution remains explicitly confirmed and deterministic even when the chat path uses LLM planning or grounded research. Slack/dash routing hardening normalizes bullet/list-prefixed thread messages before routing, keeps explicit threaded commands on the deterministic preview path, supports 2-3 name compare prompts, and allows `compare X and Y, then buy £20 of the stronger one` to stage a confirm-gated preview instead of executing directly. `SlackCommandLog` remains the legacy one-shot audit trail. Local automated validation, schema verification, and VPS signoff completed on 2026-03-28. See [US-1.9 Validation Signoff](docs/US19_VALIDATION_SIGNOFF.md).
- Channels (outbound): Slack webhook + SMTP email
- Event types:
  - `trade_instruction_approved`
  - `trade_execution_result`
  - `cycle_run_summary`
  - `state_transition`
  - `critical_cycle_failure`
  - `order_adjustment`
- Audit table: `notification_logs` (`sent|failed|skipped|deduped`)

Default low-noise routing profile:
- `trade_instruction_approved` -> Slack
- `trade_execution_result` -> Slack + Email
- `cycle_run_summary` -> Slack
- `state_transition` -> Slack + Email
- `critical_cycle_failure` -> Slack + Email
- `order_adjustment` -> Slack
- `include_dry_run_alerts: false`

### Slack + Email hookup (VPS)

1. Set `.env` values:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ALERT_EMAIL_FROM=alerts@yourdomain.com
ALERT_EMAIL_TO=ops@yourdomain.com
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASS=SG_xxx
SMTP_USE_TLS=true
```

2. Restart container:

```bash
docker compose down
docker compose up -d --build
```

3. Verify effective config:

```bash
docker compose exec investment-agent python -c "
from src.utils.config import get_settings
s=get_settings()
print(s.notification_include_dry_run_alerts, s.notification_routes.get('cycle_run_summary'))
"
```

4. Verify email/slack send attempts:

```bash
docker compose exec investment-agent python -c "
from sqlalchemy import text
from src.data.database import get_session
s=get_session()
rows=s.execute(text(\"\"\"
SELECT timestamp,event_type,channel,status,attempt_number,error_message
FROM notification_logs
ORDER BY id DESC
LIMIT 20
\"\"\")).fetchall()
print(*rows, sep='\n')
s.close()
"
```

## Testing

```bash
poetry run pytest -v                          # All tests
poetry run pytest tests/test_risk_manager.py  # Risk agent (43 tests)
poetry run pytest tests/test_execution.py     # Execution (52 tests)
poetry run pytest tests/test_strategy.py      # Strategy (17 tests)
poetry run pytest tests/test_moderation.py    # Moderation (21 tests)
poetry run pytest tests/test_cost_tracker.py  # Cost tracker (16 tests)
poetry run pytest tests/test_screening_cooldown.py  # Screening + seed universe (10 tests)
poetry run pytest tests/test_opportunity_scorer.py tests/test_opportunity_optimizer.py  # UOV scoring + optimizer (5 tests)
poetry run pytest tests/test_notifications_service.py tests/test_notifications_providers.py tests/test_notifications_formatters.py tests/test_notifications_integration.py  # Notifications (20 tests)
```

## Project Structure

```
src/
├── orchestrator/       # Main control loop + state machine
├── agents/
│   ├── market_data/    # yfinance, Finnhub, Alpha Vantage, per-ticker news, universe screener, seed universe
│   ├── strategy/       # Momentum, mean reversion, factor, Claude synthesis
│   ├── moderation/     # GPT-4o + Gemini investment committee (full data + strategy assessment)
│   ├── risk/           # Hard rules with VETO power
│   ├── opportunity/    # UOV scorer + optimizer (ranking, queueing, swap suggestions)
│   ├── execution/      # T212 client + order manager: market, stop-loss, dedup
│   ├── notifications/  # Slack/email alerts, routing/retries/dedup, notification logging
│   └── reporting/      # Trade journals, daily/weekly reports, performance tracker, trade outcome tracker
├── data/               # SQLAlchemy models, Alembic migrations
├── scheduler/          # APScheduler with persistent job store
├── backtesting/        # Engine, paper broker, io (yfinance fetch + CSV cache), walk-forward, promotion report
└── utils/              # Config, logger, cost tracker
docs/                   # Project documentation (including archived plans in docs/archived/)
├── AGENTIC_RESEARCH.md          # Agentic research: design, tool definitions, phases
├── AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md  # US-4.4 step-by-step checklist
├── FOLLOWUP_RESEARCH_ROUTING_PLAN.md  # Follow-up routing policy (static-first, materiality + complexity gates)
├── ARCHITECTURE.md              # System architecture and component diagrams
├── BACKTESTING.md               # Backtesting engine, walk-forward validation, promotion report
├── CHAT_AND_COMMANDS.md         # ChatOps: trade alerts, notification routing, planned commands
├── COMPETITIVE_ANALYSIS.md      # Assessment vs professional quant systems
├── DASHBOARD.md                 # Web dashboard architecture, phases, frontend/backend design
├── CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md  # Canonical HTTPS rollout/runbook for zeninvest.zenouz.ai
├── DASHBOARD_DEPLOYMENT.md      # Dashboard VPS deployment: Cloudflare, nginx, certs, verification, rollback
├── DATA_EXPORT_RUNBOOK.md       # VPS-to-local data export with integrity checks
├── DATA_RATIONALE.md            # Every data point's purpose and keep/remove verdict
├── DEPLOYMENT.md                # VPS deployment and monitoring guide
├── GOVERNANCE.md                # Governance framework, 9 risk rules, cost controls, audit trail
├── LOCAL_SETUP.md               # Local setup guide (Trading 212 Practice)
├── ORDER_MANAGEMENT_PROJECT.md  # Stop-loss, trailing stops, limit dip-buy: design and config
├── PRESENTATION.md              # Project presentation and summary
└── SOPHISTICATION_ROADMAP.md    # Prioritised improvement roadmap
notebooks/
├── diagnostics.ipynb       # Component diagnostics: every pipeline step (Config → Backtesting → Walk-Forward) with expected outputs
├── research_api_investigation.ipynb  # Phase 0 baseline: provider/API capability + SEC EDGAR validation
├── research_api_decision_framework.ipynb  # Phase 0.2: routing policy benchmark (difficulty gating, action mode, provider policy)
├── enriched_instruments.ipynb  # Inspect enriched instrument data (sector, market_cap, industry, summary)
├── brave_api_smoke.py      # Manual smoke test for Brave Search + Answers APIs (requires API keys)
├── brave_tavily_comparison.py  # Compare Brave vs Tavily extraction (sector, market_cap)
└── enrichment_benchmark.py # Benchmark BRAVE_SEARCH vs BRAVE_ANSWERS vs TAVILY: cost, time, accuracy
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design, component diagrams, data flow
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) — prioritised user stories for systematic improvement
- [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md) — honest assessment vs professional quant systems
- [Governance](docs/GOVERNANCE.md) — 9 risk rules, security guardrails, cost controls, audit trail
- [Data Rationale](docs/DATA_RATIONALE.md) — every data point's purpose, decision path, and keep/remove verdict
- [Deployment](docs/DEPLOYMENT.md) — VPS setup, Docker, monitoring, alerts; manual mirror of `main` to `zenouz-ai/zeninvest` (see “Mirror main to zenouz-ai/zeninvest” in that doc)
- [VPS Runtime Stability Plan](docs/VPS_RUNTIME_STABILITY_PLAN.md) — failure-mode diagnosis, target architecture, systemd split, migration model, and verification
- [VPS Systemd Runbook](docs/VPS_SYSTEMD_RUNBOOK.md) — lean non-Docker service install/start/check commands for a small VPS
- [Dashboard](docs/DASHBOARD.md) — web dashboard architecture, phases, frontend/backend design
- [Cloudflare Dashboard Domain Plan](docs/CLOUDFLARE_DASHBOARD_DOMAIN_PLAN.md) — canonical `zeninvest.zenouz.ai` HTTPS rollout with Cloudflare + Nginx
- [Dashboard Deployment](docs/DASHBOARD_DEPLOYMENT.md) — VPS deployment and verification for the internal-only dashboard + public nginx ingress posture
- [Chat & Commands](docs/CHAT_AND_COMMANDS.md) — trade alerts, notification routing, planned inbound commands
- [Backtesting](docs/BACKTESTING.md) — engine, walk-forward validation, promotion report
- [Order Management](docs/ORDER_MANAGEMENT_PROJECT.md) — stop-loss, trailing stops, limit dip-buy: design and config
- [Agentic Research](docs/AGENTIC_RESEARCH.md) — canonical architecture and conventions; [Implementation Plan](docs/AGENTIC_RESEARCH_IMPLEMENTATION_PLAN.md) — checklist; [Follow-up Routing Plan](docs/FOLLOWUP_RESEARCH_ROUTING_PLAN.md) — routing policy
- [Data Export Runbook](docs/DATA_EXPORT_RUNBOOK.md) — VPS-to-local export procedure with integrity checks
- [Local Setup](docs/LOCAL_SETUP.md) — local setup guide for Trading 212 Practice
- [Presentation](docs/PRESENTATION.md) — project overview and summary

## Risk Rules (never overridden by LLMs)

- No single stock > 15% of portfolio
- No single sector > 35%
- Portfolio avg pairwise correlation < 0.7
- 30% drawdown → CAUTIOUS mode; 40% → HALTED (liquidate all); configurable in settings
- VIX > 25: max 8% position; VIX > 35: max 5%
- Daily loss > 2%: no new buys for 24 hours
- Cash floor: always >= 10%
- Min 5 positions once invested (checked for SELL and REDUCE actions)
- CAUTIOUS mode: no new BUYs (only SELL/REDUCE/HOLD)

## Cycle Output

Each cycle returns a JSON result with:
- **trades** — executed trades with industry, market cap, business description, reasoning, allocation, moderation/risk verdicts, stop-loss
- **rejected_stocks** — stocks considered but not traded, tagged by the stage that blocked them (`strategy_hold`, `moderation_blocked`, `risk_reject`, `opportunity_queue`, `opportunity_filtered`) with company metadata, rejection reason, and UOV diagnostics (`uov_ewma`, `uov_z`) for opportunity stages
- **opportunity_ranking** — per-ticker UOV scores (`uov_raw`, `uov_z`, `uov_final`, `uov_ewma`) persisted each cycle
- **queued_candidates** — BUY opportunities held in the UOV queue when not executed immediately
- **swap_candidates** — non-executing suggestions where a candidate's UOV materially exceeds weakest held position
- **cost_summary** — LLM spend for the cycle

This enables immediate post-cycle review and long-term analysis of missed opportunities.

### Universal Opportunity Value (UOV)

The orchestrator computes a cross-cycle UOV for each assessed ticker:
- `uov_raw` — weighted hybrid score from sub-strategy signals, conviction, moderation/risk outputs, sentiment proxy, and market-cap proxy
- `uov_z` — cross-sectional z-score of `uov_raw` within the cycle
- `uov_final` — `uov_z` plus deterministic stage penalties (HOLD/BLOCKED/REJECT/RESIZE)
- `uov_ewma` — smoothed cross-cycle score (`half-life = 6 cycles` by default)

Execution behavior:
- `mode: shadow` — compute/log UOV and queue state but preserve legacy BUY execution ordering
- `mode: active` — rank approved BUYs by `uov_ewma`, execute top opportunities first, queue remaining candidates, and emit conservative swap suggestions (no autonomous SELLs)

## Order Types

- **Market orders** — BUY, SELL, REDUCE (partial sell) via T212 market order API
- **Stop-loss orders** — Automatically placed after BUY executions using Claude's `stop_loss_pct` (GTC validity)
- **£500 BUY floor + whole-share preference** — BUY and limit-BUY paths are lifted to `min_order_value_gbp` when the requested trade value is below the floor, provided enough cash remains after the cash-floor guard. Autonomous BUY sizing prefers whole shares with a small configurable overspend tolerance and only falls back to fractional shares when a whole-share order cannot satisfy policy. If there is not enough spendable cash to place the minimum order, the BUY is skipped. SELL, REDUCE, and protective stop-loss orders are allowed below the floor so small holdings can still be exited/protected. REDUCE is intentionally rare and currently restricted to 50% profit trims; if a trim would leave a holding below the cleanup threshold, execution converts it to a full SELL.
- **REDUCE floor safeguard** — If a REDUCE would leave a position below £500, execution is automatically converted to a full SELL
- **Slow, profit-driven exits** — Ordinary autonomous SELLs require meaningful unrealized profit (`sell_min_profit_pct`, default `15%`) and a `gain_realization` trigger, while `hard_exit` is reserved for severe thesis breaks or risk events. REDUCE is intentionally rare: only `25%` or `50%` profit trims are allowed, and only after the configured gain thresholds are reached. Residual holdings below `small_position_cleanup_value_gbp` (default `£200`) are liquidated immediately in a pre-strategy deterministic pass, using the broker-reported live quantity and skipping the strategy/moderation/risk LLM path for that cleanup ticker
- **Order deduplication** — 5-minute window prevents double-execution
- **Stale pending SELL cleanup** — If a later live cycle flips a ticker from an earlier pending market `SELL` to `HOLD`/`QUEUED`, the orchestrator cancels the stale pending broker order so the latest view wins
- **Moderation fail-open serialization** — moderator `MODIFY` extras are normalized defensively; malformed `modifications` payloads are ignored instead of crashing the cycle or Slack single-ticker review path
- **Broker error detail preservation** — failed market and stop orders now keep the Trading 212 HTTP status/body snippet in the recorded error so alerts can distinguish issues like minimum order value vs reserved-share conflicts
- **Ticker normalization** — plain symbols returned by strategy (e.g. `AAPL`) are normalized to T212 instrument IDs (e.g. `AAPL_US_EQ`) before execution when an unambiguous mapping exists

## Universe Screening

Each cycle discovers new candidates beyond existing positions:
- **Curated seed universe** — Derived from T212 instrument list (~6900 US equities, 100% tradeable). Regenerate with `poetry run python scripts/generate_seed_from_t212.py --from-db`. Bulk enrich sector/market_cap/industry/summary: `poetry run python scripts/bulk_enrich_instruments.py`. Backfill industry/summary for already-enriched: `poetry run python scripts/backfill_industry_summary.py`. Used as fallback when instruments table lacks enriched data.
- **Sector-balanced sampling** — minimum 3 candidates per sector to avoid concentration
- **Market-cap tiers** — 70% large cap ($10B+), 20% mid cap ($2B-$10B), 10% small cap ($300M-$2B)
- **Screening cooldown & mix** — stocks are stamped with `last_screened_at` after each screen and excluded for a cooldown window (default effective intraday cooldown `4h` via `effective_screening_cooldown_override`), allowing the next intraday cycle to revisit the prior pool. Autonomous re-reviews are also rate-limited per ticker: at least `review_cooldown_days` (default `2`) between reviews and at most `max_reviews_per_30_days` (default `10`) in a rolling 30-day window. Slack single-ticker reviews bypass this screener gate. Within the eligible pool, `get_screened_universe()` targets a configurable share of fresh (never-reviewed) tickers via `uninvestigated_target_pct` (default ~50%).
- **Data availability filtering** — tickers that fail yfinance OHLCV fetch are permanently flagged `data_available=False` and excluded from all future screens
- **Metadata enrichment** — sector, market_cap, industry, and business summary back-filled from yfinance into instruments table (~5,477 deployed). Strategy prompt falls back to Instrument when yfinance returns sparse data.
- **Company profiles** — `longBusinessSummary` from yfinance is included in the Claude strategy prompt so it can reason about competitive moats, regulatory exposure, and news impact
- Skipped in CAUTIOUS mode (no new positions allowed)

## Cost Management

LLM costs tracked per-call with daily/monthly budget enforcement:
- Anthropic (Sonnet): £1.00/day
- OpenAI (GPT-4o): £0.75/day
- Google (Gemini Flash): £0.50/day
- Monthly cap: £50.00

Graceful degradation: skip Gemini → skip GPT-4o → skip strategy cycle → halt

## Project Evolution

This is a **POC (v1.0)** designed to validate the architecture and begin collecting live performance data. The system will evolve through evidence-based phases:

1. **Phase 1 (Current):** Deploy POC, build performance tracking and trade outcome feedback loop
2. **Phase 2:** Calibrate conviction scores and strategy weights from live data (~50+ trades)
3. **Phase 3:** Portfolio-level intelligence (risk-parity sizing, regime detection)
4. **Phase 4:** Signal enhancement (volume, earnings calendar, sector rotation)
5. **Phase 5:** ~~Backtesting engine~~ — delivered (engine, walk-forward, promotion report, yfinance fetch + CSV cache)
6. **Phase 6:** ML-assisted improvements (only if justified by accumulated evidence)

See [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) for full details, timelines, and priority matrix.
