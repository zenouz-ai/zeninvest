# Mac Environment Setup & Notebook Guide

Step-by-step instructions for setting up the Investment Agent on macOS and running the diagnostics notebook.

---

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| macOS       | 12 (Monterey) | 14+ (Sonoma) |
| Python      | 3.11    | 3.12        |
| Disk space  | 500 MB  | 1 GB        |
| RAM         | 4 GB    | 8 GB        |

You will also need API keys for 6 services (see Step 3 below).

---

## Quick Start (automated)

Run the one-liner from the project root:

```bash
chmod +x scripts/setup_mac.sh
./scripts/setup_mac.sh
```

This installs everything and prints next-step instructions. If you prefer to do it manually, follow the steps below.

---

## Manual Setup

### Step 1 — Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On **Apple Silicon** (M1/M2/M3/M4), add Homebrew to your PATH:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Verify:

```bash
brew --version
```

### Step 2 — Install Python 3.11+

```bash
brew install python@3.11
```

Verify:

```bash
python3.11 --version   # Should print Python 3.11.x
```

### Step 3 — Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3.11 -
```

Add to PATH (if not already):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Verify:

```bash
poetry --version
```

### Step 4 — Install project dependencies

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
- **Core:** anthropic, openai, google-genai, yfinance, pandas, numpy, sqlalchemy, etc.
- **Dev:** pytest, pytest-asyncio, pytest-cov, mypy, jupyter, ipykernel

### Step 5 — Configure API keys

```bash
cp config/.env.example .env
open .env   # or use your preferred editor
```

Fill in all 7 keys:

| Variable | Service | Get it from |
|----------|---------|-------------|
| `T212_API_KEY` | Trading 212 (Practice) | [Trading 212 Settings → API](https://app.trading212.com/) |
| `T212_API_SECRET` | Trading 212 | Same page |
| `ANTHROPIC_API_KEY` | Claude (strategy) | [console.anthropic.com](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | GPT-4o (moderator) | [platform.openai.com](https://platform.openai.com/) |
| `GOOGLE_AI_API_KEY` | Gemini Flash (moderator) | [aistudio.google.com](https://aistudio.google.com/) |
| `FINNHUB_API_KEY` | Finnhub (analyst data) | [finnhub.io](https://finnhub.io/) |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage (news) | [alphavantage.co](https://www.alphavantage.co/support/#api-key) |

> **Note:** The agent runs in **Practice/Demo mode** by default. No real money is at risk.

### Step 6 — Initialise the database

```bash
poetry run alembic upgrade head
```

This creates the SQLite database with all required tables (system_state, instruments, orders, etc.).

### Step 7 — Register Jupyter kernel

```bash
poetry run python -m ipykernel install --user \
    --name investment-agent \
    --display-name "Investment Agent (Python)"
```

---

## Running Tests

### Run the full test suite (111 tests)

```bash
poetry run pytest -v
```

### Run individual test files

```bash
poetry run pytest tests/test_risk_manager.py -v   # 43 risk rule tests
poetry run pytest tests/test_execution.py -v       # 14 execution tests
poetry run pytest tests/test_strategy.py -v        # 17 strategy tests
poetry run pytest tests/test_moderation.py -v      # 21 moderation tests
poetry run pytest tests/test_cost_tracker.py -v    # 16 cost tracker tests
```

### Run with coverage report

```bash
poetry run pytest --cov=src --cov-report=term-missing -v
```

### Run type checking

```bash
poetry run mypy src/
```

---

## Running the Diagnostics Notebook

The notebook at `notebooks/diagnostics.ipynb` tests every pipeline component independently.

### Launch

```bash
poetry run jupyter notebook notebooks/diagnostics.ipynb
```

This opens the notebook in your browser. Select the **"Investment Agent (Python)"** kernel if prompted.

### What each section tests

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

### Running without API keys

Sections 0-8, 12, 15, and 17-18 work **without any API keys** (they use free yfinance data and local computations). You can run these first to verify the local setup is correct before adding paid API keys.

### Expected LLM costs per notebook run

| Provider | Approximate cost |
|----------|-----------------|
| Anthropic (Claude Sonnet) | ~$0.01-0.03 |
| OpenAI (GPT-4o) | ~$0.003 |
| Google (Gemini Flash) | ~$0.003 |
| **Total** | **~$0.02-0.04** |

---

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

### Resetting the database

If you need a clean start:

```bash
rm -f data/investment_agent.db
poetry run alembic upgrade head
```
