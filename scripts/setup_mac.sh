#!/usr/bin/env bash
# =============================================================================
# Investment Agent — Mac Environment Setup
# =============================================================================
# This script sets up a macOS environment for running the Investment Agent.
# It installs Homebrew (if needed), Python 3.11+, Poetry, project dependencies,
# initialises the database, and registers the Jupyter kernel.
#
# Usage:
#   chmod +x scripts/setup_mac.sh
#   ./scripts/setup_mac.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# 1. Homebrew
# ---------------------------------------------------------------------------
info "Checking Homebrew..."
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for Apple Silicon Macs
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
else
    info "Homebrew already installed ($(brew --version | head -1))"
fi

# ---------------------------------------------------------------------------
# 2. Python 3.11+
# ---------------------------------------------------------------------------
REQUIRED_PYTHON_MINOR=11

info "Checking Python..."
PYTHON_CMD=""

# Check if a suitable Python already exists
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        PY_VERSION=$("$cmd" --version 2>&1 | awk '{print $2}')
        PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
        if (( PY_MINOR >= REQUIRED_PYTHON_MINOR )); then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    info "Installing Python 3.11 via Homebrew..."
    brew install python@3.11
    PYTHON_CMD="python3.11"
fi

PY_VERSION=$("$PYTHON_CMD" --version 2>&1)
info "Using $PY_VERSION ($PYTHON_CMD)"

# ---------------------------------------------------------------------------
# 3. Poetry
# ---------------------------------------------------------------------------
info "Checking Poetry..."
if ! command -v poetry &>/dev/null; then
    info "Installing Poetry..."
    curl -sSL https://install.python-poetry.org | "$PYTHON_CMD" -
    # Add Poetry to PATH
    export PATH="$HOME/.local/bin:$PATH"
    if ! grep -q 'poetry' ~/.zprofile 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
    fi
else
    info "Poetry already installed ($(poetry --version))"
fi

# Configure Poetry to use the correct Python and create venvs in-project
poetry env use "$PYTHON_CMD" 2>/dev/null || true
poetry config virtualenvs.in-project true

# ---------------------------------------------------------------------------
# 4. Install project dependencies
# ---------------------------------------------------------------------------
info "Installing project dependencies (core + dev)..."
poetry install

# ---------------------------------------------------------------------------
# 5. Environment file
# ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
    info "Creating .env from template..."
    cp config/.env.example .env
    warn "Edit .env and add your API keys before running the agent."
    warn "Required keys: T212_API_KEY, T212_API_SECRET, ANTHROPIC_API_KEY,"
    warn "               OPENAI_API_KEY, GOOGLE_AI_API_KEY, FINNHUB_API_KEY,"
    warn "               ALPHA_VANTAGE_API_KEY"
else
    info ".env already exists — skipping copy."
fi

# ---------------------------------------------------------------------------
# 6. Initialise database
# ---------------------------------------------------------------------------
info "Initialising database (Alembic migrations)..."
poetry run alembic upgrade head

# ---------------------------------------------------------------------------
# 7. Register Jupyter kernel
# ---------------------------------------------------------------------------
info "Registering Jupyter kernel 'investment-agent'..."
poetry run python -m ipykernel install --user --name investment-agent --display-name "Investment Agent (Python)"

# ---------------------------------------------------------------------------
# 8. Verify installation
# ---------------------------------------------------------------------------
info "Running quick verification..."
echo ""
echo "  Python  : $("$PYTHON_CMD" --version 2>&1)"
echo "  Poetry  : $(poetry --version 2>&1)"
echo "  pytest  : $(poetry run pytest --version 2>&1 | head -1)"
echo "  jupyter : $(poetry run jupyter --version 2>&1 | head -1)"
echo "  alembic : $(poetry run alembic --version 2>&1 | head -1)"
echo ""

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------
echo ""
info "============================================="
info "  Mac setup complete!"
info "============================================="
echo ""
echo "  Next steps:"
echo ""
echo "  1. Add your API keys to .env:"
echo "       open .env"
echo ""
echo "  2. Run the test suite:"
echo "       poetry run pytest -v"
echo ""
echo "  3. Launch the diagnostics notebook:"
echo "       poetry run jupyter notebook notebooks/diagnostics.ipynb"
echo "       (Select kernel: 'Investment Agent (Python)')"
echo ""
echo "  4. Run a dry-run cycle:"
echo "       poetry run python -m src.orchestrator.main --dry-run"
echo ""
