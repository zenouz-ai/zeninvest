# Investment Agent

[![CI](https://github.com/KayvanNejabati/Investment-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/KayvanNejabati/Investment-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="branding/ZenInvest.png" alt="ZenInvest" width="820" />
</p>

Autonomous investment agent that trades via the Trading 212 API (Practice/Demo mode) using a multi-LLM strategy pipeline. Currently deployed as a **Proof of Concept (v1.0)** to gather live performance data and improve through evidence-backed iterations.

**Status:** POC, **1011 pytest cases currently pass**, and the dashboard frontend production build is clean. Deployment posture remains Docker Compose on VPS. For roadmap and recent delivered work, see [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md), [Sprint Week 1](docs/SPRINT_WEEK_1.md), and [Zen Evolution Engine](docs/ZEN_EVOLUTION_ENGINE.md).

## Brand Assets

For the full visual system, logo rules, color tokens, and usage guidelines, see [Brand Guide](branding/BRAND.md).

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

<p align="center">
  <img src="branding/ZenInvest_Promo.png" alt="ZenInvest promotional poster" width="760" />
</p>

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

Tune parameters in `config/settings.yaml`.

Most commonly adjusted keys:
- **Trading:** `cycle_frequency`, scheduling times/timezone, `max_positions`, `cash_floor_pct`
- **Risk:** drawdown thresholds, concentration caps, volatility gates
- **Models/Budgets:** strategy/moderation model IDs and provider cost limits

Full settings guide: [Local Setup](docs/LOCAL_SETUP.md) and [Architecture](docs/ARCHITECTURE.md).

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
poetry run python -m src.orchestrator.main --status        # System status
poetry run python -m src.orchestrator.main --pause         # Pause trading
poetry run python -m src.orchestrator.main --resume        # Resume trading
poetry run python -m src.orchestrator.main --reset-peak    # Clear incorrect peak / CAUTIOUS latch
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
```

Extended command reference: [Local Setup](docs/LOCAL_SETUP.md).

### Backtesting

```bash
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
```

See [Backtesting](docs/BACKTESTING.md) (includes walk-forward validation and promotion report) for details.

### Run the scheduler (continuous)

```bash
poetry run python -m src.scheduler.scheduler
```

### Dashboard

Run the backend from the project root (so `src` and `dashboard` are importable):

```bash
# Start the dashboard API server (local dev)
poetry run uvicorn dashboard.backend.app.main:app --host 127.0.0.1 --port 8000

# API at http://localhost:8000, OpenAPI docs at http://localhost:8000/docs
```

Key routes include runs, status, universe, portfolio, orders, decisions, opportunity, outcomes, costs, macro, chat, and evolution workflows. Full API details are in OpenAPI (`/docs`) and [Dashboard Documentation](docs/DASHBOARD.md).

Enable via `dashboard.enabled: true` and `dashboard.events_enabled: true` in `config/settings.yaml`.

### Dashboard Frontend

Brand and design system details: [Brand Guide](branding/BRAND.md).

```bash
cd dashboard/frontend
nvm use    # Node 20 LTS (see dashboard/frontend/.nvmrc)
npm install
npm run dev    # Dev server on http://localhost:3000 (proxies API)
npm run build  # Production build (outputs to dist/)
```

Frontend includes authenticated operator views and sanitized public views across Dashboard, Universe, Portfolio, Runs, Opportunity, Insights, Order Management, Chat, World News, Costs, Roadmap, and Evolution. For full IA/UX details, see [Dashboard Documentation](docs/DASHBOARD.md) and [UX Audit](docs/UX_AUDIT.md).

**Schedule (configurable):**

| Job | When | Notes |
|-----|------|-------|
| Analysis cycles | Mon–Fri, from configured schedule mode | `intraday`: `10:00`, `12:30`, `15:15` America/New_York (DST-aware; resolves to `14:00`, `16:30`, `19:15` UTC during US EDT). `standard`: `07:00`, `19:00` UTC (2 cycles). |
| Intraday refresh lane | Mon–Fri `09:50`, `10:10`, `12:20`, `12:40`, `15:05`, `15:25` America/New_York; Sat/Sun `17:00` America/New_York | Broker truth sync, portfolio snapshot refresh, held/pending/queued market-data warming, deterministic stop/profit-lock maintenance, and dashboard freshness updates. |
| Daily snapshot | 21:30 UTC daily | Portfolio snapshot + daily report |
| Weekly report | Friday 22:00 UTC | End-of-week summary |
| Instrument refresh | Sunday 12:00 UTC | Update tradable universe from T212 |
| Strategy episode scan | 02:00 UTC daily | Auto-scans git strategy/risk/execution changes and auto-confirms new attribution episodes |

Set `cycle_frequency: intraday`, `schedule_mode: market_session`, `schedule_timezone: America/New_York`, and `cycle_times_local: ["10:00", "12:30", "15:15"]` in `config/settings.yaml` for DST-aware regular-session scheduling. Use `standard` for the original 2-cycle fixed-UTC cadence.

### Docker

Compose stack runs scheduler, Slack listener, dashboard, and nginx ingress. Production is served at `https://zeninvest.zenouz.ai` with internal-only dashboard app exposure.

```bash
# Build and run all services (scheduler + Slack listener + dashboard + nginx ingress)
docker compose up -d --build

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

Deployment details: [Deployment Guide](docs/DEPLOYMENT.md).

## Chat Notifications

Outbound alerting is enabled via Slack webhook + SMTP email with fail-open delivery and persistent `notification_logs` audit rows. Inbound Slack commands support review, direct trade, strategy-triggered trade, and cancel flows.

Default low-noise routing:
- `trade_instruction_approved` -> Slack
- `trade_execution_result` -> Slack + Email
- `cycle_run_summary` -> Slack
- `state_transition` -> Slack + Email
- `critical_cycle_failure` -> Slack + Email
- `order_adjustment` -> Slack
- `include_dry_run_alerts: false`

Full conversational workflow and command semantics: [Conversational Trading Workflow](docs/CONVERSATIONAL_TRADING_WORKFLOW.md).

### Slack + Email hookup (VPS)

Set notification env vars in `.env`, restart the compose stack, and verify delivery in `notification_logs`.

Complete setup and verification commands: [Deployment Guide](docs/DEPLOYMENT.md) and [VPS Systemd Runbook](docs/VPS_SYSTEMD_RUNBOOK.md).

## Testing

```bash
poetry run pytest -v
```

For focused test commands by subsystem, see [Local Setup](docs/LOCAL_SETUP.md).

## Project Structure

High-level layout:
- `src/` — orchestrator, agents, data, scheduler, utilities
- `dashboard/` — backend API + frontend UI
- `docs/` — architecture, deployment, governance, roadmap, feature docs
- `tests/` — unit/integration coverage
- `notebooks/` — diagnostics and research notebooks

Detailed structure and component responsibilities: [Architecture](docs/ARCHITECTURE.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design, component diagrams, data flow
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) — prioritised user stories for systematic improvement
- [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md) — honest assessment vs professional quant systems
- [Governance](docs/GOVERNANCE.md) — 9 risk rules, security guardrails, cost controls, audit trail
- [Data Rationale](docs/DATA_RATIONALE.md) — every data point's purpose, decision path, and keep/remove verdict
- [Deployment](docs/DEPLOYMENT.md) — VPS setup, Docker, monitoring, alerts; manual mirror of `main` to `zenouz-ai/zeninvest` (see “Mirror main to zenouz-ai/zeninvest” in that doc)
- [VPS Systemd Runbook](docs/VPS_SYSTEMD_RUNBOOK.md) — lean non-Docker service install/start/check commands for a small VPS
- [Dashboard](docs/DASHBOARD.md) — web dashboard architecture, phases, frontend/backend design
- [Conversational Trading Workflow](docs/CONVERSATIONAL_TRADING_WORKFLOW.md) — multi-turn Slack/dashboard chat sessions, command interface
- [Audit Index](docs/AUDIT_INDEX.md) — cross-reference of all audit findings and remediation status
- [Backtesting](docs/BACKTESTING.md) — engine, walk-forward validation, promotion report
- [Order Management](docs/ORDER_MANAGEMENT_PROJECT.md) — stop-loss, trailing stops, limit dip-buy: design and config
- [Agentic Research](docs/AGENTIC_RESEARCH.md) — canonical architecture and conventions; [Follow-up Routing Plan](docs/FOLLOWUP_RESEARCH_ROUTING_PLAN.md) — routing policy
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

Each cycle records trades, rejected candidates by pipeline stage, UOV rankings/queue outcomes, and per-cycle cost summaries. This supports quick operator review and long-term diagnostics.

Data model and run semantics: [Architecture](docs/ARCHITECTURE.md) and [Governance](docs/GOVERNANCE.md).

### Universal Opportunity Value (UOV)

UOV blends strategy, moderation/risk, and market context signals into per-ticker scores (`uov_raw`, `uov_z`, `uov_final`, `uov_ewma`) used for ranking and queueing.

Modes:
- `shadow` — compute/log only
- `active` — rank BUY execution and manage queue/swap suggestions

## Order Types

Execution supports market BUY/SELL/REDUCE, auto stop-loss placement, trailing/tiered profit-lock behavior, limit dip-buy paths, order deduplication, and stale pending-order cleanup.

Detailed mechanics and policy constraints: [Order Management](docs/ORDER_MANAGEMENT_PROJECT.md).

## Universe Screening

Screening uses a curated T212 seed universe with sector-balanced and market-cap-tiered sampling, cooldown/review gates, and metadata enrichment fallbacks. In CAUTIOUS mode, new BUYs are blocked by risk policy.

Methodology and rationale: [Data Rationale](docs/DATA_RATIONALE.md) and [Architecture](docs/ARCHITECTURE.md).

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
4. **Phase 4:** Signal enhancement (volume and earnings delivered; sector rotation later)
5. **Phase 5:** ~~Backtesting engine~~ — delivered (engine, walk-forward, promotion report, yfinance fetch + CSV cache)
6. **Phase 6:** ML-assisted improvements (only if justified by accumulated evidence)

See [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) for full details, timelines, and priority matrix.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, coding guidelines, and the PR process.

## Security

To report a security vulnerability, please follow our [Security Policy](SECURITY.md). **Do not open a public GitHub issue for security reports.**

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
