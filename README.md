# ZenInvest

[![CI](https://github.com/KayvanNejabati/Investment-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/KayvanNejabati/Investment-agent/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/pytest-1043%20cases-00c853.svg)](#quick-start)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="branding/ZenInvest.png" alt="ZenInvest" width="820" />
</p>

**Autonomous multi-LLM investment committee that researches, debates, and trades — with hard safety guardrails humans can trust.**

**Problem.** Markets move faster than any solo operator can reliably track. Signal is buried under filings, headlines, sector rotation, macro shocks, and the emotional bias that comes with discretionary decision-making.

**Solution.** ZenInvest is ZENOUZ.ai's autonomous investment committee: Claude leads strategy, GPT-4o challenges assumptions, Gemini scores independent risk, and deterministic Python guardrails retain final veto power over capital at risk.

**Why Us.** This repo is not a single-model trading bot. It combines agentic research with real-time web tools, proactive macro intelligence, cost-aware graceful degradation, and a full audit trail across decisions, risk checks, orders, dashboard views, and Slack workflows.

<p align="center">
  <img src="branding/ZenInvest_Promo.png" alt="ZenInvest promotional poster" width="760" />
</p>

**Status:** Proof of Concept (`v1.0`) with **1043 pytest cases** in the suite, Docker Compose deployment on VPS, and canonical HTTPS access at `https://zeninvest.zenouz.ai`. Delivery status lives in [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md), [dashboard/frontend/src/data/roadmap.ts](dashboard/frontend/src/data/roadmap.ts), and [Zen Evolution Engine](docs/ZEN_EVOLUTION_ENGINE.md).

## How It Works

```text
Orchestrator (configurable: intraday = 10:00/12:30/15:15 America/New_York, standard = 07:00/19:00 UTC)
  ├── Market Data Agent    → yfinance + Finnhub + Alpha Vantage + macro intelligence
  ├── Universe Screener    → sector-balanced, cap-tiered candidate discovery
  ├── Strategy Agent       → momentum + mean reversion + factor + Claude synthesis
  ├── Moderation Panel     → GPT-4o skeptic + Gemini risk assessor
  ├── Risk Agent           → deterministic Python guardrails with VETO power
  ├── Opportunity Agent    → UOV scoring, queueing, and BUY prioritisation
  ├── Execution Agent      → Trading 212 market/limit/stop order workflows
  ├── Refresh Lane         → broker sync, stop maintenance, freshness updates
  ├── Notification Agent   → Slack + email alerts with fail-open delivery
  └── Journal & Reporting  → runs, trade journals, costs, outcomes, reports
```

Each cycle starts with market and macro context, screens a fresh candidate set, synthesizes a thesis, debates it across multiple LLMs, applies deterministic risk rules, ranks opportunities, executes via Trading 212, and records the entire chain for later review.

The refresh lane keeps the system grounded in broker truth between full strategy cycles by syncing orders, warming held-name data, and maintaining protective stops without screening new instruments.

**State Machine:** `ACTIVE -> CAUTIOUS -> HALTED`

### Key Differentiators

- Multi-LLM adversarial committee, not a single-model autopilot
- Agentic research with 5 tools and per-member budgets across the committee
- 9 deterministic risk rules that no LLM can override
- Cost-aware graceful degradation: `FULL -> NO_GEMINI -> NO_GPT4O -> NO_STRATEGY -> HALTED`
- Proactive macro intelligence with `RISK_ON` / `RISK_OFF` / `NEUTRAL` regime detection
- Real-time operator dashboard, live activity feed, and Slack conversational trading
- Walk-forward backtesting and promotion-oriented validation tooling

## API Ecosystem

| API | Role | Why It Matters |
|-----|------|----------------|
| **Trading 212** | Order execution on Practice/Demo | Safe autonomous trading with market, limit, stop-loss, and cancel workflows |
| **Anthropic Claude** | Strategy synthesis | Primary decision-maker for conviction, thesis construction, and tool-using research |
| **OpenAI GPT-4o** | Skeptical moderation | Challenges assumptions and reduces confirmation bias before execution |
| **Google Gemini** | Risk assessment | Adds an independent third view on risk, fragility, and downside scenarios |
| **yfinance** | OHLCV, indicators, fundamentals | Free, reliable baseline market data for screening, signals, and company context |
| **Finnhub** | Analyst recs, insider sentiment, macro headlines | Adds qualitative and headline-driven context that raw prices miss |
| **Alpha Vantage** | News sentiment, sector performance | Brings ticker-level sentiment extraction and sector rotation signals |
| **Brave Search** | Primary web research provider | Powers real-time agentic research when the committee needs live web context |
| **Tavily** | Fallback web research provider | Adds redundancy and structured extraction when Brave is unavailable or insufficient |
| **SEC EDGAR** | Filing search | Gives the strategy and moderators direct access to primary-source filings for thesis validation |

## Agentic Research

ZenInvest gives all three committee members independent tool-use loops. Strategy, Skeptic, and Risk can each call `web_search`, `news_search`, `sector_search`, `sec_search`, and `macro_search` before finalising a verdict.

Research is budgeted, not unbounded: per-cycle caps are `20` calls for Strategy, `8` for Skeptic, `7` for Risk, with a shared pipeline-wide ceiling of `35` calls. Brave is primary, Tavily is fallback, and SEC EDGAR stays free for filing-heavy workflows. Shared monthly search limits are also enforced across research and enrichment: Brave Search `2000`, Brave Answers `2000`, Tavily `1000`.

Every tool invocation is logged with member, query, provider, cache hit, latency, summary, and cost so operators can inspect exactly how research influenced a decision from the dashboard or API.

Deep dive: [Agentic Research](docs/AGENTIC_RESEARCH.md)

## Proactive Macro Intelligence

Macro intelligence runs on its own schedule, derives a live market regime (`RISK_ON`, `RISK_OFF`, or `NEUTRAL`), and injects that state into strategy and moderation prompts before trades are sized or approved.

The result is visible operationally in the dashboard's World News experience: regime history, macro headlines, sector snapshots, and action-plan context are all persisted rather than treated as ephemeral prompt text.

Architecture details: [Architecture](docs/ARCHITECTURE.md) and [Proactive Macro News Intelligence](docs/PROACTIVE_MACRO_NEWS_INTELLIGENCE.md)

## Dashboard & Operator Interface

ZenInvest ships with a 12-page dashboard surface spanning Dashboard, Universe, Runs, Portfolio, Opportunity, Insights, Order Management, Costs, Chat, World News, Roadmap, and Evolution. The React frontend and FastAPI backend expose portfolio state, orders, decisions, opportunity queue, costs, world-news context, roadmap visibility, and real-time SSE activity from the running system.

Operator routes are authenticated; public routes are intentionally sanitized. Slack extends the same control surface into conversational trading with multi-turn review, confirm, reject, cancel, and strategy-triggered trade flows backed by audited session history and a planner-led chat console.

Interface docs: [Dashboard](docs/DASHBOARD.md), [Conversational Trading Workflow](docs/CONVERSATIONAL_TRADING_WORKFLOW.md), and [Zen Evolution Engine](docs/ZEN_EVOLUTION_ENGINE.md)

## Quick Start

### Prerequisites

- Python `3.11+`
- [Poetry](https://python-poetry.org/docs/#installation)
- Core API keys in a project-root `.env` copied from `config/.env.example`

### Install

```bash
git clone <repo-url> && cd Investment-agent
poetry install
cp config/.env.example .env
poetry run alembic upgrade head
```

### Run a Dry Cycle

```bash
poetry run python -m src.orchestrator.main --dry-run
```

### Run the Scheduler

```bash
poetry run python -m src.scheduler.scheduler
```

Full setup, env vars, frontend tooling, and troubleshooting: [Local Setup](docs/LOCAL_SETUP.md)

## Backtesting

```bash
poetry run python -m src.backtesting.main --config backtests/default.yaml
poetry run python -m src.backtesting.main --config backtests/default.yaml --walk-forward
poetry run python -m src.backtesting.main --synthetic --output-dir backtests/results/run1
```

Backtesting guide: [Backtesting](docs/BACKTESTING.md)

## Schedule

| Job | When | Notes |
|-----|------|-------|
| Analysis cycles | Mon-Fri | `intraday`: `10:00`, `12:30`, `15:15` America/New_York; `standard`: `07:00`, `19:00` UTC |
| Refresh lane | Mon-Fri around analysis cycles + weekend refresh | Broker truth sync, data freshness, stop maintenance, pending-order cleanup |
| Daily snapshot | `21:30 UTC` | Portfolio snapshot plus daily report |
| Weekly report | `Friday 22:00 UTC` | End-of-week summary |
| Instrument refresh | `Sunday 12:00 UTC` | Tradable universe refresh from Trading 212 |
| Strategy episode scan | `02:00 UTC daily` | Auto-publishes git-backed strategy attribution episodes |

Scheduling architecture and config semantics: [Architecture](docs/ARCHITECTURE.md)

## Docker

```bash
docker compose up -d --build
docker compose logs -f investment-agent
docker compose logs -f dashboard
docker compose logs -f slack-listener
docker compose logs -f nginx
```

Production deployment, ingress, notifications, and VPS operations: [Deployment](docs/DEPLOYMENT.md)

## Safety Guardrails

These rules are deterministic Python and remain final even when every LLM agrees. Current defaults below come from `config/settings.yaml` and are configurable:

- No single stock above `20%` of portfolio
- No single sector above `40%`
- Portfolio average pairwise correlation below `0.7`
- `30%` drawdown triggers `CAUTIOUS`; `40%` triggers `HALTED` and liquidation
- `VIX > 25` caps new positions at `8%`; `VIX > 35` caps them at `5%`
- Daily loss above `2%` blocks new buys for `24h`
- Cash floor always stays at or above `10%`
- Minimum `5` positions once invested
- `CAUTIOUS` mode blocks new `BUY` actions unless adding to an existing winner, and caps size at `8%`

Governance details: [Governance](docs/GOVERNANCE.md)

## Cost Management

ZenInvest tracks LLM and research spend per call and enforces daily plus monthly budgets:

- Anthropic: `£2.00/day`
- OpenAI: `£1.00/day`
- Google: `£1.00/day`
- Monthly cap: `£60.00`

When budgets tighten, the system degrades gracefully instead of failing unpredictably.

## Project Evolution

ZenInvest remains a **POC (`v1.0`)** focused on evidence-backed iteration rather than premature complexity. The canonical roadmap source currently marks **37 of 51 milestones delivered (73%)**, with the Evolution Planner providing the operator-facing workflow for scoped future improvements.

Roadmap: [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) and [dashboard/frontend/src/data/roadmap.ts](dashboard/frontend/src/data/roadmap.ts)

## Documentation Index

- [Architecture](docs/ARCHITECTURE.md) — pipeline, data flow, scheduling, dashboard/API topology
- [Agentic Research](docs/AGENTIC_RESEARCH.md) — tool-use architecture, provider routing, budgets, audit model
- [Dashboard](docs/DASHBOARD.md) — frontend/backend architecture, page map, UX, public/private split
- [Conversational Trading Workflow](docs/CONVERSATIONAL_TRADING_WORKFLOW.md) — Slack and dashboard multi-turn trading flows
- [Backtesting](docs/BACKTESTING.md) — engine, walk-forward validation, promotion report
- [Governance](docs/GOVERNANCE.md) — risk rules, audit trail, safety posture
- [Deployment](docs/DEPLOYMENT.md) — Docker Compose, nginx, HTTPS, alerts, VPS operations
- [Local Setup](docs/LOCAL_SETUP.md) — install, env vars, tests, frontend runtime, troubleshooting
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) — canonical backlog and delivery status
- [Zen Evolution Engine](docs/ZEN_EVOLUTION_ENGINE.md) — Evolution Planner scope and policy gates
- [Data Rationale](docs/DATA_RATIONALE.md) — why each data source exists and whether it earns its cost
- [Presentation](docs/PRESENTATION.md) — stakeholder-ready overview of the system story
- [Brand Guide](branding/BRAND.md) — ZENOUZ.ai / ZenInvest visual system

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions, and PR expectations.

## Security

Report vulnerabilities through [SECURITY.md](SECURITY.md). Do not open public issues for security disclosures.

## License

MIT. See [LICENSE](LICENSE).
