---
title: Local Setup and Live Run Guide
tags: [setup, local, macos, testing]
status: active
last_updated: 2026-03-29
related: [DEPLOYMENT.md]
---

# Local Setup and Live Run Guide

> Complete guide for setting up the Investment Agent locally, running tests, and executing live trading cycles on macOS and other platforms.

## Purpose

Set up the development environment, verify all components work, run tests, and execute trading cycles on the Trading 212 Practice API.

## Prerequisites

| Requirement | Minimum | Recommended | Notes |
|-------------|---------|-------------|-------|
| macOS | 12 (Monterey) | 14+ (Sonoma) | For macOS; other platforms: Linux/Windows work with Poetry |
| Python | 3.11 | 3.12 | Installed via Homebrew (macOS) or system package manager |
| Poetry | Latest | Latest | Dependency and environment manager |
| Disk space | 500 MB | 1 GB | For project, virtualenv, and cache |
| RAM | 4 GB | 8 GB | For running cycles and tests simultaneously |
| API keys | 7 required | + optional notification keys | See [API Keys](#api-keys) section |
| Trading 212 account | Practice mode | — | Demo account, not Live |

## Quick Start (macOS Automated)

For macOS users, run the one-liner from the project root:

```bash
chmod +x scripts/setup_mac.sh
./scripts/setup_mac.sh
```

This installs everything and prints next-step instructions. If you prefer manual setup, follow the steps below.

## Installation

### Common Setup (All Platforms)

#### 1. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Add Poetry to your PATH (if not already):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Verify:

```bash
poetry --version
```

#### 2. Install Project Dependencies

From the project root (`Investment-agent/`):

```bash
# Tell Poetry to use your Python 3.11+ installation
poetry env use python3.11

# Keep the virtualenv inside the project (.venv/)
poetry config virtualenvs.in-project true

# Install all dependencies (core + dev tools including pytest & jupyter)
poetry install
```

This installs **all** packages from `pyproject.toml` including:

- **Core:** anthropic, openai, google-genai, yfinance, pandas, numpy, sqlalchemy, httpx, etc.
- **Dev:** pytest, pytest-asyncio, pytest-cov, mypy, jupyter, ipykernel

#### 3. Configure API Keys

Copy the example `.env` file and fill in all required keys:

```bash
cp config/.env.example .env
# Edit .env with your API keys (use your preferred editor)
```

See [API Keys](#api-keys) section below for the required keys and where to obtain them.

#### 4. Initialize the Database

```bash
poetry run alembic upgrade head
```

This creates the SQLite database at `data/investment_agent.db` with all required tables (system_state, instruments, orders, strategy_decisions, moderation_logs, risk_decisions, etc.).

### macOS-Specific Steps

#### 1. Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### 2. Handle Apple Silicon PATH (M1/M2/M3/M4)

On **Apple Silicon** Macs, add Homebrew to your PATH:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Verify Homebrew is accessible:

```bash
brew --version
```

#### 3. Install Python 3.11+

```bash
brew install python@3.11
```

Verify:

```bash
python3.11 --version   # Should print Python 3.11.x
```

#### 4. Install C Compiler (if needed)

Some packages may need a C compiler on Apple Silicon:

```bash
brew install gcc
```

If `poetry install` fails on a C extension, retry with:

```bash
export CC=gcc-13
poetry install
```

#### 5. Register Jupyter Kernel

After installing dependencies, register a Jupyter kernel for the diagnostics notebook:

```bash
poetry run python -m ipykernel install --user \
    --name investment-agent \
    --display-name "Investment Agent (Python)"
```

You can skip this step if you only plan to run CLI commands.

## API Keys

Fill in these 7 required keys in `.env`. Optional notification keys (Slack, SMTP) are documented in `config/.env.example`.

| Variable | Service | Purpose | Get it from |
|----------|---------|---------|-------------|
| `T212_API_KEY` | Trading 212 (Practice) | Trade execution | [app.trading212.com/settings](https://app.trading212.com/) |
| `T212_API_SECRET` | Trading 212 | Trade execution | Same page |
| `ANTHROPIC_API_KEY` | Claude (Sonnet) | Strategy synthesis | [console.anthropic.com](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | GPT-4o | Moderation (skeptic) | [platform.openai.com](https://platform.openai.com/) |
| `GOOGLE_AI_API_KEY` | Gemini Flash | Moderation (risk assessor) | [aistudio.google.com](https://aistudio.google.com/) |
| `FINNHUB_API_KEY` | Finnhub | Analyst recs, insider sentiment | [finnhub.io](https://finnhub.io/) |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | News sentiment, sector performance | [alphavantage.co/support](https://www.alphavantage.co/support/#api-key) |

Optional investigation-only keys (not required for normal setup):

| Variable | Service | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | OpenRouter | Nemotron integration investigation |
| `NVIDIA_API_KEY` | NVIDIA NIM | Nemotron integration investigation |

Use these only if running investigation steps in `docs/Nemotron_3_Super_Integration_Investigation.md`. Leave unset for standard local development and current production-equivalent behavior.

**Note:** The agent runs in **Practice/Demo mode** by default. No real money is at risk. See [Switching to Live Mode](#switching-to-live-mode) before trading with real capital.

## Running Tests

### Full Test Suite

```bash
poetry run pytest -v
```

This runs all 721 collected tests using in-memory SQLite fixtures.

### Individual Test Files

```bash
poetry run pytest tests/test_risk_manager.py -v       # 43 risk rule tests
poetry run pytest tests/test_execution.py -v          # 14 execution tests
poetry run pytest tests/test_strategy.py -v           # 17 strategy tests
poetry run pytest tests/test_moderation.py -v         # 21 moderation tests
poetry run pytest tests/test_cost_tracker.py -v       # 16 cost tracker tests
```

### Coverage Report

```bash
poetry run pytest --cov=src --cov-report=term-missing -v
```

### Type Checking

```bash
poetry run mypy src/
```

### Dashboard Frontend Runtime

Use Node 20 LTS for `dashboard/frontend`.

```bash
cd dashboard/frontend
nvm use   # reads .nvmrc
npm install
npm test
npm run build
```

The frontend toolchain is pinned to `node >=20 <21`. Newer major Node versions are not part of the supported local toolchain.

## Diagnostics Notebook

The notebook at `notebooks/diagnostics.ipynb` tests every pipeline component independently and is useful for validating your setup before running live cycles.

### Launch

```bash
poetry run jupyter notebook notebooks/diagnostics.ipynb
```

This opens the notebook in your browser. Select the **"Investment Agent (Python)"** kernel if prompted.

### What Each Section Tests

| Section | What it validates | API keys needed |
|---------|-------------------|-----------------|
| 0. Environment Setup | Python path, project root | None |
| 1. Configuration | settings.yaml loads correctly | None |
| 2. Database & Models | SQLite tables exist, row counts | None |
| 3. State Machine | ACTIVE/CAUTIOUS/HALTED transitions | None |
| 4. Cost Tracker | Budget enforcement, degradation levels | None |
| 5. yfinance OHLCV | Historical price data retrieval | None (free) |
| 6. Indicators | RSI, MACD, Bollinger Bands, 50MA | None |
| 7. Fundamentals | P/E, P/B, ROE, margins, debt/equity | None (free) |
| 8. Macro Data | VIX, S&P 500 vs 200MA, market regime | None (free) |
| 9. Macro Intelligence | Sector performance (AV SECTOR), economic headlines (Finnhub /news) | `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY` |
| 10. Finnhub API | Analyst recommendations, insider sentiment, market news | `FINNHUB_API_KEY` |
| 11. Alpha Vantage | News sentiment (broad + per-ticker), sector performance | `ALPHA_VANTAGE_API_KEY` |
| 12. Sub-Strategies | Momentum, mean reversion, factor scoring | None |
| 13. Claude Synthesis | Strategy decisions via Anthropic API | `ANTHROPIC_API_KEY` |
| 14. Moderation Panel | GPT-4o + Gemini consensus | `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY` |
| 15. Risk Manager | All 9 hard risk rules | None |
| 16. T212 Client | Account cash, positions | `T212_API_KEY` |
| 17. Order Manager | Dry-run order execution | None |
| 18. Trade Journal | Markdown journal generation | None |
| 19. Orchestrator | Full dry-run cycle (end-to-end) | All keys |
| 20. Database Inspection | Recent activity across all tables | None |
| 21. Summary Report | Pass/warn/fail for every component | None |

### Running Without API Keys

Sections 0-8, 12, 15, and 17-18 work **without any API keys** (they use free yfinance data and local computations). You can run these first to verify the local setup is correct before adding paid API keys.

### Optional: Brave/Tavily Enrichment Scripts

If using Brave Search, Brave Answers, or Tavily for batch enrichment, you can validate connectivity with:

```bash
poetry run python notebooks/brave_api_smoke.py      # Smoke test Brave Search + Answers (requires BRAVE_* keys)
poetry run python notebooks/brave_tavily_comparison.py  # Compare Brave vs Tavily extraction
poetry run python notebooks/enrichment_benchmark.py     # Benchmark cost, time, accuracy across providers
```

These are **manual scripts** (not pytest); they call real APIs and print results.

### Expected LLM Costs Per Notebook Run

| Provider | Approximate cost |
|----------|-----------------|
| Anthropic (Claude Sonnet) | ~$0.01-0.03 |
| OpenAI (GPT-4o) | ~$0.003 |
| Google (Gemini Flash) | ~$0.003 |
| **Total** | **~$0.02-0.04** |

## Pre-Flight Checklist

Run these checks before your first live cycle to ensure all components are configured correctly.

### 1. Verify API Keys

```bash
poetry run python -c "
from src.utils.config import get_settings
s = get_settings()
print('T212 API Key:', s.t212_api_key[:8] + '...')
print('Anthropic:', s.anthropic_api_key[:8] + '...')
print('OpenAI:', s.openai_api_key[:8] + '...')
print('Google AI:', s.google_ai_api_key[:8] + '...')
print('Finnhub:', s.finnhub_api_key[:8] + '...')
print('Alpha Vantage:', s.alpha_vantage_api_key[:8] + '...')
"
```

### 2. Verify Trading 212 Connectivity

```bash
poetry run python -c "
from src.agents.execution.t212_client import T212Client
client = T212Client()
try:
    cash = client.get_cash()
    print('Cash balance:', cash)
    info = client.get_account_info()
    print('Account info:', info)
    positions = client.get_portfolio()
    print(f'Open positions: {len(positions)}')
finally:
    client.close()
"
```

**Expected:** Returns your practice account cash balance (typically £50,000 for demo).

### 3. Verify Config Settings

```bash
# Verify trading mode
grep "mode:" config/settings.yaml
# Should show: mode: active

# Ensure demo URL
grep "base_url:" config/settings.yaml
# Should show: base_url: https://demo.trading212.com/api/v0
```

### 4. Check Database State

```bash
poetry run python -c "
from src.orchestrator.state_machine import StateMachine
sm = StateMachine()
state = sm.get_state()
print('System state:', state['state'])
print('Paused:', state.get('paused', False))
"
```

If state is HALTED or paused, resume:

```bash
poetry run python -m src.orchestrator.main --resume
```

### 5. Check Budget Headroom

```bash
poetry run python -c "
from src.utils.cost_tracker import get_degradation_level, get_cost_summary
print('Degradation:', get_degradation_level().value)
print('Costs today:', get_cost_summary(days=1))
"
```

### 6. Verify Notification Channel Config (Optional)

```bash
poetry run python -c "
from src.utils.config import get_settings
s = get_settings()
print('Notifications enabled:', s.notification_enabled)
print('Channels:', s.notification_channels)
print('Include dry-run alerts:', s.notification_include_dry_run_alerts)
print('Slack configured:', bool(s.slack_webhook_url))
print('Email configured:', bool(s.smtp_host and s.alert_email_to and s.alert_email_from))
"
```

If you are testing email locally with Mailpit/MailHog (or another local SMTP sink), set `SMTP_USE_TLS=false` in `.env` because those sinks typically do not support STARTTLS on port `1025`.

## Running Cycles

### How the Universe Works

On first run, the instruments table is empty. The screener automatically seeds it with **S&P 1500 (~1506 constituents)** (AAPL, MSFT, GOOGL, JPM, JNJ, XOM, etc.) across all 11 GICS sectors, sorted by market cap. This eliminates the "possibly delisted" noise from random T212 tickers.

As cycles run:

- **yfinance enrichment** back-fills real sector, industry, market_cap, and `longBusinessSummary` (company description) for each stock
- Tickers that fail OHLCV fetch are flagged `data_available=False` and permanently excluded
- The business summary is included in Claude's strategy prompt so it can reason about competitive moats and news impact

After a few cycles, the instruments table is fully enriched and the screener uses real data instead of seed defaults.

### Dry Run (Recommended First)

Before executing real trades, run a dry-run cycle to verify the full pipeline:

```bash
poetry run python -m src.orchestrator.main --dry-run
```

**What this does:**

- Seeds the universe with S&P 1500 (~1506 stocks, first run only, then uses enriched data)
- Fetches real market data (yfinance, Finnhub, Alpha Vantage, macro intelligence: sector performance + economic headlines)
- Fetches company business summaries from yfinance for qualitative analysis
- Runs strategy synthesis with Claude (real API call, ~£0.01)
- Runs moderation with GPT-4o + Gemini (real API calls, ~£0.005)
- Runs risk checks (local, no API cost)
- Logs orders as `dry_run` status (no real trades placed)
- Flags any tickers that fail OHLCV fetch as `data_available=False`

**Review the output:**

- Check that decisions are reasonable (sensible tickers, appropriate allocations)
- Verify moderation verdicts make sense
- Confirm risk checks are applied correctly
- Check cost summary is within budget
- Check that "Skipped N candidates with no OHLCV data" is low (should decrease over cycles as bad tickers are flagged)
- If notifications are configured, confirm Slack receives concise alerts and email receives full cycle summaries

**UOV calibration:** To inspect UOV scores without changing execution order, run with `--uov-diagnostic`. This forces UOV into shadow mode and prints `uov_ewma`/`uov_z` for all BUY candidates to stderr, useful for tuning `immediate_threshold_z` and `queue_threshold_z` in `config/settings.yaml`.

### Live Cycle

```bash
poetry run python -m src.orchestrator.main
```

**What this does:**

- Same as dry run, but actually places orders via Trading 212 API
- Orders are market orders on the **Practice** account
- Each trade is journaled in `journals/` directory

**Dashboard alternative:** When the dashboard is running (`dashboard.enabled: true`), you can trigger cycles via the **Dry Run** and **Live Run** buttons on Dashboard Home, and force-sell positions via the **Force Sell** button on the Portfolio page — no CLI/SSH required. Pause/Resume is also available from the Dashboard.

## Running the Scheduler (Continuous Operation)

For continuous automated trading:

```bash
# Foreground (see logs in terminal)
poetry run python -m src.scheduler.scheduler

# Background with nohup
nohup poetry run python -m src.scheduler.scheduler > logs/scheduler.log 2>&1 &
echo $! > scheduler.pid
```

**Scheduled jobs:**

| Job | Schedule | Description |
|-----|----------|-------------|
| Analysis cycle | From configured schedule mode (intraday: 10:00/12:30/15:15 America/New_York; standard: 07:00/19:00 UTC) Mon-Fri | Trading cycle |
| Daily snapshot | 21:30 UTC daily | Portfolio snapshot + daily report |
| Weekly report | Fri 22:00 UTC | Weekly performance summary |
| Instrument refresh | Sun 12:00 UTC | Update tradable instrument universe |

## Monitoring

### Check System Status

```bash
poetry run python -m src.orchestrator.main --status
```

### Watch Logs in Real-Time

```bash
tail -f logs/orchestrator.log
tail -f logs/order_manager.log
tail -f logs/strategy_engine.log
```

### Check Recent Orders

```bash
poetry run python -c "
from sqlalchemy import text
from src.data.database import get_session
s = get_session()
rows = s.execute(text('SELECT timestamp, ticker, action, quantity, price, status FROM orders ORDER BY timestamp DESC LIMIT 10')).fetchall()
for r in rows: print(r)
s.close()
"
```

### Check Notification Send Logs

```bash
poetry run python -c "
from sqlalchemy import text
from src.data.database import get_session
s = get_session()
rows = s.execute(text('SELECT timestamp, event_type, channel, status, attempt_number FROM notification_logs ORDER BY timestamp DESC LIMIT 20')).fetchall()
for r in rows: print(r)
s.close()
"
```

### Check Today's Costs

```bash
poetry run python -c "
from src.utils.cost_tracker import get_cost_summary
print(get_cost_summary(days=1))
"
```

## Emergency Controls

### Pause All Trading

```bash
poetry run python -m src.orchestrator.main --pause
```

### Force Sell a Position

```bash
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
```

### Resume Trading

```bash
poetry run python -m src.orchestrator.main --resume
```

### Stop the Scheduler

```bash
# If running with PID file
kill $(cat scheduler.pid)

# Or find the process
ps aux | grep scheduler
kill <PID>
```

## Trading 212 Notes

### Ticker Format

Trading 212 uses compound tickers:

- US stocks: `AAPL_US_EQ`, `MSFT_US_EQ`, `GOOGL_US_EQ`
- UK stocks: `BP._UK_EQ`, `HSBA_UK_EQ`

The strategy may occasionally return plain symbols (`AAPL`, `NEM`). The orchestrator normalizes these to T212 instrument IDs before order placement via `stocks_data` and an instruments-table fallback.

### Practice vs Live

- Practice API: `https://demo.trading212.com/api/v0`
- Live API: `https://live.trading212.com/api/v0`
- **Always verify `config/settings.yaml` has the demo URL before running**

### Rate Limits

- Trading 212 enforces rate limits via `x-ratelimit-remaining` header
- The T212Client automatically pauses when remaining < 5

## Post-Run Review

After each cycle, review:

1. **Trade journals** in `journals/` — full markdown reports per trade
2. **Database** — query strategy_decisions, moderation_logs, risk_decisions tables
3. **Cost logs** — ensure spending is within budget
4. **API logs** — check for errors or unusual response times
5. **Portfolio** via Trading 212 app/website — verify positions match expectations

## Switching to Live Mode

> **WARNING:** Only switch to live mode after extensive practice testing.

1. Create Trading 212 Live API keys
2. Update `.env` with live API credentials
3. Change `config/settings.yaml`:
   ```yaml
   trading:
     mode: live
     base_url: https://live.trading212.com/api/v0
   ```
4. Consider reducing position sizes and increasing conviction thresholds
5. Start with `--dry-run` on the live endpoint first to verify connectivity

## Troubleshooting

### `poetry: command not found`

Add Poetry to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Make it permanent:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
```

### `Python version ^3.11 not found`

Install Python 3.11 and point Poetry to it:

```bash
brew install python@3.11
poetry env use python3.11
poetry install
```

### `No module named 'src'`

Make sure you run commands from the project root directory and use `poetry run`:

```bash
cd /path/to/Investment-agent
poetry run pytest -v
```

### Jupyter kernel not showing "Investment Agent (Python)"

Re-register the kernel:

```bash
poetry run python -m ipykernel install --user \
    --name investment-agent \
    --display-name "Investment Agent (Python)"
```

Then restart Jupyter and select the kernel from the menu: **Kernel → Change Kernel → Investment Agent (Python)**.

### `alembic upgrade head` fails

Ensure you are in the project root (where `alembic.ini` is located):

```bash
ls alembic.ini   # Should show the file
poetry run alembic upgrade head
```

### Apple Silicon (M1/M2/M3/M4) issues

Some packages may need Rosetta or specific compiler flags. If `poetry install` fails on a C extension:

```bash
brew install gcc
export CC=gcc-13
poetry install
```

### Resetting the Database

If you need a clean start:

```bash
rm -f data/investment_agent.db
poetry run alembic upgrade head
```

## Related Notes

- [Deployment (VPS)](DEPLOYMENT.md) (§13 covers dashboard deployment)
- [Data Export Runbook](DATA_EXPORT_RUNBOOK.md)
- [Architecture](ARCHITECTURE.md)
- [Nemotron Investigation](Nemotron_3_Super_Integration_Investigation.md)
