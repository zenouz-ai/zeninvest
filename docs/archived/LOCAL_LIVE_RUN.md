# Local Live Run Guide

Step-by-step checklist for running the Investment Agent locally with real Trading 212 API connectivity.

## Prerequisites

- [ ] Python 3.11+ installed
- [ ] Poetry installed (`pip install poetry`)
- [ ] All dependencies installed (`poetry install`)
- [ ] Database migrations applied (`poetry run alembic upgrade head`)
- [ ] `.env` file configured with all 7 required API keys
- [ ] (Optional) Slack/SMTP notification keys configured for chat alerts
- [ ] Trading 212 **Practice** account created (not Live)
- [ ] Diagnostics notebook run successfully (all PASS)

## Initial Setup (First Time Only)

### Install and Migrate

```bash
# Install dependencies
poetry install

# Configure environment
cp config/.env.example .env
# Edit .env with your 7 required API keys (and optional notification keys)

# Create/migrate the SQLite database
poetry run alembic upgrade head
```

This creates `data/investment_agent.db` with all tables (instruments, orders, strategy_decisions, etc.).

### How the Universe Works

On first run, the instruments table is empty. The screener automatically seeds it with **~160 curated well-known US equities** (AAPL, MSFT, GOOGL, JPM, JNJ, XOM, etc.) across all 11 GICS sectors, sorted by market cap. This eliminates the "possibly delisted" noise from random T212 tickers.

As cycles run:
- **yfinance enrichment** back-fills real sector, industry, market_cap, and `longBusinessSummary` (company description) for each stock
- Tickers that fail OHLCV fetch are flagged `data_available=False` and permanently excluded
- The business summary is included in Claude's strategy prompt so it can reason about competitive moats and news impact

After a few cycles, the instruments table is fully enriched and the screener uses real data instead of seed defaults.

## Pre-Flight Checklist

### 1. Verify API Keys

```bash
# Check all keys are set
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

### 6. (Optional) Verify Notification Channel Config

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

## Running a Live Dry Run (Recommended First)

Before executing real trades, run a dry-run cycle to verify the full pipeline:

```bash
poetry run python -m src.orchestrator.main --dry-run
```

**What this does:**
- Seeds the universe with ~160 curated stocks (first run only, then uses enriched data)
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

## Running a Live Cycle

```bash
# Single live cycle
poetry run python -m src.orchestrator.main
```

**What this does:**
- Same as dry run, but actually places orders via Trading 212 API
- Orders are market orders on the **Practice** account
- Each trade is journaled in `journals/` directory

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
| Analysis cycle | From `cycle_times_utc` (intraday: 08/12/16 UTC; standard: 07/19 UTC) Mon-Fri | Trading cycle |
| Daily snapshot | 21:30 UTC daily | Portfolio snapshot + daily report |
| Weekly report | Fri 22:00 UTC | Weekly performance summary |
| Instrument refresh | Sun 12:00 UTC | Update tradable instrument universe |

## Monitoring During Live Run

### Check system status
```bash
poetry run python -m src.orchestrator.main --status
```

### Watch logs in real-time
```bash
tail -f logs/orchestrator.log
tail -f logs/order_manager.log
tail -f logs/strategy_engine.log
```

### Check recent orders
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

### Check notification send logs
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

### Check today's costs
```bash
poetry run python -c "
from src.utils.cost_tracker import get_cost_summary
print(get_cost_summary(days=1))
"
```

## Emergency Controls

### Pause all trading
```bash
poetry run python -m src.orchestrator.main --pause
```

### Force sell a position
```bash
poetry run python -m src.orchestrator.main --force-sell AAPL_US_EQ
```

### Resume trading
```bash
poetry run python -m src.orchestrator.main --resume
```

### Stop the scheduler
```bash
# If running with PID file
kill $(cat scheduler.pid)

# Or find the process
ps aux | grep scheduler
kill <PID>
```

## Trading 212 API Notes

### Ticker Format
Trading 212 uses compound tickers:
- US stocks: `AAPL_US_EQ`, `MSFT_US_EQ`, `GOOGL_US_EQ`
- UK stocks: `BP._UK_EQ`, `HSBA_UK_EQ`

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
