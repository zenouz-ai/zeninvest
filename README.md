# Investment Agent

Autonomous investment agent that trades via the Trading 212 API (Practice/Demo mode) using a multi-LLM strategy pipeline. Currently deployed as a **Proof of Concept (v1.0)** to gather live performance data, with a [sophistication roadmap](docs/SOPHISTICATION_ROADMAP.md) for systematic improvement based on evidence.

**Status:** POC — 119 tests passing, deployment-ready for VPS.

## Architecture

```
Orchestrator (every 12h)
  ├── Market Data Agent    → yfinance + Finnhub + Alpha Vantage (per-ticker news)
  ├── Universe Screener    → Sector-balanced, cap-tiered candidate discovery
  ├── Strategy Agent       → Momentum + Mean Reversion + Factor → Claude Sonnet synthesis
  ├── Moderation Panel     → GPT-4o (skeptic) + Gemini (risk assessor) → consensus
  ├── Risk Agent           → Hard rules, VETO power, never overridden by LLMs
  ├── Execution Agent      → Trading 212 API: market orders + stop-loss + dedup
  └── Journal & Reporting  → Per-trade journals, daily + weekly reports
```

**State Machine:** ACTIVE → CAUTIOUS (>5% drawdown) → HALTED (>15% drawdown, liquidate all)

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
- **Trading:** cycle times, position limits, cash floor
- **Risk:** drawdown thresholds, VIX limits, sector caps, correlation limits
- **Universe:** candidate count, sector balance, market-cap tiers, screening cooldown
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
poetry run python -m src.orchestrator.main --pause        # Pause trading
poetry run python -m src.orchestrator.main --resume       # Resume trading
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ  # Force sell
poetry run python -m src.orchestrator.main --report       # Generate daily report
```

### Run the scheduler (continuous)

```bash
poetry run python -m src.scheduler.scheduler
```

Schedule:
- Analysis cycles: 07:00 and 19:00 UTC, Mon-Fri
- Daily snapshot: 21:30 UTC
- Weekly report: Friday 22:00 UTC
- Instrument refresh: Sunday 12:00 UTC

### Docker

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f investment-agent
```

## Testing

```bash
poetry run pytest -v                          # All tests
poetry run pytest tests/test_risk_manager.py  # Risk agent (43 tests)
poetry run pytest tests/test_execution.py     # Execution (14 tests)
poetry run pytest tests/test_strategy.py      # Strategy (17 tests)
poetry run pytest tests/test_moderation.py    # Moderation (21 tests)
poetry run pytest tests/test_cost_tracker.py  # Cost tracker (16 tests)
poetry run pytest tests/test_screening_cooldown.py  # Screening cooldown (6 tests)
```

## Project Structure

```
src/
├── orchestrator/       # Main control loop + state machine
├── agents/
│   ├── market_data/    # yfinance, Finnhub, Alpha Vantage, per-ticker news, universe screener
│   ├── strategy/       # Momentum, mean reversion, factor, Claude synthesis
│   ├── moderation/     # GPT-4o + Gemini investment committee (full data + strategy assessment)
│   ├── risk/           # Hard rules with VETO power
│   ├── execution/      # T212 client + order manager: market, stop-loss, dedup
│   └── reporting/      # Trade journals, daily/weekly reports
├── data/               # SQLAlchemy models, Alembic migrations
├── scheduler/          # APScheduler with persistent job store
└── utils/              # Config, logger, cost tracker
docs/                   # Project documentation
├── ARCHITECTURE.md     # System architecture and component diagrams
├── COMPETITIVE_ANALYSIS.md  # Assessment vs professional quant systems
├── DEPLOYMENT.md       # VPS deployment and monitoring guide
├── GOVERNANCE.md       # Governance framework and security guardrails
├── LOCAL_LIVE_RUN.md   # Local live run guide (Trading 212 Practice)
├── PRESENTATION.md     # Project presentation and summary
└── SOPHISTICATION_ROADMAP.md  # Prioritised improvement roadmap
notebooks/
└── diagnostics.ipynb   # Component diagnostics and integration tests
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design, component diagrams, data flow
- [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) — prioritised user stories for systematic improvement
- [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md) — honest assessment vs professional quant systems
- [Data Rationale](docs/DATA_RATIONALE.md) — every data point's purpose, decision path, and keep/remove verdict
- [Deployment](docs/DEPLOYMENT.md) — VPS setup, Docker, monitoring, alerts
- [Governance](docs/GOVERNANCE.md) — security guardrails, kill switches, audit trail
- [Local Live Run](docs/LOCAL_LIVE_RUN.md) — step-by-step guide for Trading 212 Practice mode
- [Presentation](docs/PRESENTATION.md) — project overview and summary

## Risk Rules (never overridden by LLMs)

- No single stock > 15% of portfolio
- No single sector > 35%
- Portfolio avg pairwise correlation < 0.7
- 5% drawdown → CAUTIOUS mode; 15% → HALTED (liquidate all)
- VIX > 25: max 8% position; VIX > 35: max 5%
- Daily loss > 2%: no new buys for 24 hours
- Cash floor: always >= 10%
- Min 5 positions once invested (checked for SELL and REDUCE actions)

## Order Types

- **Market orders** — BUY, SELL, REDUCE (partial sell) via T212 market order API
- **Stop-loss orders** — Automatically placed after BUY executions using Claude's `stop_loss_pct` (GTC validity)
- **Order deduplication** — 5-minute window prevents double-execution

## Universe Screening

Each cycle discovers new candidates beyond existing positions:
- **Sector-balanced sampling** — minimum 3 candidates per sector to avoid concentration
- **Market-cap tiers** — 40% large cap ($10B+), 35% mid cap ($2B-$10B), 25% small cap ($300M-$2B)
- **Screening cooldown** — stocks are stamped with `last_screened_at` after each screen and excluded for 72 hours (configurable via `screening_cooldown_hours`), ensuring broader universe coverage across cycles
- **Metadata enrichment** — sector/market_cap back-filled from yfinance into instruments table over time
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
5. **Phase 5:** Backtesting engine for historical validation
6. **Phase 6:** ML-assisted improvements (only if justified by accumulated evidence)

See [Sophistication Roadmap](docs/SOPHISTICATION_ROADMAP.md) for full details, timelines, and priority matrix.
